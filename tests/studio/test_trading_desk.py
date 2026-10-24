"""The trading desk end to end: scripted seats on made-up market data, through
the debate, the risk period, cooling-off, the hard limits, the account check,
and the order modes; plus exits, debriefs, the kill switch, and restarts."""

import asyncio
import csv
import hashlib
import io
import json
import math
import re
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import httpx
import pytest

from free_claude_code.studio import resilience
from free_claude_code.studio.memory import MemoryService
from free_claude_code.studio.models import now_ms
from free_claude_code.studio.resilience import ServiceError
from free_claude_code.studio.trading import fills as fills_module
from free_claude_code.studio.trading.brokers import registry
from free_claude_code.studio.trading.brokers.base import (
    Account,
    Holding,
    OrderRequest,
    OrderResult,
    Rules,
    fingerprint,
)
from free_claude_code.studio.trading.brokers.registry import BrokerSpec, KeyField
from free_claude_code.studio.trading.config import LIVE_AUTO_PHRASE, SeatConfig
from free_claude_code.studio.trading.data import Quote
from free_claude_code.studio.trading.decisions import config_version, decision_id
from free_claude_code.studio.trading.desk import ASKED, TradingDesk, TradingError
from free_claude_code.studio.trading.instruments import Instrument, parse_symbol
from free_claude_code.studio.trading.keyvault import KeyVault
from free_claude_code.studio.trading.positions import Plan
from free_claude_code.studio.trading.records import (
    TradeAudit,
    TradeDebrief,
    TradeDecision,
    TradeEvent,
    TradeEvidence,
    TradeFill,
    TradeForecast,
    TradeOrder,
    TradePosition,
    TradeRound,
    TradeWeights,
)
from free_claude_code.studio.trading.scanner import Candidate
from free_claude_code.studio.workers import WorkerPool


def data(value: object) -> Any:
    return value


# ------------------------------------------------------------ made-up markets


def bars_for(interval: str, start: float) -> tuple[list[int], list[float]]:
    count, step = {
        "1d": (320, 86_400),
        "1h": (200, 3_600),
        "15m": (120, 900),
        "1m": (30, 60),
    }.get(interval, (100, 86_400))
    now = int(time.time())
    stamps = [now - (count - index) * step for index in range(count)]
    closes = [
        start * (1.0015 ** (index * step / 86_400)) * (1 + 0.01 * math.sin(index / 5))
        for index in range(count)
    ]
    if interval != "1d":
        # Finer bars end at the same price as the daily chart.
        daily_last = start * (1.0015 ** (319)) * (1 + 0.01 * math.sin(319 / 5))
        shift = daily_last / closes[-1]
        closes = [value * shift for value in closes]
    return stamps, closes


def market(request: httpx.Request) -> httpx.Response:
    host = request.url.host
    path = unquote(request.url.path)
    if host.endswith("finance.yahoo.com") and "/v8/finance/chart/" in path:
        symbol = path.rsplit("/", 1)[-1]
        interval = request.url.params.get("interval", "1d")
        if symbol.endswith("=X"):
            rate = 0.65
            return httpx.Response(
                200,
                json={
                    "chart": {
                        "result": [
                            {
                                "meta": {"regularMarketPrice": rate, "currency": "USD"},
                                "timestamp": [int(time.time())],
                                "indicators": {
                                    "quote": [
                                        {
                                            "open": [rate],
                                            "high": [rate],
                                            "low": [rate],
                                            "close": [rate],
                                            "volume": [0],
                                        }
                                    ]
                                },
                            }
                        ]
                    }
                },
            )
        start = 15.0 if symbol == "^VIX" else 100.0
        stamps, closes = bars_for(interval, start)
        if symbol == "^VIX":
            closes = [15.0] * len(closes)
        _, daily = bars_for("1d", start)
        return httpx.Response(
            200,
            json={
                "chart": {
                    "result": [
                        {
                            "meta": {
                                "regularMarketPrice": closes[-1]
                                if symbol == "^VIX"
                                else daily[-1],
                                "regularMarketTime": int(time.time()) - 30,
                                "currency": "AUD" if symbol.endswith(".AX") else "USD",
                            },
                            "timestamp": stamps,
                            "indicators": {
                                "quote": [
                                    {
                                        "open": [c * 0.998 for c in closes],
                                        "high": [c * 1.01 for c in closes],
                                        "low": [c * 0.99 for c in closes],
                                        "close": closes,
                                        # Coins trade in dollars here, so
                                        # this is a busy market either way.
                                        "volume": [50_000_000.0] * len(closes),
                                    }
                                ]
                            },
                        }
                    ],
                    "error": None,
                }
            },
        )
    if host == "api.exchange.coinbase.com" and path.endswith("/ticker"):
        _, daily = bars_for("1d", 100.0)
        price = daily[-1]
        return httpx.Response(
            200,
            json={
                "price": f"{price:.6f}",
                "bid": f"{price * 0.9998:.6f}",
                "ask": f"{price * 1.0002:.6f}",
                "volume": "12345.6",
                "time": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            },
        )
    if host == "api.kraken.com" and path.endswith("/Ticker"):
        _, daily = bars_for("1d", 100.0)
        price = daily[-1] * KRAKEN_SHIFT["factor"]
        return httpx.Response(
            200,
            json={
                "error": [],
                "result": {
                    "XXBTZUSD": {
                        "a": [f"{price * 1.0002:.6f}", "1", "1.000"],
                        "b": [f"{price * 0.9998:.6f}", "1", "1.000"],
                        "c": [f"{price:.6f}", "0.1"],
                        "v": ["100.0", "2000.0"],
                    }
                },
            },
        )
    if host == "api.coingecko.com":
        if path.endswith("/search/trending"):
            return httpx.Response(200, json={"coins": []})
        return httpx.Response(200, json=[])
    if host == "api.dexscreener.com":
        return httpx.Response(200, json={"pairs": []})
    return httpx.Response(404, json={"error": "not served in tests"})


MARKET = httpx.MockTransport(market)
KRAKEN_SHIFT = {"factor": 1.0}
"""Moves Kraken's made-up price away from the others in a test."""


# ------------------------------------------------------------ scripted seats


def forecast_json(p_up: float = 0.66, **extra: object) -> str:
    return json.dumps(
        {
            "stance": "buy" if p_up >= 0.55 else "hold",
            "p_up": p_up,
            "horizon_days": 5,
            "expected_move_pct": 3.0,
            "p_target": 0.55,
            "confidence": 0.7,
            "reasons": ["uptrend with rising volume"],
            "risks": ["crypto-wide selloff"],
            **extra,
        }
    )


def number_after(label: str, text: str) -> float:
    found = re.search(rf"{label} ([0-9.e+-]+)", text)
    assert found is not None, label
    return float(found.group(1).rstrip("."))


def pack_id(prompt: str) -> str:
    found = re.search(r"EVIDENCE PACK (\S+) for", prompt)
    assert found is not None, "no evidence pack in the prompt"
    return found.group(1)


def levels(prompt: str, *, stop_atr: float = 2.0) -> dict[str, float]:
    """A plan around the price in the prompt: stop 2 ATR below, target 5 ATR
    above (reward-to-risk 2.5)."""
    price = number_after("PRICE NOW", prompt)
    atr_value = number_after("ATR", prompt)
    return {
        "entry_low": round(price * 0.999, 6),
        "entry_high": round(price * 1.001, 6),
        "stop_loss": round(price - stop_atr * atr_value, 6),
        "take_profit": round(price + 5 * atr_value, 6),
    }


def call_json(prompt: str, seat: int, *, p_up: float = 0.66) -> str:
    """A seat's checked call, as the contract wants it."""
    about = re.search(r"YOUR CALL IS ABOUT (\S+) \((\w+)\)", prompt)
    assert about is not None, "no symbol in the prompt"
    found: dict[str, object] = {
        "symbol": about.group(1),
        "asset_class": about.group(2),
        "direction": "long",
        "confidence": 70,
        "p_up": p_up,
        "p_target": 0.55,
        "expected_move_pct": 3.0,
        "main_reason": "Uptrend with rising volume [C1]",
        "thesis": "The trend [C1] and the price [F1] agree.",
        "prove_wrong": ["a daily close below the stop"],
        "evidence": ["F1", "C1"],
        "order_type": "market",
        "holding_days": 5,
        "open_questions": ["Is the breakout volume real?"],
        "ideas": [{"idea": "wait for a pullback to a lower limit", "kind": "simulate"}],
        "changed": "Nothing material changed [F1].",
        "data_timestamp": pack_id(prompt),
        **levels(prompt),
    }
    if seat == 2:
        found["next_earnings"] = ""
    if seat == 3:
        found["events"] = [{"name": "FOMC", "date": "2099-01-01"}]
    return json.dumps(found)


