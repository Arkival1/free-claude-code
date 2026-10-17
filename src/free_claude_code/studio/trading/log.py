"""The desk's live feed: every seat's words, every check, every order.

Each line goes to Studio's database (the Trading page reads new lines by
number) and to a plain daily log file in ``trading/logs`` (one JSON object a
line, 30 days kept) that can be read without the app.
"""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from loguru import logger

from free_claude_code.core.json_types import JsonObject

from ..models import now_ms
from ..store import StudioStore
from .decisions import AUDIT_KINDS, system_version
from .records import TradeAudit, TradeEvent

KEEP_EVENTS = 20_000
"""Older feed lines are dropped from the database (the log files keep them)."""
KEEP_LOG_DAYS = 30
LOUD_KINDS = frozenset({"order", "fill", "error", "risk_gate", "check"})
"""Kinds also written to FCC's own log."""

SEAT_NAMES = {
    0: "Desk",
    1: "Technical Analyst",
    2: "Researcher",
    3: "Macro & Sentiment",
    4: "Risk Guardian",
    5: "Portfolio Manager",
}


class Feed:
    def __init__(self, store: StudioStore, logs: Path) -> None:
        self._store = store
        self._logs = logs
        self._seq: int | None = None
        self._ready = asyncio.Lock()
        self._written = 0
        self._pruned_day = ""
        self.config_version = ""
        """The settings' version, kept with every audit line."""
        self._system = system_version()

    async def _next(self) -> int:
        if self._seq is None:
            async with self._ready:
                if self._seq is None:
                    found = await self._store.find(
                        TradeEvent, order_by="seq DESC", limit=1
                    )
                    self._seq = found[0].seq if found else 0
        self._seq += 1
        return self._seq

    async def emit(
        self,
        kind: str,
        text: str,
        *,
        seat: int = 0,
        round_id: str = "",
        symbol: str = "",
        stage: str = "",
        data: JsonObject | None = None,
    ) -> TradeEvent:
        event = TradeEvent(
            seq=await self._next(),
            round_id=round_id,
            kind=kind,
            seat=seat,
            symbol=symbol,
            stage=stage,
            text=" ".join(text.split())[:4000],
            data=data or {},
            created_at=now_ms(),
        )
        await self._store.put(event)
        if kind in AUDIT_KINDS:
            await self._store.put(
                TradeAudit(
                    kind=kind,
                    text=event.text,
                    symbol=symbol,
                    round_id=round_id,
                    order_id=str((data or {}).get("order_id") or ""),
                    config_version=self.config_version,
                    system_version=self._system,
                    data=data or {},
                    created_at=event.created_at,
                )
            )
        self._write_line(event)
        if kind in LOUD_KINDS:
            logger.info("Trading: {} {}", symbol or "", event.text[:300])
        self._written += 1
        if self._written % 500 == 0:
            await self._store.delete_before(TradeEvent, "seq", event.seq - KEEP_EVENTS)
        return event

    async def since(self, after: int, *, limit: int = 300) -> list[TradeEvent]:
        """Lines after number ``after`` (all recent ones for 0)."""
        if after <= 0:
            recent = await self._store.find(
                TradeEvent, order_by="seq DESC", limit=min(limit, 150)
            )
            return list(reversed(recent))
        return list(
            await self._store.find_after(
                TradeEvent, "seq", after, order_by="seq ASC", limit=limit
            )
        )

    async def for_round(self, round_id: str) -> list[TradeEvent]:
        return list(
            await self._store.find(
                TradeEvent, where={"round_id": round_id}, order_by="seq ASC"
            )
        )

    def _write_line(self, event: TradeEvent) -> None:
        when = datetime.fromtimestamp(event.created_at / 1000, tz=UTC)
        day = when.strftime("%Y-%m-%d")
        line = json.dumps(
            {
                "time": when.isoformat(timespec="seconds"),
                "seq": event.seq,
                "kind": event.kind,
                "seat": SEAT_NAMES.get(event.seat, str(event.seat)),
                "symbol": event.symbol,
                "stage": event.stage,
                "text": event.text,
            },
            ensure_ascii=False,
        )
        try:
            self._logs.mkdir(parents=True, exist_ok=True)
            with (self._logs / f"{day}.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            if day != self._pruned_day:
                self._pruned_day = day
                self._prune(when)
        except OSError as error:
            logger.info("Trading: couldn't write the desk log: {}", error)

    def _prune(self, now: datetime) -> None:
        oldest = (now - timedelta(days=KEEP_LOG_DAYS)).strftime("%Y-%m-%d")
        for path in self._logs.glob("*.jsonl"):
            if path.stem < oldest:
                path.unlink(missing_ok=True)


def event_view(event: TradeEvent) -> JsonObject:
    return {
        "seq": event.seq,
        "round_id": event.round_id,
        "kind": event.kind,
        "seat": event.seat,
        "seat_name": SEAT_NAMES.get(event.seat, ""),
        "symbol": event.symbol,
        "stage": event.stage,
        "text": event.text,
        "data": event.data,
        "at": event.created_at,
    }
