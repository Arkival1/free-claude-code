"""Decision records and the audit trail.

Every cycle (one candidate through the data checks, the debate, the risk
period, and any order) gets one decision record, written at the start and
brought up to date as things happen:
- timing: when the cycle started, when the evidence pack was made, when
  each seat answered, when the decision was final, when the order was
  decided; and the price at the analysis, at the final check, when the
  order was sent, and at the fill;
- what was known: the evidence pack's id, its data sources and times, its
  facts and calculations, and the conflicts found;
- what was said: each seat's outputs (with the model and prompt version)
  and the whole debate as it appeared in the feed;
- what was checked: every rule with what was measured and the limit, and
  the reasons anything was refused;
- what happened: the final decision, whether an order was sent, and the
  result (the profit or loss once the position is closed).
The configuration's version (a hash of the settings) and FCC's version are
kept with every record, so a decision can be traced to the rules it ran
under.

The audit trail keeps the lines that matter for oversight (decisions,
checks, orders, broker answers, fills, exits, errors, settings and mode
changes, the kill switch) for good: unlike the live feed it is never
pruned. Both can be searched and exported.
"""

import hashlib
import json
from collections.abc import Callable, Sequence
from importlib import metadata

from free_claude_code.core.json_types import JsonObject

from ..models import now_ms
from ..store import StudioStore
from .config import DeskConfig
from .records import TradeAudit, TradeDecision, TradeEvent, TradeRound

AUDIT_KINDS = frozenset(
    {
        "decision",
        "risk_gate",
        "risk_report",
        "engine",
        "check",
        "cooling",
        "order",
        "fill",
        "error",
        "data_quality",
        "evidence",
        "info_test",
        "guardian_review",
        "final_challenge",
        "kill",
        "mode",
        "settings",
        "stale",
        "breaker",
        "alert",
        "position",
        "dead_letter",
        "learning",
    }
)
"""Feed kinds that also go to the audit trail."""

ROUND_TO_DECISION = {
    "held": "no_trade",
    "blocked": "blocked",
    "failed": "failed",
    "advice": "advice",
    "aborted": "rejected",
    "discarded": "discarded",
    "pending": "approved",
    "alert": "alert",
}
"""A round's closing status as the decision's status (the order's own
progress is recorded as it happens)."""

PROGRESSED = frozenset(
    {
        "order_submitted",
        "partially_filled",
        "position_open",
        "exit_pending",
        "position_closed",
    }
)
"""Once an order is out, the order's own progress sets the status."""
MAX_TRANSCRIPT = 600
MAX_LINE = 1500
_VOLATILE = frozenset({"running", "accounts", "live_auto_confirmed_at"})


def config_version(config: DeskConfig) -> str:
    """A short hash of the settings that shape decisions (not whether the
    desk is running), so a record names the exact rules it ran under."""
    values = {
        key: value for key, value in config.model_dump().items() if key not in _VOLATILE
    }
    text = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def system_version() -> str:
    try:
        return metadata.version("free-claude-code")
    except metadata.PackageNotFoundError:
        return "unknown"


def decision_id(round_id: str) -> str:
    return f"dec_{round_id.removeprefix('trd_')}"


def _merge(base: JsonObject, changes: JsonObject) -> JsonObject:
    """Shallow merge, one level deeper for mappings (timing, prices)."""
    merged: JsonObject = dict(base)
    for key, value in changes.items():
        old = merged.get(key)
        if isinstance(old, dict) and isinstance(value, dict):
            merged[key] = {**old, **value}
        else:
            merged[key] = value
    return merged


def _words(*parts: object) -> str:
    return " ".join(" ".join(str(part).lower().split()) for part in parts if part)[
        :4000
    ]


