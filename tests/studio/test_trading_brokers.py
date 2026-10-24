"""Every trading platform adapter on a mock network: signing, the requests it
sends, how it reads answers, and how it finds an order after a lost answer."""

import base64
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from free_claude_code.studio.resilience import ServiceError, Web
from free_claude_code.studio.trading.brokers.alpaca import AlpacaBroker
from free_claude_code.studio.trading.brokers.base import OrderRequest, Sent
from free_claude_code.studio.trading.brokers.btcmarkets import BtcMarketsBroker
from free_claude_code.studio.trading.brokers.btcmarkets import sign as btcm_sign
from free_claude_code.studio.trading.brokers.catalog import PLATFORMS, ensure_catalog
from free_claude_code.studio.trading.brokers.coinbase import CoinbaseBroker, jwt_token
from free_claude_code.studio.trading.brokers.coinspot import CoinSpotBroker
from free_claude_code.studio.trading.brokers.ibkr import IbkrBroker
from free_claude_code.studio.trading.brokers.independent_reserve import (
    IndependentReserveBroker,
    signature,
)
from free_claude_code.studio.trading.brokers.kraken import (
    KrakenBroker,
    kraken_client_id,
    sign,
)
from free_claude_code.studio.trading.brokers.registry import (
    BROKERS,
    BrokerSetupError,
    check_values,
    make_broker,
)
from free_claude_code.studio.trading.brokers.swyftx import SwyftxBroker
from free_claude_code.studio.trading.brokers.webhook import WebhookBroker, dig, render
from free_claude_code.studio.trading.data import MarketData
from free_claude_code.studio.trading.instruments import parse_symbol


def data(value: object) -> Any:
    return value


