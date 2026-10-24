"""The briefing: one pack of facts every seat reads before the debate.

It is built once per candidate: the chart on three timeframes, the market
regime, the base rates of similar setups, the Researcher's news, the market
calendar, meme-coin warning signs, matching lessons from past debriefs, and
(for each seat alone) its own track record. Plain code works out every
number; the seats argue about what they mean.
"""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field

from free_claude_code.core.json_types import JsonObject

from .data import MarketData, Quote
from .forecasts import SeatRecord
from .indicators import Bar, TechBrief, beta, closes, returns, technical_brief
from .instruments import Instrument, parse_symbol
from .patterns import BaseRate, base_rates, setup_tag
from .providers.dexscreener import DexFacts
from .records import TradePosition
from .regime import UNKNOWN, Regime, read_regime
from .research import DeskResearch, ResearchPack

MARKET_LABELS = {
    "us": "US share",
    "asx": "ASX share",
    "crypto": "crypto coin",
    "dex": "DEX token (research only)",
}


@dataclass(frozen=True, slots=True)
class Briefing:
    instrument: Instrument
    quote: Quote
    tech: TechBrief
    regime: Regime
    base: BaseRate | None
    research: ResearchPack
    macro: ResearchPack
    lessons: tuple[str, ...]
    records: dict[int, SeatRecord]
    setup: str
    dex: DexFacts | None
    held: TradePosition | None
    tags: tuple[str, ...]
    beta: float | None
    daily: tuple[Bar, ...] = field(repr=False, default=())
    meme_warnings: tuple[str, ...] = ()
    evidence_text: str = field(repr=False, default="")
    """The numbered evidence pack, once built; the seats then read it in
    place of the plain briefing."""

    @property
    def symbol(self) -> str:
        return self.instrument.symbol

    @property
    def price(self) -> float:
        return self.quote.price

    def shared(self) -> str:
        if self.evidence_text:
            return self.evidence_text
        instrument = self.instrument
        label = MARKET_LABELS.get(instrument.market, instrument.market)
        if instrument.meme:
            label = "meme coin"
        held = (
            f"WE HOLD {self.held.qty:g} at {self.held.avg_price:g}"
            + (f", stop {self.held.stop_loss:g}" if self.held.stop_loss else "")
            + (f", target {self.held.take_profit:g}" if self.held.take_profit else "")
            if self.held is not None
            else "Not held."
        )
        sections = [
            f"SYMBOL {instrument.symbol}: {label}, prices in {self.quote.currency}. "
            f"Now {self.quote.price:g} ({self.quote.source}).",
            held,
            f"SCANNER TAGS: {', '.join(self.tags) or 'none'}",
            "CHART:\n" + self.tech.lines(),
            self.regime.lines()
            + (f"; beta to the index {self.beta:.2f}" if self.beta is not None else ""),
            self.base.lines()
            if self.base is not None
            else "Base rates: too little history.",
            "NEWS AND FACTS (gathered by the Researcher):\n" + self.research.lines(),
            "MARKET CALENDAR AND MOOD:\n" + self.macro.lines(),
        ]
        if self.dex is not None:
            facts = self.dex
            sections.append(
                f"MEME-COIN CHECKS: deepest pool ${facts.liquidity_usd:,.0f} on "
                f"{facts.dex or facts.chain}; 24h volume ${facts.volume_24h:,.0f}; "
                f"{facts.buys_24h} buys vs {facts.sells_24h} sells; age "
                + (
                    f"{facts.age_days:.0f} days"
                    if facts.age_days is not None
                    else "unknown"
                )
                + "; warnings: "
                + (", ".join(self.meme_warnings) or "none")
            )
        if self.lessons:
            sections.append(
                "LESSONS FROM PAST DEBRIEFS:\n"
                + "\n".join(f"- {lesson}" for lesson in self.lessons)
            )
        return "\n\n".join(sections)

    def for_seat(self, seat: int) -> str:
        record = self.records.get(seat)
        mine = f"\n\nYOUR TRACK RECORD: {record.line()}" if record is not None else ""
        return self.shared() + mine

    def view(self) -> JsonObject:
        return {
            "symbol": self.instrument.symbol,
            "instrument": self.instrument.view(),
            "quote": self.quote.view(),
            "tech": self.tech.view(),
            "regime": self.regime.view(),
            "base": self.base.view() if self.base is not None else None,
            "research": self.research.view(),
            "macro": self.macro.view(),
            "lessons": list(self.lessons),
            "setup": self.setup,
            "dex": self.dex.view() if self.dex is not None else None,
            "meme_warnings": list(self.meme_warnings),
            "tags": list(self.tags),
            "beta": round(self.beta, 3) if self.beta is not None else None,
            "held": (
                {"qty": self.held.qty, "avg_price": self.held.avg_price}
                if self.held is not None
                else None
            ),
        }


Recall = Callable[[str], Awaitable[list[str]]]


async def build_briefing(
    instrument: Instrument,
    *,
    data: MarketData,
    research: DeskResearch,
    recall: Recall,
    records: dict[int, SeatRecord],
    held: TradePosition | None = None,
    tags: Sequence[str] = (),
    meme_liquidity: float = 250_000.0,
    meme_age_days: float = 14.0,
) -> Briefing:
    """Gather everything at once (each source in parallel)."""
    vix_wanted = instrument.market in {"us", "asx"}
    charts, (news, macro), quote, dex = await asyncio.gather(
        asyncio.gather(
            data.bars(instrument, "1d"),
            data.bars(instrument, "1h"),
            data.bars(instrument, "15m"),
            data.index_bars(instrument.market),
            data.bars(parse_symbol("^VIX"), "1d") if vix_wanted else _nothing(),
        ),
        asyncio.gather(research.gather(instrument), research.macro(instrument.market)),
        data.quote(instrument),
        data.dex_facts(instrument),
    )
    daily, hourly, m15, index, vix = charts
    if not daily:
        raise ValueError(f"No price history for {instrument.symbol}.")
    tech = technical_brief(daily, hourly, m15)
    regime = read_regime(instrument.market, index, vix) if index else UNKNOWN
    rates = base_rates(daily, index=index)
    setup = setup_tag(daily)
    asset_returns = returns(closes(daily[-61:]))
    index_returns = returns(closes(index[-61:])) if index else []
    lessons = await recall(
        " ".join(
            [
                instrument.symbol,
                instrument.market,
                regime.label,
                *tags,
                "meme" if instrument.meme else "",
            ]
        )
    )
    warnings = (
        tuple(dex.warnings(min_liquidity=meme_liquidity, min_age_days=meme_age_days))
        if dex is not None
        else ()
    )
    return Briefing(
        instrument=instrument,
        quote=quote,
        tech=tech,
        regime=regime,
        base=rates,
        research=news,
        macro=macro,
        lessons=tuple(lessons[:4]),
        records=records,
        setup=setup,
        dex=dex,
        held=held,
        tags=tuple(tags),
        beta=beta(asset_returns, index_returns) if index_returns else None,
        daily=tuple(daily),
        meme_warnings=warnings,
    )


async def _nothing() -> list[Bar]:
    return []