class Seats:
    """Answers every stage by its task line, and records what each seat saw."""

    def __init__(
        self,
        *,
        action: str = "buy",
        grade: str = "B",
        defer: bool = False,
        stop_atr: float = 2.0,
    ) -> None:
        self.action = action
        self.grade = grade
        self.defer = defer
        self.stop_atr = stop_atr
        self.calls: list[tuple[int, str]] = []

    async def __call__(
        self, seat: SeatConfig, system: str, prompt: str, max_tokens: int
    ) -> str:
        self.calls.append((seat.seat, prompt))
        if "RISK ASSESSMENT PERIOD" in prompt:
            if seat.seat == 4:
                return json.dumps(
                    {
                        "grade": self.grade,
                        "concerns": ["weekend gap"],
                        "conditions": ["no oversizing"],
                    }
                )
            if seat.seat == 5:
                return json.dumps(
                    {"size_factor": 1, "defer": self.defer, "note": "Keep the size."}
                )
            return json.dumps(
                {"concerns": [], "conditions": [], "note": "Stop sits below support."}
            )
        if (
            "TASK: Opening forecast" in prompt
            or "TASK: Updated forecast" in prompt
            or "TASK: Closing statement" in prompt
        ):
            return call_json(prompt, seat.seat)
        if "TASK: Cross-examine" in prompt:
            return forecast_json(
                0.65, agree=["trend"], disagree=["too fast"], question="Is volume real?"
            )
        if "TASK: Pre-mortem" in prompt:
            return forecast_json(
                0.5,
                failure_story="The breakout failed on thin volume.",
                worst_case_pct=6,
                objections=[
                    {"target": 1, "point": "Breakout volume is thin", "blocking": True}
                ],
                verdict="caution",
            )
        if "TASK: Rebuttal" in prompt:
            return forecast_json(
                0.65,
                answers=[
                    {
                        "point": "1",
                        "answer": "Volume is above its average.",
                        "conceded": False,
                    }
                ],
            )
        if "TASK: Guardian reply" in prompt:
            return forecast_json(
                0.6, resolved=["volume"], objections=[], verdict="proceed"
            )
        if "TASK: Decide" in prompt:
            if self.action != "buy":
                return json.dumps(
                    {
                        "action": self.action,
                        "confidence": 50,
                        "p_up": 0.5,
                        "rationale": "Not convinced.",
                        "data_timestamp": pack_id(prompt),
                    }
                )
            return json.dumps(
                {
                    "action": "long",
                    "order_type": "market",
                    "size_pct": 100,
                    "holding_days": 5,
                    "p_up": 0.66,
                    "p_target": 0.6,
                    "confidence": 70,
                    "rationale": "Trend, volume, and base rates agree [C1].",
                    "supporting": ["F1", "C1"],
                    "prove_wrong": ["a daily close below the stop"],
                    "answers": [],
                    "data_timestamp": pack_id(prompt),
                    **levels(prompt, stop_atr=self.stop_atr),
                }
            )
        if "TASK: Evidence attack" in prompt:
            listed = prompt.split("ITEMS TO TEST", 1)[1].split("TASK:", 1)[0]
            return json.dumps(
                {
                    "items": [
                        {"id": ref, "verdict": "holds"}
                        for ref in re.findall(r"^\[([A-Z]\d+)\]", listed, re.M)
                    ],
                    "still_buy_without_strongest": True,
                }
            )
        if "TASK: Risk review" in prompt:
            return json.dumps(
                {
                    "verdict": "approved",
                    "reasons": ["The stop sits below support [C1]."],
                    "evidence": ["C1"],
                    "data_timestamp": pack_id(prompt),
                }
            )
        if "TASK: Final challenge" in prompt:
            return json.dumps({"verdict": "clear", "point": "Stop sits below support."})
        if "TASK: Debrief" in prompt:
            return json.dumps(
                {
                    "predicted": "a rise",
                    "happened": "it fell to the stop",
                    "missed": "the weekend gap",
                    "lesson": f"seat {seat.seat}: size down before weekends",
                }
            )
        if "CAME DUE AND MISSED" in prompt:
            return json.dumps(
                {"notes": ["chased the move"], "lesson": "wait for a pullback"}
            )
        if "session debrief" in prompt:
            return json.dumps({"summary": "A quiet session.", "watch": "rates"})
        if "weekly review" in prompt:
            return json.dumps(
                {
                    "summary": "The Technical Analyst led the week.",
                    "suggestions": [
                        {
                            "text": "too many weak buys",
                            "setting": "min_confidence",
                            "value": 0.65,
                        }
                    ],
                }
            )
        return "{}"


class FakeLive:
    """A live platform that fills market orders and can lose one answer."""

    id = "fake"
    name = "Fake Broker"
    live = True
    supports_brackets = False

    def __init__(self) -> None:
        self.cash = 20_000.0
        self.book: dict[str, OrderResult] = {}
        self.held: dict[str, float] = {}
        self.placed = 0
        self.lose_answer = False
        self.partial: float | None = None
        """Fill only this share of an order at first (the rest stays open)."""
        self.unsure = False
        """Lookups can't say whether an order arrived."""
        self.permissions: tuple[str, ...] | None = None
        self.refuse = False
        """The platform refuses the keys (they were revoked)."""

    def markets(self) -> frozenset[str]:
        return frozenset({"us", "asx", "crypto"})

    async def account(self) -> Account:
        if self.refuse:
            raise ServiceError("401 unauthorized: bad token secret-token", status=401)
        return Account(
            number="U1234567",
            fingerprint=fingerprint("fake", "U1234567"),
            currency="AUD",
            equity=self.cash,
            cash=self.cash,
            buying_power=self.cash,
            live=True,
            permissions=self.permissions,
        )

    async def positions(self) -> list[Holding]:
        return [
            Holding(symbol, qty, 100.0, "USD")
            for symbol, qty in self.held.items()
            if qty > 0
        ]

    async def rules(self, instrument: Instrument) -> Rules:
        return Rules(tradable=True, broker_symbol=instrument.symbol)

    async def quote(self, instrument: Instrument) -> Quote | None:
        _, daily = bars_for("1d", 100.0)
        price = daily[-1]
        return Quote(
            instrument.symbol,
            price,
            "USD",
            time.time(),
            "Fake live",
            price * 0.9998,
            price * 1.0002,
        )

    async def place(self, order: OrderRequest) -> OrderResult:
        self.placed += 1
        share = self.partial or 1.0
        result = OrderResult(
            broker_order_id=f"live-{self.placed}",
            status="filled" if share >= 1 else "partially_filled",
            client_id=order.client_id,
            symbol=order.instrument.symbol,
            filled_qty=order.qty * share,
            fill_price=100.0,
            fees=1.0,
        )
        self.book[order.client_id] = result
        change = order.qty if order.side == "buy" else -order.qty
        self.held[order.instrument.symbol] = (
            self.held.get(order.instrument.symbol, 0.0) + change
        )
        if self.lose_answer:
            self.lose_answer = False
            raise ServiceError("read timed out", transient=True)
        return result

    async def find(self, client_id: str) -> OrderResult | None:
        if self.unsure:
            raise ServiceError("no answer about that order", transient=False)
        return self.book.get(client_id)

    async def cancel(self, broker_order_id: str) -> None:
        return None

    async def open_orders(self) -> list[OrderResult]:
        return []

    async def aclose(self) -> None:
        return None


class FakeLock:
    """Stands in for Windows' protection in tests (a fixed wrapping key)."""

    name = "test lock"

    def wrap(self, key: bytes) -> bytes:
        return bytes(b ^ 0x5A for b in key)

    def unwrap(self, blob: bytes) -> bytes:
        return bytes(b ^ 0x5A for b in blob)


@pytest.fixture
def make_desk(tmp_path: Path, store):
    built: list[TradingDesk] = []

    def build(
        seats: Seats | None = None, *, clock: float | None = None
    ) -> tuple[TradingDesk, Seats]:
        script = seats or Seats()

        async def online() -> bool:
            return True

        desk = TradingDesk(
            store=store,
            root=tmp_path / "trading",
            think=script,
            search=lambda: None,
            memory=lambda: MemoryService(store),
            keys=KeyVault(tmp_path / "trading-keys.vault", protector=FakeLock()),
            workers=WorkerPool(cpu=lambda: None),
            online=online,
            transport=MARKET,
            clock=(lambda: clock) if clock is not None else time.time,
        )
        # Ticks in these tests never start a market scan by themselves.
        desk._last_scan = time.time()
        built.append(desk)
        return desk, script

    yield build