def market_data(handler=None) -> MarketData:
    def offline(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    return MarketData(
        Web(transport=httpx.MockTransport(handler or offline), attempts=1)
    )


def iso(seconds: float) -> str:
    """A time as CoinSpot writes it (ISO 8601, UTC)."""
    return datetime.fromtimestamp(seconds, tz=UTC).isoformat().replace("+00:00", "Z")


def order(symbol: str, qty: float, *, side: str = "buy", **extra: Any) -> OrderRequest:
    return OrderRequest(
        client_id="fcc-abc123",
        instrument=parse_symbol(symbol),
        side="sell" if side == "sell" else "buy",
        qty=qty,
        **extra,
    )


class Recorder:
    """A mock platform: answers by path and keeps every request it saw."""

    def __init__(self, routes: dict[str, Any]) -> None:
        self.routes = routes
        self.seen: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        key = f"{request.method} {request.url.path}"
        answer = self.routes.get(key, self.routes.get(request.url.path))
        if answer is None:
            return httpx.Response(404, json={"message": "not found"})
        if callable(answer):
            answer = answer(request)
        if isinstance(answer, httpx.Response):
            return answer
        return httpx.Response(200, json=answer)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    def last(self, path: str) -> httpx.Request:
        return [request for request in self.seen if request.url.path == path][-1]


# ------------------------------------------------------------ the catalogue


def test_every_platform_is_offered_with_australian_notes():
    ensure_catalog()
    ids = {spec.id for spec in PLATFORMS}
    assert ids == {
        "alpaca",
        "ibkr",
        "kraken",
        "coinbase",
        "btcmarkets",
        "independentreserve",
        "coinspot",
        "swyftx",
        "hyperliquid",
        "webhook",
    }
    for spec in PLATFORMS:
        assert BROKERS[spec.id] is spec
        assert spec.australia and spec.get_keys and spec.factory is not None
        if spec.id != "webhook" and any(field.secret for field in spec.fields):
            # Exchange keys never need withdrawal rights.
            assert "withdrawal" in spec.get_keys
    view = data(
        BROKERS["kraken"].view({"api_key": "k", "api_secret": "s", "quote": "AUD"})
    )
    assert view["connected"]
    assert [f["value"] for f in view["fields"]] == ["", "", "AUD"]
    with pytest.raises(BrokerSetupError, match="must be one of"):
        check_values("kraken", {"quote": "EUR"})
    with pytest.raises(BrokerSetupError, match="needs: API key"):
        make_broker("kraken", {}, data=market_data())
    with pytest.raises(BrokerSetupError, match="must run on this PC"):
        make_broker("ibkr", {"gateway": "https://example.com:5000"}, data=market_data())


# ------------------------------------------------------------ Alpaca


@pytest.mark.asyncio
async def test_alpaca_brackets_whole_shares_and_finds_orders_by_client_id():
    platform = Recorder(
        {
            "GET /v2/account": {
                "account_number": "PA1234567",
                "status": "ACTIVE",
                "currency": "USD",
                "equity": "10000",
                "cash": "8000",
                "buying_power": "16000",
                "daytrade_count": 2,
                "pattern_day_trader": False,
            },
            "GET /v2/assets/AAPL": {
                "tradable": True,
                "status": "active",
                "fractionable": True,
            },
            "POST /v2/orders": lambda request: httpx.Response(
                200,
                json={
                    "id": "ord-1",
                    "client_order_id": json.loads(request.content)["client_order_id"],
                    "status": "accepted",
                    "symbol": "AAPL",
                    "filled_qty": "0",
                },
            ),
            "GET /v2/orders:by_client_order_id": {
                "id": "ord-1",
                "client_order_id": "fcc-abc123",
                "status": "filled",
                "symbol": "AAPL",
                "filled_qty": "3",
                "filled_avg_price": "190.5",
            },
        }
    )
    broker = AlpacaBroker(
        {"key_id": "PK1", "secret": "sk", "account": "paper"},
        market_data(),
        platform.transport(),
    )
    account = await broker.account()
    assert account.number == "PA1234567" and account.status == "active"
    assert account.day_trades == 2 and broker.name == "Alpaca (paper)"
    placed = await broker.place(order("AAPL", 3, stop_loss=180.0, take_profit=210.0))
    sent = json.loads(platform.last("/v2/orders").content)
    assert sent["order_class"] == "bracket" and sent["time_in_force"] == "gtc"
    assert sent["stop_loss"] == {"stop_price": "180"}
    assert sent["take_profit"] == {"limit_price": "210"}
    assert platform.last("/v2/orders").headers["APCA-API-KEY-ID"] == "PK1"
    assert placed.raw["bracket"] is True and placed.status == "submitted"
    fractional = await broker.place(
        order("AAPL", 0.5, stop_loss=180.0, take_profit=210.0)
    )
    assert json.loads(platform.last("/v2/orders").content).get("order_class") is None
    assert fractional.raw["bracket"] is False
    found = await broker.find("fcc-abc123")
    assert found is not None and found.status == "filled" and found.fill_price == 190.5
    crypto = await broker.rules(parse_symbol("BTC"))
    assert not crypto.tradable
    assert (await broker.rules(parse_symbol("BHP.AX"))).note.startswith(
        "Alpaca trades US"
    )
    await broker.aclose()


# ------------------------------------------------------------ Kraken


def test_kraken_signs_like_its_documented_example():
    assert (
        sign(
            "/0/private/AddOrder",
            "nonce=1616492376594&ordertype=limit&pair=XBTUSD&price=37500&type=buy&volume=1.25",
            "1616492376594",
            "kQH5HW/8p1uGOVjbgWA7FunAmGO8lsSUXNsu3eow76sz84Q18fWxnyRzBHCd3pd5nE9qa99HAZtuZuj6F1huXg==",
        )
        == "4/dpxb3iT4tp/ZCVEwSnEsLxx0bqyhLpdfOpc6fn7OR8+UClSV5n9E6aSS8MPtnRfp32bAb0nmbRn6H8ndwLUQ=="
    )
    assert (
        kraken_client_id("fcc-1")
        == kraken_client_id("fcc-1")
        != kraken_client_id("fcc-2")
    )
    assert len(kraken_client_id("fcc-1")) == 36


@pytest.mark.asyncio
async def test_kraken_trades_aud_pairs_and_finds_by_client_id():
    secret = base64.b64encode(b"secret-bytes").decode()
    pairs = {
        "XXBTZAUD": {
            "altname": "XBTAUD",
            "quote": "ZAUD",
            "lot_decimals": 8,
            "ordermin": "0.0001",
            "status": "online",
        },
        "XDGUSD": {
            "altname": "XDGUSD",
            "quote": "ZUSD",
            "lot_decimals": 8,
            "ordermin": "50",
            "status": "online",
        },
    }
    platform = Recorder(
        {
            "GET /0/public/AssetPairs": {"error": [], "result": pairs},
            "POST /0/private/AddOrder": {
                "error": [],
                "result": {
                    "txid": ["OABC-123"],
                    "descr": {"order": "buy 0.01 XBTAUD @ market"},
                },
            },
            "POST /0/private/OpenOrders": {"error": [], "result": {"open": {}}},
            "POST /0/private/ClosedOrders": {
                "error": [],
                "result": {
                    "closed": {
                        "OABC-123": {
                            "status": "closed",
                            "vol_exec": "0.01",
                            "price": "95000",
                            "fee": "2.5",
                            "cl_ord_id": kraken_client_id("fcc-abc123"),
                            "descr": {"pair": "XBTAUD"},
                        }
                    }
                },
            },
            "POST /0/private/Balance": {"error": ["EAPI:Invalid key"]},
        }
    )
    broker = KrakenBroker(
        {"api_key": "key", "api_secret": secret, "quote": "AUD"},
        market_data(),
        platform.transport(),
        clock=lambda: 1_700_000_000.0,
    )
    rules = await broker.rules(parse_symbol("BTC"))
    assert (
        rules.broker_symbol == "XBTAUD"
        and rules.min_qty == 0.0001
        and rules.qty_step == 1e-8
    )
    assert (await broker.rules(parse_symbol("DOGE"))).broker_symbol == "XDGUSD"
    placed = await broker.place(order("BTC", 0.01))
    sent = platform.last("/0/private/AddOrder")
    form = {key: values[0] for key, values in parse_qs(sent.content.decode()).items()}
    assert (
        form["pair"] == "XBTAUD" and form["type"] == "buy" and form["volume"] == "0.01"
    )
    assert form["cl_ord_id"] == kraken_client_id("fcc-abc123")
    assert sent.headers["API-Sign"] == sign(
        "/0/private/AddOrder", sent.content.decode(), form["nonce"], secret
    )
    assert placed.broker_order_id == "OABC-123" and placed.raw["currency"] == "AUD"
    found = await broker.find("fcc-abc123")
    assert found is not None and found.status == "filled" and found.fees == 2.5
    assert found.raw["currency"] == "AUD"
    with pytest.raises(Exception, match="Invalid key"):
        await broker.account()
    await broker.aclose()


# ------------------------------------------------------------ Coinbase


def test_coinbase_tokens_are_signed_jwts():
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()
    token = jwt_token(
        "organizations/o/apiKeys/k",
        pem,
        "POST",
        "/api/v3/brokerage/orders",
        now=1000.0,
        nonce="n1",
    )
    head, body, signed = token.split(".")

    def decode(part: str) -> Any:
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))

    assert decode(head) == {
        "alg": "ES256",
        "kid": "organizations/o/apiKeys/k",
        "nonce": "n1",
        "typ": "JWT",
    }
    claims = decode(body)
    assert claims["uri"] == "POST api.coinbase.com/api/v3/brokerage/orders"
    assert claims["iss"] == "cdp" and claims["exp"] - claims["nbf"] == 120
    raw = base64.urlsafe_b64decode(signed + "=" * (-len(signed) % 4))
    der = encode_dss_signature(
        int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")
    )
    key.public_key().verify(der, f"{head}.{body}".encode(), ec.ECDSA(hashes.SHA256()))


