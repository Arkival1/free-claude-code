"""The investment stress test: what this trade, and the whole account, could
lose in bad conditions, measured from the asset's own history.

It is added on top of the original stress cases in assessment.py (1-3 ATR
drops, a gap past the stop, a flash crash, the index -3%), which still run
first, on the original size, with their original effect. Nothing here can
loosen them: these scenarios only add cases, and the limits below can only
shrink or block a trade.

Scenarios (only candles that started before now are read):
- the worst day in up to two years, with no way out that day;
- the worst five days in a row, if the stop couldn't be filled (a halt or an
  outage);
- a gap through the stop at the worst opening gap on record (a stop does not
  guarantee its price);
- volatility doubling: the stop fills two ATRs worse;
- a market crash: the index's worst five days (at least -10% for shares,
  -25% for coins) times the asset's beta, for this trade and for the whole
  account at once;
- a liquidity shock: leaving at the stop when the spread is five times wider
  and the order is a large share of a day's trading;
- asset-specific: a meme coin halving; shares with results due inside the
  holding window gapping by their worst gap; a US asset in an Australian
  account losing the worst five days of AUD/USD;
- up to two scenarios the Risk Guardian proposes (each a fall of 0-90%).

Limits (the owner's settings; learning never changes them): the worst case
for one trade, and for the whole account with the trade, as a share of the
account. A trade over the per-trade limit is cut to fit; if even the
smallest size the platform allows breaks it, or the account-wide limit is
broken, the trade is blocked.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Literal

from free_claude_code.core.json_types import JsonObject

from .indicators import Bar

HISTORY_DAYS = 500
RUN_DAYS = 5
SHARE_CRASH_FLOOR = -0.10
COIN_CRASH_FLOOR = -0.25
MEME_CRASH = -0.50
SPREAD_SHOCK = 5.0
IMPACT_PER_ADV = 0.1
"""Extra exit cost, in %, per 1% of a day's trading the order makes up."""
MAX_GUARDIAN_SCENARIOS = 2


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    assumption: str
    """What was assumed, in plain words, with where the number came from."""
    move_pct: float
    """The price move assumed against the position, in % (negative)."""
    loss: float
    """In the base currency (never negative)."""
    pct_of_equity: float
    source: Literal["history", "floor", "guardian", "fixed"]
    scope: Literal["trade", "account"] = "trade"

    def line(self) -> str:
        return (
            f"{self.name}: {self.assumption}; loss {self.loss:,.2f} "
            f"({self.pct_of_equity:.2f}% of the account)"
        )

    def view(self) -> JsonObject:
        return {
            "name": self.name,
            "assumption": self.assumption,
            "move_pct": round(self.move_pct, 3),
            "loss": round(self.loss, 2),
            "pct_of_equity": round(self.pct_of_equity, 3),
            "source": self.source,
            "scope": self.scope,
        }


@dataclass(frozen=True, slots=True)
class Holding:
    """Something already held, for the account-wide crash."""

    symbol: str
    value: float
    """In the base currency."""
    beta: float | None = None
    crypto: bool = False


@dataclass(frozen=True, slots=True)
class StressInput:
    symbol: str
    market: str
    """us, asx, or crypto."""
    side: Literal["long", "short"]
    qty: float
    entry: float
    stop: float
    fx: float
    """Base currency per unit of the asset's currency."""
    equity: float
    """The account's value in the base currency."""
    atr: float | None
    daily: Sequence[Bar]
    index_daily: Sequence[Bar] = ()
    beta: float | None = None
    meme: bool = False
    spread_pct: float | None = None
    avg_daily_turnover: float | None = None
    """In the asset's currency."""
    holdings: Sequence[Holding] = ()
    fx_daily: Sequence[Bar] = ()
    """Daily candles of the asset's currency priced in the base currency
    (only for an asset in another currency)."""
    earnings_in_window: bool = False
    guardian: Sequence[tuple[str, float]] = ()
    """The Risk Guardian's own scenarios: (name, fall in %, 0-90)."""
    min_qty: float = 0.0
    """The smallest size the platform allows (0 = any)."""
    extra: Sequence[tuple[str, float]] = ()
    """The original stress cases from the risk report: (name, loss in the
    base currency at ``qty``). They are kept exactly, so the worst case here
    is never smaller than the original worst case."""