async def crypto_only(desk: TradingDesk, **extra: object) -> None:
    values: dict[str, object] = {
        "markets": {"us": False, "asx": False, "crypto": True, "meme": False},
        "assessment": {"cooling_crypto_minutes": 0},
    }
    values.update(extra)
    await desk.update_config(values, on_pc=True)


def btc(*tags: str) -> Candidate:
    return Candidate(parse_symbol("BTC"), 1.0, tags or ("uptrend",))


async def kinds(store) -> list[str]:
    return [event.kind for event in await store.find(TradeEvent, order_by="seq ASC")]


# ------------------------------------------------------------ paper, end to end


@pytest.mark.asyncio
async def test_broken_data_checks_block_the_pick_instead_of_killing_the_round(
    make_desk, store, monkeypatch
):
    desk, seats = make_desk()
    await crypto_only(desk, running=True)

    async def broken(instrument: Instrument) -> list:
        raise RuntimeError("a feed sent nonsense")

    monkeypatch.setattr(desk._data, "snapshots", broken)
    await desk._consider(btc(), desk.config())
    assert seats.calls == []
    [round_] = await store.find(TradeRound)
    assert round_.status == "blocked" and "Data checks ran" in round_.note
    assert "a feed sent nonsense" in round_.note
    assert not await store.find(TradeOrder)


@pytest.mark.asyncio
async def test_a_price_disagreement_halves_the_order(make_desk, store):
    async def order_qty() -> float:
        desk, _ = make_desk()
        await crypto_only(desk)
        desk._save(desk.config().model_copy(update={"running": True}))
        await desk._consider(btc(), desk.config())
        orders = await store.find(TradeOrder, order_by="created_at DESC")
        return orders[0].qty

    calm = await order_qty()
    KRAKEN_SHIFT["factor"] = 1.01
    try:
        disputed = await order_qty()
    finally:
        KRAKEN_SHIFT["factor"] = 1.0
    later, earlier = await store.find(TradeRound, order_by="created_at DESC")
    calm_cut = data(earlier.data)["quality"]["size_factor"]
    quality = data(later.data)["quality"]
    # Kraken is 1% away from Coinbase and Yahoo (over the 0.5% tolerance,
    # under the 1.5% that blocks): the trade goes ahead at half the size it
    # would otherwise have had (the calm run only lost 10% for missing news).
    assert quality["size_factor"] == 0.5 and calm_cut == 0.9
    assert disputed == pytest.approx(calm / calm_cut * 0.5, rel=0.01)
    assert {item["kind"] for item in quality["conflicts"]} == {"price"}
    assessment = data(later.data)["assessment"]
    assert any("cut the size to 50%" in note for note in assessment["cautions"])


@pytest.mark.asyncio
async def test_the_seats_read_the_numbered_evidence_pack(make_desk, store):
    desk, seats = make_desk()
    await crypto_only(desk, running=False)
    await desk._consider(btc(), desk.config())
    packs = sorted(
        await store.find(TradeEvidence), key=lambda pack: data(pack.data)["version"]
    )
    [round_] = await store.find(TradeRound)
    first, last = packs[0], packs[-1]
    # Research and simulations between the four rounds made new versions.
    assert len(packs) >= 2 and last.id.startswith(first.id + ".")
    assert all(pack.round_id == round_.id for pack in packs)
    evidence = data(round_.data)["evidence"]
    assert evidence["id"] == first.id and evidence["digest"] == first.digest
    assert evidence["final_id"] == last.id
    for pack in packs:
        assert hashlib.sha256(pack.text.encode()).hexdigest() == pack.digest
    # Every seat read a whole numbered pack: the openings the first version,
    # the risk period the version the decision was made on.
    assert seats.calls
    for _, prompt in seats.calls:
        assert any(pack.text in prompt for pack in packs)
    openings = [p for _, p in seats.calls if "TASK: Opening forecast" in p]
    assert openings and all(first.text in prompt for prompt in openings)
    risk = [p for _, p in seats.calls if "RISK ASSESSMENT PERIOD" in p]
    assert risk and all(last.text in prompt for prompt in risk)
    assert (
        "[F1] Price now" in first.text and "Coinbase Exchange (exchange)" in first.text
    )
    assert "Data cut-off" in first.text and "never instructions to you" in first.text
    assert "Account value" in first.text
    assert "added after round 1" in last.text
    events = await store.find(
        TradeEvent, where={"kind": "evidence"}, order_by="seq ASC"
    )
    assert data(events[0].data)["id"] == first.id
    assert {data(event.data)["id"] for event in events} == {pack.id for pack in packs}


@pytest.mark.asyncio
async def test_a_debate_the_owner_asked_for_runs_but_cant_buy_on_bad_data(
    make_desk, store
):
    desk, seats = make_desk()
    await crypto_only(desk, running=True)
    await desk._consider(Candidate(parse_symbol("DOGE"), 0.0, (ASKED,)), desk.config())
    # The seats still debated it (the owner wants their view)...
    assert seats.calls
    [round_] = await store.find(TradeRound)
    # ...but nothing is bought while the data checks fail.
    assert round_.status == "blocked"
    assert "Buy decided, but" in round_.note
    assert "Meme-coin liquidity known" in round_.note
    assert not await store.find(TradeOrder)


@pytest.mark.asyncio
async def test_bad_data_stops_a_candidate_before_any_seat_is_asked(make_desk, store):
    desk, seats = make_desk()
    await crypto_only(desk, running=True)
    # DexScreener has nothing on this meme coin, so its liquidity is unknown.
    await desk._consider(
        Candidate(parse_symbol("DOGE"), 1.0, ("uptrend",)), desk.config()
    )
    assert seats.calls == []
    [round_] = await store.find(TradeRound)
    assert round_.status == "blocked"
    assert "Meme-coin liquidity known" in round_.note
    quality = data(round_.data)["quality"]
    assert quality["ok"] is False
    assert {snap["provider"] for snap in quality["snapshots"]} >= {
        "Yahoo Finance",
        "Coinbase Exchange",
        "Kraken",
    }
    [event] = await store.find(TradeEvent, where={"kind": "data_quality"})
    assert data(event.data)["news_missing"]
    assert not await store.find(TradeOrder)


@pytest.mark.asyncio
async def test_a_paper_trade_goes_through_every_stage(make_desk, store):
    desk, seats = make_desk()
    await crypto_only(desk, running=False)
    await desk.update_config({"running": True}, on_pc=True)
    config = desk.config().model_copy(update={"running": True})
    desk._save(config)
    await desk._consider(btc(), desk.config())

    seen = await kinds(store)
    for kind in (
        "briefing",
        "opening",
        "cross_exam",
        "pre_mortem",
        "rebuttal",
        "guardian_reply",
        "closing",
        "consensus",
        "decision",
        "final_challenge",
        "risk_report",
        "risk_note",
        "cooling",
    ):
        assert kind in seen, kind
    assert seen.count("opening") == 3
    # Openings are blind: no seat saw another's opening.
    openings = [
        prompt for seat, prompt in seats.calls if "TASK: Opening forecast" in prompt
    ]
    assert openings and all(
        "THE OTHER ANALYSTS SAID" not in prompt for prompt in openings
    )
    # Every seat saw its own track record.
    assert all(
        "YOUR TRACK RECORD" in prompt for _, prompt in seats.calls if "TASK:" in prompt
    )

    forecasts = await store.find(TradeForecast)
    assert {f.stage for f in forecasts} == {"opening", "closing", "decision"}
    assert len([f for f in forecasts if f.stage == "closing"]) == 4

    [order] = await store.find(TradeOrder)
    assert order.status == "cooling" and order.side == "buy" and order.qty > 0
    assessment = data(order.data["assessment"])
    assert assessment["passed"] and assessment["grade"] == "B"
    assert assessment["reward_risk"] == pytest.approx(2.5, rel=0.01)

    await desk.tick()
    [order] = await store.find(TradeOrder)
    assert order.status == "filled", order.reason
    assert order.fill_price and order.fx_rate == pytest.approx(1 / 0.65)
    position = await store.get(TradePosition, "paper:BTC")
    assert position is not None and position.stop_loss == order.stop_loss
    seen = await kinds(store)
    assert {"check", "order", "fill"} <= set(seen)
    [record] = await store.find(TradeRound)
    assert record.status == "traded"
    assert all(f.traded for f in await store.find(TradeForecast))
    status = data(await desk.status())
    assert status["mode"] == "paper" and status["account"]["equity_base"] > 9_900
    await desk.close()


