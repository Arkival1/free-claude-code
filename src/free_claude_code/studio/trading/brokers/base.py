"""What every trading platform adapter provides, and the shapes it answers in.

Failures are ``ServiceError``s (see ``studio.resilience``): ``transient`` says
whether trying again can help and ``sent`` whether an order could have
reached the platform, which is what keeps an order from going twice.
"""

import hashlib
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal
from typing import Literal, Protocol

from free_claude_code.core.json_types import JsonObject

from ...resilience import ServiceError
from ..data import Quote
from ..instruments import Instrument


def fingerprint(platform: str, account_number: str) -> str:
    """A stable id for an account that never reveals its number."""
    digest = hashlib.sha256(f"{platform}:{account_number}".encode()).hexdigest()
    return digest[:16]


def masked(account_number: str) -> str:
    text = account_number.strip()
    if len(text) <= 4:
        return "•" * len(text)
    return "•" * min(6, len(text) - 4) + text[-4:]


@dataclass(frozen=True, slots=True)
class Account:
    """The account an adapter is connected to, as the platform reports it."""

    number: str
    """Shown masked; never logged in full."""
    fingerprint: str
    currency: str
    equity: float
    cash: float
    buying_power: float
    status: str = "active"
    """active, restricted, blocked, or unknown."""
    live: bool = False
    day_trades: int | None = None
    pattern_day_trader: bool = False
    note: str = ""

    def view(self) -> JsonObject:
        return {
            "number": masked(self.number),
            "fingerprint": self.fingerprint,
            "currency": self.currency,
            "equity": round(self.equity, 2),
            "cash": round(self.cash, 2),
            "buying_power": round(self.buying_power, 2),
            "status": self.status,
            "live": self.live,
            "day_trades": self.day_trades,
            "pattern_day_trader": self.pattern_day_trader,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class Holding:
    symbol: str
    qty: float
    avg_price: float
    currency: str
    market_value: float | None = None


@dataclass(frozen=True, slots=True)
class Rules:
    """What the platform allows for one symbol."""

    tradable: bool
    broker_symbol: str = ""
    min_qty: float = 0.0
    qty_step: float = 0.0
    """Quantities must be a whole number of these; 0 means any amount."""
    min_value: float = 0.0
    """In the symbol's own currency."""
    fractional: bool = True
    note: str = ""

    def fit(self, qty: float) -> float:
        """Round a quantity down to what the platform accepts."""
        if qty <= 0:
            return 0.0
        step = self.qty_step if self.qty_step > 0 else (0.0 if self.fractional else 1.0)
        if step > 0:
            exponent = Decimal(str(step)).normalize().as_tuple().exponent
            digits = max(0, -exponent) if isinstance(exponent, int) else 8
            qty = round(int(qty / step + 1e-9) * step, digits)
        else:
            # Any amount: keep 8 decimal places, rounded down.
            qty = float(
                Decimal(str(qty)).quantize(Decimal("1e-8"), rounding=ROUND_DOWN)
            )
        return qty if qty >= self.min_qty and qty > 0 else 0.0


@dataclass(frozen=True, slots=True)
class OrderRequest:
    client_id: str
    instrument: Instrument
    side: Literal["buy", "sell"]
    qty: float
    order_type: Literal["market", "limit"] = "market"
    limit_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    price_currency: str = "USD"
    """The currency the prices above are in (the symbol's own); a platform
    that prices the pair in another currency converts them."""


@dataclass(frozen=True, slots=True)
class OrderResult:
    broker_order_id: str
    status: str
    """submitted, filled, partially_filled, cancelled, rejected, or needs_reply
    (the platform wants a person to confirm a warning)."""
    client_id: str = ""
    symbol: str = ""
    filled_qty: float = 0.0
    fill_price: float | None = None
    fees: float = 0.0
    note: str = ""
    raw: JsonObject = field(default_factory=dict)
    """Extras: ``currency`` the fill price is in, ``fee_currency`` the fees
    are in (both default to the order's own), ``bracket`` when the platform
    holds the stop and target, ``reply`` when it wants a person to confirm."""

    @property
    def done(self) -> bool:
        return self.status in {"filled", "cancelled", "rejected"}


def rejected(message: str, *, host: str = "") -> ServiceError:
    """A refusal that trying again won't change."""
    return ServiceError(message, transient=False, host=host)


class Broker(Protocol):
    """One trading platform, paper or live."""

    id: str
    name: str
    live: bool
    supports_brackets: bool
    """Whether the platform itself holds the stop-loss and take-profit, so they
    work while the PC is off; otherwise the desk watches them."""

    def markets(self) -> frozenset[str]: ...

    async def account(self) -> Account: ...

    async def positions(self) -> list[Holding]: ...

    async def rules(self, instrument: Instrument) -> Rules: ...

    async def quote(self, instrument: Instrument) -> Quote | None: ...

    async def place(self, order: OrderRequest) -> OrderResult: ...

    async def find(self, client_id: str) -> OrderResult | None: ...

    async def cancel(self, broker_order_id: str) -> None: ...

    async def open_orders(self) -> list[OrderResult]: ...

    async def aclose(self) -> None: ...
