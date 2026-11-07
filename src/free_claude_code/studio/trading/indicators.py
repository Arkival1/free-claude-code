"""Chart maths in plain Python: averages, momentum, volatility, and levels.

Nothing here needs numpy: a few hundred bars a symbol is quick in plain
Python, and the desk works each symbol out once per scan, in a thread.
"""

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass

from free_claude_code.core.json_types import JsonObject


@dataclass(frozen=True, slots=True)
class Bar:
    """One candle: when it started (Unix seconds), its prices, and volume."""

    t: int
    o: float
    h: float
    l: float  # noqa: E741 - the usual name for a candle's low
    c: float
    v: float = 0.0


def closes(bars: Sequence[Bar]) -> list[float]:
    return [bar.c for bar in bars]


def sma(values: Sequence[float], n: int) -> list[float | None]:
    found: list[float | None] = []
    total = 0.0
    for index, value in enumerate(values):
        total += value
        if index >= n:
            total -= values[index - n]
        found.append(total / n if index >= n - 1 else None)
    return found


def ema(values: Sequence[float], n: int) -> list[float | None]:
    found: list[float | None] = []
    k = 2 / (n + 1)
    current: float | None = None
    for index, value in enumerate(values):
        if index < n - 1:
            found.append(None)
            continue
        if current is None:
            current = sum(values[index - n + 1 : index + 1]) / n
        else:
            current = value * k + current * (1 - k)
        found.append(current)
    return found


def rsi(values: Sequence[float], n: int = 14) -> list[float | None]:
    """Wilder's relative strength index, 0-100."""
    found: list[float | None] = [None] * len(values)
    if len(values) <= n:
        return found
    gains = losses = 0.0
    for index in range(1, n + 1):
        change = values[index] - values[index - 1]
        gains += max(change, 0.0)
        losses += max(-change, 0.0)
    average_gain, average_loss = gains / n, losses / n
    found[n] = _rsi_value(average_gain, average_loss)
    for index in range(n + 1, len(values)):
        change = values[index] - values[index - 1]
        average_gain = (average_gain * (n - 1) + max(change, 0.0)) / n
        average_loss = (average_loss * (n - 1) + max(-change, 0.0)) / n
        found[index] = _rsi_value(average_gain, average_loss)
    return found


def _rsi_value(gain: float, loss: float) -> float:
    if loss == 0:
        return 100.0 if gain > 0 else 50.0
    return 100 - 100 / (1 + gain / loss)