@dataclass(frozen=True, slots=True)
class StressReport:
    scenarios: tuple[Scenario, ...]
    trade_limit_pct: float
    account_limit_pct: float
    qty: float
    """The size asked for."""
    max_qty: float
    """The largest size that keeps every trade scenario inside the limit."""
    blocked: bool
    reasons: tuple[str, ...] = field(default=())

    @property
    def worst_trade(self) -> Scenario | None:
        found = [item for item in self.scenarios if item.scope == "trade"]
        return _worst(found)

    @property
    def worst_account(self) -> Scenario | None:
        found = [item for item in self.scenarios if item.scope == "account"]
        return _worst(found)

    @property
    def size_factor(self) -> float:
        if self.blocked or self.qty <= 0:
            return 0.0
        return min(1.0, self.max_qty / self.qty)

    def lines(self) -> str:
        rows = [item.line() for item in self.scenarios]
        rows.append(
            f"Limits: worst case per trade {self.trade_limit_pct:g}% of the "
            f"account, whole account {self.account_limit_pct:g}%"
        )
        rows.extend(self.reasons)
        return "\n".join(rows)

    def view(self) -> JsonObject:
        worst_trade = self.worst_trade
        worst_account = self.worst_account
        return {
            "scenarios": [item.view() for item in self.scenarios],
            "trade_limit_pct": self.trade_limit_pct,
            "account_limit_pct": self.account_limit_pct,
            "qty": self.qty,
            "max_qty": self.max_qty,
            "size_factor": round(self.size_factor, 4),
            "blocked": self.blocked,
            "reasons": list(self.reasons),
            "worst_trade": worst_trade.view() if worst_trade is not None else None,
            "worst_account": worst_account.view()
            if worst_account is not None
            else None,
        }


def _worst(items: Sequence[Scenario]) -> Scenario | None:
    """The scenario with the largest loss, or None when there are none."""
    return max(items, key=_loss) if items else None


def _loss(item: Scenario) -> float:
    return item.loss


def _past(bars: Sequence[Bar], now: float) -> list[Bar]:
    found = sorted(
        (bar for bar in bars if bar.t < now and bar.c > 0), key=lambda b: b.t
    )
    return found[-(HISTORY_DAYS + 1) :]


def worst_day(bars: Sequence[Bar], now: float) -> float | None:
    """The worst close-to-close day, as a fraction (negative), or None."""
    past = _past(bars, now)
    moves = [after.c / before.c - 1 for before, after in pairwise(past)]
    return min(moves) if moves else None


def worst_run(bars: Sequence[Bar], now: float, days: int = RUN_DAYS) -> float | None:
    """The worst fall over ``days`` days in a row (close to close)."""
    past = _past(bars, now)
    if len(past) <= days:
        return None
    return min(past[i + days].c / past[i].c - 1 for i in range(len(past) - days))


def worst_gap(bars: Sequence[Bar], now: float) -> float | None:
    """The worst opening gap below the previous close."""
    past = _past(bars, now)
    gaps = [after.o / before.c - 1 for before, after in pairwise(past) if after.o > 0]
    return min(gaps) if gaps else None


def worst_rise(bars: Sequence[Bar], now: float, days: int = 1) -> float | None:
    """For a short position: the worst rise over ``days`` days (positive)."""
    past = _past(bars, now)
    if len(past) <= days:
        return None
    return max(past[i + days].c / past[i].c - 1 for i in range(len(past) - days))


