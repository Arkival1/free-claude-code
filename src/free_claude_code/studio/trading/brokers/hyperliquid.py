"""Hyperliquid (beta): coin perpetual futures, the exchange the Invo app
trades on.

Invo has no public API; it is non-custodial and routes its trades to
Hyperliquid. To let the desk trade the same account Invo uses, the owner
creates an API wallet for that account on app.hyperliquid.xyz and pastes
its private key here (with the account's address). An API wallet can place
and cancel orders but can't withdraw: withdrawals need the main wallet's
own signature. FCC also refuses to sign anything but orders, cancels and
the leverage setting (see ``hlsign``).

Safety, on top of every check the desk already makes:
- 1x leverage only, isolated margin, set before the first order in a coin:
  no borrowed money, and a loss can't spread to the rest of the account;
- long only: a sell can only reduce a position, never open a short;
- every buy sends its stop-loss (and target) to the exchange as trigger
  orders that only reduce the position, so they work while the PC is off;
- each order carries a client order id made from FCC's own, so after a lost
  answer it is looked up, never sent twice;
- fees are read from the account's fills; funding (paid every hour between
  longs and shorts) is in the account value the exchange reports.
Marked beta: built against Hyperliquid's API documentation and its SDK's
test values, not yet against a live account; use the testnet or a small
order first.
"""

import hashlib
import math
import time
from collections.abc import Callable, Mapping

import httpx

from free_claude_code.core.json_types import JsonObject

from ...resilience import ServiceError, read_json
from ..data import MarketData, Quote
from ..hlsign import address_of, private_key, sign_action, wire
from ..instruments import Instrument
from ..providers.hyperliquid import MAINNET, TESTNET, HyperliquidData
from .base import (
    Account,
    Holding,
    OrderRequest,
    OrderResult,
    Rules,
    fingerprint,
    rejected,
)
from .common import Nonce, items, make_web, number, obj, text

MIN_ORDER_USD = 10.0
"""Hyperliquid's smallest order value."""
MARKET_SLIPPAGE = 0.01
"""A market order is sent as an immediate limit this far past the book."""


def cloid_of(client_id: str) -> str:
    """Hyperliquid's client order id (16 bytes) made from FCC's own."""
    return "0x" + hashlib.sha256(client_id.encode()).hexdigest()[:32]


def price_text(price: float, size_decimals: int) -> str:
    """A price as Hyperliquid accepts it: 5 significant figures, and no
    more decimals than 6 minus the coin's size decimals."""
    rounded = round(float(f"{price:.5g}"), max(0, 6 - size_decimals))
    return wire(rounded)


def size_text(size: float, size_decimals: int) -> str:
    step = 10**size_decimals
    return wire(math.floor(size * step + 1e-9) / step)