@pytest.mark.asyncio
async def test_coinbase_refusals_are_clear():
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()
    platform = Recorder(
        {
            "GET /api/v3/brokerage/products/BTC-USD": {
                "product_id": "BTC-USD",
                "base_increment": "0.00000001",
                "base_min_size": "0.00001",
                "status": "online",
            },
            "POST /api/v3/brokerage/orders": {
                "success": False,
                "error_response": {"message": "Insufficient balance in source account"},
            },
        }
    )
    broker = CoinbaseBroker(
        {"key_name": "organizations/o/apiKeys/k", "private_key": pem},
        market_data(),
        platform.transport(),
    )
    with pytest.raises(Exception, match="Insufficient balance"):
        await broker.place(order("BTC", 0.001))
    sent = json.loads(platform.last("/api/v3/brokerage/orders").content)
    assert sent["client_order_id"] == "fcc-abc123"
    assert sent["order_configuration"] == {"market_market_ioc": {"base_size": "0.001"}}
    assert (
        platform.last("/api/v3/brokerage/orders")
        .headers["Authorization"]
        .startswith("Bearer ")
    )
    await broker.aclose()


# ------------------------------------------------------------ BTC Markets and Independent Reserve


@pytest.mark.asyncio
async def test_btc_markets_signs_and_reads_fills_from_trades():
    secret = base64.b64encode(b"bm-secret").decode()
    platform = Recorder(
        {
            "GET /v3/markets": [
                {
                    "marketId": "BTC-AUD",
                    "minOrderAmount": "0.0001",
                    "amountDecimals": "8",
                    "status": "Online",
                }
            ],
            "POST /v3/orders": {
                "orderId": "77",
                "clientOrderId": "fcc-abc123",
                "marketId": "BTC-AUD",
                "amount": "0.01",
                "openAmount": "0",
                "status": "Fully Matched",
            },
            "GET /v3/orders": [
                {
                    "orderId": "77",
                    "clientOrderId": "fcc-abc123",
                    "marketId": "BTC-AUD",
                    "amount": "0.01",
                    "openAmount": "0",
                    "status": "Fully Matched",
                }
            ],
            "GET /v3/trades": [
                {"price": "100000", "amount": "0.004", "fee": "1.2"},
                {"price": "100100", "amount": "0.006", "fee": "1.8"},
            ],
        }
    )
    broker = BtcMarketsBroker(
        {"api_key": "k", "api_secret": secret}, market_data(), platform.transport()
    )
    placed = await broker.place(order("BTC", 0.01))
    request = platform.last("/v3/orders")
    body = request.content.decode()
    assert json.loads(body)["side"] == "Bid" and json.loads(body)["type"] == "Market"
    stamp = request.headers["BM-AUTH-TIMESTAMP"]
    assert request.headers["BM-AUTH-SIGNATURE"] == btcm_sign(
        "POST", "/v3/orders", stamp, body, secret
    )
    expected = base64.b64encode(
        hmac.new(
            base64.b64decode(secret),
            f"POST/v3/orders{stamp}{body}".encode(),
            hashlib.sha512,
        ).digest()
    ).decode()
    assert request.headers["BM-AUTH-SIGNATURE"] == expected
    assert placed.status == "filled" and placed.filled_qty == 0.01
    found = await broker.find("fcc-abc123")
    assert found is not None and found.fees == pytest.approx(3.0)
    assert found.fill_price == pytest.approx(100060.0)
    await broker.aclose()


