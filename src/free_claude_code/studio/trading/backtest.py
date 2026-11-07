"""The backtest: the desk's own rules replayed on past daily prices.

It is a historical simulation, labelled as such, and never a prediction:
- Only closed daily candles: a candle still forming is dropped before
  anything runs. Each day's decision reads only candles up to that day's
  close, and its order fills at the next day's open, so nothing is decided
  on a price that wasn't known yet.
- The same rules as live trading where they can be replayed: the scanner's
  setup score picks candidates, the market regime's policy (no new trades
  in an extreme market, smaller sizes, wider stops when it says so), the
  hard limits' position sizing, at most the owner's number of open
  positions, the position manager (stop to the entry at +1R, a trailing
  stop if set, the time exit), fees, a spread and slippage.
- What can't be replayed: the seats' debate (it costs a lot, and the models
  already know what happened next), so entries come from the setup score,
  stops from the ATR and targets from a reward-to-risk ratio.
- Real-market frictions: a gap through the stop fills at the open (a stop
  doesn't guarantee its price), a day with no volume can't trade (halted),
  days with no candle are holidays, and an order takes at most a tenth of
  the day's volume (the rest isn't filled). When the stop and target are
  both inside one day's range, the stop is assumed to come first.
- The symbols are today's list, so ones that were delisted are missing
  (survivorship bias): results look better than they would have been.
"""

import statistics
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from free_claude_code.core.json_types import JsonObject

from .config import RiskLimits
from .fills import ASSUMED_SPREAD_PCT, MIN_SLIPPAGE_PCT
from .indicators import Bar, setup_score, technical_brief
from .positions import Plan, manage
from .regime import policy_for, read_regime
from .risk import size_position

DAY_S = 86_400
HISTORY = 260
"""Daily candles read for each decision (enough for a 200-day average)."""
WARM_UP = 60
PARTICIPATION = 0.1
LABEL = (
    "Historical simulation of the desk's rules on past daily prices (entries "
    "from the setup score, not the seats' debate). Past results are not a "
    "prediction, and today's symbol list leaves out ones since delisted."
)


@dataclass(frozen=True, slots=True)
class Settings:
    market: str
    equity: float = 10_000.0
    limits: RiskLimits = field(default_factory=RiskLimits)
    min_score: float = 2.0
    stop_atr: float = 2.0
    min_stop_atr: float = 1.0
    reward_risk: float = 2.0
    holding_days: int = 10
    trailing_pct: float | None = None
    fee_pct: float = 0.1
    min_fee: float = 1.0
    fx: float = 1.0
    """Base currency per unit of the symbols' currency."""
    meme: bool = False


@dataclass(slots=True)
class _Open:
    symbol: str
    qty: float
    entry: float
    stop: float
    target: float
    plan: Plan
    opened_day: int
    fees: float
    high: float
    low: float
    last: float
    """The latest close (a holiday keeps the one before)."""


@dataclass(frozen=True, slots=True)
class Trade:
    symbol: str
    entry_day: int
    exit_day: int
    qty: float
    entry: float
    exit: float
    reason: str
    pnl: float
    r_multiple: float
    fees: float

    def view(self) -> JsonObject:
        return {
            "symbol": self.symbol,
            "entry_day": self.entry_day,
            "exit_day": self.exit_day,
            "qty": round(self.qty, 8),
            "entry": round(self.entry, 6),
            "exit": round(self.exit, 6),
            "reason": self.reason,
            "pnl": round(self.pnl, 2),
            "r": round(self.r_multiple, 2),
            "fees": round(self.fees, 2),
        }


def closed_only(bars: Sequence[Bar], now: float) -> list[Bar]:
    """Daily candles that have finished: one whose day hasn't ended yet is
    still forming and is dropped."""
    return [bar for bar in bars if bar.t + DAY_S <= now]


def _day(t: int) -> int:
    return t // DAY_S


