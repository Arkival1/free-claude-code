"""The scanner: which symbols are worth a debate this round.

Every symbol in the watchlist and the market lists gets a cheap chart read
(plain code, no model), and a setup score: uptrends, breakouts on volume,
pullbacks in an uptrend, oversold bounces. Only the best few go on to the
costly five-seat debate, and anything held is always reviewed so the desk
can decide to sell. Shares are only scanned while their market is open.
"""

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from loguru import logger

from ..workers import WorkerPool
from .data import MarketData
from .indicators import setup_score, technical_brief
from .instruments import Instrument

MIN_BARS = 30


@dataclass(frozen=True, slots=True)
class Candidate:
    instrument: Instrument
    score: float
    tags: tuple[str, ...]
    held: bool = False


async def scan(
    instruments: Sequence[Instrument],
    *,
    data: MarketData,
    workers: WorkerPool,
    held: set[str],
    limit: int,
    is_open: Callable[[str], bool],
    max_reviews: int = 3,
) -> list[Candidate]:
    """The top ``limit`` setups, plus up to ``max_reviews`` held symbols."""

    async def read(instrument: Instrument) -> Candidate | None:
        if not instrument.tradable or not is_open(instrument.market):
            return None
        async with workers.lane(
            "data", label=f"scan {instrument.symbol}", low_priority=True
        ):
            bars = await data.bars(instrument, "1d")
        if len(bars) < MIN_BARS:
            return None
        try:
            brief = technical_brief(bars)
        except ValueError:
            return None
        score, tags = setup_score(brief)
        return Candidate(instrument, score, tags, held=instrument.symbol in held)

    found = await asyncio.gather(
        *(read(item) for item in instruments), return_exceptions=True
    )
    candidates: list[Candidate] = []
    for item, result in zip(instruments, found, strict=True):
        if isinstance(result, asyncio.CancelledError):
            raise result
        if isinstance(result, BaseException):
            logger.info("Trading: couldn't scan {}: {}", item.symbol, result)
            continue
        if result is not None:
            candidates.append(result)
    reviews = [c for c in candidates if c.held][:max_reviews]
    fresh = sorted(
        (c for c in candidates if not c.held and c.score > 0),
        key=lambda c: c.score,
        reverse=True,
    )[:limit]
    return reviews + fresh
