"""Hyperliquid (Invo's exchange): FCC's own signing matches the official
SDK's test values, only orders/cancels/leverage can be signed, and the
account adapter trades 1x isolated, long only, with exchange-held stops."""

import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from free_claude_code.studio.trading.brokers.base import OrderRequest
from free_claude_code.studio.trading.brokers.hyperliquid import (
    HyperliquidBroker,
    cloid_of,
    price_text,
)
from free_claude_code.studio.trading.hlsign import (
    action_hash,
    keccak256,
    packb,
    private_key,
    sign_action,
    wire,
)
from free_claude_code.studio.trading.instruments import parse_symbol

from .test_trading_brokers import market_data

ROOT = Path(__file__).parents[2]
SDK_TESTS = ROOT / "vendor/hyperliquid-python-sdk/source/signing_test.py.txt"
KEY = private_key("0x0123456789012345678901234567890123456789012345678901234567890123")
DUMMY = {"type": "dummy", "num": 100_000_000_000}
TESTS_ONLY = frozenset({"dummy", "order"})


def order_action(**extra: object) -> dict[str, object]:
    wire_order: dict[str, object] = {
        "a": 1,
        "b": True,
        "p": wire(100),
        "s": wire(100),
        "r": False,
        "t": {"limit": {"tif": "Gtc"}},
    }
    wire_order.update(extra)
    return {"type": "order", "orders": [wire_order], "grouping": "na"}


# (action, mainnet, vault, r, s, v): the SDK's own test values.
VECTORS = [
    (
        DUMMY,
        True,
        None,
        "0x53749d5b30552aeb2fca34b530185976545bb22d0b3ce6f62e31be961a59298",
        "0x755c40ba9bf05223521753995abb2f73ab3229be8ec921f350cb447e384d8ed8",
        27,
    ),
    (
        DUMMY,
        False,
        None,
        "0x542af61ef1f429707e3c76c5293c80d01f74ef853e34b76efffcb57e574f9510",
        "0x17b8b32f086e8cdede991f1e2c529f5dd5297cbe8128500e00cbaf766204a613",
        28,
    ),
    (
        order_action(),
        True,
        None,
        "0xd65369825a9df5d80099e513cce430311d7d26ddf477f5b3a33d2806b100d78e",
        "0x2b54116ff64054968aa237c20ca9ff68000f977c93289157748a3162b6ea940e",
        28,
    ),
    (
        order_action(c="0x00000000000000000000000000000001"),
        True,
        None,
        "0x41ae18e8239a56cacbc5dad94d45d0b747e5da11ad564077fcac71277a946e3",
        "0x3c61f667e747404fe7eea8f90ab0e76cc12ce60270438b2058324681a00116da",
        27,
    ),
    (
        DUMMY,
        True,
        "0x1719884eb866cb12b2287399b15f7db5e7d775ea",
        "0x3c548db75e479f8012acf3000ca3a6b05606bc2ec0c29c50c515066a326239",
        "0x4d402be7396ce74fbba3795769cda45aec00dc3125a984f2a9f23177b190da2c",
        28,
    ),
    (
        order_action(
            t={"trigger": {"isMarket": True, "triggerPx": "103", "tpsl": "sl"}}
        ),
        True,
        None,
        "0x98343f2b5ae8e26bb2587daad3863bc70d8792b09af1841b6fdd530a2065a3f9",
        "0x6b5bb6bb0633b710aa22b721dd9dee6d083646a5f8e581a20b545be6c1feb405",
        27,
    ),
]


@pytest.mark.parametrize(("action", "mainnet", "vault", "r", "s", "v"), VECTORS)
def test_signatures_match_the_official_sdk(action, mainnet, vault, r, s, v):
    signed = sign_action(
        action, KEY, 0, mainnet=mainnet, vault=vault, allowed=TESTS_ONLY
    )
    assert int(str(signed["r"]), 16) == int(r, 16)
    assert int(str(signed["s"]), 16) == int(s, 16)
    assert signed["v"] == v
    # The values come from the vendored SDK tests, kept in the repo.
    assert r in SDK_TESTS.read_text(encoding="utf-8")


