"""The account check before every order: is it safe to send this, right now?

It reads the live account and the platform's rules, and checks:
- the platform answers, and it's the account the owner verified;
- the account can trade, and has the money (or the holding, to sell);
- the platform trades this symbol, in this size;
- the market is open, and the price hasn't run from the decision's;
- the price is fresh, not flagged halted, and (for buys) the bid/ask spread
  is inside the limit (a sell to protect a position is never held up by it);
- no other order for the symbol is open;
- the US pattern-day-trader rule won't lock the account.
It runs again when the owner taps Approve, since prices and balances move.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from free_claude_code.core.json_types import JsonObject

from ..resilience import ServiceError
from .brokers.base import Account, Broker, OrderRequest
from .data import Quote


@dataclass(frozen=True, slots=True)
class CheckItem:
    name: str
    ok: bool
    detail: str
    blocking: bool = True


@dataclass(frozen=True, slots=True)
class CheckReport:
    items: tuple[CheckItem, ...]
    account: JsonObject

    @property
    def passed(self) -> bool:
        return all(item.ok or not item.blocking for item in self.items)

    @property
    def failures(self) -> tuple[str, ...]:
        return tuple(
            f"{item.name}: {item.detail}"
            for item in self.items
            if not item.ok and item.blocking
        )

    def view(self) -> JsonObject:
        return {
            "passed": self.passed,
            "items": [
                {
                    "name": item.name,
                    "ok": item.ok,
                    "detail": item.detail,
                    "blocking": item.blocking,
                }
                for item in self.items
            ],
            "account": self.account,
        }


async def pre_trade_check(
    *,
    broker: Broker,
    order: OrderRequest,
    decision_price: float,
    value: float,
    rate: Callable[[str], Awaitable[float]],
    verified: str,
    slippage_pct: float,
    market_open: bool,
    quote: Quote | None,
    base_currency: str,
    held: float,
    now: float | None = None,
    max_age_s: float | None = None,
    spread_limit_pct: float | None = None,
) -> CheckReport:
    """Check one order against the live account and the platform's rules."""
    items: list[CheckItem] = []
    symbol = order.instrument.symbol
    try:
        account = await broker.account()
    except ServiceError as error:
        items.append(CheckItem("Platform answers", False, str(error)))
        return CheckReport(tuple(items), {})
    items.append(CheckItem("Platform answers", True, broker.name))
    items.append(_identity(broker, account, verified))
    items.append(
        CheckItem(
            "Account can trade",
            account.status == "active",
            f"The platform says the account is {account.status}.",
        )
    )
    if order.side == "buy":
        buying_power = account.buying_power * await rate(account.currency)
        needed = value * 1.02
        items.append(
            CheckItem(
                "Enough buying power",
                buying_power >= needed,
                f"{buying_power:,.2f} {base_currency} available for "
                f"{needed:,.2f} (order plus 2% for fees).",
            )
        )
    else:
        items.append(
            CheckItem(
                "Holding to sell",
                held + 1e-12 >= order.qty,
                f"{held:g} held, selling {order.qty:g}.",
            )
        )
    try:
        rules = await broker.rules(order.instrument)
    except ServiceError as error:
        items.append(CheckItem("Symbol tradable here", False, str(error)))
    else:
        items.append(
            CheckItem(
                "Symbol tradable here",
                rules.tradable,
                rules.note or f"{broker.name} trades {symbol}.",
            )
        )
        if rules.tradable:
            fitted = rules.fit(order.qty)
            size_ok = fitted > 0 and abs(fitted - order.qty) <= max(
                1e-9, order.qty * 1e-9
            )
            items.append(
                CheckItem(
                    "Size fits the platform",
                    size_ok,
                    f"{order.qty:g} units"
                    + (f" (minimum {rules.min_qty:g})" if rules.min_qty else "")
                    + (f", in steps of {rules.qty_step:g}" if rules.qty_step else ""),
                )
            )
            if rules.min_value and quote is not None:
                worth = order.qty * quote.price
                items.append(
                    CheckItem(
                        "Order is big enough",
                        worth >= rules.min_value,
                        f"Worth {worth:,.2f} {quote.currency}; the platform's "
                        f"minimum is {rules.min_value:,.2f}.",
                        blocking=order.side == "buy",
                    )
                )
    items.append(
        CheckItem(
            "Market open",
            market_open,
            "Trading now."
            if market_open
            else "Closed; the desk will try next session.",
        )
    )
    if quote is None:
        items.append(CheckItem("Live price", False, f"No live price for {symbol}."))
    else:
        moved = abs(quote.price / decision_price - 1) * 100 if decision_price else 0.0
        items.append(
            CheckItem(
                "Price still near the decision",
                moved <= slippage_pct,
                f"{quote.price:g} now vs {decision_price:g} at the decision "
                f"({moved:.2f}% move; limit {slippage_pct:g}%).",
            )
        )
        items.extend(
            _quote_quality(
                quote,
                buying=order.side == "buy",
                live=broker.live,
                now=now,
                max_age_s=max_age_s,
                spread_limit_pct=spread_limit_pct,
            )
        )
    try:
        waiting = [
            result
            for result in await broker.open_orders()
            if result.symbol == symbol and result.client_id != order.client_id
        ]
    except ServiceError as error:
        items.append(CheckItem("No other open order", False, str(error)))
    else:
        items.append(
            CheckItem(
                "No other open order",
                not waiting,
                "None open."
                if not waiting
                else f"{len(waiting)} already open for {symbol}.",
            )
        )
    if order.instrument.market == "us" and account.live and account.currency == "USD":
        risky = account.equity < 25_000 and (account.day_trades or 0) >= 3
        items.append(
            CheckItem(
                "US day-trading rule",
                not risky or account.pattern_day_trader,
                f"{account.day_trades or 0} day trades in 5 days; under $25k US "
                "a fourth locks the account.",
                blocking=risky and not account.pattern_day_trader,
            )
        )
    return CheckReport(tuple(items), account.view())


