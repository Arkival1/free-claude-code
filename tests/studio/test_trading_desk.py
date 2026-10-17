"""The trading desk end to end: scripted seats on made-up market data, through
the debate, the risk period, cooling-off, the hard limits, the account check,
and the order modes; plus exits, debriefs, the kill switch, and restarts."""

import hashlib
import json
import math
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import httpx
import pytest

from free_claude_code.studio.connectors import ConnectorStore
from free_claude_code.studio.memory import MemoryService
from free_claude_code.studio.resilience import ServiceError
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
from free_claude_code.studio.trading.desk import ASKED, TradingDesk, TradingError
from free_claude_code.studio.trading.instruments import Instrument, parse_symbol
from free_claude_code.studio.trading.records import (
    TradeDebrief,
    TradeEvent,
    TradeEvidence,
    TradeForecast,
    TradeOrder,
    TradePosition,
    TradeRound,
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


def levels(prompt: str) -> dict[str, float]:
    """A plan around the price in the prompt: stop 2 ATR below, target 5 ATR
    above (reward-to-risk 2.5)."""
    price = number_after("PRICE NOW", prompt)
    atr_value = number_after("ATR", prompt)
    return {
        "entry_low": round(price * 0.999, 6),
        "entry_high": round(price * 1.001, 6),
        "stop_loss": round(price - 2 * atr_value, 6),
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
        self, *, action: str = "buy", grade: str = "B", defer: bool = False
    ) -> None:
        self.action = action
        self.grade = grade
        self.defer = defer
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
                    **levels(prompt),
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

    def markets(self) -> frozenset[str]:
        return frozenset({"us", "asx", "crypto"})

    async def account(self) -> Account:
        return Account(
            number="U1234567",
            fingerprint=fingerprint("fake", "U1234567"),
            currency="AUD",
            equity=self.cash,
            cash=self.cash,
            buying_power=self.cash,
            live=True,
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
        result = OrderResult(
            broker_order_id=f"live-{self.placed}",
            status="filled",
            client_id=order.client_id,
            symbol=order.instrument.symbol,
            filled_qty=order.qty,
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
        return self.book.get(client_id)

    async def cancel(self, broker_order_id: str) -> None:
        return None

    async def open_orders(self) -> list[OrderResult]:
        return []

    async def aclose(self) -> None:
        return None


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
            keys=ConnectorStore(tmp_path / "trading-keys.json"),
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
    assert desk.config().running is False
    assert desk._loop_task is None
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
