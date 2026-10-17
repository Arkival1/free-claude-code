"""What the trading desk keeps in Studio's database."""

from typing import Literal

from pydantic import Field

from free_claude_code.core.json_types import JsonObject

from ..models import Record, new_id, now_ms

type TradeMode = Literal["paper", "alert_only", "live_approve", "live_auto"]
TRADE_MODES: tuple[str, ...] = ("paper", "alert_only", "live_approve", "live_auto")
"""paper: practice with fake money on real prices (the default);
alert_only: analyse and alert, never order; live_approve: real orders after
the owner's tap; live_auto: real orders on their own, inside every limit."""

type OrderStatus = Literal[
    "cooling",
    "awaiting_approval",
    "approved",
    "submitting",
    "submitted",
    "filled",
    "partially_filled",
    "cancelled",
    "denied",
    "expired",
    "aborted",
    "blocked",
    "rejected",
    "failed",
]
OPEN_ORDER_STATUSES = frozenset(
    {"cooling", "awaiting_approval", "approved", "submitting", "submitted"}
)
"""Orders that may still trade; a new one for the same symbol waits."""


class TradeRound(Record):
    """One candidate taken through briefing, debate, and the risk period."""

    id: str = Field(default_factory=lambda: new_id("trd"))
    symbol: str
    market: str = ""
    status: str = "running"
    """running, then traded, held, blocked, aborted, or failed."""
    depth: str = "balanced"
    consensus: float = 0.0
    """The track-record-weighted chance of a rise the seats ended on."""
    note: str = ""
    data: JsonObject = Field(default_factory=dict)
    """The briefing summary, the decision, and the risk assessment."""
    created_at: int = Field(default_factory=now_ms)
    updated_at: int = Field(default_factory=now_ms)


class TradeEvidence(Record):
    """The numbered evidence pack the seats saw for one round, exactly as
    they saw it (its text is hashed in ``digest``)."""

    id: str = Field(default_factory=lambda: new_id("evp"))
    round_id: str = ""
    symbol: str = ""
    cutoff_ms: int = 0
    """Nothing in the pack is from after this time (Unix ms)."""
    digest: str = ""
    text: str = ""
    data: JsonObject = Field(default_factory=dict)
    """Every item with its number, source, time, and status."""
    created_at: int = Field(default_factory=now_ms)


class TradeDecision(Record):
    """One cycle's complete decision record: when each step happened and at
    what price, what was known, what every seat said, what the checks
    found, and what came of it. Kept for good and searchable."""

    id: str = Field(default_factory=lambda: new_id("dec"))
    round_id: str = ""
    symbol: str = ""
    market: str = ""
    mode: str = "paper"
    status: str = "analysis"
    """analysis, advice, no_trade, blocked, discarded, failed, approved,
    rejected, order_submitted, partially_filled, position_open,
    exit_pending, or position_closed."""
    reason: str = ""
    order_id: str = ""
    pack_id: str = ""
    config_version: str = ""
    system_version: str = ""
    pnl: float | None = None
    order_submitted: bool = False
    search: str = ""
    """Lower-case words to search on: symbol, status, reasons, decision."""
    data: JsonObject = Field(default_factory=dict)
    created_at: int = Field(default_factory=now_ms)
    updated_at: int = Field(default_factory=now_ms)


class TradeAudit(Record):
    """One line of the audit trail: decisions, checks, orders, broker
    answers, fills, exits, errors, settings and mode changes, and the kill
    switch. Never pruned."""

    id: str = Field(default_factory=lambda: new_id("aud"))
    kind: str
    text: str
    symbol: str = ""
    round_id: str = ""
    order_id: str = ""
    config_version: str = ""
    system_version: str = ""
    data: JsonObject = Field(default_factory=dict)
    created_at: int = Field(default_factory=now_ms)


class TradeEvent(Record):
    """One line of the live feed: a seat speaking, a check, an order, a fill."""

    id: str = Field(default_factory=lambda: new_id("tev"))
    seq: int
    round_id: str = ""
    kind: str
    """briefing, opening, cross_exam, pre_mortem, rebuttal, guardian_reply,
    closing, decision, final_challenge, risk_report, risk_note, cooling,
    risk_gate, check, order, fill, debrief, lesson, scan, info, or error."""
    seat: int = 0
    """1-5 for a seat; 0 for the desk itself."""
    symbol: str = ""
    stage: str = ""
    """The debate stage it belongs to, e.g. 'Rebuttal 2/2'."""
    text: str = ""
    data: JsonObject = Field(default_factory=dict)
    created_at: int = Field(default_factory=now_ms)