@pytest.mark.asyncio
async def test_the_decision_engine_checks_every_buy_and_records_it(make_desk, store):
    desk, _ = make_desk()
    await crypto_only(desk)
    desk._save(desk.config().model_copy(update={"running": True}))
    await desk._consider(btc(), desk.config())
    [order] = await store.find(TradeOrder)
    assessment = data(order.data["assessment"])
    rules = {rule["rule"]: rule for rule in assessment["rules"]}
    assert rules["Stop far enough from the entry"]["passed"]
    assert all(rule["passed"] for rule in rules.values() if rule["blocking"])
    # The investment stress test kept every original case.
    names = {item["name"] for item in assessment["stress_test"]["scenarios"]}
    assert {"1 ATR drop", "3 ATR drop", "15% flash crash", "Index falls 3%"} <= names
    assert "Market crash across the whole account" in names
    assert 0 < assessment["scorecard"]["confidence"] <= 1
    # The order goes ahead with the lower confidence, never a higher one.
    assert order.data["confidence"] <= order.data["manager_confidence"]
    assert "engine" in await kinds(store)
    await desk.close()


@pytest.mark.asyncio
async def test_a_stop_inside_the_noise_is_blocked_in_code(make_desk, store):
    desk, _ = make_desk(Seats(stop_atr=0.5))
    await crypto_only(desk)
    desk._save(desk.config().model_copy(update={"running": True}))
    await desk._consider(btc(), desk.config())
    assert await store.find(TradeOrder) == ()
    [record] = await store.find(TradeRound)
    assert record.status == "blocked" and "Stop far enough" in record.note
    await desk.close()


@pytest.mark.asyncio
async def test_a_hold_places_nothing_and_a_stopped_desk_only_advises(make_desk, store):
    desk, _ = make_desk(Seats(action="hold"))
    await crypto_only(desk)
    await desk._consider(btc(), desk.config())
    assert await store.find(TradeOrder) == ()
    [record] = await store.find(TradeRound)
    assert record.status == "held"

    advice, _ = make_desk()
    await crypto_only(advice)
    await advice._consider(btc(), advice.config())
    rounds = await store.find(TradeRound, order_by="created_at ASC")
    assert rounds[-1].status == "advice"
    assert await store.find(TradeOrder) == ()
    await desk.close()
    await advice.close()


@pytest.mark.asyncio
async def test_a_poor_grade_or_a_deferral_stops_the_trade(make_desk, store):
    desk, _ = make_desk(Seats(grade="E"))
    await crypto_only(desk, running=True)
    desk._save(desk.config().model_copy(update={"running": True}))
    await desk._consider(btc(), desk.config())
    [record] = await store.find(TradeRound)
    assert record.status == "blocked" and "worse than the C minimum" in record.note
    assert await store.find(TradeOrder) == ()

    deferring, _ = make_desk(Seats(defer=True))
    deferring._save(desk.config())
    await deferring._consider(btc(), deferring.config())
    rounds = await store.find(TradeRound, order_by="created_at ASC")
    assert rounds[-1].status == "blocked" and "deferred" in rounds[-1].note
    await desk.close()
    await deferring.close()


@pytest.mark.asyncio
async def test_the_cooling_off_check_aborts_when_the_price_runs(make_desk, store):
    desk, _ = make_desk()
    await crypto_only(desk)
    desk._save(desk.config().model_copy(update={"running": True}))
    await desk._consider(btc(), desk.config())
    [order] = await store.find(TradeOrder)
    # Pretend the decision was made at a price 5% lower.
    await store.put(
        order.model_copy(
            update={
                "data": {
                    **order.data,
                    "assessment": {
                        **data(order.data["assessment"]),
                        "entry": order.entry_price * 0.95,
                    },
                }
            }
        )
    )
    await desk.tick()
    [order] = await store.find(TradeOrder)
    assert order.status == "aborted" and "moved" in order.reason
    await desk.close()


@pytest.mark.asyncio
async def test_stops_close_positions_and_trigger_a_trade_debrief(make_desk, store):
    desk, _ = make_desk()
    await crypto_only(desk)
    desk._save(desk.config().model_copy(update={"running": True}))
    await desk._consider(btc(), desk.config())
    await desk.tick()
    position = await store.get(TradePosition, "paper:BTC")
    assert position is not None
    # The stop is now above the price: the next tick sells.
    await store.put(position.model_copy(update={"stop_loss": position.avg_price * 2}))
    await desk.tick()
    assert await store.get(TradePosition, "paper:BTC") is None
    sells = [o for o in await store.find(TradeOrder) if o.side == "sell"]
    assert sells and sells[0].status == "filled"
    # The debrief runs as the next round's first chore.
    await desk._round()
    [debrief] = await store.find(TradeDebrief, where={"kind": "trade"})
    assert "stop-loss" in debrief.title
    assert debrief.lesson == "seat 5: size down before weekends"
    assert len(data(debrief.data)["notes"]) == 5
    remembered = await MemoryService(store).recall(
        "trading:desk", "BTC crypto", own_only=True
    )
    assert any("size down before weekends" in entry.text for entry in remembered)
    assert "lesson" in await kinds(store)
    await desk.close()


# ------------------------------------------------------------ live platforms


@pytest.fixture
def fake_platform(monkeypatch):
    broker = FakeLive()
    spec = BrokerSpec(
        id="fake",
        name="Fake Broker",
        markets=("us", "asx", "crypto"),
        what="test",
        get_keys="test",
        australia="test",
        fields=(KeyField("token", "Token"),),
        factory=lambda values, data, transport: broker,
    )
    monkeypatch.setitem(registry.BROKERS, "fake", spec)
    return broker


async def go_live(
    desk: TradingDesk, mode: str = "live_approve", confirm: str = ""
) -> None:
    await desk.save_keys("fake", {"token": "secret-token"})
    shown = data(await desk.test_broker("fake"))
    await desk.confirm_account("fake", shown["account"]["fingerprint"])
    await desk.update_config(
        {"mode": mode, "broker": "fake"}, on_pc=True, confirm=confirm
    )


@pytest.mark.asyncio
async def test_going_live_needs_the_pc_keys_a_verified_account_and_the_phrase(
    make_desk, fake_platform
):
    desk, _ = make_desk()
    with pytest.raises(TradingError, match="Add your Fake Broker keys"):
        await desk.update_config({"mode": "live_approve", "broker": "fake"}, on_pc=True)
    await desk.save_keys("fake", {"token": "secret-token"})
    with pytest.raises(TradingError, match="Verify your Fake Broker account"):
        await desk.update_config({"mode": "live_approve", "broker": "fake"}, on_pc=True)
    shown = data(await desk.test_broker("fake"))
    assert shown["account"]["number"] == "••••4567"
    await desk.confirm_account("fake", shown["account"]["fingerprint"])
    with pytest.raises(TradingError, match="only be switched on from the PC"):
        await desk.update_config(
            {"mode": "live_approve", "broker": "fake"}, on_pc=False
        )
    with pytest.raises(TradingError, match=LIVE_AUTO_PHRASE):
        await desk.update_config({"mode": "live_auto", "broker": "fake"}, on_pc=True)
    config = await desk.update_config(
        {"mode": "live_auto", "broker": "fake"}, on_pc=True, confirm=LIVE_AUTO_PHRASE
    )
    assert config.live_auto_confirmed_at > 0
    brokers = data(await desk.brokers())
    fake = next(b for b in brokers if b["id"] == "fake")
    assert fake["verified"] and fake["fields"][0]["set"]
    assert fake["fields"][0]["value"] == ""
    await desk.close()


@pytest.mark.asyncio
async def test_live_orders_wait_for_approval_and_are_checked_again(
    make_desk, store, fake_platform
):
    desk, _ = make_desk()
    await crypto_only(desk)
    await go_live(desk)
    desk._save(desk.config().model_copy(update={"running": True}))
    await desk._consider(btc(), desk.config())
    await desk.tick()
    [order] = await store.find(TradeOrder)
    assert order.status == "awaiting_approval" and order.broker == "fake"
    assert data(order.data["check"])["passed"]
    assert fake_platform.placed == 0
    approved = data(await desk.approve(order.id))
    assert approved["status"] == "filled"
    assert fake_platform.placed == 1
    assert await store.get(TradePosition, "fake:BTC") is not None
    with pytest.raises(TradingError, match="not waiting"):
        await desk.approve(order.id)
    await desk.close()


@pytest.mark.asyncio
async def test_a_lost_answer_never_orders_twice(make_desk, store, fake_platform):
    desk, _ = make_desk()
    await crypto_only(desk)
    await go_live(desk, "live_auto", LIVE_AUTO_PHRASE)
    desk._save(desk.config().model_copy(update={"running": True}))
    fake_platform.lose_answer = True
    await desk._consider(btc(), desk.config())
    await desk.tick()
    [order] = await store.find(TradeOrder)
    assert order.status == "filled"
    assert fake_platform.placed == 1
    await desk.close()