def test_the_action_hash_matches_production():
    eth = order_action(a=4, p=wire(1670.1), s=wire(0.0147), t={"limit": {"tif": "Ioc"}})
    assert action_hash(eth, 1677777606040).hex() == (
        "0fcbeda5ae3c4950a548021552a4fea2226858c4453571bf3f24ba017eac2908"
    )


def test_keccak_and_messagepack_basics():
    assert keccak256(b"").hex() == (
        "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
    )
    assert packb({"a": 1, "b": [True, None, -1, 300]}) == (
        b"\x82\xa1a\x01\xa1b\x94\xc3\xc0\xff\xcd\x01\x2c"
    )


@pytest.mark.parametrize("kind", ["withdraw3", "usdSend", "spotSend", "approveAgent"])
def test_money_moves_and_key_changes_are_never_signed(kind: str):
    with pytest.raises(PermissionError):
        sign_action({"type": kind, "amount": "1"}, KEY, 1)


def test_client_ids_and_prices_follow_the_exchange_rules():
    assert cloid_of("fcc-abc") == cloid_of("fcc-abc")
    assert len(cloid_of("fcc-abc")) == 34 and cloid_of("fcc-abc").startswith("0x")
    assert price_text(65432.123, 5) == "65432"
    assert price_text(0.123456789, 0) == "0.12346"


# ------------------------------------------------------------ the adapter

ADDRESS = "0x" + "ab" * 20