class HyperliquidBroker:
    id = "hyperliquid"
    supports_brackets = True

    def __init__(
        self,
        values: Mapping[str, str],
        data: MarketData,
        transport: httpx.AsyncBaseTransport | None = None,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._testnet = values.get("environment", "mainnet") == "testnet"
        base = TESTNET if self._testnet else MAINNET
        self._base = base
        self.live = not self._testnet
        self.name = "Hyperliquid (testnet)" if self._testnet else "Hyperliquid"
        self._address = values.get("address", "").strip().lower()
        if not (self._address.startswith("0x") and len(self._address) == 42):
            raise ValueError("The account address must be 0x and 40 hex characters.")
        self._secret = private_key(values.get("agent_key", ""))
        self.agent = address_of(self._secret)
        self._web = make_web(
            transport, base.removeprefix("https://"), per_second=2.0, burst=4
        )
        self._public = HyperliquidData(self._web, base=base, wall=clock)
        self._nonce = Nonce(clock)
        self._isolated: set[int] = set()
        self._data = data

    def markets(self) -> frozenset[str]:
        return frozenset({"crypto"})

    async def _info(self, body: dict[str, object]) -> object:
        return await self._public.info(body)

    async def _send(self, action: dict[str, object]) -> dict[str, object]:
        nonce = self._nonce()
        signature = sign_action(action, self._secret, nonce, mainnet=not self._testnet)
        response = await self._web.request(
            "POST",
            f"{self._base}/exchange",
            json={"action": action, "nonce": nonce, "signature": signature},
            retry=False,
            what="Hyperliquid",
        )
        body = obj(read_json(response, what="Hyperliquid"))
        if body.get("status") != "ok":
            raise rejected(
                f"Hyperliquid refused it: {text(body.get('response'))[:200]}"
            )
        return obj(body.get("response"))

    # ------------------------------------------------------------ account

    async def account(self) -> Account:
        state = obj(
            await self._info({"type": "clearinghouseState", "user": self._address})
        )
        summary = obj(state.get("marginSummary"))
        equity = number(summary.get("accountValue"))
        cash = number(state.get("withdrawable"))
        return Account(
            number=self._address,
            fingerprint=_fingerprint(self._address, self._testnet),
            currency="USD",
            equity=equity,
            cash=cash,
            buying_power=cash,
            live=self.live,
            # An API wallet can't withdraw (that needs the main wallet).
            permissions=("view", "trade"),
            note=(
                f"Hyperliquid account {self._address[:6]}…{self._address[-4:]}, "
                f"trading through API wallet {self.agent[:6]}…{self.agent[-4:]}."
            ),
        )

    async def positions(self) -> list[Holding]:
        state = obj(
            await self._info({"type": "clearinghouseState", "user": self._address})
        )
        found: list[Holding] = []
        for row in items(state.get("assetPositions")):
            position = obj(row.get("position"))
            size = number(position.get("szi"))
            if size > 0:
                found.append(
                    Holding(
                        text(position.get("coin")).upper(),
                        size,
                        number(position.get("entryPx")),
                        "USD",
                        number(position.get("positionValue")) or None,
                    )
                )
        return found

    async def rules(self, instrument: Instrument) -> Rules:
        if instrument.market != "crypto":
            return Rules(tradable=False, note="Hyperliquid trades coins only.")
        try:
            _, listing, _ = await self._public.asset(instrument.symbol)
        except ServiceError as error:
            return Rules(tradable=False, note=str(error))
        decimals = int(number(listing.get("szDecimals")))
        return Rules(
            tradable=True,
            broker_symbol=instrument.symbol.upper(),
            qty_step=10.0**-decimals,
            min_value=MIN_ORDER_USD,
            note="Perpetual future at 1x, isolated, long only.",
        )

    async def quote(self, instrument: Instrument) -> Quote | None:
        try:
            snap = await self._public.book(instrument.symbol)
        except ServiceError:
            return None
        if not snap.last:
            return None
        return Quote(
            instrument.symbol,
            snap.last,
            "USD",
            snap.timestamp or 0.0,
            self.name,
            snap.bid,
            snap.ask,
            note="; ".join(snap.notes),
            stamped=snap.timestamp is not None,
        )

    # ------------------------------------------------------------ orders

    async def _one_x_isolated(self, asset: int) -> None:
        """Set 1x isolated leverage before the first order in a coin."""
        if asset in self._isolated:
            return
        await self._send(
            {"type": "updateLeverage", "asset": asset, "isCross": False, "leverage": 1}
        )
        self._isolated.add(asset)

    async def place(self, order: OrderRequest) -> OrderResult:
        coin = order.instrument.symbol.upper()
        asset, listing, _ = await self._public.asset(coin)
        decimals = int(number(listing.get("szDecimals")))
        buying = order.side == "buy"
        if buying:
            await self._one_x_isolated(asset)
        if order.order_type == "limit" and order.limit_price is not None:
            price = order.limit_price
            tif = "Gtc"
        else:
            snap = await self._public.book(coin)
            side = snap.ask if buying else snap.bid
            if not side:
                raise rejected(f"No live {'ask' if buying else 'bid'} for {coin}.")
            price = side * (1 + MARKET_SLIPPAGE if buying else 1 - MARKET_SLIPPAGE)
            tif = "Ioc"
        size = size_text(order.qty, decimals)
        if float(size) <= 0:
            raise rejected(f"{order.qty:g} {coin} is below Hyperliquid's size step.")
        wires: list[dict[str, object]] = [
            {
                "a": asset,
                "b": buying,
                "p": price_text(price, decimals),
                "s": size,
                # A sell only ever reduces a position: never a short.
                "r": not buying,
                "t": {"limit": {"tif": tif}},
                "c": cloid_of(order.client_id),
            }
        ]
        legs = []
        if buying:
            for level, kind in ((order.take_profit, "tp"), (order.stop_loss, "sl")):
                if level is None:
                    continue
                legs.append(kind)
                wires.append(
                    {
                        "a": asset,
                        "b": False,
                        "p": price_text(level, decimals),
                        "s": size,
                        "r": True,
                        "t": {
                            "trigger": {
                                "isMarket": True,
                                "triggerPx": price_text(level, decimals),
                                "tpsl": kind,
                            }
                        },
                    }
                )
        action: dict[str, object] = {
            "type": "order",
            "orders": wires,
            "grouping": "normalTpsl" if legs else "na",
        }
        answer = await self._send(action)
        statuses = items(obj(answer.get("data")).get("statuses"))
        if not statuses:
            raise ServiceError("Hyperliquid didn't say what happened to the order.")
        first = statuses[0]
        if first.get("error"):
            raise rejected(f"Hyperliquid refused the order: {text(first.get('error'))}")
        protected = bool(legs) and all(
            not status.get("error") for status in statuses[1 : 1 + len(legs)]
        )
        return _result(first, order.client_id, coin, buying, protected)

    async def find(self, client_id: str) -> OrderResult | None:
        found = obj(
            await self._info(
                {
                    "type": "orderStatus",
                    "user": self._address,
                    "oid": cloid_of(client_id),
                }
            )
        )
        if found.get("status") != "order":
            return None
        detail = obj(found.get("order"))
        placed = obj(detail.get("order"))
        oid = int(number(placed.get("oid")))
        coin = text(placed.get("coin")).upper()
        state = text(detail.get("status"))
        fills = [
            row
            for row in items(
                await self._info({"type": "userFills", "user": self._address})
            )
            if int(number(row.get("oid"))) == oid
        ]
        filled = sum(number(row.get("sz")) for row in fills)
        value = sum(number(row.get("sz")) * number(row.get("px")) for row in fills)
        fees = sum(number(row.get("fee")) for row in fills)
        original = number(placed.get("origSz"))
        status = (
            "filled"
            if state == "filled" or (original and filled >= original - 1e-12)
            else "partially_filled"
            if filled > 0 and state == "open"
            else "cancelled"
            if state in {"canceled", "marginCanceled", "reduceOnlyCanceled"}
            else "rejected"
            if state == "rejected"
            else "submitted"
        )
        return OrderResult(
            broker_order_id=f"{coin}:{oid}",
            status=status,
            client_id=client_id,
            symbol=coin,
            filled_qty=filled,
            fill_price=value / filled if filled else None,
            fees=fees,
            raw={
                "currency": "USD",
                "fee_currency": "USD",
                "side": "buy" if text(placed.get("side")) == "B" else "sell",
            },
        )

    async def cancel(self, broker_order_id: str) -> None:
        coin, _, oid = broker_order_id.partition(":")
        if not oid.isdigit():
            raise rejected(f"Not a Hyperliquid order id: {broker_order_id!r}.")
        asset, _, _ = await self._public.asset(coin)
        await self._send({"type": "cancel", "cancels": [{"a": asset, "o": int(oid)}]})

    async def open_orders(self) -> list[OrderResult]:
        return [
            OrderResult(
                broker_order_id=f"{text(row.get('coin')).upper()}:{int(number(row.get('oid')))}",
                status="submitted",
                symbol=text(row.get("coin")).upper(),
                raw={
                    "currency": "USD",
                    "side": "buy" if text(row.get("side")) == "B" else "sell",
                },
            )
            for row in items(
                await self._info({"type": "openOrders", "user": self._address})
            )
        ]

    async def aclose(self) -> None:
        await self._web.aclose()


def _fingerprint(address: str, testnet: bool) -> str:
    return fingerprint("hyperliquid" + (":testnet" if testnet else ""), address)


def _result(
    status: Mapping[str, object],
    client_id: str,
    coin: str,
    buying: bool,
    protected: bool,
) -> OrderResult:
    raw: JsonObject = {
        "currency": "USD",
        "side": "buy" if buying else "sell",
        "bracket": protected,
        # Fees come with the fills (read on the next check), not here.
        "fees_reported": False,
    }
    filled = obj(status.get("filled"))
    if filled:
        return OrderResult(
            broker_order_id=f"{coin}:{int(number(filled.get('oid')))}",
            status="filled",
            client_id=client_id,
            symbol=coin,
            filled_qty=number(filled.get("totalSz")),
            fill_price=number(filled.get("avgPx")) or None,
            raw=raw,
        )
    resting = obj(status.get("resting"))
    return OrderResult(
        broker_order_id=f"{coin}:{int(number(resting.get('oid')))}",
        status="submitted",
        client_id=client_id,
        symbol=coin,
        raw=raw,
    )