@pytest.mark.asyncio
async def test_unanswered_approvals_expire_and_denials_stick(
    make_desk, store, fake_platform
):
    desk, _ = make_desk()
    await crypto_only(desk)
    await go_live(desk)
    desk._save(desk.config().model_copy(update={"running": True}))
    await desk._consider(btc(), desk.config())
    await desk.tick()
    [order] = await store.find(TradeOrder)
    await store.put(order.model_copy(update={"due_at": 1}))
    await desk.tick()
    [order] = await store.find(TradeOrder)
    assert order.status == "expired"
    with pytest.raises(TradingError, match="not waiting"):
        await desk.deny(order.id)
    await desk.close()


@pytest.mark.asyncio
async def test_the_kill_switch_cancels_everything_waiting(make_desk, store):
    desk, _ = make_desk()
    await crypto_only(desk, assessment={"cooling_crypto_minutes": 10})
    desk._save(desk.config().model_copy(update={"running": True}))
    await desk._consider(btc(), desk.config())
    [order] = await store.find(TradeOrder)
    assert order.status == "cooling"
    status = data(await desk.kill())
    assert status["running"] is False
    [order] = await store.find(TradeOrder)
    assert order.status == "cancelled"
    await desk.close()


@pytest.mark.asyncio
async def test_after_a_restart_only_paper_trading_resumes(make_desk, fake_platform):
    desk, _ = make_desk()
    await go_live(desk)
    desk._save(desk.config().model_copy(update={"running": True}))
    await desk.resume()
    # Live trading stays paused until Start, but what is held is still
    # watched (stops and targets keep working after a restart).
    assert desk.config().running is False
    assert desk._loop_task is not None and not desk._loop_task.done()
    paper, _ = make_desk()
    await paper.update_config({"mode": "paper"}, on_pc=True)
    paper._save(paper.config().model_copy(update={"running": True}))
    await paper.resume()
    assert paper._loop_task is not None
    await paper.close()
    await desk.close()


# ------------------------------------------------------------ forecasts and reviews


@pytest.mark.asyncio
async def test_due_forecasts_are_scored_and_reviews_suggest_changes(make_desk, store):
    desk, _ = make_desk()
    created = int((time.time() - 10 * 86_400) * 1000)
    await store.put_many(
        [
            TradeForecast(
                seat=1,
                symbol="BTC",
                market="crypto",
                p_up=0.8,
                entry_price=50.0,
                horizon_days=2,
                due_at=created + 2 * 86_400_000,
                created_at=created,
            ),
            TradeForecast(
                seat=2,
                symbol="BTC",
                market="crypto",
                p_up=0.2,
                entry_price=50.0,
                horizon_days=2,
                due_at=created + 2 * 86_400_000,
                created_at=created,
            ),
        ]
    )
    await desk._score_forecasts(desk.config())
    scored = {f.seat: f for f in await store.find(TradeForecast)}
    assert scored[1].status == "scored" and scored[1].hit
    assert scored[2].status == "scored" and not scored[2].hit
    await desk._round()
    assert await store.find(TradeDebrief, where={"kind": "forecast"})

    await desk.debrief_now("weekly")
    await desk._round()
    [review] = await store.find(TradeDebrief, where={"kind": "weekly"})
    suggestions = data(review.data)["suggestions"]
    assert suggestions[0]["setting"] == "min_confidence"
    before = desk.config().risk.min_confidence
    accepted = data(await desk.accept_suggestion(review.id, 0, on_pc=True))
    assert accepted["accepted"] and desk.config().risk.min_confidence == 0.65 != before
    await desk.close()


@pytest.mark.asyncio
async def test_session_debriefs_follow_market_closes(make_desk, store):
    # An hour after the crypto day closes (14:00 UTC).
    desk, _ = make_desk(clock=datetime(2026, 10, 14, 15, 0, tzinfo=UTC).timestamp())
    await desk._schedule_debriefs(desk.config())
    # The first look only notes the closes; nothing to sum up yet.
    assert desk._chores == []
    state = desk._state()
    marks = data(state["debriefs"])
    marks["crypto"] = marks["crypto"] - 86_400_000
    state["debriefs"] = marks
    desk._save_state(state)
    await desk._schedule_debriefs(desk.config())
    assert len(desk._chores) == 1
    await desk._round()
    [session] = await store.find(TradeDebrief, where={"kind": "session"})
    assert session.market == "crypto" and session.summary == "A quiet session."
    await desk.close()


@pytest.mark.asyncio
async def test_the_tax_export_and_summary(make_desk, store):
    desk, _ = make_desk()
    await crypto_only(desk)
    desk._save(desk.config().model_copy(update={"running": True}))
    await desk._consider(btc(), desk.config())
    await desk.tick()
    position = await store.get(TradePosition, "paper:BTC")
    assert position is not None
    await store.put(
        position.model_copy(update={"take_profit": position.avg_price * 0.5})
    )
    await desk.tick()
    text = await desk.export_csv()
    assert text.count("\n") == 2 and "BTC" in text
    summary = data(await desk.summary())
    assert summary["closed_trades"] == 1
    await desk.close()


# ------------------------------------------------------------ decision records and audit


@pytest.mark.asyncio
async def test_a_trade_keeps_a_complete_decision_record(make_desk, store):
    desk, _ = make_desk()
    await crypto_only(desk)
    desk._save(desk.config().model_copy(update={"running": True}))
    await desk._consider(btc(), desk.config())
    await desk.tick()
    [record] = await store.find(TradeDecision)
    [round_] = await store.find(TradeRound)
    assert record.id == decision_id(round_.id) and record.round_id == round_.id
    assert record.status == "position_open" and record.order_submitted
    assert record.config_version == config_version(desk.config())
    assert record.pack_id and record.order_id
    found = data(record.data)
    for key in (
        "cycle_id",
        "evidence",
        "data_sources",
        "data_timestamps",
        "facts",
        "calculations",
        "seat_outputs",
        "conflicts",
        "final_decision",
        "risk_checks",
        "models",
        "prompt_version",
        "transcript",
    ):
        assert key in found, key
    assert {"Coinbase Exchange", "Yahoo Finance"} <= set(found["data_sources"])
    assert found["facts"] and found["calculations"]
    assert set(found["seat_outputs"]["closing"]) == {"1", "2", "3", "4"}
    assert found["seat_outputs"]["plan"]["action"] == "long"
    assert found["final_decision"]["action"] == "buy"
    assert any(rule["rule"].startswith("Stop far") for rule in found["risk_checks"])
    timing = found["timing"]
    for key in (
        "cycle_start",
        "pack_created",
        "seat_responses",
        "final_decision",
        "order_decision",
        "final_check",
        "submitted",
        "fill",
    ):
        assert timing.get(key), key
    assert timing["cycle_start"] <= timing["final_decision"] <= timing["fill"]
    prices = found["prices"]
    for key in ("analysis", "final_check", "submission", "fill"):
        assert prices.get(key), key
    assert any(line["kind"] == "decision" for line in found["transcript"])

    # Closing the position records the result.
    position = await store.get(TradePosition, "paper:BTC")
    assert position is not None
    await store.put(position.model_copy(update={"stop_loss": position.avg_price * 2}))
    await desk.tick()
    record = await store.get(TradeDecision, record.id)
    assert record is not None and record.status == "position_closed"
    assert record.pnl is not None and data(record.data)["result"]["exit"]
    # The record can be found again by symbol, status, and words.
    assert await desk.decisions(symbol="BTC", status="position_closed")
    assert await desk.decisions(text="btc closed")
    assert not await desk.decisions(symbol="ETH")
    await desk.close()


@pytest.mark.asyncio
async def test_information_to_a_no_trade_with_its_record(make_desk, store):
    """The end-to-end information run: data in, quality checked, a pack
    built, all five seats asked, a conflict found, the checks run, no trade,
    and the complete record kept."""
    desk, seats = make_desk(Seats(action="no_trade"))
    await crypto_only(desk)
    KRAKEN_SHIFT["factor"] = 1.01
    try:
        await desk._consider(btc(), desk.config())
    finally:
        KRAKEN_SHIFT["factor"] = 1.0
    assert {seat for seat, _ in seats.calls} == {1, 2, 3, 4, 5}
    [record] = await store.find(TradeDecision)
    assert record.status == "no_trade" and not record.order_submitted
    found = data(record.data)
    assert any(item["kind"] == "price" for item in found["conflicts"])
    assert found["quality"]["summary"] and found["evidence"]["first_id"]
    assert found["final_decision"]["action"] == "hold"
    assert found["seat_outputs"]["plan"]["action"] == "no_trade"
    assert found["transcript"] and found["timing"]["final_decision"]
    await desk.close()