class TradeOrder(Record):
    """An order from the moment the desk decides to trade until it ends."""

    id: str = Field(default_factory=lambda: new_id("tor"))
    client_id: str
    """Sent to the platform, so a retry can never place it twice."""
    round_id: str = ""
    broker: str = "paper"
    mode: str = "paper"
    symbol: str
    market: str = ""
    side: Literal["buy", "sell"] = "buy"
    qty: float
    order_type: Literal["market", "limit"] = "market"
    limit_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    entry_price: float = 0.0
    """The price the decision was made at, in the symbol's own currency."""
    currency: str = "USD"
    status: str = "cooling"
    broker_order_id: str = ""
    filled_qty: float = 0.0
    fill_price: float | None = None
    fees: float = 0.0
    fx_rate: float = 1.0
    """Base currency per unit of the symbol's currency at the fill."""
    reason: str = ""
    data: JsonObject = Field(default_factory=dict)
    """The decision, the risk assessment, and the account check."""
    due_at: int = 0
    """When the cooling-off wait ends, or the approval expires."""
    created_at: int = Field(default_factory=now_ms)
    updated_at: int = Field(default_factory=now_ms)


class TradeFill(Record):
    """One fill as it happened: the new quantity since the last update (not
    the running total), its price, and its fees. Positions change by these
    amounts only, so a partly filled order is never counted twice."""

    id: str = Field(default_factory=lambda: new_id("tfl"))
    order_id: str
    round_id: str = ""
    broker: str = ""
    symbol: str = ""
    side: str = "buy"
    qty: float
    price: float | None = None
    """In the symbol's own currency."""
    fees: float = 0.0
    """In the base currency; unknown when the platform doesn't say."""
    fees_known: bool = True
    currency: str = ""
    created_at: int = Field(default_factory=now_ms)


class TradePosition(Record):
    """What is held: the paper account's own, or a live platform's, cached."""

    id: str
    """``broker:symbol``."""
    broker: str
    symbol: str
    market: str = ""
    qty: float
    avg_price: float
    """In the symbol's own currency."""
    currency: str = "USD"
    cost_base: float = 0.0
    """What was paid, fees included, in the base currency."""
    stop_loss: float | None = None
    take_profit: float | None = None
    round_id: str = ""
    data: JsonObject = Field(default_factory=dict)
    opened_at: int = Field(default_factory=now_ms)
    created_at: int = Field(default_factory=now_ms)
    updated_at: int = Field(default_factory=now_ms)


class TradeForecast(Record):
    """One seat's measurable call, scored when it comes due."""

    id: str = Field(default_factory=lambda: new_id("tfc"))
    round_id: str = ""
    seat: int
    stage: str = "closing"
    """opening, closing, or decision."""
    symbol: str
    market: str = ""
    regime: str = ""
    setup: str = ""
    horizon_days: int = 5
    p_up: float = 0.5
    expected_move: float = 0.0
    """Percent."""
    p_target: float | None = None
    target: float | None = None
    stop: float | None = None
    entry_price: float = 0.0
    confidence: float = 0.5
    traded: bool = False
    due_at: int = 0
    status: str = "open"
    """open, scored, or void (no price to score against)."""
    outcome_move: float | None = None
    hit: bool | None = None
    brier: float | None = None
    log_score: float | None = None
    target_first: bool | None = None
    created_at: int = Field(default_factory=now_ms)
    scored_at: int | None = None


class TradeDebrief(Record):
    """A look back: after a trade, after forecasts resolve, a session, a week."""

    id: str = Field(default_factory=lambda: new_id("tdb"))
    kind: Literal["trade", "forecast", "session", "weekly"]
    round_id: str = ""
    symbol: str = ""
    market: str = ""
    title: str
    summary: str = ""
    lesson: str = ""
    data: JsonObject = Field(default_factory=dict)
    """Each seat's notes, the numbers, and any suggestions."""
    created_at: int = Field(default_factory=now_ms)