def run(
    bars: Mapping[str, Sequence[Bar]],
    index: Sequence[Bar],
    settings: Settings,
    *,
    now: float,
) -> JsonObject:
    history = {
        symbol: {_day(bar.t): bar for bar in closed_only(found, now)}
        for symbol, found in bars.items()
    }
    ordered = {symbol: sorted(found) for symbol, found in history.items()}
    index_days = {_day(bar.t): bar for bar in closed_only(index, now)}
    index_order = sorted(index_days)
    index_bars = [index_days[day] for day in index_order]
    days = sorted({day for found in history.values() for day in found})
    if len(days) <= WARM_UP:
        return {
            "label": LABEL,
            "error": f"Not enough closed daily candles ({len(days)}; "
            f"{WARM_UP + 1} needed).",
        }
    spread = ASSUMED_SPREAD_PCT.get("meme" if settings.meme else settings.market, 0.2)
    cost = (spread / 2 + MIN_SLIPPAGE_PCT) / 100
    cash = settings.equity
    marked = cash
    held: dict[str, _Open] = {}
    pending: dict[str, tuple[float, float, float]] = {}
    trades: list[Trade] = []
    curve: list[JsonObject] = []
    fees_total = 0.0
    invested_days = 0

    def fee(value: float) -> float:
        return max(settings.min_fee, value * settings.fee_pct / 100)

    def close_out(position: _Open, day: int, price: float, reason: str) -> None:
        nonlocal cash, fees_total
        fill = price * (1 - cost)
        value = position.qty * fill * settings.fx
        exit_fee = fee(value)
        cash += value - exit_fee
        fees_total += exit_fee
        pnl = (fill - position.entry) * position.qty * settings.fx - (
            position.fees + exit_fee
        )
        first_stop = position.plan.initial_stop
        risk = position.entry - first_stop if first_stop is not None else 0.0
        trades.append(
            Trade(
                position.symbol,
                position.opened_day,
                day,
                position.qty,
                position.entry,
                fill,
                reason,
                pnl,
                (fill - position.entry) / risk if risk > 0 else 0.0,
                position.fees + exit_fee,
            )
        )
        del held[position.symbol]

    for number, day in enumerate(days):
        # 1. Orders decided at yesterday's close fill at today's open.
        for symbol, (qty, stop, target) in list(pending.items()):
            bar = history[symbol].get(day)
            if bar is None:
                continue  # a holiday for it: the order waits
            del pending[symbol]
            if bar.v <= 0 or bar.o <= stop:
                continue  # halted, or it opened through the stop: no entry
            volume_cap = (
                PARTICIPATION * bar.v / bar.o
                if settings.market == "crypto"
                else PARTICIPATION * bar.v
            )
            qty = min(qty, volume_cap)
            fill = bar.o * (1 + cost)
            value = qty * fill * settings.fx
            entry_fee = fee(value)
            if qty <= 0 or value + entry_fee > cash:
                continue
            cash -= value + entry_fee
            fees_total += entry_fee
            plan = Plan(
                entry=fill,
                initial_stop=stop if stop < fill else None,
                trailing_pct=settings.trailing_pct,
                holding_days=settings.holding_days,
                opened_at=float(day * DAY_S),
            )
            held[symbol] = _Open(
                symbol, qty, fill, stop, target, plan, day, entry_fee, fill, fill, fill
            )
        # 2. What is held: a gap through the stop, the stop, the target,
        #    then the position manager and the time exit at the close.
        for symbol, position in list(held.items()):
            bar = history[symbol].get(day)
            if bar is None or bar.v <= 0:
                continue  # a holiday or a halt: nothing can trade today
            position.last = bar.c
            if bar.o <= position.stop:
                close_out(position, day, bar.o, "gapped through the stop")
                continue
            if bar.l <= position.stop:
                close_out(position, day, position.stop, "stop-loss")
                continue
            if bar.h >= position.target:
                close_out(position, day, max(position.target, bar.o), "take-profit")
                continue
            step = manage(
                position.plan,
                price=bar.c,
                stop=position.stop,
                high=max(position.high, bar.h),
                low=min(position.low, bar.l),
                now=float((day + 1) * DAY_S),
            )
            position.high, position.low = step.high, step.low
            position.stop = step.stop if step.stop is not None else position.stop
            if step.exit:
                close_out(position, day, bar.c, "holding period over")
        # 3. Today's close: value the account, then decide tomorrow's orders
        #    from candles up to today only.
        marked = cash + sum(
            position.qty * position.last * settings.fx for position in held.values()
        )
        if held:
            invested_days += 1
        curve.append({"day": day * DAY_S, "equity": round(marked, 2)})
        if number < WARM_UP:
            continue
        upto = bisect_right(index_order, day)
        regime = read_regime(settings.market, index_bars[max(0, upto - HISTORY) : upto])
        policy = policy_for(regime)
        if not policy.allow_new_trades:
            continue
        room = settings.limits.max_open_positions - len(held) - len(pending)
        if room <= 0:
            continue
        ideas: list[tuple[float, str, Bar, float]] = []
        for symbol, found in history.items():
            if symbol in held or symbol in pending or day not in found:
                continue
            upto = bisect_right(ordered[symbol], day)
            past = [found[d] for d in ordered[symbol][max(0, upto - HISTORY) : upto]]
            if len(past) < WARM_UP:
                continue
            try:
                brief = technical_brief(past)
            except ValueError:
                continue
            score, _ = setup_score(brief)
            if score >= settings.min_score and brief.atr:
                ideas.append((score, symbol, past[-1], brief.atr))
        for _, symbol, bar, atr_value in sorted(ideas, reverse=True)[:room]:
            distance = max(settings.stop_atr, settings.min_stop_atr) * atr_value
            distance *= policy.stop_atr_factor
            stop = bar.c - distance
            if stop <= 0:
                continue
            target = bar.c + settings.reward_risk * distance
            sizing = size_position(
                equity=marked,
                price=bar.c,
                stop=stop,
                fx=settings.fx,
                limits=settings.limits,
                meme=settings.meme,
                regime_scale=regime.risk_scale * policy.size_factor,
            )
            if sizing.qty > 0:
                pending[symbol] = (sizing.qty, stop, target)
    # Whatever is still held is valued at its last close (not sold).
    final = marked
    return {
        "label": LABEL,
        "market": settings.market,
        "symbols": sorted(bars),
        "from": days[0] * DAY_S,
        "to": days[-1] * DAY_S,
        "metrics": _metrics(settings.equity, final, curve, trades, fees_total)
        | {"days_invested_pct": round(invested_days / len(days) * 100, 1)},
        "curve": curve,
        "trades": [trade.view() for trade in trades],
        "still_held": sorted(held),
        "assumptions": {
            "spread_pct": spread,
            "slippage_pct": MIN_SLIPPAGE_PCT,
            "fee_pct": settings.fee_pct,
            "min_fee": settings.min_fee,
            "participation": PARTICIPATION,
            "min_score": settings.min_score,
            "stop_atr": settings.stop_atr,
            "reward_risk": settings.reward_risk,
            "holding_days": settings.holding_days,
            "trailing_pct": settings.trailing_pct,
        },
    }