@pytest.mark.asyncio
async def test_a_stale_decision_is_discarded_and_analysed_again(
    make_desk, store, monkeypatch
):
    desk, _ = make_desk()
    await crypto_only(desk)
    desk._save(desk.config().model_copy(update={"running": True}))
    real = desk._latest

    async def moved(briefing, config):
        found = await real(briefing, config)
        assert found is not None
        # 1.2%: past the 1% entry band, but not so far that the evidence
        # test fails the price first (it fails at 1.5%).
        return replace(found, last=(found.last or 0) * 1.012)

    monkeypatch.setattr(desk, "_latest", moved)
    await desk._consider(btc(), desk.config())
    [round_] = await store.find(TradeRound)
    assert round_.status == "discarded" and "moved" in round_.note
    [record] = await store.find(TradeDecision)
    assert record.status == "discarded"
    assert desk._rechecks == ["BTC"]
    # Analysed again at most once in a while.
    await desk._consider(btc(), desk.config())
    assert desk._rechecks == ["BTC"]

    # A decision that took too long is discarded too.
    old = TradeRound(symbol="BTC", created_at=now_ms() - 2 * 3600 * 1000)
    why = await desk._stale(data(None), desk.config(), old)
    assert "took 120 min" in why
    await desk.close()


@pytest.mark.asyncio
async def test_the_audit_trail_keeps_orders_settings_and_the_kill_switch(
    make_desk, store
):
    desk, _ = make_desk()
    await crypto_only(desk)
    desk._save(desk.config().model_copy(update={"running": True}))
    await desk._consider(btc(), desk.config())
    await desk.tick()
    await desk.update_config({"candidates": 3}, on_pc=True)
    await desk.kill()
    kinds = {line.kind for line in await store.find(TradeAudit)}
    for kind in (
        "decision",
        "engine",
        "order",
        "fill",
        "check",
        "cooling",
        "settings",
        "kill",
    ):
        assert kind in kinds, kind
    settings = (await desk.audit_trail(kind="settings"))[0]
    assert settings["config_version"] == config_version(desk.config())
    assert await desk.audit_trail(kind="order", symbol="BTC")
    assert await desk.audit_trail(text="kill switch")
    table = list(csv.reader(io.StringIO(await desk.audit_csv(kind="fill"))))
    assert table[0][:3] == ["time_utc", "kind", "symbol"] and len(table) >= 2
    assert all(row[1] == "fill" for row in table[1:])
    await desk.close()


# ------------------------------------------------------------ protection and modes


async def closed_trade(store, pnl: float) -> None:
    await store.put(
        TradeDecision(
            round_id=f"trd_{len(await store.find(TradeDecision))}",
            symbol="BTC",
            status="position_closed",
            pnl=pnl,
        )
    )


@pytest.mark.asyncio
async def test_a_losing_streak_trips_the_breaker_until_the_cool_down(make_desk, store):
    desk, _ = make_desk()
    await crypto_only(desk)
    desk._save(desk.config().model_copy(update={"running": True}))
    for _ in range(3):
        await closed_trade(store, -25.0)
    await desk._protect(desk.config())
    assert "circuit breaker" in desk._entry_block(desk.config())
    # No new trade starts: the buy is stopped before the risk period.
    await desk._consider(btc(), desk.config())
    rounds = await store.find(TradeRound)
    assert rounds[-1].status == "blocked" and "circuit breaker" in rounds[-1].note
    assert await store.find(TradeOrder) == ()
    assert "breaker" in {line.kind for line in await store.find(TradeAudit)}
    # After the cool-down, with no new losses since it tripped, it clears.
    later = time.time() + 61 * 60
    desk._clock = lambda: later
    desk._last_protect = 0.0
    await desk._protect(desk.config())
    assert desk._entry_block(desk.config()) == ""
    await desk.close()


@pytest.mark.asyncio
async def test_a_burst_of_errors_trips_the_breaker_and_the_owner_can_reset_it(
    make_desk, store
):
    desk, _ = make_desk()
    await crypto_only(desk)
    for number in range(5):
        await desk.feed.emit("error", f"Broker answered 500 (#{number})")
    await desk._protect(desk.config())
    assert "errors" in desk._entry_block(desk.config())
    with pytest.raises(TradingError):
        await desk.reset_breaker(on_pc=False)
    await desk.reset_breaker(on_pc=True)
    assert desk._entry_block(desk.config()) == ""
    await desk.close()


@pytest.mark.asyncio
async def test_stopping_the_desk_still_watches_stops_and_targets(make_desk, store):
    desk, _ = make_desk()
    await crypto_only(desk)
    desk._save(desk.config().model_copy(update={"running": True}))
    await desk._consider(btc(), desk.config())
    await desk.tick()
    position = await store.get(TradePosition, "paper:BTC")
    assert position is not None
    await desk.stop()
    await store.put(position.model_copy(update={"stop_loss": position.avg_price * 2}))
    await desk.tick()
    assert await store.get(TradePosition, "paper:BTC") is None
    await desk.close()


@pytest.mark.asyncio
async def test_the_kill_switch_latches_and_needs_a_typed_phrase_to_close_all(
    make_desk, store, fake_platform
):
    desk, _ = make_desk()
    await crypto_only(desk)
    desk._save(desk.config().model_copy(update={"running": True}))
    await desk._consider(btc(), desk.config())
    await desk.tick()
    assert await store.get(TradePosition, "paper:BTC") is not None
    await desk.save_keys("fake", {"token": "secret-token"})
    with pytest.raises(TradingError):
        await desk.kill(flatten=True, confirm="yes")
    await desk.kill(flatten=True, confirm="CLOSE EVERYTHING", reason="test")
    # Every account with keys was covered, and the holding was sold.
    assert await store.get(TradePosition, "paper:BTC") is None
    [line] = await desk.audit_trail(kind="kill")
    assert set(data(line["data"])["accounts"]) == {
        "Paper account (practice)",
        "Fake Broker",
    }
    # It stays on until released, and only from the PC.
    with pytest.raises(TradingError):
        await desk.start()
    with pytest.raises(TradingError):
        await desk.release_kill(on_pc=False)
    await desk.release_kill(on_pc=True)
    await desk.start()
    assert desk.config().running
    await desk.close()


@pytest.mark.asyncio
async def test_alert_only_analyses_and_alerts_but_never_orders(make_desk, store):
    desk, _ = make_desk()
    await crypto_only(desk, mode="alert_only")
    desk._save(desk.config().model_copy(update={"running": True}))
    assert not desk.config().live
    await desk._consider(btc(), desk.config())
    assert await store.find(TradeOrder) == ()
    [round_] = await store.find(TradeRound)
    assert round_.status == "alert"
    assert "alert" in await kinds(store)
    [record] = await store.find(TradeDecision)
    assert record.status == "alert" and not record.order_submitted
    await desk.close()


@pytest.mark.asyncio
async def test_each_market_can_trade_on_its_own_verified_account(
    make_desk, fake_platform
):
    desk, _ = make_desk()
    await go_live(desk)
    config = desk.config()
    assert config.broker_for("crypto") == "fake" and config.live_brokers() == ["fake"]
    # A route to an account with no keys or no verification is refused.
    with pytest.raises(TradingError):
        await desk.update_config({"routes": {"us": "alpaca"}}, on_pc=True)
    routed = config.model_copy(update={"routes": {"crypto": "fake"}})
    assert routed.broker_for("crypto") == "fake"
    assert routed.broker_for("us") == "fake"
    assert config.model_copy(update={"mode": "paper"}).broker_for("crypto") == "paper"
    await desk.close()


# ------------------------------------------------------------ S7 execution


@pytest.mark.asyncio
async def test_partial_fills_change_a_position_by_what_is_new_only(
    make_desk, store, fake_platform
):
    desk, _ = make_desk()
    await crypto_only(desk)
    await go_live(desk, "live_auto", LIVE_AUTO_PHRASE)
    desk._save(desk.config().model_copy(update={"running": True}))
    fake_platform.partial = 0.4
    await desk._consider(btc(), desk.config())
    await desk.tick()
    [order] = await store.find(TradeOrder)
    assert order.status == "partially_filled"
    first, total = order.filled_qty, order.qty
    position = await store.get(TradePosition, "fake:BTC")
    assert position is not None and position.qty == pytest.approx(first)
    # The platform reports running totals: the rest fills at 102.
    fake_platform.book[order.client_id] = OrderResult(
        broker_order_id="live-1",
        status="filled",
        client_id=order.client_id,
        symbol="BTC",
        filled_qty=total,
        fill_price=(first * 100.0 + (total - first) * 102.0) / total,
        fees=2.0,
    )
    await desk.tick()
    await desk.tick()
    position = await store.get(TradePosition, "fake:BTC")
    assert position is not None and position.qty == pytest.approx(total)
    fills = await store.find(TradeFill, where={"order_id": order.id})
    assert sum(fill.qty for fill in fills) == pytest.approx(total)
    assert sorted(fill.price or 0 for fill in fills) == pytest.approx([100.0, 102.0])
    # Fees too: the parts add up to the order's total (in the base currency).
    done = await store.get(TradeOrder, order.id)
    assert done is not None and done.fees > 0
    assert sum(fill.fees for fill in fills) == pytest.approx(done.fees)
    # Selling in two parts takes off only what each part sold.
    fake_platform.partial = 0.5
    await desk._exit(position, "a test exit", desk.config(), force=True)
    [sell] = [item for item in await store.find(TradeOrder) if item.side == "sell"]
    assert sell.status == "partially_filled"
    left = await store.get(TradePosition, "fake:BTC")
    assert left is not None and left.qty == pytest.approx(total / 2)
    assert left.cost_base == pytest.approx(position.cost_base / 2)
    fake_platform.book[sell.client_id] = OrderResult(
        broker_order_id="live-2",
        status="filled",
        client_id=sell.client_id,
        symbol="BTC",
        filled_qty=sell.qty,
        fill_price=101.0,
        fees=1.0,
    )
    await desk.tick()
    assert await store.get(TradePosition, "fake:BTC") is None
    await desk.close()