class Exchange:
    """A mock Hyperliquid: answers info queries and records signed actions."""

    def __init__(self) -> None:
        self.actions: list[dict[str, object]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if request.url.path == "/exchange":
            action = body["action"]
            assert body["signature"]["v"] in {27, 28}
            self.actions.append(action)
            if action["type"] == "order":
                first = (
                    {"filled": {"totalSz": "0.01", "avgPx": "100.5", "oid": 77}}
                    if action["orders"][0]["t"]["limit"]["tif"] == "Ioc"
                    else {"resting": {"oid": 78}}
                )
                legs = [
                    {"resting": {"oid": 79 + i}}
                    for i in range(len(action["orders"]) - 1)
                ]
                return httpx.Response(
                    200,
                    json={
                        "status": "ok",
                        "response": {
                            "type": "order",
                            "data": {"statuses": [first, *legs]},
                        },
                    },
                )
            return httpx.Response(
                200, json={"status": "ok", "response": {"type": "default"}}
            )
        kind = body["type"]
        if kind == "metaAndAssetCtxs":
            return httpx.Response(
                200,
                json=[
                    {
                        "universe": [
                            {"name": "ETH", "szDecimals": 4},
                            {"name": "BTC", "szDecimals": 5},
                        ]
                    },
                    [
                        {"funding": "0.0000125"},
                        {"funding": "-0.00001", "dayNtlVlm": "1e9"},
                    ],
                ],
            )
        if kind == "l2Book":
            return httpx.Response(
                200,
                json={
                    "coin": body["coin"],
                    "time": int(time.time() * 1000),
                    "levels": [
                        [{"px": "99.9", "sz": "5", "n": 1}],
                        [{"px": "100.1", "sz": "5", "n": 1}],
                    ],
                },
            )
        if kind == "clearinghouseState":
            return httpx.Response(
                200,
                json={
                    "marginSummary": {"accountValue": "1500.5"},
                    "withdrawable": "1200",
                    "assetPositions": [
                        {
                            "position": {
                                "coin": "BTC",
                                "szi": "0.01",
                                "entryPx": "100.5",
                                "positionValue": "1.0",
                            }
                        }
                    ],
                },
            )
        if kind == "orderStatus":
            return httpx.Response(
                200,
                json={
                    "status": "order",
                    "order": {
                        "order": {
                            "coin": "BTC",
                            "oid": 77,
                            "origSz": "0.01",
                            "side": "B",
                        },
                        "status": "filled",
                    },
                },
            )
        if kind == "userFills":
            return httpx.Response(
                200,
                json=[
                    {"oid": 77, "sz": "0.004", "px": "100", "fee": "0.01"},
                    {"oid": 77, "sz": "0.006", "px": "101", "fee": "0.02"},
                    {"oid": 5, "sz": "9", "px": "1", "fee": "9"},
                ],
            )
        if kind == "openOrders":
            return httpx.Response(200, json=[{"coin": "BTC", "oid": 79, "side": "A"}])
        return httpx.Response(404, json={})


def broker(exchange: Exchange) -> HyperliquidBroker:
    return HyperliquidBroker(
        {
            "address": ADDRESS,
            "agent_key": "0x0123456789012345678901234567890123456789012345678901234567890123",
            "environment": "testnet",
        },
        market_data(),
        httpx.MockTransport(exchange),
    )


def request(
    side: str, *, stop: float | None = None, target: float | None = None
) -> OrderRequest:
    return OrderRequest(
        client_id="fcc-test",
        instrument=parse_symbol("BTC"),
        side="sell" if side == "sell" else "buy",
        qty=0.01,
        stop_loss=stop,
        take_profit=target,
    )


def orders_of(action: dict[str, object]) -> list[dict[str, Any]]:
    found = action["orders"]
    assert isinstance(found, list)
    return [dict(item) for item in found if isinstance(item, dict)]


@pytest.mark.asyncio
async def test_a_buy_is_1x_isolated_with_the_stop_and_target_on_the_exchange():
    exchange = Exchange()
    hl = broker(exchange)
    assert not hl.live and hl.name == "Hyperliquid (testnet)"
    result = await hl.place(request("buy", stop=95.0, target=110.0))
    leverage, order = exchange.actions
    assert leverage == {
        "type": "updateLeverage",
        "asset": 1,
        "isCross": False,
        "leverage": 1,
    }
    assert order["grouping"] == "normalTpsl"
    entry, target, stop = orders_of(order)
    assert (
        entry["b"] is True
        and entry["r"] is False
        and entry["c"] == cloid_of("fcc-test")
    )
    assert entry["t"] == {"limit": {"tif": "Ioc"}} and float(entry["p"]) > 100.1
    assert target["r"] is True and target["t"]["trigger"]["tpsl"] == "tp"
    assert stop["r"] is True and stop["t"]["trigger"]["tpsl"] == "sl"
    assert result.status == "filled" and result.raw["bracket"] is True
    assert result.fill_price == 100.5 and result.raw["fees_reported"] is False
    await hl.aclose()


@pytest.mark.asyncio
async def test_a_sell_only_ever_reduces_a_position():
    exchange = Exchange()
    hl = broker(exchange)
    await hl.place(request("sell"))
    [order] = exchange.actions
    [sell] = orders_of(order)
    assert sell["b"] is False and sell["r"] is True
    assert order["grouping"] == "na"
    await hl.aclose()


@pytest.mark.asyncio
async def test_lost_answers_are_found_by_client_id_with_fees_from_the_fills():
    hl = broker(Exchange())
    found = await hl.find("fcc-test")
    assert found is not None and found.status == "filled"
    assert found.filled_qty == pytest.approx(0.01)
    assert found.fill_price == pytest.approx(100.6)
    assert found.fees == pytest.approx(0.03)
    account = await hl.account()
    assert account.equity == 1500.5 and account.cash == 1200
    assert account.permissions == ("view", "trade") and not account.live
    [holding] = await hl.positions()
    assert holding.symbol == "BTC" and holding.qty == 0.01
    rules = await hl.rules(parse_symbol("BTC"))
    assert rules.tradable and rules.qty_step == pytest.approx(0.00001)
    quote = await hl.quote(parse_symbol("BTC"))
    assert quote is not None and quote.bid == 99.9 and quote.ask == 100.1
    assert "funding" in quote.note and quote.stamped
    [leg] = await hl.open_orders()
    assert leg.raw["side"] == "sell" and leg.broker_order_id == "BTC:79"
    await hl.aclose()