def stress_test(
    given: StressInput,
    *,
    now: float,
    trade_limit_pct: float,
    account_limit_pct: float,
) -> StressReport:
    """Every scenario for the trade and the account, and what the limits
    leave of the size."""
    qty = max(0.0, given.qty)
    if qty <= 0 or given.equity <= 0 or given.entry <= 0:
        return StressReport(
            (),
            trade_limit_pct,
            account_limit_pct,
            qty,
            0.0,
            True,
            ("Nothing to test: no size or no account value.",),
        )
    long = given.side == "long"
    unit_value = given.entry * given.fx
    value = qty * unit_value
    scenarios: list[Scenario] = []

    def add(
        name: str,
        assumption: str,
        move: float,
        loss: float,
        source: Literal["history", "floor", "guardian", "fixed"],
        scope: Literal["trade", "account"] = "trade",
    ) -> None:
        loss = max(0.0, loss)
        scenarios.append(
            Scenario(
                name,
                assumption,
                move * 100,
                loss,
                loss / given.equity * 100,
                source,
                scope,
            )
        )

    crypto = given.market == "crypto"
    # 1. The worst day, with no way out that day.
    if long:
        day = worst_day(given.daily, now)
        if day is not None and day < 0:
            add(
                "Platform outage for a day" if crypto else "Worst day on record",
                f"the worst day in the last {HISTORY_DAYS} ({day:+.1%}) with no way out",
                day,
                value * -day,
                "history",
            )
    else:
        rise = worst_rise(given.daily, now)
        if rise is not None and rise > 0:
            add(
                "Worst day against a short",
                f"the worst rise in a day ({rise:+.1%}) with no way out",
                -rise,
                value * rise,
                "history",
            )

    # 2. Five bad days in a row with the stop unfilled.
    if long:
        run = worst_run(given.daily, now)
        if run is not None and run < 0:
            add(
                "Worst five days, stop not filled",
                f"the worst {RUN_DAYS} days in a row ({run:+.1%}), as in a halt or outage",
                run,
                value * -run,
                "history",
            )
    else:
        rise = worst_rise(given.daily, now, RUN_DAYS)
        if rise is not None and rise > 0:
            add(
                "Worst five days against a short",
                f"the worst {RUN_DAYS}-day rise ({rise:+.1%})",
                -rise,
                value * rise,
                "history",
            )

    # 3. A gap through the stop at the worst opening gap on record.
    gap = worst_gap(given.daily, now) if long else None
    if long and gap is not None and gap < 0 and given.stop > 0:
        fill = given.stop * (1 + gap)
        add(
            "Gap through the stop (worst on record)",
            f"the price opens {gap:+.1%} below the stop's level, so the stop fills at {fill:g}",
            fill / given.entry - 1,
            qty * (given.entry - fill) * given.fx,
            "history",
        )

    # 4. Volatility doubles: the stop fills two ATRs worse.
    if given.atr and given.atr > 0 and given.stop > 0:
        fill = given.stop - 2 * given.atr if long else given.stop + 2 * given.atr
        loss_per = (given.entry - fill) if long else (fill - given.entry)
        add(
            "Volatility doubles at the stop",
            f"the stop fills two ATRs ({2 * given.atr:g}) worse, at {fill:g}",
            -loss_per / given.entry,
            qty * loss_per * given.fx,
            "fixed",
        )

    # 5. A market crash, for the trade and for the whole account.
    index_run = worst_run(given.index_daily, now) if given.index_daily else None
    floor = COIN_CRASH_FLOOR if crypto else SHARE_CRASH_FLOOR
    crash = min(index_run if index_run is not None else 0.0, floor)
    beta = given.beta if given.beta is not None else 1.0
    crash_source: Literal["history", "floor"] = (
        "history" if index_run is not None and index_run <= floor else "floor"
    )
    # A crash only hurts a long position (a short's risk is a rally, above).
    own_crash = crash * max(0.0, beta) if long else 0.0
    if long and own_crash < 0:
        add(
            "Market crash",
            f"the index falls {crash:+.1%} (worst {RUN_DAYS} days on record, at least {floor:+.0%}) x beta {beta:.2f}",
            own_crash,
            value * -own_crash,
            crash_source,
        )
    held_loss = 0.0
    for holding in given.holdings:
        held_beta = holding.beta if holding.beta is not None else 1.0
        held_crash = COIN_CRASH_FLOOR if holding.crypto else SHARE_CRASH_FLOOR
        fall = min(crash if holding.crypto == crypto else held_crash, held_crash)
        held_loss += holding.value * -fall * max(0.0, held_beta)
    account_loss = held_loss + (value * -own_crash if long and own_crash < 0 else 0.0)
    add(
        "Market crash across the whole account",
        f"every holding falls with its market (shares at least {SHARE_CRASH_FLOOR:+.0%}, coins at least {COIN_CRASH_FLOOR:+.0%}) x its beta, this trade included",
        crash,
        account_loss,
        crash_source,
        "account",
    )

    # 6. A liquidity shock at the stop.
    if given.stop > 0:
        spread = (given.spread_pct or 0.0) * SPREAD_SHOCK
        participation = (
            value / given.fx / given.avg_daily_turnover * 100
            if given.avg_daily_turnover and given.avg_daily_turnover > 0
            else None
        )
        impact = (participation or 0.0) * IMPACT_PER_ADV
        cost = spread / 2 + impact
        stop_loss = (given.entry - given.stop) if long else (given.stop - given.entry)
        per_unit = stop_loss + given.stop * cost / 100
        add(
            "Liquidity shock at the stop",
            f"leaving at the stop with the spread {SPREAD_SHOCK:g}x wider ({spread:.2f}%)"
            + (
                f" and the order {participation:.2f}% of a day's trading"
                if participation is not None
                else "; the day's trading is unknown"
            ),
            -per_unit / given.entry,
            qty * per_unit * given.fx,
            "fixed",
        )

    # 7. Asset-specific.
    if given.meme and long:
        add(
            "Meme coin halves",
            "a meme coin falls 50% and its liquidity halves",
            MEME_CRASH,
            value * -MEME_CRASH,
            "fixed",
        )
    if given.earnings_in_window and long and gap is not None and gap < 0:
        add(
            "Results inside the holding window",
            f"the share gaps by its worst gap on record ({gap:+.1%}) on results day, past the stop",
            gap,
            value * -gap,
            "history",
        )
    if given.fx_daily and long:
        fx_run = worst_run(given.fx_daily, now)
        if fx_run is not None and fx_run < 0:
            add(
                "Currency move",
                f"the asset's currency loses its worst {RUN_DAYS} days against the account's ({fx_run:+.1%})",
                fx_run,
                value * -fx_run,
                "history",
            )

    # 8. The Risk Guardian's own scenarios (bounded; they only add cases).
    for name, fall in list(given.guardian)[:MAX_GUARDIAN_SCENARIOS]:
        if not isinstance(fall, int | float) or math.isnan(fall):
            continue
        bounded = min(90.0, max(0.0, abs(float(fall))))
        add(
            f"Guardian: {name[:80]}",
            f"the Risk Guardian's scenario: a {bounded:g}% move against the position",
            -bounded / 100,
            value * bounded / 100,
            "guardian",
        )

    # 9. The original stress cases, exactly as the risk report worked them out.
    for name, loss in given.extra:
        add(
            name,
            "an original stress case, worked out as before",
            -loss / value if value else 0.0,
            loss,
            "fixed",
        )

    # The limits.
    trade = [item for item in scenarios if item.scope == "trade"]
    worst = _worst(trade)
    reasons: list[str] = []
    max_qty = qty
    if worst is not None and worst.pct_of_equity > trade_limit_pct:
        max_qty = qty * trade_limit_pct / worst.pct_of_equity
        reasons.append(
            f"The worst case ({worst.name}) would cost {worst.pct_of_equity:.2f}% of the "
            f"account, over the {trade_limit_pct:g}% limit: the size is cut to {max_qty:g}."
        )
    blocked = False
    if max_qty <= 0 or (given.min_qty and max_qty < given.min_qty):
        blocked = True
        reasons.append(
            "Even the smallest size the platform allows breaks the stress limit."
        )
    account = _worst([item for item in scenarios if item.scope == "account"])
    if account is not None:
        kept = max_qty / qty if qty else 0.0
        own = value * -own_crash if long and own_crash < 0 else 0.0
        account_pct = (held_loss + own * kept) / given.equity * 100
        if account_pct > account_limit_pct:
            blocked = True
            reasons.append(
                f"A market crash would cost the whole account {account_pct:.2f}% with this "
                f"trade, over the {account_limit_pct:g}% limit."
            )
    return StressReport(
        scenarios=tuple(scenarios),
        trade_limit_pct=trade_limit_pct,
        account_limit_pct=account_limit_pct,
        qty=qty,
        max_qty=0.0 if blocked else max_qty,
        blocked=blocked,
        reasons=tuple(reasons),
    )