@pytest.mark.asyncio
async def test_an_order_nobody_can_confirm_stays_open_and_pauses_trading(
    make_desk, store, fake_platform, monkeypatch
):
    monkeypatch.setattr(resilience, "LOOKUP_PAUSE_SECONDS", 0.0)
    desk, _ = make_desk()
    await crypto_only(desk)
    await go_live(desk, "live_auto", LIVE_AUTO_PHRASE)
    desk._save(desk.config().model_copy(update={"running": True}))
    fake_platform.lose_answer = True
    fake_platform.unsure = True
    await desk._consider(btc(), desk.config())
    await desk.tick()
    [order] = await store.find(TradeOrder)
    # Not "failed": it may have gone through, so it is never sent again.
    assert order.status == "submitting" and fake_platform.placed == 1
    assert "couldn't match" in desk._entry_block(desk.config()).lower()
    await desk._protect(desk.config())
    assert "circuit breaker" in desk._entry_block(desk.config())
    # A later check that gets an answer matches it, and the cause is gone.
    fake_platform.unsure = False
    desk._last_reconcile = 0.0
    await desk.tick()
    [order] = await store.find(TradeOrder)
    assert order.status == "filled" and fake_platform.placed == 1
    assert desk._unmatched_text() == ""
    assert await store.get(TradePosition, "fake:BTC") is not None
    await desk.close()


@pytest.mark.asyncio
async def test_the_owner_settles_an_order_that_never_matches(
    make_desk, store, fake_platform, monkeypatch
):
    monkeypatch.setattr(resilience, "LOOKUP_PAUSE_SECONDS", 0.0)
    desk, _ = make_desk()
    await crypto_only(desk)
    await go_live(desk, "live_auto", LIVE_AUTO_PHRASE)
    desk._save(desk.config().model_copy(update={"running": True}))
    fake_platform.lose_answer = True
    fake_platform.unsure = True
    await desk._consider(btc(), desk.config())
    await desk.tick()
    await desk._protect(desk.config())
    assert desk._entry_block(desk.config())
    await desk.reset_breaker(on_pc=True)
    [order] = await store.find(TradeOrder)
    assert order.status == "unconfirmed" and "reset" in order.reason
    assert desk._unmatched_text() == ""
    # Still never sent again, and the next checks keep the breaker clear.
    desk._last_reconcile = 0.0
    desk._last_protect = 0.0
    await desk.tick()
    assert fake_platform.placed == 1
    assert desk._entry_block(desk.config()) == ""
    await desk.close()


@pytest.mark.asyncio
async def test_after_a_restart_a_platform_without_order_ids_is_told_what_was_sent(
    make_desk, store, fake_platform
):
    remembered: list[str] = []

    def remember(sent) -> None:
        remembered.append(f"{sent.side} {sent.qty:g} {sent.symbol}")

    desk, _ = make_desk()
    await crypto_only(desk)
    await go_live(desk, "live_auto", LIVE_AUTO_PHRASE)
    fake_platform.remember = remember
    fake_platform.unsure = True
    cut_off = TradeOrder(
        client_id="fcc-cut-off",
        broker="fake",
        mode="live_auto",
        symbol="BTC",
        market="crypto",
        qty=0.01,
        status="submitting",
        data={"sent_at": time.time() - 30},
    )
    await store.put(cut_off)
    await desk.resume()
    assert remembered == ["buy 0.01 BTC"]
    # It can't be matched, so it stays open (not "never reached").
    found = await store.get(TradeOrder, cut_off.id)
    assert found is not None and found.status == "submitting"
    assert "BTC" in desk._unmatched_text()
    await desk.close()


@pytest.mark.asyncio
async def test_platform_stops_stay_until_each_holding_is_actually_sold(
    make_desk, store, fake_platform
):
    desk, _ = make_desk()
    await go_live(desk, "live_auto", LIVE_AUTO_PHRASE)
    await store.put(
        TradePosition(
            id="fake:AAPL",
            broker="fake",
            symbol="AAPL",
            market="us",
            qty=10,
            avg_price=100.0,
            currency="USD",
            cost_base=1500.0,
            stop_loss=90.0,
            take_profit=120.0,
            data={"bracket": True},
        )
    )
    fake_platform.held["AAPL"] = 10
    legs = [
        OrderResult("leg-stop", "submitted", symbol="AAPL", raw={"side": "sell"}),
        OrderResult("leg-target", "submitted", symbol="AAPL", raw={"side": "sell"}),
        OrderResult("buy-msft", "submitted", symbol="MSFT", raw={"side": "buy"}),
    ]
    cancelled: list[str] = []

    async def open_orders() -> list[OrderResult]:
        return [leg for leg in legs if leg.broker_order_id not in cancelled]

    async def cancel(broker_order_id: str) -> None:
        cancelled.append(broker_order_id)

    fake_platform.supports_brackets = True
    fake_platform.open_orders = open_orders
    fake_platform.cancel = cancel
    market = {"open": False}
    desk._is_open = lambda name: market["open"]
    # The kill switch cancels what waits, but a holding's own stop and
    # target on the platform protect it, so they stay.
    await desk.kill(reason="test")
    assert cancelled == ["buy-msft"]
    await desk.release_kill(on_pc=True)
    # Closing everything while the market is shut: nothing can sell yet, so
    # the stop and target stay too.
    await desk.kill(flatten=True, confirm="CLOSE EVERYTHING", reason="test")
    assert cancelled == ["buy-msft"]
    position = await store.get(TradePosition, "fake:AAPL")
    assert position is not None and position.data["bracket"]
    # Once the market opens the sale is tried again, cancelling the
    # platform's stop and target first (it would refuse the sell otherwise).
    market["open"] = True
    desk._exit_tried.clear()
    await desk.tick()
    assert set(cancelled) == {"buy-msft", "leg-stop", "leg-target"}
    position = await store.get(TradePosition, "fake:AAPL")
    assert position is None or not position.data["bracket"]
    assert [
        order.symbol for order in await store.find(TradeOrder) if order.side == "sell"
    ] == ["AAPL"]
    await desk.close()


@pytest.mark.asyncio
async def test_a_cancelled_practice_order_is_recorded_not_left_open(make_desk, store):
    desk, _ = make_desk()
    await crypto_only(desk)
    order = TradeOrder(
        client_id="fcc-wait",
        symbol="BTC",
        market="crypto",
        qty=0.01,
        order_type="limit",
        limit_price=1.0,
        status="submitted",
    )
    await store.put(order)
    waiting = await desk._paper(desk.config()).place(
        OrderRequest(
            client_id="fcc-wait",
            instrument=parse_symbol("BTC"),
            side="buy",
            qty=0.01,
            order_type="limit",
            limit_price=1.0,
        )
    )
    assert waiting.status == "submitted"
    await desk.kill(reason="test")
    await desk.tick()
    found = await store.get(TradeOrder, order.id)
    assert found is not None and found.status == "cancelled"
    await desk.close()


