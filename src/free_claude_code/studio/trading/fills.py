"""How a practice order would fill on the real market, worked out from real
prices. Only the practice (paper) account uses this; a real account fills
however its platform fills.

- The price: a buy pays the ask and a sell gets the bid, from a live order
  book when one is known (Coinbase or Kraken for coins, or the quote's own).
  With no live book (shares, mostly) an assumed spread is used instead,
  labelled as such, and deliberately not small.
- Slippage on top: at least 0.05%, more for an order that is big next to
  what the market trades (the square-root rule: a day's volatility times
  the square root of the order's share of a day's turnover).
- Partial fills: each minute the account takes at most a tenth of what the
  market trades in an average minute; the rest fills in later minutes, at
  the prices then. A thin market fills slowly, as it would for real.
- A limit order fills only once the ask (buying) or bid (selling) reaches
  its price, never beyond it, and expires after a day.
These are assumptions about a real fill, not a record of one; each fill
says which were used.
"""

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from .indicators import Bar
from .quality import daily_turnover

ASSUMED_SPREAD_PCT = {"us": 0.10, "asx": 0.30, "crypto": 0.20, "meme": 2.0}
"""The whole bid-ask spread assumed when no live book is known."""
MIN_SLIPPAGE_PCT = 0.05
UNKNOWN_VOLUME_SLIPPAGE_PCT = 0.5
"""Slippage when the market's turnover isn't known (cautious)."""
PARTICIPATION = 0.1
"""The most of an average minute's turnover one practice order takes."""
TRADING_MINUTES = {"us": 390.0, "asx": 360.0, "crypto": 1440.0}
LIMIT_HOURS = 24.0
"""A practice limit order not reached in this long expires."""
HISTORY_DAYS = 20


@dataclass(frozen=True, slots=True)
class Conditions:
    """What the market looks like for one practice fill."""

    price: float
    bid: float | None = None
    ask: float | None = None
    book: str = ""
    """Who gave the bid and ask; "" when no live book is known."""
    turnover: float | None = None
    """Average money traded a day, in the symbol's currency."""
    volatility: float | None = None
    """Standard deviation of daily returns (0.02 is 2%)."""


@dataclass(frozen=True, slots=True)
class Slice:
    qty: float
    """0 when nothing fills this time (a limit not reached)."""
    price: float
    slippage_pct: float
    basis: str
    """How the price was worked out, in plain words."""


def conditions(
    price: float,
    bars: Sequence[Bar],
    *,
    market: str,
    bid: float | None = None,
    ask: float | None = None,
    book: str = "",
) -> Conditions:
    """The market from a live price and the daily candles. The newest candle
    is still forming (part of a day), so only the ones before it count."""
    closed = list(bars[:-1])[-HISTORY_DAYS:]
    traded = [bar for bar in closed if bar.v > 0]
    turnover = (
        sum(daily_turnover(bar, market) for bar in traded) / len(traded)
        if traded
        else None
    )
    returns = [
        later.c / earlier.c - 1 for earlier, later in pairwise(closed) if earlier.c > 0
    ]
    volatility = statistics.pstdev(returns) if len(returns) >= 5 else None
    valid = bid is not None and ask is not None and 0 < bid <= ask
    return Conditions(
        price=price,
        bid=bid if valid else None,
        ask=ask if valid else None,
        book=book if valid else "",
        turnover=turnover if turnover and turnover > 0 else None,
        volatility=volatility,
    )


def next_slice(
    *,
    side: str,
    remaining: float,
    seen: Conditions,
    profile: str,
    market: str,
    minutes: float,
    limit: float | None = None,
    step: float = 0.0,
) -> Slice:
    """How much of what is left fills now, and at what price."""
    buying = side == "buy"
    if seen.bid is not None and seen.ask is not None:
        reference = seen.ask if buying else seen.bid
        basis = f"{seen.book} {'ask' if buying else 'bid'}"
    else:
        spread = ASSUMED_SPREAD_PCT.get(profile, ASSUMED_SPREAD_PCT["meme"])
        half = spread / 200
        reference = seen.price * (1 + half if buying else 1 - half)
        basis = f"an assumed {spread:g}% spread (no live bid/ask)"
    if limit is not None and (reference > limit if buying else reference < limit):
        return Slice(0.0, reference, 0.0, f"{basis} hasn't reached the limit")
    qty = remaining
    if seen.turnover is not None and reference > 0:
        per_minute = seen.turnover / TRADING_MINUTES.get(market, 1440.0)
        qty = min(remaining, PARTICIPATION * per_minute * max(0.0, minutes) / reference)
    if step > 0:
        # Whole units (ASX shares): at least one, never more than is left.
        qty = min(remaining, max(step, math.floor(qty / step) * step))
    if seen.turnover is None:
        slippage = UNKNOWN_VOLUME_SLIPPAGE_PCT
    else:
        impact = (
            100 * seen.volatility * math.sqrt(qty * reference / seen.turnover)
            if seen.volatility is not None
            else 0.0
        )
        slippage = max(MIN_SLIPPAGE_PCT, impact)
    price = reference * (1 + slippage / 100 if buying else 1 - slippage / 100)
    if limit is not None:
        # A limit order never fills beyond its price.
        price = min(price, limit) if buying else max(price, limit)
    return Slice(qty, price, slippage, f"{basis}, slippage {slippage:.2f}%")
