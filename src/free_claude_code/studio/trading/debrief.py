"""Debriefs: the desk looks back, learns, and carries the lessons forward.

- After a trade closes, each of the five seats says what it predicted, what
  happened, and what it missed; the Guardian says whether its objections came
  true; the Portfolio Manager writes the desk's lesson, which is saved to the
  desk's memory (tagged by symbol, market, setup, and regime) and comes back
  in the briefing the next time something similar is debated.
- When forecasts come due, the worst misses get a one-line self-critique from
  the seat that made them.
- At each market close (the ASX and the US at 16:00 local time, crypto at a
  set hour) the session is summed up: forecasts resolved, hit rate, profit
  and loss, the best and worst seat, and whether the desk is overconfident.
- Each week, a review: the seat leaderboard, which setups and regimes worked,
  and up to two suggested setting changes the owner can accept. Nothing
  changes on its own.
"""

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable, Sequence

from free_claude_code.core.json_types import JsonObject

from ..llm import StudioLLMError
from ..store import StudioStore
from .config import DeskConfig
from .forecasts import records
from .log import SEAT_NAMES, Feed
from .records import TradeDebrief, TradeForecast, TradeRound
from .seats import (
    DebriefNote,
    MissNotes,
    SessionNote,
    Think,
    WeeklyReview,
    ask_json,
)

Remember = Callable[[str, list[str]], Awaitable[None]]
"""Save a lesson to the desk's memory with tags."""

DEBRIEF_KEYS = '"predicted": "...", "happened": "...", "missed": "...", "lesson": "..."'
MISS_KEYS = '"notes": ["one line per miss: why it missed"], "lesson": "..."'
SESSION_KEYS = '"summary": "3-4 sentences", "watch": "one thing to watch next session"'
WEEKLY_KEYS = (
    '"summary": "4-6 sentences", "suggestions": [{"text": "why", "setting": '
    '"one of: min_confidence, min_consensus, min_grade, min_reward_risk, '
    'meme_position_pct, candidates, depth", "value": "the new value"}]'
)

SUGGESTIBLE: dict[str, tuple[str, ...]] = {
    "min_confidence": ("risk", "min_confidence"),
    "min_consensus": ("risk", "min_consensus"),
    "meme_position_pct": ("risk", "meme_position_pct"),
    "min_grade": ("assessment", "min_grade"),
    "min_reward_risk": ("assessment", "min_reward_risk"),
    "candidates": ("candidates",),
    "depth": ("depth",),
}
"""The settings a weekly review may suggest; the owner accepts each one."""


