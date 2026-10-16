"""Hard risk rules, written as plain code that no model's reply can talk past.

Two jobs: size a position from the risk the owner allows per trade (so a wide
stop means fewer shares), and gate every order against the limits on the
Trading page. Selling to close is always allowed: it only ever lowers risk.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from free_claude_code.core.json_types import JsonObject

from .brokers.base import Rules
from .config import RiskLimits


@dataclass(frozen=True, slots=True)
class Sizing:
    qty: float
    value: float
    """In the base currency."""
    at_risk: float
    """Lost, in the base currency, if the stop is hit (before slippage)."""
    bound_by: str
    """Which limit set the size: risk, position cap, order cap, or platform."""

    def view(self) -> JsonObject:
        return {
            "qty": self.qty,
            "value": round(self.value, 2),
            "at_risk": round(self.at_risk, 2),
            "bound_by": self.bound_by,
        }


def size_position(
    *,
    equity: float,
    price: float,
    stop: float,
    fx: float,
    limits: RiskLimits,
    meme: bool = False,
    regime_scale: float = 1.0,
    size_pct: float = 100.0,
    rules: Rules | None = None,
) -> Sizing:
    """How much to buy: the smallest of what the risk budget, the position
    cap, and the order cap allow, scaled by the market regime and the
    Portfolio Manager's chosen share (0-100%), rounded to the platform's
    rules."""
    unit_price = price * fx
    unit_risk = (price - stop) * fx
    if equity <= 0 or unit_price <= 0 or unit_risk <= 0:
        return Sizing(0.0, 0.0, 0.0, "no valid stop below the price")
    budget = equity * limits.risk_per_trade_pct / 100 * max(0.0, regime_scale)
    cap_pct = limits.meme_position_pct if meme else limits.max_position_pct
    options = {
        "risk": budget / unit_risk,
        "position cap": equity * cap_pct / 100 / unit_price,
        "order cap": limits.max_order_value / unit_price,
    }
    bound_by = min(options, key=lambda name: options[name])
    qty = options[bound_by] * max(0.0, min(100.0, size_pct)) / 100
    if rules is not None:
        fitted = rules.fit(qty)
        if fitted < qty and fitted == 0:
            bound_by = "platform minimum"
        qty = fitted
    return Sizing(qty, qty * unit_price, qty * unit_risk, bound_by)


@dataclass(frozen=True, slots=True)
class Exposure:
    """One open position, valued in the base currency."""

    symbol: str
    value: float
    meme: bool = False


@dataclass(frozen=True, slots=True)
class GateResult:
    allowed: bool
    reasons: tuple[str, ...]
    """Why it was blocked (empty when allowed)."""
    notes: tuple[str, ...] = ()

    def view(self) -> JsonObject:
        return {
            "allowed": self.allowed,
            "reasons": list(self.reasons),
            "notes": list(self.notes),
        }


def risk_gate(
    *,
    symbol: str,
    side: str,
    qty: float,
    price: float,
    stop: float | None,
    take_profit: float | None,
    value: float,
    meme: bool,
    confidence: float,
    consensus: float,
    limits: RiskLimits,
    equity: float,
    positions: Sequence[Exposure],
    held_qty: float,
    trades_today: int,
    day_change_pct: float,
    last_trade_ms: Mapping[str, int],
    open_order_symbols: Sequence[str],
    now_ms: int,
) -> GateResult:
    """Check one order against every hard limit."""
    reasons: list[str] = []
    notes: list[str] = []
    if qty <= 0:
        reasons.append("The size works out to nothing.")
    if side == "sell":
        if held_qty + 1e-12 < qty:
            reasons.append(f"Only {held_qty:g} held, so {qty:g} can't be sold.")
        return GateResult(not reasons, tuple(reasons), ("Selling only lowers risk.",))
    if symbol in limits.deny:
        reasons.append(f"{symbol} is on the do-not-trade list.")
    if limits.allow and symbol not in limits.allow:
        reasons.append(f"{symbol} isn't on the allowed list.")
    if stop is None:
        if limits.require_stop:
            reasons.append("Every buy needs a stop-loss.")
    elif stop >= price:
        reasons.append("The stop-loss must sit below the entry price.")
    if take_profit is not None and take_profit <= price:
        reasons.append("The take-profit must sit above the entry price.")
    if value > limits.max_order_value * 1.0001:
        reasons.append(
            f"The order (${value:,.2f}) is over the ${limits.max_order_value:,.0f} cap."
        )
    current = sum(item.value for item in positions if item.symbol == symbol)
    cap_pct = limits.meme_position_pct if meme else limits.max_position_pct
    if equity > 0 and (current + value) / equity * 100 > cap_pct + 1e-6:
        reasons.append(
            f"{symbol} would be {(current + value) / equity * 100:.1f}% of the "
            f"account; the cap is {cap_pct:g}%."
        )
    others = {item.symbol for item in positions if item.symbol != symbol}
    if (
        symbol not in {item.symbol for item in positions}
        and len(others) >= limits.max_open_positions
    ):
        reasons.append(
            f"Already {len(others)} positions open; the limit is "
            f"{limits.max_open_positions}."
        )
    if trades_today >= limits.max_trades_per_day:
        reasons.append(
            f"{trades_today} trades today already (limit {limits.max_trades_per_day})."
        )
    if day_change_pct <= -limits.max_daily_loss_pct:
        reasons.append(
            f"The account is down {-day_change_pct:.1f}% today; trading stops at "
            f"{limits.max_daily_loss_pct:g}%."
        )
    last = last_trade_ms.get(symbol)
    if last is not None and limits.cooldown_minutes:
        waited = (now_ms - last) / 60_000
        if waited < limits.cooldown_minutes:
            reasons.append(
                f"{symbol} traded {waited:.0f} min ago; the cool-down is "
                f"{limits.cooldown_minutes} min."
            )
    if confidence < limits.min_confidence:
        reasons.append(
            f"Confidence {confidence:.2f} is under the {limits.min_confidence:.2f} minimum."
        )
    if consensus < limits.min_consensus:
        reasons.append(
            f"The seats' weighted chance of a rise ({consensus:.2f}) is under "
            f"{limits.min_consensus:.2f}."
        )
    if meme and equity > 0:
        meme_total = sum(item.value for item in positions if item.meme) + value
        if meme_total / equity * 100 > limits.meme_total_pct + 1e-6:
            reasons.append(
                f"Meme coins would be {meme_total / equity * 100:.1f}% of the account; "
                f"the cap is {limits.meme_total_pct:g}%."
            )
    if symbol in open_order_symbols:
        reasons.append(f"An order for {symbol} is already open.")
    if not reasons:
        notes.append("Every hard limit passed.")
    return GateResult(not reasons, tuple(reasons), tuple(notes))