def _identity(broker: Broker, account: Account, verified: str) -> CheckItem:
    if not broker.live:
        return CheckItem("The account you verified", True, "The paper account.")
    if not verified:
        return CheckItem(
            "The account you verified",
            False,
            "Verify this account on the Trading page before live orders.",
        )
    return CheckItem(
        "The account you verified",
        account.fingerprint == verified,
        "Same account as verified."
        if account.fingerprint == verified
        else "This isn't the account you verified; check the keys.",
    )


def _quote_quality(
    quote: Quote,
    *,
    buying: bool,
    live: bool,
    now: float | None,
    max_age_s: float | None,
    spread_limit_pct: float | None,
) -> list[CheckItem]:
    """Freshness, halts, and the spread, from the quote the order will meet.
    They block new buys; sells to protect a position go ahead regardless."""
    found: list[CheckItem] = []
    if quote.note == "halted":
        found.append(
            CheckItem(
                "Not halted",
                False,
                f"{quote.source} marks {quote.symbol} halted.",
                blocking=buying,
            )
        )
    if now is not None and max_age_s is not None:
        if quote.at <= 0:
            found.append(
                CheckItem(
                    "Price fresh",
                    False,
                    f"{quote.source} gave no time for its price"
                    + (f" ({quote.note})" if quote.note else "")
                    + ".",
                    blocking=buying and live,
                )
            )
        else:
            age = max(0.0, now - quote.at)
            found.append(
                CheckItem(
                    "Price fresh",
                    age <= max_age_s,
                    f"{quote.source}'s price is {age:.0f} s old "
                    f"(limit {max_age_s:.0f} s).",
                    blocking=buying,
                )
            )
    if spread_limit_pct is not None:
        spread = quote.spread_pct
        if spread is None:
            found.append(
                CheckItem(
                    "Spread acceptable",
                    False,
                    f"{quote.source} gave no bid and ask"
                    + ("." if live else "; paper fills assume a spread."),
                    blocking=buying and live,
                )
            )
        else:
            found.append(
                CheckItem(
                    "Spread acceptable",
                    spread <= spread_limit_pct,
                    f"{spread:.3f}% between bid and ask (limit {spread_limit_pct:g}%).",
                    blocking=buying,
                )
            )
    return found