class Debriefs:
    def __init__(
        self,
        *,
        store: StudioStore,
        feed: Feed,
        think: Think,
        remember: Remember,
    ) -> None:
        self._store = store
        self._feed = feed
        self._think = think
        self._remember = remember

    async def _ask[M: (DebriefNote, MissNotes, SessionNote, WeeklyReview)](
        self,
        config: DeskConfig,
        seat: int,
        prompt: str,
        model: type[M],
        keys: str,
        tokens: int,
    ) -> M | None:
        try:
            return await ask_json(
                self._think,
                config.seat(seat),
                prompt,
                model,
                max_tokens=tokens,
                keys=keys,
            )
        except StudioLLMError:
            return None

    async def trade(
        self,
        config: DeskConfig,
        *,
        symbol: str,
        market: str,
        round_record: TradeRound | None,
        entry: float,
        exit_price: float,
        gain: float,
        held_days: float,
        reason: str,
        setup: str = "",
        regime: str = "",
    ) -> TradeDebrief:
        """Every seat looks back at a closed trade; the PM writes the lesson."""
        move = (exit_price / entry - 1) * 100 if entry else 0.0
        result = (
            f"TRADE RESULT for {symbol}: bought at {entry:g}, sold at {exit_price:g} "
            f"({move:+.2f}%) after {held_days:.1f} days because {reason}; "
            f"{'profit' if gain >= 0 else 'loss'} of {abs(gain):,.2f} {config.currency}."
        )
        calls: dict[int, str] = {}
        forecasts: list[TradeForecast] = []
        if round_record is not None:
            forecasts = list(
                await self._store.find(
                    TradeForecast, where={"round_id": round_record.id}
                )
            )
        objections = ""
        if round_record is not None:
            found = round_record.data.get("objections")
            if isinstance(found, list) and found:
                objections = "\n".join(f"- {item}" for item in found[:5])
        for forecast in forecasts:
            if forecast.stage in {"closing", "decision"}:
                calls[forecast.seat] = (
                    f"{forecast.p_up:.0%} chance of a rise in {forecast.horizon_days}d, "
                    f"expected {forecast.expected_move:+.1f}%"
                )

        async def look_back(seat: int) -> tuple[int, DebriefNote | None]:
            prompt = "\n\n".join(
                part
                for part in (
                    result,
                    f"YOUR CALL WAS: {calls.get(seat, 'not recorded')}",
                    f"THE RISK GUARDIAN'S OBJECTIONS WERE:\n{objections}"
                    if objections
                    else "",
                    "TASK: Debrief. What did you predict, what actually happened, "
                    "what did you miss? Give one lesson for next time."
                    + (
                        " Say plainly whether your objections came true."
                        if seat == 4
                        else ""
                    )
                    + (
                        " Your lesson is the desk's lesson: make it specific and "
                        "useful for similar trades."
                        if seat == 5
                        else ""
                    ),
                    f"Reply with ONLY this JSON object: {{{DEBRIEF_KEYS}}}",
                )
                if part
            )
            return seat, await self._ask(
                config, seat, prompt, DebriefNote, DEBRIEF_KEYS, 320
            )

        notes: dict[int, DebriefNote] = {}
        for seat, note in await asyncio.gather(
            *(look_back(seat) for seat in range(1, 6))
        ):
            if note is None:
                continue
            notes[seat] = note
            await self._feed.emit(
                "debrief",
                f"Missed: {note.missed or '-'} Lesson: {note.lesson or '-'}",
                seat=seat,
                round_id=round_record.id if round_record else "",
                symbol=symbol,
                stage="Trade debrief",
                data={"note": note.model_dump()},
            )
        lesson = notes[5].lesson if 5 in notes and notes[5].lesson else ""
        if lesson:
            tags = [symbol, market, "trade", *setup.split(), *regime.split()]
            await self._remember(
                f"{symbol} ({market}): {lesson}", [t for t in tags if t]
            )
            await self._feed.emit(
                "lesson",
                lesson,
                seat=5,
                round_id=round_record.id if round_record else "",
                symbol=symbol,
                stage="Trade debrief",
            )
        debrief = TradeDebrief(
            kind="trade",
            round_id=round_record.id if round_record else "",
            symbol=symbol,
            market=market,
            title=f"{symbol}: {move:+.2f}% ({reason})",
            summary=result,
            lesson=lesson,
            data={
                "notes": {str(seat): note.model_dump() for seat, note in notes.items()},
                "gain": round(gain, 2),
                "move_pct": round(move, 3),
                "held_days": round(held_days, 2),
                "reason": reason,
            },
        )
        await self._store.put(debrief)
        return debrief

    async def forecasts(
        self, config: DeskConfig, scored: Sequence[TradeForecast]
    ) -> TradeDebrief | None:
        """The worst misses among newly scored forecasts get a self-critique."""
        misses = sorted(
            (f for f in scored if f.hit is False and f.brier is not None),
            key=lambda f: f.brier or 0.0,
            reverse=True,
        )[:4]
        if not misses:
            return None
        by_seat: dict[int, list[TradeForecast]] = defaultdict(list)
        for forecast in misses:
            if forecast.seat in SEAT_NAMES:
                by_seat[forecast.seat].append(forecast)

        async def critique(
            seat: int, items: list[TradeForecast]
        ) -> tuple[int, MissNotes | None]:
            lines = "\n".join(
                f"- {f.symbol}: you gave {f.p_up:.0%} for a rise in {f.horizon_days}d; "
                f"it moved {f.outcome_move or 0:+.2f}%."
                for f in items
            )
            prompt = (
                f"THESE FORECASTS OF YOURS CAME DUE AND MISSED:\n{lines}\n\n"
                "TASK: In one line each, why did you miss? Then one lesson.\n\n"
                f"Reply with ONLY this JSON object: {{{MISS_KEYS}}}"
            )
            return seat, await self._ask(
                config, seat, prompt, MissNotes, MISS_KEYS, 260
            )

        notes: dict[int, MissNotes] = {}
        for seat, found in await asyncio.gather(
            *(critique(seat, items) for seat, items in by_seat.items())
        ):
            if found is None:
                continue
            notes[seat] = found
            await self._feed.emit(
                "debrief",
                "; ".join(found.notes)
                + (f" Lesson: {found.lesson}" if found.lesson else ""),
                seat=seat,
                stage="Forecast debrief",
                data={"notes": found.model_dump()},
            )
            if found.lesson:
                symbols = sorted({f.symbol for f in by_seat[seat]})
                await self._remember(
                    f"{SEAT_NAMES[seat]} on missed forecasts: {found.lesson}",
                    ["forecast", *symbols],
                )
        debrief = TradeDebrief(
            kind="forecast",
            title=f"{len(misses)} missed forecasts",
            summary="; ".join(
                f"{f.symbol} {SEAT_NAMES.get(f.seat, '')} {f.p_up:.0%} up, moved "
                f"{f.outcome_move or 0:+.1f}%"
                for f in misses
            ),
            data={"notes": {str(seat): n.model_dump() for seat, n in notes.items()}},
        )
        await self._store.put(debrief)
        return debrief

    async def session(
        self,
        config: DeskConfig,
        *,
        market: str,
        since_ms: int,
        realised: float,
        trades: int,
    ) -> TradeDebrief:
        """Sum up one market's session."""
        scored = [
            f
            for f in await self._store.find(
                TradeForecast, where={"status": "scored", "market": market}
            )
            if (f.scored_at or 0) >= since_ms
        ]
        stats = _stats(scored)
        lessons = [
            debrief.lesson
            for debrief in await self._store.find(
                TradeDebrief,
                where={"kind": "trade", "market": market},
                order_by="created_at DESC",
                limit=5,
            )
            if debrief.created_at >= since_ms and debrief.lesson
        ]
        facts = (
            f"SESSION: {market.upper()}. Forecasts resolved: {stats['count']}; direction "
            f"right {_pct(stats['hit_rate'])}; average Brier {stats['brier'] if stats['brier'] is not None else 'n/a'}. "
            f"Trades: {trades}; realised {realised:+,.2f} {config.currency}. "
            f"Best seat: {stats['best'] or 'n/a'}; worst seat: {stats['worst'] or 'n/a'}. "
            f"Calibration: said {_pct(stats['said'])}, happened {_pct(stats['hit_rate'])}."
            + (
                ("\nLESSONS TODAY:\n" + "\n".join(f"- {item}" for item in lessons))
                if lessons
                else ""
            )
        )
        note = await self._ask(
            config,
            5,
            f"{facts}\n\nTASK: Write the session debrief and one thing to watch next "
            f"session.\n\nReply with ONLY this JSON object: {{{SESSION_KEYS}}}",
            SessionNote,
            SESSION_KEYS,
            400,
        )
        summary = note.summary if note is not None and note.summary else facts
        debrief = TradeDebrief(
            kind="session",
            market=market,
            title=f"{market.upper()} session: {stats['count']} forecasts, {trades} trades",
            summary=summary,
            lesson=note.watch if note is not None else "",
            data={
                **stats,
                "realised": round(realised, 2),
                "trades": trades,
                "facts": facts,
            },
        )
        await self._store.put(debrief)
        await self._feed.emit(
            "debrief", summary, seat=5, stage=f"{market.upper()} session debrief"
        )
        return debrief

    async def weekly(self, config: DeskConfig, *, since_ms: int) -> TradeDebrief:
        """The weekly review: leaderboard, what worked, and suggestions."""
        everything = list(
            await self._store.find(
                TradeForecast,
                where={"status": "scored"},
                order_by="scored_at DESC",
                limit=3000,
            )
        )
        week = [f for f in everything if (f.scored_at or 0) >= since_ms]
        board = records(everything)
        board_week = records(week)
        leaderboard = [
            {
                "seat": seat,
                "name": SEAT_NAMES[seat],
                "all_time": board[seat].view(),
                "week": board_week[seat].view(),
            }
            for seat in range(1, 6)
        ]
        groups: dict[str, list[TradeForecast]] = defaultdict(list)
        for forecast in week:
            if forecast.regime:
                groups[f"regime {forecast.regime}"].append(forecast)
            for part in forecast.setup.split():
                if part.startswith(("RSI:", "200d:")):
                    groups[part].append(forecast)
        what_worked = sorted(
            (
                {
                    "group": name,
                    "count": len(items),
                    "hit_rate": round(sum(1 for f in items if f.hit) / len(items), 3),
                }
                for name, items in groups.items()
                if len(items) >= 3
            ),
            key=lambda row: -float(row["hit_rate"]),
        )
        facts = "WEEKLY REVIEW.\nLEADERBOARD (this week / all time):\n" + "\n".join(
            f"- {SEAT_NAMES[seat]}: {board_week[seat].line()} / {board[seat].line()}"
            for seat in range(1, 6)
        )
        if what_worked:
            facts += "\nWHAT WORKED (direction right):\n" + "\n".join(
                f"- {row['group']}: {float(row['hit_rate']):.0%} of {row['count']}"
                for row in what_worked[:8]
            )
        facts += (
            f"\nCURRENT SETTINGS: min_confidence {config.risk.min_confidence}, "
            f"min_consensus {config.risk.min_consensus}, min_grade "
            f"{config.assessment.min_grade}, min_reward_risk "
            f"{config.assessment.min_reward_risk}, meme_position_pct "
            f"{config.risk.meme_position_pct}, candidates {config.candidates}, depth {config.depth}."
        )
        review = await self._ask(
            config,
            5,
            f"{facts}\n\nTASK: Write the weekly review and suggest at most two "
            "setting changes that the numbers support (or none).\n\n"
            f"Reply with ONLY this JSON object: {{{WEEKLY_KEYS}}}",
            WeeklyReview,
            WEEKLY_KEYS,
            600,
        )
        suggestions: list[JsonObject] = [
            {
                "text": item.text,
                "setting": item.setting,
                "value": item.value,
                "accepted": False,
            }
            for item in (review.suggestions if review is not None else [])
            if item.setting in SUGGESTIBLE and item.value not in (None, "")
        ]
        summary = review.summary if review is not None and review.summary else facts
        debrief = TradeDebrief(
            kind="weekly",
            title=f"Weekly review: {len(week)} forecasts scored",
            summary=summary,
            data={
                "leaderboard": leaderboard,
                "what_worked": what_worked,
                "suggestions": suggestions,
                "facts": facts,
            },
        )
        await self._store.put(debrief)
        await self._feed.emit(
            "debrief",
            summary
            + (
                f" Suggestions: {len(suggestions)} to accept or skip."
                if suggestions
                else ""
            ),
            seat=5,
            stage="Weekly review",
        )
        return debrief


def _pct(value: object) -> str:
    return f"{float(value):.0%}" if isinstance(value, int | float) else "n/a"


def _stats(scored: Sequence[TradeForecast]) -> JsonObject:
    if not scored:
        return {
            "count": 0,
            "hit_rate": None,
            "brier": None,
            "said": None,
            "best": "",
            "worst": "",
        }
    by_seat: dict[int, list[float]] = defaultdict(list)
    for forecast in scored:
        by_seat[forecast.seat].append(forecast.brier or 0.0)
    ranked = sorted(by_seat.items(), key=lambda item: sum(item[1]) / len(item[1]))
    return {
        "count": len(scored),
        "hit_rate": round(sum(1 for f in scored if f.hit) / len(scored), 3),
        "brier": round(sum(f.brier or 0.0 for f in scored) / len(scored), 4),
        "said": round(sum(max(f.p_up, 1 - f.p_up) for f in scored) / len(scored), 3),
        "best": SEAT_NAMES.get(ranked[0][0], "") if ranked else "",
        "worst": SEAT_NAMES.get(ranked[-1][0], "") if len(ranked) > 1 else "",
    }