@pytest.mark.asyncio
async def test_independent_reserve_signs_parameters_in_order():
    platform = Recorder(
        {
            "GET /Public/GetOrderMinimumVolumes": {"Xbt": 0.0001, "Doge": 10},
            "POST /Private/PlaceMarketOrder": {
                "OrderGuid": "g-1",
                "Status": "Filled",
                "VolumeFilled": 0.01,
                "AvgPrice": 99000,
                "FeePercent": 0.005,
                "PrimaryCurrencyCode": "Xbt",
            },
            "POST /Private/GetOrderDetails": {
                "OrderGuid": "g-1",
                "Status": "Filled",
                "VolumeFilled": 0.01,
                "AvgPrice": 99000,
                "PrimaryCurrencyCode": "Xbt",
            },
        }
    )
    broker = IndependentReserveBroker(
        {"api_key": "ir-key", "api_secret": "ir-secret"},
        market_data(),
        platform.transport(),
        clock=lambda: 1_700_000_000.0,
    )
    placed = await broker.place(order("BTC", 0.01))
    sent = json.loads(platform.last("/Private/PlaceMarketOrder").content)
    assert sent["primaryCurrencyCode"] == "Xbt" and sent["orderType"] == "MarketBid"
    assert sent["clientId"] == "fcc-abc123"
    expected = signature(
        "https://api.independentreserve.com/Private/PlaceMarketOrder",
        "ir-key",
        sent["nonce"],
        [
            ("primaryCurrencyCode", "Xbt"),
            ("secondaryCurrencyCode", "Aud"),
            ("orderType", "MarketBid"),
            ("volume", "0.01"),
            ("clientId", "fcc-abc123"),
        ],
        "ir-secret",
    )
    assert sent["signature"] == expected and expected.isupper()
    assert placed.status == "filled" and placed.fees == pytest.approx(
        0.005 * 0.01 * 99000
    )
    assert (await broker.find("fcc-abc123")) is not None
    await broker.aclose()