class DecisionBook:
    def __init__(self, store: StudioStore, clock: Callable[[], float]) -> None:
        self._store = store
        self._clock = clock

    async def start(
        self,
        round_record: TradeRound,
        *,
        config: DeskConfig,
        tags: Sequence[str] = (),
        price: float | None = None,
    ) -> TradeDecision:
        record = TradeDecision(
            id=decision_id(round_record.id),
            round_id=round_record.id,
            symbol=round_record.symbol,
            market=round_record.market,
            mode=config.mode,
            status="analysis",
            config_version=config_version(config),
            system_version=system_version(),
            search=_words(round_record.symbol, "analysis", *tags),
            data={
                "cycle_id": round_record.id,
                "tags": list(tags),
                "timing": {"cycle_start": round_record.created_at / 1000},
                "prices": {"analysis": price},
            },
        )
        await self._store.put(record)
        return record

    async def get(self, round_id: str) -> TradeDecision | None:
        if not round_id:
            return None
        return await self._store.get(TradeDecision, decision_id(round_id))

    async def update(
        self,
        round_id: str,
        *,
        status: str | None = None,
        reason: str | None = None,
        data: JsonObject | None = None,
        **fields: object,
    ) -> TradeDecision | None:
        found = await self.get(round_id)
        if found is None:
            return None
        changes: dict[str, object] = dict(fields)
        if status is not None:
            changes["status"] = status
        if reason is not None:
            changes["reason"] = reason[:1000]
        merged = _merge(found.data, data or {})
        decision = merged.get("final_decision")
        action = decision.get("action") if isinstance(decision, dict) else ""
        tags = merged.get("tags")
        changes["data"] = merged
        changes["search"] = _words(
            found.symbol,
            changes.get("status", found.status),
            changes.get("reason", found.reason),
            action,
            found.round_id,
            changes.get("order_id", found.order_id),
            *(tags if isinstance(tags, list) else ()),
        )
        changes["updated_at"] = now_ms()
        updated = found.model_copy(update=changes)
        await self._store.put(updated)
        return updated

    async def closed(self, round_id: str, round_status: str, note: str) -> None:
        """A round closed: its decision takes the matching status."""
        status = ROUND_TO_DECISION.get(round_status)
        if status is None:
            return
        found = await self.get(round_id)
        if found is None:
            return
        if found.status in PROGRESSED:
            notes = found.data.get("later_notes")
            kept = list(notes) if isinstance(notes, list) else []
            await self.update(
                round_id, data={"later_notes": [*kept, f"{round_status}: {note}"][-20:]}
            )
            return
        await self.update(
            round_id,
            status=status,
            reason=note,
            data={"rejection_reasons": [note]}
            if status in {"blocked", "rejected", "discarded", "failed"}
            else {},
        )

    async def transcript(self, round_id: str, events: Sequence[TradeEvent]) -> None:
        """Keep the debate as the feed showed it, with the decision (the feed
        itself is pruned; this isn't)."""
        lines = [
            {
                "seq": event.seq,
                "kind": event.kind,
                "seat": event.seat,
                "stage": event.stage,
                "text": event.text[:MAX_LINE],
                "at": event.created_at,
            }
            for event in events[-MAX_TRANSCRIPT:]
        ]
        await self.update(round_id, data={"transcript": lines})

    async def audit(
        self,
        kind: str,
        text: str,
        *,
        symbol: str = "",
        round_id: str = "",
        order_id: str = "",
        config: DeskConfig | None = None,
        data: JsonObject | None = None,
    ) -> None:
        await self._store.put(
            TradeAudit(
                kind=kind,
                text=" ".join(text.split())[:4000],
                symbol=symbol,
                round_id=round_id,
                order_id=order_id,
                config_version=config_version(config) if config is not None else "",
                system_version=system_version(),
                data=data or {},
            )
        )

    async def search(
        self,
        *,
        symbol: str = "",
        status: str = "",
        text: str = "",
        since_ms: int | None = None,
        until_ms: int | None = None,
        limit: int = 100,
    ) -> tuple[TradeDecision, ...]:
        where: dict[str, object] = {}
        if symbol:
            where["symbol"] = symbol.upper()
        if status:
            where["status"] = status
        return await self._store.find_matching(
            TradeDecision,
            where=where,
            contains=("search", text) if text.strip() else None,
            since=("created_at", since_ms) if since_ms is not None else None,
            until=("created_at", until_ms) if until_ms is not None else None,
            limit=limit,
        )

    async def trail(
        self,
        *,
        kind: str = "",
        symbol: str = "",
        text: str = "",
        since_ms: int | None = None,
        until_ms: int | None = None,
        limit: int = 200,
    ) -> tuple[TradeAudit, ...]:
        where: dict[str, object] = {}
        if kind:
            where["kind"] = kind
        if symbol:
            where["symbol"] = symbol.upper()
        return await self._store.find_matching(
            TradeAudit,
            where=where,
            contains=("text", text) if text.strip() else None,
            since=("created_at", since_ms) if since_ms is not None else None,
            until=("created_at", until_ms) if until_ms is not None else None,
            limit=limit,
        )


def decision_view(record: TradeDecision) -> JsonObject:
    return {
        "id": record.id,
        "round_id": record.round_id,
        "symbol": record.symbol,
        "market": record.market,
        "mode": record.mode,
        "status": record.status,
        "reason": record.reason,
        "order_id": record.order_id,
        "pack_id": record.pack_id,
        "config_version": record.config_version,
        "system_version": record.system_version,
        "pnl": record.pnl,
        "order_submitted": record.order_submitted,
        "data": record.data,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def audit_view(record: TradeAudit) -> JsonObject:
    return {
        "id": record.id,
        "kind": record.kind,
        "text": record.text,
        "symbol": record.symbol,
        "round_id": record.round_id,
        "order_id": record.order_id,
        "config_version": record.config_version,
        "system_version": record.system_version,
        "data": record.data,
        "created_at": record.created_at,
    }