@pytest.mark.asyncio
async def test_the_position_manager_raises_the_stop_and_ends_on_time(make_desk, store):
    desk, _ = make_desk()
    await crypto_only(desk)
    desk._save(desk.config().model_copy(update={"running": True}))
    await desk._consider(btc(), desk.config())
    await desk.tick()
    position = await store.get(TradePosition, "paper:BTC")
    assert position is not None
    plan = position.data["plan"]
    assert plan["entry"] > 0 and plan["holding_days"] >= 1
    # The price has risen by more than the trade risked: stop to the entry.
    risk = plan["entry"] - plan["initial_stop"]
    moved, ended = await desk._manage(
        position,
        Plan.read(plan),
        plan["entry"] + 1.5 * risk,
        move_stop=True,
    )
    assert moved.stop_loss == plan["entry"] and ended == ""
    assert moved.data["mfe_pct"] > 0
    assert "position" in await kinds(store)
    # Past the holding period the watcher sells it, and the record says why.
    later = time.time() + (plan["holding_days"] + 1) * 86_400
    desk._clock = lambda: later
    await desk.tick()
    assert await store.get(TradePosition, "paper:BTC") is None
    [record] = await store.find(TradeDecision)
    result = record.data["result"]
    assert "holding period" in result["exit"]
    assert result["mfe_pct"] > 0 and result["planned_stop"] == plan["initial_stop"]
    await desk.close()


@pytest.mark.asyncio
async def test_a_failing_debrief_is_retried_then_set_aside(make_desk, store):
    desk, _ = make_desk()
    tries: list[int] = []

    async def broken() -> None:
        tries.append(1)
        raise RuntimeError("model offline")

    desk._chores.append(broken)
    await desk._round()
    assert len(tries) == 1 and len(desk._retries) == 1
    # Not due yet: nothing runs; once due it runs again.
    await desk.tick()
    assert len(tries) == 1
    for _ in range(2):
        desk._retries[0].due = 0.0
        await desk.tick()
        assert desk._round_task is not None
        await desk._round_task
    assert len(tries) == 3 and desk._retries == []
    health = await desk.health()
    assert health["dead_letters"] and health["heartbeat_age_s"] is not None
    assert "dead_letter" in {line.kind for line in await store.find(TradeAudit)}
    await desk.close()


@pytest.mark.asyncio
async def test_learned_weights_are_versioned_and_the_owner_can_undo_them(
    make_desk, store
):
    desk, _ = make_desk()
    report = await desk.learning()
    assert report["active_version"] == 0 and report["weights"]["1"] == 1.0
    await store.put(
        TradeWeights(version=1, weights={"1": 1.1, "2": 0.9}, reason="test")
    )
    _, weights = await desk._active_weights()
    assert weights[1] == 1.1 and weights[3] == 1.0
    scored = await desk._seat_records([])
    assert scored[1].weight == 1.1
    with pytest.raises(TradingError):
        await desk.rollback_weights(on_pc=False)
    undone = await desk.rollback_weights(on_pc=True)
    assert undone["active_version"] == 0
    [version] = undone["versions"]
    assert version["status"] == "rolled_back"
    # Nothing to learn from yet: the attempt is kept as rejected, with why.
    await desk._learn(desk.config())
    newest = (await desk.learning())["versions"][0]
    assert newest["status"] == "rejected" and "50 scored" in newest["reason"]
    await desk.close()


@pytest.mark.asyncio
async def test_a_backtest_runs_on_past_prices_and_is_kept(make_desk):
    desk, _ = make_desk()
    result = await desk.backtest(market="crypto", symbols=["BTC"], days=120)
    assert "historical simulation" in str(result["label"]).lower()
    [kept] = await desk.backtests()
    assert kept["id"] == result["id"]
    with pytest.raises(TradingError):
        await desk.backtest(market="forex")
    await desk.close()


@pytest.mark.asyncio
async def test_a_key_that_can_move_money_is_never_verified(make_desk, fake_platform):
    desk, _ = make_desk()
    await desk.save_keys("fake", {"token": "secret-token"})
    fake_platform.permissions = ("view", "trade", "transfer")
    with pytest.raises(TradingError, match="move money"):
        await desk.test_broker("fake")
    fake_platform.permissions = ("view", "trade")
    assert data(await desk.test_broker("fake"))["account"]["permissions"] == [
        "view",
        "trade",
    ]
    await desk.close()


@pytest.mark.asyncio
async def test_keys_that_fail_their_check_switch_real_money_off(
    make_desk, store, fake_platform
):
    desk, _ = make_desk()
    await go_live(desk, "live_auto", LIVE_AUTO_PHRASE)
    desk._save(desk.config().model_copy(update={"running": True}))
    await desk._check_credentials(desk.config())
    assert desk.config().live
    fake_platform.refuse = True
    desk._last_credentials = 0.0
    await desk._check_credentials(desk.config())
    config = desk.config()
    assert config.mode == "paper" and not config.running
    line = (await desk.audit_trail(kind="mode"))[0]
    assert "switched off" in str(line["text"])
    # The secret the platform echoed back never reaches the record.
    assert "secret-token" not in str(line["text"])
    await desk.close()


@pytest.mark.asyncio
async def test_saved_secrets_never_reach_the_feed(make_desk, store, fake_platform):
    desk, _ = make_desk()
    await desk.save_keys("fake", {"token": "secret-token"})
    await desk.feed.emit("error", "Fake Broker said: token secret-token is wrong")
    texts = [event.text for event in await store.find(TradeEvent)]
    assert texts and not any("secret-token" in text for text in texts)
    trail = [line.text for line in await store.find(TradeAudit)]
    assert any("Saved the Fake Broker keys" in text for text in trail)
    await desk.close()


@pytest.mark.asyncio
async def test_practice_keys_never_trade_real_money(
    make_desk, monkeypatch, fake_platform
):
    desk, _ = make_desk()
    monkeypatch.setattr(
        "free_claude_code.studio.trading.desk.environment_of",
        lambda broker_id, values: "practice",
    )
    await desk.save_keys("fake", {"token": "secret-token"})
    shown = data(await desk.test_broker("fake"))
    await desk.confirm_account("fake", shown["account"]["fingerprint"])
    with pytest.raises(TradingError, match="practice account"):
        await desk.update_config({"mode": "live_approve", "broker": "fake"}, on_pc=True)
    await desk.close()


@pytest.mark.asyncio
async def test_practice_end_to_end_partial_fill_restart_exit_and_audit(
    make_desk, store, monkeypatch
):
    # A thin market at first: the buy fills only in part.
    monkeypatch.setattr(fills_module, "PARTICIPATION", 1e-9)
    desk, _ = make_desk()
    await crypto_only(desk)
    desk._save(desk.config().model_copy(update={"running": True}))
    await desk._consider(btc(), desk.config())
    await desk.tick()
    [order] = await store.find(TradeOrder)
    assert order.status == "partially_filled" and 0 < order.filled_qty < order.qty
    first = order.filled_qty
    # FCC restarts: a new desk on the same records matches everything first.
    await desk.close()
    again, _ = make_desk()
    await again._reconcile()
    assert again._unmatched_text() == ""
    # The market deepens: the rest fills, and nothing is sent twice.
    monkeypatch.setattr(fills_module, "PARTICIPATION", 1e9)
    later = time.time() + 120
    again._clock = lambda: later
    await again.tick()
    [order] = await store.find(TradeOrder)
    assert order.status == "filled" and order.filled_qty == pytest.approx(order.qty)
    fills = await store.find(TradeFill, where={"order_id": order.id})
    assert len(fills) == 2 and fills[0].qty + fills[1].qty == pytest.approx(order.qty)
    assert any(fill.qty == pytest.approx(first) for fill in fills)
    paper = json.loads((again._root / "paper.json").read_text())
    assert len(paper["orders"]) == 1
    # The stop is hit: the holding is sold, and the record has the result.
    position = await store.get(TradePosition, "paper:BTC")
    assert position is not None and position.qty == pytest.approx(order.qty)
    await store.put(position.model_copy(update={"stop_loss": position.avg_price * 2}))
    await again.tick()
    assert await store.get(TradePosition, "paper:BTC") is None
    [record] = await store.find(TradeDecision)
    assert record.status == "position_closed" and record.pnl is not None
    assert "stop-loss" in str(record.data["result"]["exit"])
    kinds_seen = {line.kind for line in await store.find(TradeAudit)}
    assert {"order", "fill", "decision"} <= kinds_seen
    await again.close()


@pytest.mark.asyncio
async def test_two_sales_of_one_holding_at_once_sell_it_once(make_desk, store):
    desk, _ = make_desk()
    await crypto_only(desk)
    desk._save(desk.config().model_copy(update={"running": True}))
    await desk._consider(btc(), desk.config())
    await desk.tick()
    position = await store.get(TradePosition, "paper:BTC")
    assert position is not None
    # The loop and the kill switch both try to sell it at the same moment.
    await asyncio.gather(
        desk._exit(position, "the stop-loss was hit", desk.config()),
        desk._exit(position, "the kill switch", desk.config(), force=True),
    )
    assert await store.get(TradePosition, "paper:BTC") is None
    sells = [o for o in await store.find(TradeOrder) if o.side == "sell"]
    assert [o.status for o in sells] == ["filled"]
    await desk.close()
