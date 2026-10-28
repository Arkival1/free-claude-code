"""The Trading Bank as FCC Phone sees it, through the PC link.

The phone gets a read of the desk (mode, account totals, positions, the
orders waiting, the feed) and only the actions that keep money safe or stay
in practice: start practice, stop, the kill switch, deny any waiting order,
and approve a practice order. Live trading, keys, accounts and settings stay
on the PC, as on the Trading page.
"""

from free_claude_code.core.json_types import JsonObject, JsonValue

from .resilience import ServiceError
from .trading.data import MarketDataError
from .trading.desk import TradingDesk, TradingError

FEED_LINES = 40
"""How many of the newest feed lines one read sends the phone."""
ORDER_FIELDS = (
    "id",
    "symbol",
    "side",
    "qty",
    "status",
    "mode",
    "broker",
    "limit_price",
    "reason",
    "seconds_left",
    "created_at",
)
ACCOUNT_FIELDS = (
    "currency",
    "equity",
    "cash",
    "buying_power",
    "equity_base",
    "day_change_pct",
    "trades_today",
    "invested",
    "live",
    "error",
)
"""Totals only: no account number, fingerprint or permissions leave the PC."""


def _pick(view: JsonObject, fields: tuple[str, ...]) -> JsonObject:
    return {key: view[key] for key in fields if key in view}


async def desk_card(desk: TradingDesk, after: int = 0) -> JsonObject:
    """One read of the desk for the phone's Trading card."""
    status = await desk.status()
    account = status.get("account")
    positions: list[JsonValue] = []
    problem = ""
    try:
        positions = list(await desk.positions())
    except (TradingError, ServiceError, MarketDataError) as error:
        problem = str(error)
    events = (await desk.events(after))[-FEED_LINES:]
    orders = status.get("orders")
    return {
        "running": status.get("running"),
        "live": status.get("live"),
        "mode": status.get("mode"),
        "mode_label": status.get("mode_label"),
        "broker_name": status.get("broker_name"),
        "currency": status.get("currency"),
        "busy": status.get("busy"),
        "activity": status.get("activity"),
        "kill": status.get("kill"),
        "breaker": status.get("breaker"),
        "account": _pick(account, ACCOUNT_FIELDS) if isinstance(account, dict) else {},
        "positions": positions,
        "positions_problem": problem,
        "orders": [
            _pick(order, ORDER_FIELDS) for order in orders if isinstance(order, dict)
        ]
        if isinstance(orders, list)
        else [],
        "summary": await desk.summary(),
        "events": events,
        "last": events[-1]["seq"] if events else after,
    }


async def start_practice(desk: TradingDesk) -> JsonObject:
    """Start the desk from the phone: practice only (live starts on the PC)."""
    return await desk.start(on_pc=False)


async def approve_practice(desk: TradingDesk, order_id: str) -> JsonObject:
    """Approve a waiting order from the phone, if it is a practice order.
    A real-money order is approved on the PC; the phone can still deny it."""
    order = await desk.order(order_id)
    if order is None:
        raise TradingError("That order is gone.")
    if order.mode != "paper":
        raise TradingError(
            "Real-money orders are approved on the PC. You can deny it from here."
        )
    return await desk.approve(order_id)


async def kill(desk: TradingDesk, *, flatten: bool, confirm: str) -> JsonObject:
    """The emergency stop from the phone (closing everything needs the
    same typed phrase as on the PC)."""
    return await desk.kill(flatten=flatten, confirm=confirm, reason="From FCC Phone")