# ------------------------------------------------------------ CoinSpot and Swyftx


@pytest.mark.asyncio
async def test_coinspot_signs_the_body_and_finds_instant_fills():
    platform = Recorder(
        {
            "GET /pubapi/v2/latest/PEPE": {
                "status": "ok",
                "prices": {"bid": "0.000019", "ask": "0.000020", "last": "0.0000195"},
            },
            "POST /api/v2/my/buy/now": httpx.Response(504),
            "POST /api/v2/ro/my/orders/market/completed": {
                "status": "ok",
                "buyorders": [
                    # The same size an hour earlier: an older order, not this.
                    {
                        "id": "cs-1",
                        "coin": "PEPE",
                        "amount": 1000000,
                        "audtotal": 30.0,
                        "solddate": iso(time.time() - 3600),
                    },
                    {
                        "id": "cs-9",
                        "coin": "PEPE",
                        "amount": 1000000,
                        "audtotal": 19.5,
                        "solddate": iso(time.time() + 1),
                    },
                ],
                "sellorders": [],
            },
        }
    )
    broker = CoinSpotBroker(
        {"api_key": "cs-key", "api_secret": "cs-secret"},
        market_data(),
        platform.transport(),
    )
    with pytest.raises(Exception, match="504"):
        await broker.place(order("PEPE", 1_000_000))
    sent = platform.last("/api/v2/my/buy/now")
    assert sent.headers["key"] == "cs-key"
    assert (
        sent.headers["sign"]
        == hmac.new(b"cs-secret", sent.content, hashlib.sha512).hexdigest()
    )
    body = json.loads(sent.content)
    assert (
        body["amounttype"] == "coin"
        and body["threshold"] == 1.0
        and body["direction"] == "UP"
    )
    # The answer was lost: the order is found among completed ones.
    found = await broker.find("fcc-abc123")
    assert found is not None and found.status == "filled"
    assert found.broker_order_id == "cs-9"
    assert found.fill_price == pytest.approx(0.0000195)
    await broker.aclose()


@pytest.mark.asyncio
async def test_coinspot_never_guesses_after_a_restart():
    completed = {
        "status": "ok",
        "buyorders": [
            {
                "id": "cs-1",
                "coin": "PEPE",
                "amount": 1000000,
                "audtotal": 30.0,
                "solddate": iso(time.time() - 3600),
            },
            # No readable time: it can't be told apart from an older order.
            {"id": "cs-2", "coin": "PEPE", "amount": 1000000, "audtotal": 30.0},
        ],
        "sellorders": [],
    }
    platform = Recorder({"POST /api/v2/ro/my/orders/market/completed": completed})
    broker = CoinSpotBroker(
        {"api_key": "cs-key", "api_secret": "cs-secret"},
        market_data(),
        platform.transport(),
    )
    # A fresh start knows nothing of the order until it is told.
    assert await broker.find("fcc-abc123") is None
    broker.remember(Sent("fcc-abc123", "PEPE", "buy", 1_000_000, time.time() - 5))
    with pytest.raises(ServiceError, match="no completed PEPE buy"):
        await broker.find("fcc-abc123")
    await broker.aclose()