def macd(
    values: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """The MACD line, its signal line, and the histogram between them."""
    fast_line, slow_line = ema(values, fast), ema(values, slow)
    line: list[float | None] = [
        f - s if f is not None and s is not None else None
        for f, s in zip(fast_line, slow_line, strict=True)
    ]
    known = [value for value in line if value is not None]
    signal_known = ema(known, signal) if known else []
    signal_line: list[float | None] = [None] * (len(line) - len(known)) + signal_known
    histogram: list[float | None] = [
        m - s if m is not None and s is not None else None
        for m, s in zip(line, signal_line, strict=True)
    ]
    return line, signal_line, histogram


def true_ranges(bars: Sequence[Bar]) -> list[float]:
    found: list[float] = []
    for index, bar in enumerate(bars):
        if index == 0:
            found.append(bar.h - bar.l)
            continue
        previous = bars[index - 1].c
        found.append(max(bar.h - bar.l, abs(bar.h - previous), abs(bar.l - previous)))
    return found


def atr(bars: Sequence[Bar], n: int = 14) -> list[float | None]:
    """Wilder's average true range: how far price usually moves in a bar."""
    ranges = true_ranges(bars)
    found: list[float | None] = [None] * len(ranges)
    if len(ranges) < n:
        return found
    current = sum(ranges[:n]) / n
    found[n - 1] = current
    for index in range(n, len(ranges)):
        current = (current * (n - 1) + ranges[index]) / n
        found[index] = current
    return found


def bollinger(
    values: Sequence[float], n: int = 20, k: float = 2.0
) -> tuple[float | None, float | None, float | None]:
    """The latest middle, upper, and lower Bollinger bands."""
    if len(values) < n:
        return None, None, None
    window = values[-n:]
    middle = sum(window) / n
    spread = statistics.pstdev(window)
    return middle, middle + k * spread, middle - k * spread


def roc(values: Sequence[float], n: int) -> float | None:
    """Percent change over the last n bars."""
    if len(values) <= n or values[-n - 1] == 0:
        return None
    return (values[-1] / values[-n - 1] - 1) * 100


def volume_z(bars: Sequence[Bar], n: int = 20) -> float | None:
    """How unusual the latest bar's volume is against the n before it."""
    if len(bars) <= n:
        return None
    window = [bar.v for bar in bars[-n - 1 : -1]]
    spread = statistics.pstdev(window)
    if spread == 0:
        return None
    return (bars[-1].v - sum(window) / n) / spread


def adx(bars: Sequence[Bar], n: int = 14) -> float | None:
    """Wilder's average directional index: trend strength, 0-100."""
    if len(bars) < 2 * n + 1:
        return None
    plus_dm: list[float] = []
    minus_dm: list[float] = []
    ranges = true_ranges(bars)[1:]
    for index in range(1, len(bars)):
        up = bars[index].h - bars[index - 1].h
        down = bars[index - 1].l - bars[index].l
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
    smoothed_tr = sum(ranges[:n])
    smoothed_plus = sum(plus_dm[:n])
    smoothed_minus = sum(minus_dm[:n])
    dx_values: list[float] = []
    for index in range(n, len(ranges)):
        smoothed_tr = smoothed_tr - smoothed_tr / n + ranges[index]
        smoothed_plus = smoothed_plus - smoothed_plus / n + plus_dm[index]
        smoothed_minus = smoothed_minus - smoothed_minus / n + minus_dm[index]
        if smoothed_tr == 0:
            dx_values.append(0.0)
            continue
        plus_di = 100 * smoothed_plus / smoothed_tr
        minus_di = 100 * smoothed_minus / smoothed_tr
        total = plus_di + minus_di
        dx_values.append(0.0 if total == 0 else 100 * abs(plus_di - minus_di) / total)
    if len(dx_values) < n:
        return None
    current = sum(dx_values[:n]) / n
    for value in dx_values[n:]:
        current = (current * (n - 1) + value) / n
    return current


def vwap(bars: Sequence[Bar]) -> float | None:
    """The volume-weighted average price over the bars given."""
    weight = sum(bar.v for bar in bars)
    if weight <= 0:
        return None
    return sum((bar.h + bar.l + bar.c) / 3 * bar.v for bar in bars) / weight


def swing_levels(
    bars: Sequence[Bar], *, window: int = 3, keep: int = 3
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Recent supports below the last price and resistances above it, from
    swing lows and highs (a bar lower or higher than ``window`` on each side)."""
    if len(bars) < 2 * window + 1:
        return (), ()
    price = bars[-1].c
    lows: list[float] = []
    highs: list[float] = []
    for index in range(window, len(bars) - window):
        around = bars[index - window : index + window + 1]
        if bars[index].l == min(bar.l for bar in around):
            lows.append(bars[index].l)
        if bars[index].h == max(bar.h for bar in around):
            highs.append(bars[index].h)
    supports = sorted({round(low, 6) for low in lows if low < price}, reverse=True)
    resistances = sorted({round(high, 6) for high in highs if high > price})
    return tuple(supports[:keep]), tuple(resistances[:keep])


def returns(values: Sequence[float]) -> list[float]:
    return [
        values[index] / values[index - 1] - 1
        for index in range(1, len(values))
        if values[index - 1]
    ]


def correlation(a: Sequence[float], b: Sequence[float]) -> float | None:
    """Pearson correlation of two return series, matched from their ends."""
    size = min(len(a), len(b))
    if size < 10:
        return None
    x, y = list(a[-size:]), list(b[-size:])
    mean_x, mean_y = sum(x) / size, sum(y) / size
    covariance = sum((p - mean_x) * (q - mean_y) for p, q in zip(x, y, strict=True))
    spread_x = math.sqrt(sum((p - mean_x) ** 2 for p in x))
    spread_y = math.sqrt(sum((q - mean_y) ** 2 for q in y))
    if spread_x == 0 or spread_y == 0:
        return None
    return covariance / (spread_x * spread_y)


def beta(asset: Sequence[float], index: Sequence[float]) -> float | None:
    """How much the asset moves for each 1% the index moves."""
    size = min(len(asset), len(index))
    if size < 10:
        return None
    x, y = list(index[-size:]), list(asset[-size:])
    mean_x, mean_y = sum(x) / size, sum(y) / size
    variance = sum((p - mean_x) ** 2 for p in x)
    if variance == 0:
        return None
    return (
        sum((p - mean_x) * (q - mean_y) for p, q in zip(x, y, strict=True)) / variance
    )


def last(values: Sequence[float | None]) -> float | None:
    return values[-1] if values else None


@dataclass(frozen=True, slots=True)
class TechBrief:
    """The chart, read once per candidate and shared by every seat."""

    price: float
    change_1d: float | None
    change_5d: float | None
    change_20d: float | None
    sma20: float | None
    sma50: float | None
    sma200: float | None
    rsi: float | None
    rsi_hourly: float | None
    macd_hist: float | None
    atr: float | None
    atr_pct: float | None
    bb_pctb: float | None
    volume_z: float | None
    high_20: float | None
    low_20: float | None
    high_52w: float | None
    low_52w: float | None
    adx: float | None
    supports: tuple[float, ...]
    resistances: tuple[float, ...]
    trend: str
    """up, down, or sideways (from the 50- and 200-day averages)."""
    intraday: str
    """The 15-minute picture: up, down, sideways, or unknown."""
    avg_volume: float | None
    """Average daily volume over 20 days, in shares or coins."""

    def view(self) -> JsonObject:
        return {
            "price": _round(self.price),
            "change_1d": _round(self.change_1d, 2),
            "change_5d": _round(self.change_5d, 2),
            "change_20d": _round(self.change_20d, 2),
            "sma20": _round(self.sma20),
            "sma50": _round(self.sma50),
            "sma200": _round(self.sma200),
            "rsi": _round(self.rsi, 1),
            "rsi_hourly": _round(self.rsi_hourly, 1),
            "macd_hist": _round(self.macd_hist),
            "atr": _round(self.atr),
            "atr_pct": _round(self.atr_pct, 2),
            "bb_pctb": _round(self.bb_pctb, 2),
            "volume_z": _round(self.volume_z, 2),
            "high_20": _round(self.high_20),
            "low_20": _round(self.low_20),
            "high_52w": _round(self.high_52w),
            "low_52w": _round(self.low_52w),
            "adx": _round(self.adx, 1),
            "supports": [_round(level) for level in self.supports],
            "resistances": [_round(level) for level in self.resistances],
            "trend": self.trend,
            "intraday": self.intraday,
            "avg_volume": _round(self.avg_volume, 0),
        }

    def lines(self) -> str:
        """The chart as short lines for a prompt."""

        def show(value: float | None, digits: int = 2, unit: str = "") -> str:
            return "n/a" if value is None else f"{value:.{digits}f}{unit}"

        price = self.price
        rows = [
            f"Price {_price(price)}; change 1d {show(self.change_1d, 1, '%')}, "
            f"5d {show(self.change_5d, 1, '%')}, 20d {show(self.change_20d, 1, '%')}",
            f"Trend {self.trend} (15m: {self.intraday}); averages 20/50/200: "
            f"{_price(self.sma20)} / {_price(self.sma50)} / {_price(self.sma200)}; "
            f"ADX {show(self.adx, 0)}",
            f"RSI daily {show(self.rsi, 0)}, hourly {show(self.rsi_hourly, 0)}; "
            f"MACD histogram {show(self.macd_hist, 4)}; Bollinger %b "
            f"{show(self.bb_pctb, 2)}",
            f"ATR {_price(self.atr)} ({show(self.atr_pct, 1, '%')} of price); "
            f"volume vs 20-day {show(self.volume_z, 1)} sd",
            f"20-day range {_price(self.low_20)}-{_price(self.high_20)}; 52-week "
            f"{_price(self.low_52w)}-{_price(self.high_52w)}",
            "Supports "
            + (", ".join(_price(level) for level in self.supports) or "none near")
            + "; resistances "
            + (", ".join(_price(level) for level in self.resistances) or "none near"),
        ]
        return "\n".join(rows)


def _round(value: float | None, digits: int = 6) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(value, digits)


def _price(value: float | None) -> str:
    if value is None:
        return "n/a"
    if abs(value) >= 100:
        return f"{value:,.2f}"
    if abs(value) >= 1:
        return f"{value:.3f}"
    return f"{value:.8g}"


def _trend(price: float, short: float | None, long: float | None) -> str:
    if short is None:
        return "unknown"
    if long is None:
        return "up" if price > short else "down"
    if price > short > long:
        return "up"
    if price < short < long:
        return "down"
    return "sideways"


def technical_brief(
    daily: Sequence[Bar], hourly: Sequence[Bar] = (), m15: Sequence[Bar] = ()
) -> TechBrief:
    """Read the daily chart (and the hourly and 15-minute ones when given)."""
    if not daily:
        raise ValueError("No price history to read.")
    values = closes(daily)
    price = values[-1]
    sma20, sma50, sma200 = (last(sma(values, n)) for n in (20, 50, 200))
    hist = last(macd(values)[2])
    average_range = last(atr(daily))
    _, upper, lower = bollinger(values)
    pctb = (
        (price - lower) / (upper - lower)
        if upper is not None and lower is not None and upper != lower
        else None
    )
    supports, resistances = swing_levels(daily[-120:])
    recent = daily[-20:]
    year = daily[-252:]
    short_closes = closes(m15) if m15 else []
    intraday = (
        _trend(
            short_closes[-1], last(ema(short_closes, 20)), last(ema(short_closes, 50))
        )
        if len(short_closes) >= 20
        else "unknown"
    )
    return TechBrief(
        price=price,
        change_1d=roc(values, 1),
        change_5d=roc(values, 5),
        change_20d=roc(values, 20),
        sma20=sma20,
        sma50=sma50,
        sma200=sma200,
        rsi=last(rsi(values)),
        rsi_hourly=last(rsi(closes(hourly))) if len(hourly) > 15 else None,
        macd_hist=hist,
        atr=average_range,
        atr_pct=average_range / price * 100 if average_range and price else None,
        bb_pctb=pctb,
        volume_z=volume_z(daily),
        high_20=max(bar.h for bar in recent),
        low_20=min(bar.l for bar in recent),
        high_52w=max(bar.h for bar in year),
        low_52w=min(bar.l for bar in year),
        adx=adx(daily),
        supports=supports,
        resistances=resistances,
        trend=_trend(price, sma50 if sma50 is not None else sma20, sma200),
        intraday=intraday,
        avg_volume=sum(bar.v for bar in recent) / len(recent) if recent else None,
    )


def setup_score(brief: TechBrief) -> tuple[float, tuple[str, ...]]:
    """A cheap score for how interesting a long trade looks, and why; only
    the best few setups go on to the (costly) debate."""
    score = 0.0
    tags: list[str] = []
    rsi_now = brief.rsi
    if brief.trend == "up":
        score += 1.0
        tags.append("uptrend")
    elif brief.trend == "down":
        score -= 1.0
        tags.append("downtrend")
    if (
        brief.high_20 is not None
        and brief.price >= brief.high_20 * 0.995
        and (brief.volume_z or 0) > 1
    ):
        score += 1.5
        tags.append("breakout")
    if brief.trend == "up" and rsi_now is not None and rsi_now < 45:
        score += 1.0
        tags.append("pullback")
    if rsi_now is not None and rsi_now < 30:
        score += 0.7
        tags.append("oversold")
    if rsi_now is not None and rsi_now > 75:
        score -= 0.7
        tags.append("overbought")
    if (brief.change_5d or 0) > 0 and (brief.change_20d or 0) > 0:
        score += 0.5
        tags.append("momentum")
    if (brief.volume_z or 0) > 2:
        score += 0.5
        tags.append("volume spike")
    if (brief.macd_hist or 0) > 0:
        score += 0.3
    return round(score, 2), tuple(tags)