def _metrics(
    start: float,
    final: float,
    curve: Sequence[JsonObject],
    trades: Sequence[Trade],
    fees: float,
) -> JsonObject:
    peak = start
    worst = 0.0
    for point in curve:
        equity = point.get("equity")
        if not isinstance(equity, int | float):
            continue
        peak = max(peak, float(equity))
        worst = min(worst, float(equity) / peak - 1)
    wins = [trade.pnl for trade in trades if trade.pnl > 0]
    losses = [trade.pnl for trade in trades if trade.pnl <= 0]
    found: JsonObject = {
        "start_equity": round(start, 2),
        "end_equity": round(final, 2),
        "return_pct": round((final / start - 1) * 100, 2) if start else None,
        "max_drawdown_pct": round(worst * 100, 2),
        "trades": len(trades),
        "fees": round(fees, 2),
    }
    if trades:
        found["win_rate_pct"] = round(len(wins) / len(trades) * 100, 1)
        found["average_r"] = round(statistics.fmean(t.r_multiple for t in trades), 2)
        found["best_trade"] = round(max(t.pnl for t in trades), 2)
        found["worst_trade"] = round(min(t.pnl for t in trades), 2)
        lost = -sum(losses)
        found["profit_factor"] = round(sum(wins) / lost, 2) if lost > 0 else None
    return found