@pytest.mark.asyncio
async def test_swyftx_swaps_the_key_for_a_token_and_places_in_aud():
    platform = Recorder(
        {
            "POST /auth/refresh/": {"accessToken": "tok-1"},
            "GET /markets/assets/": [
                {"id": 1, "code": "AUD"},
                {"id": 3, "code": "BTC"},
            ],
            "POST /orders/": {
                "orderUuid": "ord_1",
                "order": {"status": 4, "amount": "0.01", "rate": "98000"},
            },
            "GET /orders/byId/ord_1/": {"status": 4, "amount": "0.01", "rate": "98000"},
        }
    )
    broker = SwyftxBroker({"api_key": "sw-key"}, market_data(), platform.transport())
    assert broker.name == "Swyftx (demo)"
    placed = await broker.place(order("BTC", 0.01))
    sent = platform.last("/orders/")
    assert sent.url.host == "api.demo.swyftx.com.au"
    assert sent.headers["Authorization"] == "Bearer tok-1"
    assert json.loads(sent.content) == {
        "primary": "AUD",
        "secondary": "BTC",
        "quantity": "0.01",
        "assetQuantity": "BTC",
        "orderType": 1,
    }
    assert placed.status == "filled" and placed.fill_price == 98000
    found = await broker.find("fcc-abc123")
    assert found is not None and found.broker_order_id == "ord_1"
    await broker.aclose()


@pytest.mark.asyncio
async def test_swyftx_matches_only_a_later_order_on_the_same_side():
    now = time.time()
    platform = Recorder(
        {
            "POST /auth/refresh/": {"accessToken": "tok-1"},
            "GET /orders/": [
                # A sell of the same size: the other side, not this.
                {
                    "orderUuid": "ord_s",
                    "quantity": "0.01",
                    "order_type": 2,
                    "created_time": (now + 1) * 1000,
                    "status": 4,
                },
                # The same size before it was sent: an older order.
                {
                    "orderUuid": "ord_old",
                    "quantity": "0.01",
                    "order_type": 1,
                    "created_time": (now - 3600) * 1000,
                    "status": 4,
                },
            ],
        }
    )
    broker = SwyftxBroker({"api_key": "sw-key"}, market_data(), platform.transport())
    broker.remember(Sent("fcc-abc123", "BTC", "buy", 0.01, now - 5))
    with pytest.raises(ServiceError, match="no recent BTC buy"):
        await broker.find("fcc-abc123")
    # Its own id, when FCC kept it, is asked about directly.
    platform.routes["GET /orders/byId/ord_9/"] = {
        "status": 4,
        "amount": "0.01",
        "rate": "98000",
    }
    broker.remember(Sent("fcc-def456", "BTC", "buy", 0.01, now - 5, "ord_9"))
    found = await broker.find("fcc-def456")
    assert found is not None and found.status == "filled"
    await broker.aclose()


# ------------------------------------------------------------ IBKR


@pytest.mark.asyncio
async def test_ibkr_finds_asx_shares_and_never_confirms_warnings_itself():
    platform = Recorder(
        {
            "POST /v1/api/iserver/auth/status": {
                "authenticated": True,
                "connected": True,
            },
            "POST /v1/api/tickle": {},
            "GET /v1/api/iserver/accounts": {
                "accounts": ["U7654321"],
                "selectedAccount": "U7654321",
            },
            "GET /v1/api/portfolio/U7654321/summary": {
                "netliquidation": {"amount": 25000, "currency": "AUD"},
                "totalcashvalue": {"amount": 5000, "currency": "AUD"},
                "buyingpower": {"amount": 5000, "currency": "AUD"},
            },
            "GET /v1/api/trsrv/stocks": {
                "BHP": [
                    {
                        "assetClass": "STK",
                        "contracts": [
                            {"conid": 4036812, "exchange": "ASX", "isUS": False},
                            {"conid": 11111, "exchange": "NYSE", "isUS": True},
                        ],
                    }
                ]
            },
            "POST /v1/api/iserver/account/U7654321/orders": [
                {
                    "id": "reply-1",
                    "message": ["This order exceeds 10% of your net liquidation."],
                }
            ],
            "POST /v1/api/iserver/reply/reply-1": [
                {"order_id": "555", "order_status": "Submitted"}
            ],
        }
    )
    broker = IbkrBroker(
        {"gateway": "https://localhost:5000"}, market_data(), platform.transport()
    )
    account = await broker.account()
    assert (
        account.number == "U7654321"
        and account.currency == "AUD"
        and account.equity == 25000
    )
    rules = await broker.rules(parse_symbol("BHP.AX"))
    assert (
        rules.broker_symbol == "4036812"
        and not rules.fractional
        and rules.min_value == 500
    )
    placed = await broker.place(order("BHP.AX", 20))
    sent = json.loads(platform.last("/v1/api/iserver/account/U7654321/orders").content)
    assert sent["orders"][0] == {
        "conid": 4036812,
        "orderType": "MKT",
        "side": "BUY",
        "quantity": 20,
        "tif": "DAY",
        "cOID": "fcc-abc123",
    }
    assert (
        placed.status == "needs_reply" and "10% of your net liquidation" in placed.note
    )
    assert not [r for r in platform.seen if "/reply/" in r.url.path]
    confirmed = await broker.answer_reply(
        data(placed.raw["reply"]), "fcc-abc123", "BHP.AX"
    )
    assert confirmed.status == "submitted" and confirmed.broker_order_id == "555"
    await broker.aclose()


@pytest.mark.asyncio
async def test_ibkr_asks_to_log_in_first():
    platform = Recorder({"POST /v1/api/iserver/auth/status": {"authenticated": False}})
    broker = IbkrBroker(
        {"gateway": "https://localhost:5000"}, market_data(), platform.transport()
    )
    with pytest.raises(Exception, match="Log in to the IBKR gateway"):
        await broker.account()
    await broker.aclose()


# ------------------------------------------------------------ webhook


def test_webhook_templates_keep_numbers_as_numbers():
    filled = render(
        {
            "ticker": "{code}",
            "qty": "{qty}",
            "note": "buy {qty} {code}",
            "nested": [{"stop": "{stop}"}],
        },
        {"code": "BHP", "qty": 20, "stop": 42.5},
    )
    assert filled == {
        "ticker": "BHP",
        "qty": 20,
        "note": "buy 20 BHP",
        "nested": [{"stop": 42.5}],
    }
    assert dig({"data": {"balances": [{"equity": 5}]}}, "data.balances.0.equity") == 5


@pytest.mark.asyncio
async def test_a_webhook_signs_its_signal_and_never_sends_twice():
    platform = Recorder({"POST /hooks/trade": httpx.Response(500, text="oops")})
    broker = WebhookBroker(
        {
            "url": "https://signals.example/hooks/trade",
            "secret": "s3cret",
            "account_size": "5000",
        },
        market_data(),
        platform.transport(),
    )
    account = await broker.account()
    assert account.equity == 5000 and account.currency == "AUD"
    with pytest.raises(Exception, match="500"):
        await broker.place(
            order("BHP.AX", 20, order_type="limit", limit_price=45.0, stop_loss=42.0)
        )
    sent = platform.last("/hooks/trade")
    body = json.loads(sent.content)
    assert body["ticker"] == "BHP" and body["quantity"] == 20 and body["price"] == 45.0
    assert body["stopLoss"] == {"stopPrice": 42.0}
    assert sent.headers["Authorization"] == "Bearer s3cret"
    assert (
        sent.headers["X-FCC-Signature"]
        == hmac.new(b"s3cret", sent.content, hashlib.sha256).hexdigest()
    )
    # It may have arrived: looking it up refuses rather than allowing a resend.
    with pytest.raises(Exception, match="not sent again"):
        await broker.find("fcc-abc123")
    # The same after a restart, once FCC says it may have been posted.
    restarted = WebhookBroker(
        {"url": "https://signals.example/hooks/trade", "account_size": "5000"},
        market_data(),
        platform.transport(),
    )
    restarted.remember(Sent("fcc-abc123", "BHP.AX", "buy", 20, time.time()))
    with pytest.raises(Exception, match="not sent again"):
        await restarted.find("fcc-abc123")
    await restarted.aclose()
    ok = Recorder({"POST /hooks/trade": {"id": "tp-1"}})
    sender = WebhookBroker(
        {"url": "https://signals.example/hooks/trade", "account_size": "5000"},
        market_data(),
        ok.transport(),
    )
    result = await sender.place(
        order("BHP.AX", 20, order_type="limit", limit_price=45.0)
    )
    assert (
        result.status == "filled"
        and result.raw["unconfirmed"]
        and result.broker_order_id == "tp-1"
    )
    assert await sender.find("fcc-abc123") == result
    await broker.aclose()
    await sender.aclose()
