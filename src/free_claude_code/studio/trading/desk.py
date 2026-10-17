"""The trading desk: the loop that scans, debates, assesses, and trades.

Every ten seconds the desk ticks: it finishes cooling-off waits, expires
approvals nobody answered, watches stops and targets, picks up fills, scores
forecasts that came due, and schedules debriefs. Every scan interval (15
minutes by default) it starts one round in the background: scan the markets,
then take the best few setups through the briefing, the debate, and the risk
assessment period. Rounds never overlap, and while one runs the ticks carry
on. Nothing the desk does can stop the loop: every failure is logged to the
feed and the next tick tries again. With no internet it waits.

Modes:
- paper: orders fill on the paper account, on real prices.
- live_approve: orders go to the connected platform after the owner taps
  Approve (on the PC or the phone); the account is checked again then.
- live_auto: orders go straight to the platform, still inside every hard
  limit, once the owner has typed the confirmation phrase on the PC.
After FCC restarts, only paper trading resumes by itself.
"""

import asyncio
import contextlib
import csv
import io
import json
import os
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from loguru import logger

from free_claude_code.core.json_types import JsonObject

from ..connectors import ConnectorStore
from ..memory import MemoryService
from ..models import now_ms
from ..resilience import ServiceError, Unconfirmed, Web, submit_once
from ..search import StudioSearch
from ..store import StudioStore
from ..workers import WorkerPool
from .assessment import (
    Holdings,
    RiskAssessment,
    recheck,
    resize,
    risk_report,
    risk_round,
    shrink,
)
from .breaks import Budget, Findings
from .briefing import Briefing, build_briefing
from .brokers.base import Broker, Holding, OrderRequest, OrderResult, Rules, Sent
from .brokers.catalog import ensure_catalog
from .brokers.paper import PaperBroker
from .brokers.registry import BROKERS, BrokerSetupError, check_values, make_broker
from .config import LIVE_AUTO_PHRASE, DeskConfig, DeskConfigStore
from .conflicts import applied, data_conflicts, seat_conflicts
from .contract import PROMPT_VERSION, PMDecision
from .data import (
    DATA_LIMITS,
    MarketData,
    MarketDataError,
    Quote,
    quote_snapshot,
    sizing_snapshot,
)
from .debate import Debate, DebateResult, DebateTools
from .debrief import SUGGESTIBLE, Debriefs
from .decisions import DecisionBook, audit_view, config_version, decision_view
from .engine import BuyFacts, buy_rules
from .engine import blockers as rule_blockers
from .evidence import (
    EvidencePack,
    PortfolioFacts,
    build_pack,
    price_fact,
    reading_item,
)
from .forecasts import due_at, records, score
from .indicators import Bar, true_ranges
from .information import PROVIDER_DELAY_MINUTES, InfoItem, NewsItem, QuoteSnapshot
from .instruments import Instrument, SymbolError, parse_symbol, universe
from .ledger import build_ledger, tax_csv
from .log import Feed, event_view
from .news import judge
from .positions import Plan, manage
from .precheck import pre_trade_check
from .protection import FLATTEN_PHRASE, Health, Trip, may_clear, trip
from .protection import check as breaker_check
from .providers.news import NewsFeeds
from .quality import (
    QualityCheck,
    QualityReport,
    assess,
    bid_ask_source,
    daily_turnover,
    failed_report,
    freshest,
    profile_of,
)
from .records import (
    OPEN_ORDER_STATUSES,
    TradeDebrief,
    TradeDecision,
    TradeFill,
    TradeForecast,
    TradeOrder,
    TradePosition,
    TradeRound,
)
from .regime import policy_for
from .research import DeskResearch, ReadPage
from .risk import Exposure, risk_gate, size_position
from .scanner import Candidate, scan
from .scorecard import TradeFacts, score_trade
from .seats import Decision, Forecast, Think
from .sessions import last_close, session, sydney_offset
from .stress import Holding as HeldPosition
from .stress import StressInput, StressReport, stress_test
from .worker import JOB_TRIES, Job, Lease, Steps, metrics

TICK_SECONDS = 10.0
ASKED = "asked by you"
"""The tag on a debate the owner asked for."""
FRESH = "fresh analysis after a stale decision"
RECHECK_SECONDS = 2 * 3600.0
"""A symbol is analysed again after a stale decision at most this often."""
PROTECT_SECONDS = 60.0
"""How often the circuit breaker looks at the desk's health."""
SCORE_SECONDS = 300.0
ACCOUNT_SECONDS = 30.0
DEBRIEF_LATE_HOURS = 12.0
"""A session debrief more than this late (Studio was closed) is skipped."""
ROUND_SECONDS = 45 * 60.0
"""A round still going after this long is stopped (two debate rounds)."""
EXTRA_DEBATE_ROUND_SECONDS = 15 * 60.0
"""More time for each debate round past two, for each debate in the round."""
PAGE_EXCERPT = 600
"""Characters kept from a page read between debate rounds."""
MEMORY_AREA = "trading:desk"
EXIT_RETRY_SECONDS = 600.0
"""A stop or target exit the checks blocked is tried again after this."""
PROBLEM_REPEAT_SECONDS = 600.0
"""The same problem goes to the feed at most this often."""
RECONCILE_SECONDS = 300.0
STALL_SECONDS = 120.0
"""A loop that hasn't finished a pass for this long shows as stalled."""
"""How often orders not yet matched with their account are asked about."""
DAY_MS = 86_400_000


class TradingError(ValueError):
    """Something asked of the desk can't be done; the message says why."""


@dataclass(frozen=True, slots=True)
class Tightening:
    """What the decision engine leaves of a buy: never more than before."""

    size_factor: float
    why: str
    max_qty: float | None
    """The largest size the investment stress test allows (None: not run)."""
    confidence: float


class TradingDesk:
    def __init__(
        self,
        *,
        store: StudioStore,
        root: Path,
        think: Think,
        search: Callable[[], StudioSearch | None],
        memory: Callable[[], MemoryService],
        keys: ConnectorStore,
        workers: WorkerPool,
        online: Callable[[], Awaitable[bool]],
        read_page: ReadPage | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._store = store
        self._root = root
        self._think = think
        self._memory = memory
        self._keys = keys
        self._workers = workers
        self._online = online
        self._transport = transport
        self._clock = clock
        self._sleep = sleep
        ensure_catalog()
        self._configs = DeskConfigStore(root / "desk.json")
        self._web = Web(
            transport=transport,
            limits=DATA_LIMITS,
            user_agent="FCC-Studio trading desk",
        )
        self._data = MarketData(
            self._web,
            coingecko_key=lambda: self._keys.values("coingecko").get("api_key", ""),
            wall=clock,
        )
        self.feed = Feed(store, root / "logs")
        self._decisions = DecisionBook(store, clock)
        self._rechecks: list[str] = []
        """Symbols whose decision went stale: analysed again from scratch."""
        self._rechecked: dict[str, float] = {}
        self._last_protect = 0.0
        self._unmatched: dict[str, str] = {}
        """Orders FCC couldn't match with their account (by order id), and
        why; they pause new trades until a later check matches them."""
        self._sending: set[str] = set()
        """Client ids of orders being sent right now (not for the re-check)."""
        self._last_reconcile = 0.0
        self._research = DeskResearch(search=search, read_page=read_page)
        self._news = NewsFeeds(self._web, wall=clock)
        self._debriefs = Debriefs(
            store=store, feed=self.feed, think=think, remember=self._remember
        )
        self._loop_task: asyncio.Task[None] | None = None
        self._round_task: asyncio.Task[None] | None = None
        self._requests: list[str] = []
        self._chores: list[Callable[[], Awaitable[object]] | Job] = []
        self._retries: list[Job] = []
        """Background jobs that failed, waiting for their next try."""
        self._dead: list[JsonObject] = []
        """Jobs that failed every try (also in the audit trail)."""
        self._lease = Lease(root / "desk.lease", uuid.uuid4().hex, clock)
        self._lease_note = ""
        """Why this FCC isn't running the loop (another one holds it)."""
        self._steps = Steps()
        self._heartbeat = 0.0
        self._activity: JsonObject = {}
        self._last_scan = 0.0
        self._last_score = 0.0
        self._offline = False
        self._account_cache: tuple[float, str, JsonObject] | None = None
        self._live: dict[str, tuple[str, Broker]] = {}
        self._exit_tried: dict[str, float] = {}
        self._problems: dict[str, float] = {}

    # ------------------------------------------------------------ setup

    @property
    def data(self) -> MarketData:
        return self._data

    def config(self) -> DeskConfig:
        return self._configs.load()

    def _save(self, config: DeskConfig) -> None:
        self._configs.save(config)
        self.feed.config_version = config_version(config)

    def _state(self) -> dict[str, object]:
        try:
            found = json.loads((self._root / "state.json").read_text(encoding="utf-8"))
        except FileNotFoundError, ValueError:
            return {}
        return found if isinstance(found, dict) else {}

    def _save_state(self, state: Mapping[str, object]) -> None:
        path = self._root / "state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, indent=1), encoding="utf-8")
        os.replace(temporary, path)

    async def update_config(
        self, values: Mapping[str, object], *, on_pc: bool, confirm: str = ""
    ) -> DeskConfig:
        """Change settings; going live has extra conditions (see ``_check_mode``)."""
        current = self.config()
        merged = _merge(current.model_dump(), dict(values))
        merged["accounts"] = current.accounts
        merged["running"] = current.running
        merged["live_auto_confirmed_at"] = current.live_auto_confirmed_at
        try:
            wanted = DeskConfig.model_validate(merged)
        except ValueError as error:
            raise TradingError(f"Those settings aren't valid: {error}") from error
        if (
            wanted.mode != current.mode
            or wanted.broker != current.broker
            or wanted.routes != current.routes
        ):
            wanted = self._check_mode(current, wanted, on_pc=on_pc, confirm=confirm)
        self._save(wanted)
        changed = sorted(key for key in values if key not in {"accounts", "running"})
        version = config_version(wanted)
        await self.feed.emit(
            "settings",
            f"Settings changed: {', '.join(changed) or 'none'} (settings version "
            f"{version}).",
            data={"changed": list(changed), "config_version": version},
        )
        if wanted.mode != current.mode or wanted.broker != current.broker:
            await self.feed.emit(
                "mode",
                f"Mode changed from {current.mode} on {current.broker} to "
                f"{wanted.mode} on {wanted.broker}"
                + (" from the PC" if on_pc else "")
                + f" (settings version {version}).",
                data={
                    "from": {"mode": current.mode, "broker": current.broker},
                    "to": {"mode": wanted.mode, "broker": wanted.broker},
                    "config_version": version,
                    "on_pc": on_pc,
                },
            )
        return wanted

    def _check_mode(
        self, current: DeskConfig, wanted: DeskConfig, *, on_pc: bool, confirm: str
    ) -> DeskConfig:
        if not wanted.live:
            # Practice and alert-only never touch real money.
            return wanted.model_copy(update={"live_auto_confirmed_at": 0})
        if not on_pc:
            raise TradingError("Live trading can only be switched on from the PC.")
        for routed in wanted.routes.values():
            if routed in {"", "paper"}:
                continue
            spec = BROKERS.get(routed)
            if spec is None or spec.factory is None:
                raise TradingError(f"FCC can't trade on {routed!r} yet.")
            if not self._keys.values(routed):
                raise TradingError(f"Add your {spec.name} keys first.")
            if not current.accounts.get(routed):
                raise TradingError(
                    f"Verify your {spec.name} account first (Test, then Verify)."
                )
        if wanted.broker == "paper":
            raise TradingError(
                "Pick a live platform first; the paper account is practice only."
            )
        spec = BROKERS.get(wanted.broker)
        if spec is None or spec.factory is None:
            raise TradingError(f"FCC can't trade on {wanted.broker!r} yet.")
        if not self._keys.values(wanted.broker):
            raise TradingError(f"Add your {spec.name} keys first.")
        if not current.accounts.get(wanted.broker):
            raise TradingError(
                f"Verify your {spec.name} account first (Test, then Verify), so the desk "
                "can check it's the same account before every order."
            )
        if wanted.mode == "live_auto":
            if confirm.strip() != LIVE_AUTO_PHRASE:
                raise TradingError(
                    f'To let real-money orders go without a tap, type "{LIVE_AUTO_PHRASE}".'
                )
            return wanted.model_copy(update={"live_auto_confirmed_at": now_ms()})
        return wanted.model_copy(update={"live_auto_confirmed_at": 0})

    async def reset_paper(self, cash: float | None = None) -> JsonObject:
        """Start the practice account again."""
        config = self.config()
        if cash is not None:
            config = config.model_copy(
                update={"paper_cash": max(100.0, min(10_000_000.0, cash))}
            )
            self._save(config)
        paper = self._paper(config)
        paper.reset(config.paper_cash)
        await paper.clear_positions()
        await self.feed.emit(
            "info",
            f"Paper account reset to {config.paper_cash:,.2f} {config.currency}.",
        )
        return await self.status()

    # ------------------------------------------------------------ lifecycle

    async def start(self, *, on_pc: bool = True) -> JsonObject:
        config = self.config()
        if config.live and not on_pc:
            raise TradingError("Live trading can only be started from the PC.")
        killed = self._state().get("kill")
        if isinstance(killed, dict):
            raise TradingError(
                "The kill switch is on. Release it on the PC first, then Start."
            )
        self._save(config.model_copy(update={"running": True}))
        self._ensure_loop()
        await self.feed.emit(
            "info",
            f"Desk started in {_mode_label(config)} mode on {_broker_name(config)}.",
        )
        return await self.status()

    async def stop(self) -> JsonObject:
        """Nothing new is traded; open positions keep their stops and
        targets watched, and orders already sent are still followed."""
        config = self.config()
        self._save(config.model_copy(update={"running": False}))
        if self._round_task is not None and not self._round_task.done():
            self._round_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._round_task
        self._round_task = None
        self._activity = {}
        cancelled = 0
        for order in await self._store.find(TradeOrder, where={"status": "cooling"}):
            await self._set(order, status="cancelled", reason="The desk was stopped.")
            await self._round_status(order.round_id, "aborted", "The desk was stopped.")
            cancelled += 1
        self._ensure_loop()
        await self.feed.emit(
            "info",
            "Desk stopped. Nothing new will be traded; open positions are still "
            "watched"
            + (
                f"; {cancelled} order(s) in cooling-off cancelled."
                if cancelled
                else "."
            ),
        )
        return await self.status()

    async def kill(
        self, *, flatten: bool = False, confirm: str = "", reason: str = ""
    ) -> JsonObject:
        """The emergency stop, on every connected account: nothing new is
        traded, every waiting order is cancelled, and the switch latches
        until the owner releases it. Closing every position as well needs
        the typed phrase (the second confirmation)."""
        if flatten and confirm.strip() != FLATTEN_PHRASE:
            raise TradingError(
                f'To close every position as well, type "{FLATTEN_PHRASE}".'
            )
        state = self._state()
        state["kill"] = {
            "at": self._clock(),
            "reason": reason or "the kill switch was pressed",
            "flatten": flatten,
        }
        self._save_state(state)
        await self.stop()
        config = self.config()
        cancelled = 0
        for order in await self._store.find(TradeOrder):
            if order.status in {"cooling", "awaiting_approval", "approved"}:
                await self._set(order, status="cancelled", reason="Kill switch.")
                cancelled += 1
        accounts: list[str] = []
        problems: list[str] = []
        kept = 0
        for broker in self._brokers_with_keys(config):
            accounts.append(broker.name)
            bracketed = {
                position.symbol
                for position in await self._store.find(
                    TradePosition, where={"broker": broker.id}
                )
                if position.data.get("bracket")
            }
            try:
                for result in await broker.open_orders():
                    if result.symbol in bracketed and result.raw.get("side") == "sell":
                        # A held position's own stop and target on the
                        # platform protect it: they stay (closing everything
                        # cancels them only as each holding is sold).
                        kept += 1
                        continue
                    try:
                        await broker.cancel(result.broker_order_id)
                        cancelled += 1
                    except ServiceError as error:
                        problems.append(f"{broker.name}: {error}")
            except ServiceError as error:
                problems.append(f"{broker.name}: couldn't list open orders ({error})")
        sold = 0
        if flatten:
            for broker in self._brokers_with_keys(config):
                for holding in await self._holdings(broker):
                    position = await self._position_record(broker, holding)
                    await self._exit(position, "the kill switch", config, force=True)
                    sold += 1
        state = self._state()
        latch = state.get("kill")
        if isinstance(latch, dict):
            latch.update({"cancelled": cancelled, "sold": sold, "accounts": accounts})
            state["kill"] = latch
            self._save_state(state)
        await self.feed.emit(
            "kill",
            f"Kill switch on {len(accounts)} account(s): {cancelled} orders cancelled"
            + (f", {sold} holdings sold" if flatten else "")
            + (
                f", {kept} platform stop and target orders kept on what is held"
                if kept
                else ""
            )
            + ". It stays on until you release it on the PC."
            + (f" Problems: {'; '.join(problems)}." if problems else ""),
            data={
                "cancelled": cancelled,
                "sold": sold,
                "flatten": flatten,
                "accounts": accounts,
                "problems": problems,
                "reason": reason,
            },
        )
        return await self.status()

    async def release_kill(self, *, on_pc: bool) -> JsonObject:
        """Lift the kill switch's latch (the desk still needs Start)."""
        if not on_pc:
            raise TradingError("The kill switch can only be released from the PC.")
        state = self._state()
        if state.pop("kill", None) is None:
            raise TradingError("The kill switch isn't on.")
        self._save_state(state)
        await self.feed.emit(
            "kill", "Kill switch released. Press Start when you want to trade again."
        )
        return await self.status()

    async def reset_breaker(self, *, on_pc: bool) -> JsonObject:
        """Clear the circuit breaker by hand (the owner's call, on the PC).
        Orders FCC couldn't match with their account are the owner's to
        check: the reset marks them unconfirmed (no longer open) and says
        so, rather than guessing whether they went through."""
        if not on_pc:
            raise TradingError("The circuit breaker can only be reset from the PC.")
        state = self._state()
        if state.pop("breaker", None) is None:
            raise TradingError("The circuit breaker isn't on.")
        state["breaker_since"] = self._clock()
        self._save_state(state)
        closed: list[str] = []
        for order_id, label in self._unmatched.items():
            order = await self._store.get(TradeOrder, order_id)
            if order is None or order.status != "submitting":
                continue
            why = (
                "Couldn't be matched with the account; marked unconfirmed when "
                "you reset the circuit breaker on the PC."
            )
            await self._set(order, status="unconfirmed", reason=why)
            await self._decisions.update(order.round_id, reason=why)
            closed.append(label.split(":", 1)[0])
        self._unmatched = {}
        await self.feed.emit(
            "breaker",
            "Circuit breaker reset by you on the PC."
            + (
                f" Marked unconfirmed (check the account for them): {'; '.join(closed)}."
                if closed
                else ""
            ),
        )
        return await self.status()

    async def resume(self) -> None:
        """At start-up: match FCC's records with every account first, keep
        watching what is held, carry on paper trading, and never resume
        live by itself."""
        config = self.config()
        await self._reconcile()
        self._ensure_loop()
        if not config.running:
            return
        if config.live:
            self._save(config.model_copy(update={"running": False}))
            await self.feed.emit(
                "info",
                "Live trading was paused when FCC restarted (positions are still "
                "watched). Press Start to carry on.",
            )
            return
        await self.feed.emit("info", "Paper trading resumed after a restart.")

    async def close(self) -> None:
        await self._cancel_tasks()
        self._lease.release()
        for _, broker in self._live.values():
            with contextlib.suppress(Exception):
                await broker.aclose()
        self._live.clear()
        await self._web.aclose()

    def _ensure_loop(self) -> None:
        if self._loop_task is None or self._loop_task.done():
            self._loop_task = asyncio.ensure_future(self._loop())

    async def _cancel_tasks(self) -> None:
        for task in (self._round_task, self._loop_task):
            if task is not None and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        self._round_task = None
        self._loop_task = None
        self._activity = {}

    async def _reconcile(self) -> None:
        """Orders nobody can vouch for (cut off mid-send when FCC closed, or
        whose answer was lost): ask each platform what happened to them. One
        that can't be matched stays open, so it is never sent twice, and
        pauses new trades (the circuit breaker) until a later check matches
        it, or the owner checks the account and resets the breaker."""
        config = self.config()
        self._last_reconcile = self._clock()
        unmatched: dict[str, str] = {}
        for order in await self._store.find(TradeOrder, where={"status": "submitting"}):
            if order.client_id in self._sending:
                continue
            label = f"{order.side} {order.qty:g} {order.symbol} on {order.broker}"
            remember = None
            try:
                broker = self._broker_for(order, config)
                # A platform without FCC's own order ids is told what was
                # sent (it forgets when FCC restarts) so it can look.
                remember = getattr(broker, "remember", None)
                if remember is not None:
                    remember(_sent(order))
                found = await broker.find(order.client_id)
            except (ServiceError, TradingError) as error:
                unmatched[order.id] = f"{label}: {error}"
                if order.id not in self._unmatched:
                    await self.feed.emit(
                        "error",
                        f"Couldn't match the {order.symbol} order with the "
                        f"account: {error} It stays open and isn't sent again; "
                        "new trades pause until it's matched.",
                        round_id=order.round_id,
                        symbol=order.symbol,
                    )
                continue
            if found is not None:
                await self._record(order, found, config)
            elif remember is None:
                # The platform looks orders up by FCC's own id: it has none.
                await self._set(
                    order, status="failed", reason="Never reached the platform."
                )
            else:
                unmatched[order.id] = f"{label}: no matching order found"
        if set(unmatched) - set(self._unmatched):
            self._last_protect = 0.0
        self._unmatched = unmatched

    async def _reconcile_due(self, config: DeskConfig) -> None:
        """Every few minutes, ask again about orders not yet matched."""
        if self._clock() - self._last_reconcile >= RECONCILE_SECONDS:
            await self._reconcile()

    def _unmatched_text(self) -> str:
        if not self._unmatched:
            return ""
        shown = list(self._unmatched.values())
        more = f" (and {len(shown) - 3} more)" if len(shown) > 3 else ""
        return (
            "FCC couldn't match its orders with the account: "
            + "; ".join(shown[:3])
            + more
        )

    # ------------------------------------------------------------ the loop

    async def _loop(self) -> None:
        while True:
            try:
                # Only the FCC holding the lease runs the desk, so two copies
                # open on the same data never place the same order twice.
                held = self._lease.take()
                self._lease_note = held
                if held:
                    await self._problem(
                        "Another FCC is running this trading desk; this one "
                        "waits, so nothing is done twice."
                    )
                else:
                    await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.opt(exception=True).debug("Trading desk tick failed")
                with contextlib.suppress(Exception):
                    await self._problem(f"Desk problem (it carries on): {error}")
            await self._sleep(TICK_SECONDS)

    async def tick(self) -> None:
        """One pass of everything time-driven (the loop calls this)."""
        config = self.config()
        if not await self._online():
            if not self._offline:
                self._offline = True
                await self.feed.emit(
                    "info", "No internet: the desk is waiting for it to come back."
                )
            return
        if self._offline:
            self._offline = False
            await self.feed.emit("info", "Internet is back; the desk carries on.")
        for step in (
            self._reconcile_due,
            self._sync_orders,
            self._watch_positions,
            self._protect,
            self._finish_cooling,
            self._expire_approvals,
            self._score_forecasts,
            self._schedule_debriefs,
        ):
            name = step.__name__.strip("_").replace("_", " ")
            started = time.perf_counter()
            failed = ""
            try:
                await step(config)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.opt(exception=True).debug("Trading desk step failed")
                failed = str(error) or type(error).__name__
                await self._problem(f"{name}: {error}")
            self._steps.record(
                name, time.perf_counter() - started, error=failed, at=self._clock()
            )
        now = self._clock()
        ready = [job for job in self._retries if job.due <= now]
        if ready:
            self._retries = [job for job in self._retries if job.due > now]
            self._chores.extend(ready)
        self._heartbeat = now
        due = now - self._last_scan >= config.scan_minutes * 60
        free = self._round_task is None or self._round_task.done()
        entering = config.running and not self._entry_block(config)
        waiting = self._requests or self._chores or (entering and self._rechecks)
        if free and (waiting or (entering and due)):
            if due and entering:
                self._last_scan = now
            self._round_task = asyncio.ensure_future(self._round())

    async def _round(self) -> None:
        """One round: chores first (debriefs), then requests, then a scan."""
        start = self.config()
        debates = 1 if self._requests else start.candidates
        try:
            async with asyncio.timeout(round_seconds(start, debates)):
                while self._chores:
                    chore = self._chores.pop(0)
                    job = chore if isinstance(chore, Job) else Job(chore)
                    try:
                        await job.run()
                    except asyncio.CancelledError:
                        raise
                    except Exception as error:
                        logger.exception("Trading debrief failed")
                        await self._job_failed(job, str(error) or type(error).__name__)
                config = self.config()
                if self._requests:
                    symbol = self._requests.pop(0)
                    await self._debate_symbol(symbol, config)
                elif self._entry_block(config) or not config.running:
                    pass
                elif self._rechecks:
                    symbol = self._rechecks.pop(0)
                    await self._debate_symbol(symbol, config, tags=(FRESH,))
                else:
                    await self._scan_and_debate(config)
        except TimeoutError:
            await self.feed.emit("error", "A round ran too long and was stopped.")
        finally:
            self._activity = {}

    async def _job_failed(self, job: Job, error: str) -> None:
        """Try a failed job again later, or set it aside after its last try."""
        if job.failed(error, self._clock()):
            self._retries.append(job)
            await self.feed.emit(
                "error",
                f"A {job.name} failed (try {job.tries} of {JOB_TRIES}): {error}. "
                f"Trying again in {(job.due - self._clock()) / 60:.0f} min.",
            )
            return
        entry: JsonObject = {
            "name": job.name,
            "tries": job.tries,
            "errors": list(job.errors),
            "at": self._clock(),
        }
        self._dead = [*self._dead, entry][-50:]
        await self.feed.emit(
            "error",
            f"A {job.name} failed {job.tries} times and was set aside: {error}.",
        )
        await self._decisions.audit(
            "dead_letter",
            f"A {job.name} failed {job.tries} times and was set aside.",
            data=entry,
        )

    async def health(self) -> JsonObject:
        """How the desk itself is running: the loop, each step, background
        jobs, data sources, and measures from its own records."""
        now = self._clock()
        rounds = await self._store.find(
            TradeRound, order_by="created_at DESC", limit=200
        )
        orders = await self._store.find(
            TradeOrder, order_by="created_at DESC", limit=500
        )
        decisions = await self._store.find(
            TradeDecision, order_by="created_at DESC", limit=200
        )
        return {
            "looping": self._loop_task is not None and not self._loop_task.done(),
            "heartbeat_age_s": round(now - self._heartbeat, 1)
            if self._heartbeat
            else None,
            "stalled": bool(self._heartbeat) and now - self._heartbeat > STALL_SECONDS,
            "lease": self._lease_note,
            "steps": self._steps.view(),
            "jobs_waiting": len(self._chores),
            "retries": [
                {"name": job.name, "tries": job.tries, "due": job.due}
                for job in self._retries
            ],
            "dead_letters": list(self._dead[-20:]),
            "unmatched": list(self._unmatched.values()),
            "data_sources": dict(self._data.health()),
            "metrics": metrics(rounds, orders, decisions),
        }

    async def debate(self, symbol: str) -> JsonObject:
        """Ask the desk about one symbol now (in the background)."""
        try:
            instrument = parse_symbol(symbol)
        except SymbolError as error:
            raise TradingError(str(error)) from error
        if instrument.symbol not in self._requests:
            self._requests.append(instrument.symbol)
        await self.feed.emit(
            "info",
            f"Asked to debate {instrument.symbol}; it starts as soon as the desk is free.",
        )
        if self._round_task is None or self._round_task.done():
            self._round_task = asyncio.ensure_future(self._round())
        return {"queued": instrument.symbol, "waiting": len(self._requests)}

    # ------------------------------------------------------------ rounds

    def _is_open(self, market: str) -> bool:
        return session(market, datetime.fromtimestamp(self._clock(), tz=UTC)).open

    def _markets(self, config: DeskConfig) -> frozenset[str]:
        """The markets that have an account to trade on."""
        found: set[str] = set()
        for market in ("us", "asx", "crypto"):
            with contextlib.suppress(TradingError):
                if market in self._broker(config, market).markets():
                    found.add(market)
        return frozenset(found)

    async def _scan_and_debate(self, config: DeskConfig) -> None:
        markets = self._markets(config)
        instruments = [
            item
            for item in universe(config.markets, config.watchlist)
            if item.market in markets
        ]
        if config.markets.get("meme") and "crypto" in markets:
            for symbol in (await self._data.trending_coins())[:10]:
                with contextlib.suppress(SymbolError):
                    found = parse_symbol(f"CRYPTO:{symbol}")
                    if found.symbol not in {item.symbol for item in instruments}:
                        instruments.append(found)
        held: set[str] = set()
        for broker in self._brokers_in_use(config):
            held |= {holding.symbol for holding in await self._holdings(broker)}
        for symbol in held - {item.symbol for item in instruments}:
            with contextlib.suppress(SymbolError):
                instruments.append(parse_symbol(symbol))
        self._activity = {
            "stage": "Scanning",
            "symbol": "",
            "seat": 0,
            "since": now_ms(),
        }
        candidates = await scan(
            instruments,
            data=self._data,
            workers=self._workers,
            held=held,
            limit=config.candidates,
            is_open=self._is_open,
        )
        await self.feed.emit(
            "scan",
            f"Scanned {len(instruments)} symbols; debating "
            + (
                ", ".join(f"{c.instrument.symbol} ({c.score:+.1f})" for c in candidates)
                or "none"
            )
            + ".",
            data={
                "candidates": [
                    {
                        "symbol": c.instrument.symbol,
                        "score": c.score,
                        "tags": list(c.tags),
                        "held": c.held,
                    }
                    for c in candidates
                ]
            },
        )
        for candidate in candidates:
            await self._consider(candidate, config)

    async def _debate_symbol(
        self, symbol: str, config: DeskConfig, *, tags: tuple[str, ...] = (ASKED,)
    ) -> None:
        try:
            instrument = parse_symbol(symbol)
        except SymbolError as error:
            await self.feed.emit("error", str(error))
            return
        broker = self._broker(config, instrument.market)
        held = {holding.symbol for holding in await self._holdings(broker)}
        await self._consider(
            Candidate(instrument, 0.0, tags, held=instrument.symbol in held),
            config,
        )

    async def _consider(self, candidate: Candidate, config: DeskConfig) -> None:
        instrument = candidate.instrument
        record = TradeRound(
            symbol=instrument.symbol, market=instrument.market, depth=config.depth
        )
        await self._store.put(record)
        self.feed.config_version = config_version(config)
        await self._decisions.start(record, config=config, tags=candidate.tags)
        self._activity = {
            "stage": "Briefing",
            "symbol": instrument.symbol,
            "seat": 0,
            "round_id": record.id,
            "since": now_ms(),
        }
        broker = self._broker(config, instrument.market)
        position = await self._store.get(
            TradePosition, f"{broker.id}:{instrument.symbol}"
        )
        scored = await self._scored()
        seat_records = records(scored, market=instrument.market)
        try:
            briefing = await build_briefing(
                instrument,
                data=self._data,
                research=self._research,
                recall=self._recall,
                records=seat_records,
                held=position,
                tags=candidate.tags,
                meme_liquidity=config.risk.meme_min_liquidity_usd,
                meme_age_days=config.risk.meme_min_age_days,
            )
        except (MarketDataError, ServiceError, ValueError) as error:
            await self._close_round(record, "failed", f"No briefing: {error}")
            await self.feed.emit(
                "error",
                f"Couldn't brief {instrument.symbol}: {error}",
                round_id=record.id,
                symbol=instrument.symbol,
            )
            return
        quality, news_problems, sizing = await self._check_data(
            instrument, briefing, config, record.id
        )
        if sizing is not briefing.quote:
            briefing = replace(briefing, quote=sizing)
        evidence: JsonObject = {}
        pack: EvidencePack | None = None
        try:
            pack = await self._evidence(
                briefing, quality, news_problems, config, record.id
            )
        except Exception as error:
            # Without the pack the seats would read unchecked text: no buys.
            logger.warning(
                "Trading: no evidence pack for {}: {}", instrument.symbol, error
            )
            quality = quality.with_check(
                QualityCheck(
                    "evidence",
                    "Evidence pack built",
                    False,
                    True,
                    detail=f"it couldn't be built ({type(error).__name__}: {error})",
                )
            )
        else:
            briefing = replace(briefing, evidence_text=pack.text)
            evidence = {
                "id": pack.id,
                "digest": pack.digest,
                "cutoff": pack.cutoff,
                "missing": list(pack.missing),
            }
        # Bad data skips the debate for a scanner pick. A holding is still
        # reviewed (it may need selling), and a debate the owner asked for
        # still runs as analysis; neither can buy while the data fails.
        if not quality.ok and position is None and ASKED not in candidate.tags:
            await self._close_round(
                record.model_copy(
                    update={"data": {"quality": quality.view(), "evidence": evidence}}
                ),
                "blocked",
                quality.summary(),
            )
            return
        weights = {seat: found.weight for seat, found in seat_records.items()}
        checked = briefing

        async def look_up(questions: Sequence[str], budget: Budget) -> Findings:
            return await self._look_up(checked, config, questions, budget)

        async def latest() -> QuoteSnapshot | None:
            return await self._latest(checked, config)

        async def stressed(plan: PMDecision) -> str:
            return await self._stress_preview(checked, config, quality, plan)

        debate = Debate(
            think=self._think,
            feed=self.feed,
            config=config,
            briefing=briefing,
            round_id=record.id,
            weights=weights,
            limits_text=_limits_text(config),
            on_stage=lambda stage, seat: self._activity.update(
                {"stage": stage, "seat": seat, "since": now_ms()}
            ),
            tools=DebateTools(
                pack=pack,
                clock=self._clock,
                look_up=look_up,
                latest=latest,
                keep_pack=self._keep_pack,
                stress=stressed,
                data=config.data,
                profile=profile_of(instrument),
                cost_pct=_round_trip_pct(config, quality),
            ),
        )
        result = await debate.run()
        if result.pack_id:
            evidence["final_id"] = result.pack_id
        if result.evidence_text:
            # The risk period reads the pack the decision was made on.
            briefing = replace(briefing, evidence_text=result.evidence_text)
        await self._save_forecasts(record, briefing, result)
        data: JsonObject = {
            "briefing": {
                "tech": briefing.tech.view(),
                "regime": briefing.regime.view(),
                "base": briefing.base.view() if briefing.base is not None else None,
                "price": briefing.price,
                "currency": briefing.quote.currency,
            },
            "decision": result.decision.model_dump()
            if result.decision is not None
            else None,
            "objections": [o.point for o in result.objections],
            "rebuttal_rounds": result.rebuttal_rounds,
            "converged": result.converged,
            "setup": briefing.setup,
            "regime": briefing.regime.label,
            "quality": quality.view(),
            "evidence": evidence,
            "debate": result.record(),
        }
        record = record.model_copy(update={"consensus": result.consensus, "data": data})
        await self._decisions.update(
            record.id,
            pack_id=result.pack_id or str(evidence.get("id") or ""),
            data=_decision_data(briefing, quality, evidence, result, self._clock()),
        )
        try:
            await self._settle_round(
                record, briefing, result, position, config, quality
            )
        finally:
            await self._decisions.transcript(
                record.id, await self.feed.for_round(record.id)
            )

    async def _settle_round(
        self,
        record: TradeRound,
        briefing: Briefing,
        result: DebateResult,
        position: TradePosition | None,
        config: DeskConfig,
        quality: QualityReport,
    ) -> None:
        """Act on the debate: hold, sell what we hold, or take a buy through
        the freshness check and the risk period."""
        decision = result.decision
        if decision is None or decision.action == "hold":
            if result.blocked:
                await self._close_round(record, "blocked", result.blocked)
                return
            await self._close_round(
                record, "held", decision.rationale if decision else "No decision."
            )
            return
        if decision.action == "sell":
            if position is None:
                await self._close_round(
                    record, "held", "Sell decided, but nothing is held."
                )
                return
            if not config.running:
                await self._close_round(
                    record, "advice", "Sell advised; the desk is stopped."
                )
                return
            await self._close_round(record, "traded", decision.rationale)
            await self._exit(
                position,
                "the Portfolio Manager decided to sell",
                config,
                round_id=record.id,
            )
            return
        if not quality.ok:
            await self._close_round(
                record, "blocked", f"Buy decided, but {quality.summary()}"
            )
            return
        stale = await self._stale(briefing, config, record)
        if stale:
            # An old decision never places a new order: it is set aside and
            # the symbol is analysed again from scratch.
            await self._close_round(record, "discarded", f"Decision discarded: {stale}")
            queued = self._recheck(briefing.symbol)
            await self.feed.emit(
                "stale",
                f"Decision discarded: {stale}"
                + (
                    " A fresh analysis is queued."
                    if queued
                    else " It was re-analysed recently, so the next scan decides."
                ),
                round_id=record.id,
                symbol=briefing.symbol,
            )
            return
        await self._buy(record, briefing, result, decision, config, quality)

    async def _stale(
        self, briefing: Briefing, config: DeskConfig, record: TradeRound
    ) -> str:
        """Why a buy decision is too old to act on, or "": it took longer than
        the limit, or the price left the band since the analysis."""
        minutes = (self._clock() - record.created_at / 1000) / 60
        limit = config.assessment.max_decision_minutes
        if minutes > limit:
            return f"the decision took {minutes:.0f} min (limit {limit:g} min)."
        latest: QuoteSnapshot | None = None
        try:
            latest = await self._latest(briefing, config)
        except (MarketDataError, ServiceError, ValueError) as error:
            logger.info("Trading: no price to check the decision against: {}", error)
        if latest is None or not latest.last:
            return "there was no fresh price to check the decision against."
        moved = abs(latest.last / briefing.price - 1) * 100
        band = config.assessment.entry_band_pct
        await self._decisions.update(
            record.id,
            data={
                "prices": {"final_decision": latest.last},
                "timing": {"freshness_check": self._clock()},
            },
        )
        if moved > band:
            return f"the price moved {moved:.2f}% since the analysis (band {band:g}%)."
        return ""

    def _entry_block(self, config: DeskConfig) -> str:
        """Why no new trade may start now ("" when one may): the kill switch,
        the circuit breaker, or an order not yet matched with its account
        (at once, before the breaker's next look trips it)."""
        state = self._state()
        if isinstance(state.get("kill"), dict):
            return "the kill switch is on"
        current = Trip.read(state.get("breaker"))
        if current is not None:
            return f"the circuit breaker is on ({current.reason})"
        if self._unmatched:
            return "FCC couldn't match an order with its account yet"
        return ""

    async def _protect(self, config: DeskConfig) -> None:
        """The circuit breaker: trip on what has gone wrong, clear after the
        cool-down once the cause is gone. Checked at most once a minute."""
        now = self._clock()
        if now - self._last_protect < PROTECT_SECONDS:
            return
        self._last_protect = now
        state = self._state()
        since = state.get("breaker_since")
        health = await self._health(
            config, since=float(since) if isinstance(since, int | float) else 0.0
        )
        current = Trip.read(state.get("breaker"))
        limits = config.breaker
        if current is not None:
            if may_clear(current, health, limits, now):
                state = self._state()
                state.pop("breaker", None)
                state["breaker_since"] = now
                self._save_state(state)
                await self.feed.emit(
                    "breaker",
                    f"Circuit breaker cleared ({current.reason} no longer holds): "
                    "new trades may start again.",
                    data={"cleared": current.view()},
                )
            return
        found = breaker_check(health, limits)
        if found is None:
            return
        tripped = trip(found, now=now, limits=limits)
        state = self._state()
        state["breaker"] = tripped.view()
        state["breaker_since"] = now
        self._save_state(state)
        await self.feed.emit(
            "breaker",
            f"Circuit breaker: new trades are paused because {tripped.reason}. "
            "Open positions are still managed. It clears after "
            f"{limits.cooldown_minutes} min once the cause is gone, or reset it "
            "on the PC.",
            data={"trip": tripped.view()},
        )

    async def _health(self, config: DeskConfig, *, since: float) -> Health:
        """What the circuit breaker looks at, counting only what happened
        after it last cleared."""
        broker = self._broker(config)
        day_change: float | None = None
        with contextlib.suppress(TradingError, ServiceError, MarketDataError):
            equity, _, _ = await self._account_picture(broker, config)
            _, day_change, _ = await self._day(broker, config, equity)
        since_ms = int(since * 1000)
        closed = await self._decisions.search(
            status="position_closed",
            since_ms=since_ms,
            limit=config.breaker.consecutive_losses,
        )
        results = [item.pnl for item in closed if item.pnl is not None]
        slippage: float | None = None
        for order in await self._store.find(
            TradeOrder, where={"status": "filled"}, order_by="updated_at DESC", limit=5
        ):
            if order.updated_at < since_ms:
                break
            if order.fill_price and order.entry_price > 0:
                worse = (
                    order.fill_price / order.entry_price - 1
                    if order.side == "buy"
                    else 1 - order.fill_price / order.entry_price
                )
                slippage = max(0.0, worse * 100)
                break
        window_ms = max(since_ms, now_ms() - config.breaker.errors_minutes * 60_000)
        errors = await self._decisions.trail(
            kind="error", since_ms=window_ms, limit=config.breaker.errors
        )
        streak = 0
        for item in await self._store.find(
            TradeRound, order_by="created_at DESC", limit=config.breaker.stale_rounds
        ):
            if item.created_at < since_ms:
                break
            if item.status == "blocked" and item.note.startswith(
                "Data not good enough"
            ):
                streak += 1
            else:
                break
        return Health(
            day_change_pct=day_change,
            max_daily_loss_pct=config.risk.max_daily_loss_pct,
            recent_results=results,
            last_slippage_pct=slippage,
            slippage_limit_pct=config.risk.slippage_pct,
            errors_recent=len(errors),
            stale_streak=streak,
            reconcile_failed=self._unmatched_text(),
        )

    def _recheck(self, symbol: str) -> bool:
        now = self._clock()
        if now - self._rechecked.get(symbol, -RECHECK_SECONDS) < RECHECK_SECONDS:
            return False
        self._rechecked[symbol] = now
        if symbol not in self._rechecks:
            self._rechecks.append(symbol)
        return True

    async def _check_data(
        self,
        instrument: Instrument,
        briefing: Briefing,
        config: DeskConfig,
        round_id: str,
    ) -> tuple[QualityReport, tuple[str, ...], Quote]:
        """The data-quality checks for one candidate, recorded in the feed;
        which news feeds couldn't be read; and the quote the order would be
        sized and priced from. If the checks themselves break, the report
        fails (no new buys) rather than the round."""
        broker = self._broker(config, instrument.market)
        live = config.live and broker.live
        news: list[NewsItem] = []
        missing: tuple[str, ...] = ()
        sizing = briefing.quote
        try:
            report, news, missing, sizing = await self._run_checks(
                instrument, briefing, config, broker, live
            )
        except Exception as error:
            logger.warning(
                "Trading: the data checks for {} broke: {}", instrument.symbol, error
            )
            report = failed_report(
                instrument.symbol,
                now=self._clock(),
                live=live,
                error=f"{type(error).__name__}: {error}",
            )
        view = report.view()
        view["news"] = [item.view() for item in news]
        view["news_missing"] = list(missing)
        await self.feed.emit(
            "data_quality",
            report.summary(),
            round_id=round_id,
            symbol=instrument.symbol,
            data=view,
        )
        return report, missing, sizing

    async def _run_checks(
        self,
        instrument: Instrument,
        briefing: Briefing,
        config: DeskConfig,
        broker: Broker,
        live: bool,
    ) -> tuple[QualityReport, list[NewsItem], tuple[str, ...], Quote]:
        snapshots = await self._data.snapshots(instrument)
        raw, missing = await self._news.for_instrument(instrument)
        now = self._clock()
        news = judge(
            raw,
            symbol=instrument.symbol,
            now=now,
            bars=briefing.daily,
            atr=briefing.tech.atr,
            max_age_days=config.data.news_max_age_days,
        )
        account_at: float | None = None
        platform: QuoteSnapshot | None = None
        sizing = briefing.quote
        if live:
            try:
                await broker.account()
            except (TradingError, ServiceError) as error:
                logger.info("Trading: account read failed ({})", error)
            else:
                account_at = self._clock()
            quote = None
            with contextlib.suppress(ServiceError):
                quote = await broker.quote(instrument)
            if quote is not None:
                # A price flagged delayed, frozen, halted or last-close isn't
                # real time; one without its own time is cross-checked.
                platform = quote_snapshot(
                    quote, instrument, received=now, realtime=not quote.note
                )
                snapshots = [platform, *snapshots]
                if (
                    quote.stamped
                    and quote.at > 0
                    and not quote.note
                    and quote.currency == briefing.quote.currency
                ):
                    # Live orders are sized from the platform's own
                    # real-time price, not a slower public feed.
                    sizing = quote
        report = assess(
            instrument,
            now=now,
            snapshots=snapshots,
            daily=briefing.daily,
            limits=config.data,
            live=live,
            news=news,
            account_at=account_at,
            meme_facts=(briefing.dex is not None)
            if instrument.meme or instrument.market == "dex"
            else None,
            meme_facts_note=self._data.dex_error(instrument),
            venue=await self._data.venue_status(instrument),
            sizing=sizing_snapshot(sizing, instrument, received=now),
            platform=platform,
            platform_name=broker.name,
        )
        return report, news, tuple(missing), sizing

    async def _evidence(
        self,
        briefing: Briefing,
        quality: QualityReport,
        news_problems: tuple[str, ...],
        config: DeskConfig,
        round_id: str,
    ) -> EvidencePack:
        """Number everything the seats will read, keep it, and say so."""
        instrument = briefing.instrument
        broker = self._broker(config, instrument.market)
        portfolio = await self._portfolio_facts(broker, config)
        fx: tuple[str, float, float | None] | None = None
        if instrument.currency and instrument.currency != config.currency:
            with contextlib.suppress(MarketDataError):
                rate = await self._data.fx(instrument.currency, config.currency)
                fx = (
                    f"{config.currency} per {instrument.currency}",
                    rate,
                    self._data.fx_time(instrument.currency, config.currency),
                )
        pack = build_pack(
            briefing=briefing,
            quality=quality,
            config=config,
            round_id=round_id,
            now=self._clock(),
            portfolio=portfolio,
            fx=fx,
            history_source=self._data.bars_source(instrument),
            news_problems=news_problems,
        )
        await self._store.put(pack.record())
        count = len(pack.items) + len(pack.news) + len(pack.reading)
        await self.feed.emit(
            "evidence",
            f"Evidence pack for {instrument.symbol}: {count} numbered items, "
            f"{len(pack.missing)} things missing.",
            round_id=round_id,
            symbol=instrument.symbol,
            data={
                "id": pack.id,
                "digest": pack.digest,
                "cutoff": pack.cutoff,
                "missing": list(pack.missing),
            },
        )
        return pack

    async def _portfolio_facts(
        self, broker: Broker, config: DeskConfig
    ) -> PortfolioFacts | None:
        """The account as the platform reports it now; None if it can't be
        read (the pack then says it's missing)."""
        try:
            account = await broker.account()
            rate = await self._data.fx(account.currency, config.currency)
            # Today's change is only known against an earlier reading today.
            marked = self._has_mark(broker.id)
            equity, exposures, held = await self._account_picture(broker, config)
            trades, day_change, _ = await self._day(broker, config, equity)
        except (TradingError, ServiceError, MarketDataError) as error:
            logger.info("Trading: account not read for the evidence pack ({})", error)
            return None
        return PortfolioFacts(
            currency=config.currency,
            source=broker.name,
            as_of=self._clock(),
            equity=equity,
            cash=account.cash * rate,
            positions=tuple(
                (item.symbol, held.get(item.symbol, 0.0), item.value)
                for item in exposures
            ),
            trades_today=trades,
            day_change_pct=day_change if marked else None,
            estimated=tuple(item.symbol for item in exposures if item.estimated),
        )

    async def _tighten(
        self,
        assessment: RiskAssessment,
        *,
        briefing: Briefing,
        result: DebateResult,
        decision: Decision,
        config: DeskConfig,
        quality: QualityReport,
        rules: Rules,
        fx: float,
        equity: float,
        exposures: list[Exposure],
        broker: Broker,
        round_id: str,
    ) -> Tightening:
        """The investment stress test, the conflicts, the scorecard, and every
        rule of the decision engine, on top of the risk report."""
        instrument = briefing.instrument
        policy = policy_for(briefing.regime)
        stress: StressReport | None = None
        try:
            given = await self._stress_input(
                briefing,
                config,
                quality,
                qty=assessment.qty,
                entry=assessment.entry,
                stop=assessment.stop,
                fx=fx,
                equity=equity,
                exposures=exposures,
                min_qty=rules.min_qty,
                extra=tuple((case.name, case.loss) for case in assessment.stress),
                guardian=tuple(
                    (item.name, item.fall_pct)
                    for item in (result.review.scenarios if result.review else ())
                ),
                earnings_in_window=any(
                    event.get("name") == "Earnings or results"
                    and bool(event.get("in_window"))
                    for event in assessment.events
                ),
            )
            stress = stress_test(
                given,
                now=self._clock(),
                trade_limit_pct=config.assessment.stress_trade_pct,
                account_limit_pct=config.assessment.stress_account_pct,
            )
        except (MarketDataError, ServiceError, ValueError) as error:
            logger.info("Trading: the stress test couldn't run: {}", error)
        if stress is not None:
            assessment.stress_test = stress.view()
            assessment.stress_text = stress.lines()
        conflicts = [
            *seat_conflicts(instrument.symbol, result.closing, buying=True),
            *data_conflicts(
                instrument.symbol,
                instrument.market,
                briefing.daily,
                briefing.price,
                source=self._data.bars_source(instrument),
            ),
        ]
        penalty, conflict_size, conflict_blocking = applied(conflicts)
        info = result.info_test
        worst = stress.worst_trade if stress is not None else None
        spread = bid_ask_source(
            quality.snapshots,
            quality.preferred,
            now=quality.at,
            limits=config.data,
            profile=profile_of(instrument),
        )
        card = score_trade(
            TradeFacts(
                consensus=result.consensus,
                buy_share=result.buy_share,
                quality_score=quality.score,
                reward_risk=assessment.reward_risk,
                stop_atr=assessment.stop_atr,
                trend=briefing.tech.trend,
                price=briefing.price,
                sma50=briefing.tech.sma50,
                sma200=briefing.tech.sma200,
                rsi=briefing.tech.rsi,
                held_up=sum(1 for item in info.items if item.verdict == "holds")
                if info is not None
                else None,
                tested=len(info.items) if info is not None else None,
                regime_kind=briefing.regime.kind,
                regime_extreme=briefing.regime.extreme,
                events_in_window=sum(
                    1 for event in assessment.events if event.get("in_window")
                ),
                stress_worst_pct=worst.pct_of_equity if worst is not None else None,
                stress_limit_pct=config.assessment.stress_trade_pct,
                max_correlation=max(assessment.correlations.values(), default=None),
                correlation_limit=config.assessment.max_correlation,
                position_pct=assessment.value / equity * 100 if equity > 0 else None,
                position_cap_pct=config.risk.meme_position_pct
                if instrument.meme
                else config.risk.max_position_pct,
                spread_pct=spread.spread_pct if spread is not None else None,
                spread_limit_pct=config.data.spread_pct.get(
                    profile_of(instrument), 1.0
                ),
                adv_pct=assessment.adv_pct,
                adv_limit_pct=config.assessment.max_adv_pct,
                base_target_first=briefing.base.target_first
                if briefing.base is not None
                else None,
            )
        )
        assessment.scorecard = card.view()
        assessment.scorecard_text = card.lines()
        confidence = max(0.0, min(decision.confidence - penalty / 100, card.confidence))
        assessment.confidence = confidence
        trades_today: int | None = None
        with contextlib.suppress(ServiceError, MarketDataError, TradingError):
            trades_today, _, _ = await self._day(broker, config, equity)
        checks = buy_rules(
            BuyFacts(
                data_ok=quality.ok,
                data_summary=quality.summary(),
                stop_atr=assessment.stop_atr,
                min_stop_atr=config.assessment.min_stop_atr,
                reward_risk=assessment.reward_risk,
                min_reward_risk=config.assessment.min_reward_risk,
                confidence=confidence,
                min_confidence=config.risk.min_confidence,
                consensus=result.consensus,
                min_consensus=config.risk.min_consensus,
                trades_today=trades_today,
                max_trades_per_day=config.risk.max_trades_per_day,
                objections_left=len(result.objections),
                answered=len(decision.answers),
                stress_blocked=stress.blocked if stress is not None else None,
                stress_reasons=stress.reasons if stress is not None else (),
                stress_worst_pct=worst.pct_of_equity if worst is not None else None,
                stress_limit_pct=config.assessment.stress_trade_pct,
                info_blocked=info.blocked if info is not None else None,
                conflicts_blocking=conflict_blocking,
                conflict_reasons=tuple(item.line() for item in conflicts),
            ),
            policy,
        )
        assessment.rules = [check.view() for check in checks]
        assessment.blockers.extend(rule_blockers(checks))
        failed = [check for check in checks if not check.passed]
        await self.feed.emit(
            "engine",
            (
                f"Decision engine: {len(checks) - len(failed)} of {len(checks)} rules "
                f"passed. Market: {policy.note}."
            )
            + "".join(f"\n{check.line()}" for check in failed)
            + f"\nScorecard confidence {card.confidence:.2f}; the order goes ahead "
            f"with {confidence:.2f}.",
            round_id=round_id,
            symbol=instrument.symbol,
            stage="Risk period",
            data={
                "rules": assessment.rules,
                "policy": policy.view(),
                "scorecard": card.view(),
                "stress_test": assessment.stress_test,
                "conflicts": [item.view() for item in conflicts],
            },
        )
        why = []
        if policy.size_factor < 1:
            why.append(f"the market's mood (x{policy.size_factor:g})")
        if conflict_size < 1:
            why.append(f"seats that oppose the buy (x{conflict_size:.2f})")
        return Tightening(
            size_factor=policy.size_factor * conflict_size,
            why="Size cut for " + " and ".join(why) + "." if why else "",
            max_qty=(0.0 if stress.blocked else stress.max_qty)
            if stress is not None
            else None,
            confidence=confidence,
        )

    async def _stress_input(
        self,
        briefing: Briefing,
        config: DeskConfig,
        quality: QualityReport,
        *,
        qty: float,
        entry: float,
        stop: float,
        fx: float,
        equity: float,
        exposures: list[Exposure],
        min_qty: float = 0.0,
        extra: tuple[tuple[str, float], ...] = (),
        guardian: tuple[tuple[str, float], ...] = (),
        earnings_in_window: bool = False,
    ) -> StressInput:
        instrument = briefing.instrument
        index: list[Bar] = []
        with contextlib.suppress(MarketDataError, ServiceError):
            index = await self._data.index_bars(instrument.market)
        currency: list[Bar] = []
        if briefing.quote.currency != config.currency:
            with contextlib.suppress(MarketDataError, ServiceError):
                currency = await self._data.fx_bars(
                    briefing.quote.currency, config.currency
                )
        recent = briefing.daily[-20:]
        turnover = (
            sum(daily_turnover(bar, instrument.market) for bar in recent) / len(recent)
            if recent
            else None
        )
        spread = bid_ask_source(
            quality.snapshots,
            quality.preferred,
            now=quality.at,
            limits=config.data,
            profile=profile_of(instrument),
        )
        held: list[HeldPosition] = []
        for item in exposures:
            crypto = False
            with contextlib.suppress(SymbolError):
                crypto = parse_symbol(item.symbol).market in {"crypto", "dex"}
            held.append(HeldPosition(item.symbol, item.value, None, crypto))
        return StressInput(
            symbol=instrument.symbol,
            market="crypto"
            if instrument.market in {"crypto", "dex"}
            else instrument.market,
            side="long",
            qty=qty,
            entry=entry,
            stop=stop,
            fx=fx,
            equity=equity,
            atr=briefing.tech.atr,
            daily=briefing.daily,
            index_daily=index,
            beta=briefing.beta,
            meme=instrument.meme,
            spread_pct=spread.spread_pct if spread is not None else None,
            avg_daily_turnover=turnover,
            holdings=tuple(held),
            fx_daily=currency,
            earnings_in_window=earnings_in_window,
            guardian=guardian,
            min_qty=min_qty,
            extra=extra,
        )

    async def _stress_preview(
        self,
        briefing: Briefing,
        config: DeskConfig,
        quality: QualityReport,
        plan: PMDecision,
    ) -> str:
        """The investment stress test on the plan the Guardian reviews: the
        same code the buy faces later, at the size the limits would give."""
        broker = self._broker(config, briefing.instrument.market)
        try:
            equity, exposures, _ = await self._account_picture(broker, config)
            rules = await broker.rules(briefing.instrument)
            fx = await self._data.fx(briefing.quote.currency, config.currency)
        except (ServiceError, MarketDataError, TradingError) as error:
            return f"It couldn't be run: {error}"
        stop = plan.stop_loss or 0.0
        sizing = size_position(
            equity=equity,
            price=briefing.price,
            stop=stop,
            fx=fx,
            limits=config.risk,
            meme=briefing.instrument.meme,
            regime_scale=briefing.regime.risk_scale,
            size_pct=plan.size_pct or 0.0,
            rules=rules,
        )
        given = await self._stress_input(
            briefing,
            config,
            quality,
            qty=sizing.qty,
            entry=briefing.price,
            stop=stop,
            fx=fx,
            equity=equity,
            exposures=exposures,
            min_qty=rules.min_qty,
        )
        report = stress_test(
            given,
            now=self._clock(),
            trade_limit_pct=config.assessment.stress_trade_pct,
            account_limit_pct=config.assessment.stress_account_pct,
        )
        return (
            f"At {sizing.qty:g} units (the size the limits would give):\n"
            + report.lines()
        )

    async def _keep_pack(self, pack: EvidencePack) -> None:
        """Keep each new version of the pack, so every answer can be traced
        to exactly what its seat saw."""
        await self._store.put(pack.record())

    async def _latest(
        self, briefing: Briefing, config: DeskConfig
    ) -> QuoteSnapshot | None:
        """The most reliable fresh price right now, or None (never an old
        price passed off as current)."""
        instrument = briefing.instrument
        snapshots = await self._data.snapshots(instrument)
        return freshest(
            [snap for snap in snapshots if snap.currency == briefing.quote.currency],
            now=self._clock(),
            limits=config.data,
            profile=profile_of(instrument),
        )

    async def _look_up(
        self,
        briefing: Briefing,
        config: DeskConfig,
        questions: Sequence[str],
        budget: Budget,
    ) -> Findings:
        """Between debate rounds: the latest prices, fresh dated news, and
        the seats' open questions searched on the web (within the budget)."""
        instrument = briefing.instrument
        problems: list[str] = []
        facts: list[InfoItem] = []
        try:
            snapshots = await self._data.snapshots(instrument)
        except (ServiceError, MarketDataError, ValueError) as error:
            problems.append(f"the prices couldn't be read again ({error})")
        else:
            facts = [
                price_fact(
                    snap,
                    label=f"Price on {snap.provider}, read again",
                    symbol=instrument.symbol,
                )
                for snap in snapshots
                if snap.last
            ]
        news: list[NewsItem] = []
        try:
            raw, missing = await self._news.for_instrument(instrument)
        except (ServiceError, ValueError) as error:
            problems.append(f"dated news couldn't be read ({error})")
        else:
            problems.extend(missing)
            news = judge(
                raw,
                symbol=instrument.symbol,
                now=self._clock(),
                bars=briefing.daily,
                atr=briefing.tech.atr,
                max_age_days=config.data.news_max_age_days,
            )
        reading: list[InfoItem] = []
        searched: tuple[str, ...] = ()
        if questions and budget.searches > 0:
            found = await self._research.look_up(
                instrument,
                list(questions),
                searches=budget.searches,
                pages=budget.pages,
            )
            searched = found.queries
            problems.extend(found.notes)
            for hit in found.headlines:
                text = hit.title + (f" — {hit.snippet}" if hit.snippet else "")
                reading.append(reading_item(text, hit.url, label="Web search result"))
            for link, piece in found.pages:
                reading.append(
                    reading_item(piece, link, label="From a page", limit=PAGE_EXCERPT)
                )
        return Findings(
            facts=tuple(facts),
            news=tuple(news),
            reading=tuple(reading),
            problems=tuple(problems),
            searched=searched,
        )

    async def _close_round(self, record: TradeRound, status: str, note: str) -> None:
        await self._store.put(
            record.model_copy(
                update={"status": status, "note": note[:500], "updated_at": now_ms()}
            )
        )
        await self._decisions.closed(record.id, status, note)

    async def _save_forecasts(
        self, record: TradeRound, briefing: Briefing, result: DebateResult
    ) -> None:
        created = now_ms()
        atr_value = briefing.tech.atr or 0.0
        price = briefing.price

        def make(seat: int, stage: str, view: Forecast | Decision) -> TradeForecast:
            target = stop = None
            if isinstance(view, Decision) and view.action == "buy":
                target, stop = view.take_profit, view.stop_loss
            elif atr_value:
                target, stop = price + 2 * atr_value, price - atr_value
            move = view.expected_move_pct if isinstance(view, Forecast) else 0.0
            return TradeForecast(
                round_id=record.id,
                seat=seat,
                stage=stage,
                symbol=briefing.symbol,
                market=briefing.instrument.market,
                regime=briefing.regime.label,
                setup=briefing.setup,
                horizon_days=view.horizon_days,
                p_up=view.p_up,
                expected_move=move,
                p_target=view.p_target,
                target=target,
                stop=stop,
                entry_price=price,
                confidence=view.confidence,
                due_at=due_at(created, view.horizon_days, briefing.instrument.market),
                created_at=created,
            )

        found = [make(seat, "opening", view) for seat, view in result.openings.items()]
        found += [make(seat, "closing", view) for seat, view in result.closing.items()]
        if result.decision is not None:
            found.append(make(5, "decision", result.decision))
        if found:
            await self._store.put_many(found)

    async def _buy(
        self,
        record: TradeRound,
        briefing: Briefing,
        result: DebateResult,
        decision: Decision,
        config: DeskConfig,
        quality: QualityReport,
    ) -> None:
        instrument = briefing.instrument
        broker = self._broker(config, instrument.market)
        blocked = self._entry_block(config)
        if blocked:
            await self._close_round(record, "blocked", f"Buy decided, but {blocked}.")
            await self.feed.emit(
                "risk_gate",
                f"No new trade: {blocked}.",
                round_id=record.id,
                symbol=instrument.symbol,
            )
            return
        self._activity.update({"stage": "Risk period", "seat": 0, "since": now_ms()})
        try:
            equity, exposures, _ = await self._account_picture(broker, config)
            rules = await broker.rules(instrument)
            fx = await self._data.fx(briefing.quote.currency, config.currency)
        except (ServiceError, MarketDataError) as error:
            await self._close_round(
                record, "failed", f"Couldn't read the account: {error}"
            )
            await self.feed.emit(
                "error",
                f"Risk period stopped: {error}",
                round_id=record.id,
                symbol=instrument.symbol,
            )
            return
        if not rules.tradable:
            await self._close_round(
                record, "blocked", rules.note or "Not tradable here."
            )
            await self.feed.emit(
                "risk_gate",
                f"{broker.name} can't trade {instrument.symbol}: {rules.note}",
                round_id=record.id,
                symbol=instrument.symbol,
            )
            return
        sizing = size_position(
            equity=equity,
            price=briefing.price,
            stop=decision.stop_loss or 0.0,
            fx=fx,
            limits=config.risk,
            meme=instrument.meme,
            regime_scale=briefing.regime.risk_scale,
            size_pct=decision.size_pct,
            rules=rules,
        )
        holding_bars: dict[str, list] = {}
        sectors: dict[str, str] = {}
        for item in exposures:
            with contextlib.suppress(SymbolError, MarketDataError, ServiceError):
                held = parse_symbol(item.symbol)
                sectors[item.symbol] = held.sector
                holding_bars[item.symbol] = await self._data.bars(held, "1d")
        assessment = risk_report(
            decision=decision,
            briefing=briefing,
            sizing=sizing,
            rules=rules,
            holdings=Holdings(equity, exposures, holding_bars, sectors),
            closing=result.closing,
            weights=result.weights,
            fx=fx,
            config=config,
            earnings=result.earnings,
            events=result.events,
            now_ms=now_ms(),
        )
        # The original checks above ran first, on the original size; what
        # follows can only add blockers or make the order smaller.
        tightened = await self._tighten(
            assessment,
            briefing=briefing,
            result=result,
            decision=decision,
            config=config,
            quality=quality,
            rules=rules,
            fx=fx,
            equity=equity,
            exposures=exposures,
            broker=broker,
            round_id=record.id,
        )
        await self.feed.emit(
            "risk_report",
            assessment.report(config.currency),
            round_id=record.id,
            symbol=instrument.symbol,
            stage="Risk period",
            data={"assessment": assessment.view()},
        )
        assessment = await risk_round(
            assessment,
            briefing=briefing,
            think=self._think,
            feed=self.feed,
            config=config,
            round_id=record.id,
        )
        if quality.size_factor < 1:
            # Data warnings and sources that disagree cut the final size, on
            # top of every other limit (never a bigger size).
            assessment.size_factor = min(1.0, assessment.size_factor) * (
                quality.size_factor
            )
            assessment.cautions.append(
                "Data warnings or disagreeing sources cut the size to "
                f"{quality.size_factor:.0%}."
            )
        resize(assessment, rules, fx, equity)
        shrink(assessment, tightened.size_factor, rules, fx, equity, tightened.why)
        if tightened.max_qty is not None and assessment.qty > tightened.max_qty:
            shrink(
                assessment,
                tightened.max_qty / assessment.qty,
                rules,
                fx,
                equity,
                "The investment stress test cut the size to fit its limit.",
            )
        cooling = (
            config.assessment.cooling_crypto_minutes
            if instrument.market in {"crypto", "dex"}
            else config.assessment.cooling_stocks_minutes
        )
        assessment.cooling_minutes = cooling
        data = dict(record.data)
        data["assessment"] = assessment.view()
        record = record.model_copy(update={"data": data})
        await self._decisions.update(
            record.id,
            data={
                "risk_checks": assessment.rules,
                "risk_blockers": list(assessment.blockers),
                "stress_test": assessment.stress_test,
                "scorecard": assessment.scorecard,
                "assessment": {
                    "grade": assessment.grade,
                    "qty": assessment.qty,
                    "value": assessment.value,
                    "at_risk": assessment.at_risk,
                    "reward_risk": assessment.reward_risk,
                    "confidence": assessment.confidence,
                },
                "timing": {"order_decision": self._clock()},
            },
        )
        if not assessment.passed:
            why = (
                "deferred by the Portfolio Manager"
                if assessment.deferred
                else "; ".join(assessment.blockers) or "no size left"
            )
            await self._close_round(record, "blocked", why)
            await self.feed.emit(
                "risk_gate",
                f"The risk assessment stopped the trade (grade {assessment.grade}): {why}",
                round_id=record.id,
                symbol=instrument.symbol,
                stage="Risk period",
                data={"assessment": assessment.view()},
            )
            return
        if config.alert_only:
            await self._close_round(
                record, "alert", "Alert only: the desk never orders in this mode."
            )
            await self.feed.emit(
                "alert",
                f"Alert: buy {assessment.qty:g} {instrument.symbol} near "
                f"{assessment.entry:g}, stop {assessment.stop:g}, target "
                f"{assessment.target:g} (risk grade {assessment.grade}). Nothing was "
                "ordered (alert-only mode).",
                round_id=record.id,
                symbol=instrument.symbol,
                data={"assessment": assessment.view()},
            )
            return
        if not config.running:
            await self._close_round(
                record, "advice", "The desk is stopped, so this stayed advice."
            )
            await self.feed.emit(
                "info",
                f"Advice only (the desk is stopped): buy {assessment.qty:g} "
                f"{instrument.symbol}, risk grade {assessment.grade}. Start the desk to trade.",
                round_id=record.id,
                symbol=instrument.symbol,
            )
            return
        order = TradeOrder(
            client_id=_client_id(),
            round_id=record.id,
            broker=broker.id,
            mode=config.mode,
            symbol=instrument.symbol,
            market=instrument.market,
            side="buy",
            qty=assessment.qty,
            order_type=decision.order_type,
            limit_price=decision.limit_price
            if decision.order_type == "limit"
            else None,
            stop_loss=decision.stop_loss,
            take_profit=decision.take_profit,
            entry_price=assessment.entry,
            currency=briefing.quote.currency,
            status="cooling",
            reason=decision.rationale[:500],
            data={
                "decision": decision.model_dump(),
                "plan": {
                    "trailing_pct": result.plan.trailing_stop_pct
                    if result.plan is not None
                    else None,
                    "holding_days": decision.horizon_days,
                    "invalidation": list(result.plan.prove_wrong)
                    if result.plan is not None
                    else [],
                    "thesis": decision.rationale[:300],
                },
                "assessment": assessment.view(),
                "consensus": result.consensus,
                "confidence": tightened.confidence,
                "manager_confidence": decision.confidence,
                "meme": instrument.meme,
            },
            due_at=now_ms() + int(cooling * 60_000),
        )
        await self._store.put(order)
        await self._close_round(record, "pending", decision.rationale)
        await self.feed.emit(
            "cooling",
            f"Risk grade {assessment.grade}: {assessment.qty:g} {instrument.symbol} "
            f"({assessment.value:,.2f} {config.currency}, {assessment.at_risk:,.2f} at risk). "
            f"Cooling off {cooling:g} min, then a fresh check.",
            round_id=record.id,
            symbol=instrument.symbol,
            stage="Risk period",
            data={"order_id": order.id, "due_at": order.due_at},
        )

    # ------------------------------------------------------------ orders

    async def _finish_cooling(self, config: DeskConfig) -> None:
        blocked = self._entry_block(config) or (
            "" if config.running else "the desk was stopped"
        )
        for order in await self._store.find(TradeOrder, where={"status": "cooling"}):
            if blocked and order.side == "buy":
                await self._set(order, status="aborted", reason=blocked)
                await self._round_status(order.round_id, "aborted", blocked)
                continue
            if order.due_at > now_ms():
                continue
            try:
                instrument = parse_symbol(order.symbol)
            except SymbolError:
                await self._set(order, status="failed", reason="Unknown symbol.")
                continue
            quote = None
            with contextlib.suppress(MarketDataError):
                quote = await self._data.quote(instrument)
            await self._decisions.update(
                order.round_id,
                data={
                    "prices": {"final_check": quote.price if quote else None},
                    "timing": {"final_check": self._clock()},
                },
            )
            jump = await self._volatility_jump(instrument)
            assessment = order.data.get("assessment")
            then = dict(assessment) if isinstance(assessment, dict) else {}
            titles = await self._research.fresh_titles(instrument)
            reasons = recheck(
                then,
                quote=quote,
                volatility_jump_pct=jump,
                titles_now=titles,
                code=instrument.code,
                market=instrument.market,
                config=config,
            )
            if reasons:
                await self._set(order, status="aborted", reason="; ".join(reasons))
                await self._round_status(order.round_id, "aborted", "; ".join(reasons))
                await self.feed.emit(
                    "cooling",
                    "Aborted after the cooling-off wait: " + "; ".join(reasons),
                    round_id=order.round_id,
                    symbol=order.symbol,
                    stage="Cooling-off",
                )
                continue
            await self.feed.emit(
                "cooling",
                "Cooling-off passed: price, volatility, and headlines are steady.",
                round_id=order.round_id,
                symbol=order.symbol,
                stage="Cooling-off",
            )
            await self._route(order, config)

    async def _volatility_jump(self, instrument: Instrument) -> float | None:
        """How much bigger the latest 15-minute range is than the usual one, in
        percent; None without enough bars."""
        try:
            bars = await self._data.bars(instrument, "15m")
        except MarketDataError, ServiceError:
            return None
        ranges = true_ranges(bars)
        if len(ranges) < 16:
            return None
        usual = sum(ranges[-15:-1]) / 14
        if usual <= 0:
            return None
        return (ranges[-1] / usual - 1) * 100

    async def _route(
        self, order: TradeOrder, config: DeskConfig, *, approved: bool = False
    ) -> None:
        """Hard limits, then the account check, then the order mode."""
        broker = self._broker_for(order, config)
        try:
            instrument = parse_symbol(order.symbol)
        except SymbolError:
            await self._set(order, status="failed", reason="Unknown symbol.")
            return
        try:
            equity, exposures, held = await self._account_picture(broker, config)
            fx = await self._data.fx(order.currency, config.currency)
        except (ServiceError, MarketDataError) as error:
            await self._set(
                order, status="blocked", reason=f"Couldn't read the account: {error}"
            )
            await self.feed.emit(
                "check",
                f"Blocked: couldn't read the account ({error}).",
                round_id=order.round_id,
                symbol=order.symbol,
            )
            return
        trades_today, day_change, last_trades = await self._day(broker, config, equity)
        open_symbols = [
            other.symbol
            for other in await self._store.find(TradeOrder)
            if other.id != order.id
            and other.status in OPEN_ORDER_STATUSES
            and other.broker == broker.id
        ]
        price = order.limit_price or order.entry_price
        gate = risk_gate(
            symbol=order.symbol,
            side=order.side,
            qty=order.qty,
            price=price,
            stop=order.stop_loss,
            take_profit=order.take_profit,
            value=order.qty * price * fx,
            meme=bool(order.data.get("meme")),
            confidence=_float(order.data.get("confidence"), 1.0),
            consensus=_float(order.data.get("consensus"), 1.0),
            limits=config.risk,
            equity=equity,
            positions=exposures,
            held_qty=held.get(order.symbol, 0.0),
            trades_today=trades_today,
            day_change_pct=day_change,
            last_trade_ms=last_trades,
            open_order_symbols=open_symbols,
            now_ms=now_ms(),
        )
        data = dict(order.data)
        data["gate"] = gate.view()
        if not gate.allowed:
            await self._set(
                order, status="blocked", reason="; ".join(gate.reasons), data=data
            )
            await self._round_status(order.round_id, "blocked", "; ".join(gate.reasons))
            await self.feed.emit(
                "risk_gate",
                "Hard limit: " + "; ".join(gate.reasons),
                round_id=order.round_id,
                symbol=order.symbol,
                data={"gate": gate.view()},
            )
            return
        quote = await self._quote_in(broker, instrument, order.currency)
        data["submission_price"] = quote.price if quote is not None else None
        report = await pre_trade_check(
            broker=broker,
            order=_request(order, instrument),
            decision_price=order.entry_price,
            value=order.qty * price * fx,
            rate=lambda currency: self._data.fx(currency, config.currency),
            verified=config.accounts.get(broker.id, ""),
            slippage_pct=config.risk.slippage_pct,
            market_open=self._is_open(instrument.market),
            quote=quote,
            base_currency=config.currency,
            held=held.get(order.symbol, 0.0),
            now=self._clock(),
            max_age_s=_quote_age_limit(config, instrument, live=broker.live),
            spread_limit_pct=config.data.spread_pct.get(profile_of(instrument)),
        )
        data["check"] = report.view()
        if not report.passed:
            await self._set(
                order, status="blocked", reason="; ".join(report.failures), data=data
            )
            await self._round_status(
                order.round_id, "blocked", "; ".join(report.failures)
            )
            await self.feed.emit(
                "check",
                "Account check failed: " + "; ".join(report.failures),
                round_id=order.round_id,
                symbol=order.symbol,
                data={"check": report.view()},
            )
            return
        await self.feed.emit(
            "check",
            f"Account check passed on {broker.name} ({len(report.items)} checks).",
            round_id=order.round_id,
            symbol=order.symbol,
            data={"check": report.view()},
        )
        needs_tap = broker.live and (
            config.mode == "live_approve" or not config.live_auto_confirmed_at
        )
        if needs_tap and not approved:
            due = now_ms() + config.approval_minutes * 60_000
            await self._set(order, status="awaiting_approval", data=data, due_at=due)
            await self.feed.emit(
                "order",
                f"Waiting for your approval: {order.side} {order.qty:g} {order.symbol} "
                f"on {broker.name} (expires in {config.approval_minutes} min).",
                round_id=order.round_id,
                symbol=order.symbol,
                data={"order_id": order.id},
            )
            return
        await self._execute(order.model_copy(update={"data": data}), broker, config)

    async def approve(self, order_id: str) -> JsonObject:
        order = await self._store.get(TradeOrder, order_id)
        if order is None:
            raise TradingError("That order is gone.")
        if order.status != "awaiting_approval":
            raise TradingError(
                f"That order is {order.status.replace('_', ' ')}, not waiting."
            )
        if order.due_at and order.due_at < now_ms():
            await self._set(order, status="expired", reason="Approved too late.")
            raise TradingError(
                "That approval expired; the desk will look again next round."
            )
        await self.feed.emit(
            "order",
            f"You approved {order.side} {order.qty:g} {order.symbol}; checking again.",
            round_id=order.round_id,
            symbol=order.symbol,
        )
        config = self.config()
        reply = order.data.get("reply")
        if isinstance(reply, dict):
            await self._answer_reply(order, dict(reply), config)
        else:
            await self._route(order, config, approved=True)
        updated = await self._store.get(TradeOrder, order_id)
        return order_view(updated or order)

    async def _answer_reply(
        self, order: TradeOrder, reply: JsonObject, config: DeskConfig
    ) -> None:
        """The platform asked a person to confirm a warning, and the owner
        approved: pass the confirmation on."""
        broker = self._broker_for(order, config)
        answer = getattr(broker, "answer_reply", None)
        if answer is None:
            await self._route(order, config, approved=True)
            return
        data = dict(order.data)
        data.pop("reply", None)
        order = await self._set(order, status="submitting", data=data)
        try:
            result = await answer(reply, order.client_id, order.symbol)
        except ServiceError as error:
            await self._set(order, status="rejected", reason=str(error))
            await self.feed.emit(
                "error",
                f"{broker.name} didn't take the confirmation: {error}",
                round_id=order.round_id,
                symbol=order.symbol,
            )
            return
        await self._record(order, result, config)

    async def deny(self, order_id: str) -> JsonObject:
        order = await self._store.get(TradeOrder, order_id)
        if order is None:
            raise TradingError("That order is gone.")
        if order.status != "awaiting_approval":
            raise TradingError(
                f"That order is {order.status.replace('_', ' ')}, not waiting."
            )
        updated = await self._set(order, status="denied", reason="You said no.")
        await self._round_status(order.round_id, "denied", "You said no.")
        await self.feed.emit(
            "order",
            f"You denied {order.side} {order.qty:g} {order.symbol}.",
            round_id=order.round_id,
            symbol=order.symbol,
        )
        return order_view(updated)

    async def _execute(
        self, order: TradeOrder, broker: Broker, config: DeskConfig
    ) -> None:
        instrument = parse_symbol(order.symbol)
        request = _request(order, instrument)
        order = await self._set(
            order, status="submitting", data={**order.data, "sent_at": self._clock()}
        )
        # While it is being sent, the re-check of unmatched orders leaves it be.
        self._sending.add(order.client_id)
        try:
            await self._send(order, broker, request, config)
        finally:
            self._sending.discard(order.client_id)

    async def _send(
        self,
        order: TradeOrder,
        broker: Broker,
        request: OrderRequest,
        config: DeskConfig,
    ) -> None:
        buying = order.side == "buy"
        await self._decisions.update(
            order.round_id,
            status="order_submitted" if buying else "exit_pending",
            order_submitted=True,
            **({"order_id": order.id} if buying else {}),
            data={
                "prices": {"submission": order.data.get("submission_price")}
                if buying
                else {"exit_submission": order.data.get("submission_price")},
                "timing": {"submitted" if buying else "exit_submitted": self._clock()},
            },
        )
        await self.feed.emit(
            "order",
            f"Sending {order.side} {order.qty:g} {order.symbol} ({order.order_type}) to {broker.name}.",
            round_id=order.round_id,
            symbol=order.symbol,
        )
        try:
            result = await submit_once(
                lambda: broker.place(request), lambda: broker.find(order.client_id)
            )
        except Unconfirmed as error:
            # It may have gone through: it stays open (never sent twice),
            # new trades pause, and later checks ask the platform again.
            await self._set(order, reason=str(error))
            self._unmatched[order.id] = (
                f"{order.side} {order.qty:g} {order.symbol} on {order.broker}: "
                "couldn't confirm whether it went through"
            )
            self._last_protect = 0.0
            await self.feed.emit(
                "error",
                f"Couldn't confirm whether the {order.symbol} order reached "
                f"{broker.name}, so it wasn't sent again. New trades pause until "
                "FCC can match it with the account (check the account).",
                round_id=order.round_id,
                symbol=order.symbol,
            )
            return
        except ServiceError as error:
            await self._set(
                order,
                status="rejected" if not error.transient else "failed",
                reason=str(error),
            )
            await self._round_status(order.round_id, "failed", str(error))
            await self.feed.emit(
                "error",
                f"{broker.name} didn't take the order: {error}",
                round_id=order.round_id,
                symbol=order.symbol,
            )
            return
        await self._record(order, result, config)

    async def _record(
        self, order: TradeOrder, result: OrderResult, config: DeskConfig
    ) -> None:
        """Bring an order up to date with what the platform says."""
        status = {
            "filled": "filled",
            "partially_filled": "partially_filled",
            "cancelled": "cancelled",
            "rejected": "rejected",
            "needs_reply": "awaiting_approval",
        }.get(result.status, "submitted")
        data = dict(order.data)
        changes: dict[str, object] = {}
        if result.status == "needs_reply":
            reply = result.raw.get("reply")
            if isinstance(reply, dict):
                data["reply"] = dict(reply)
            changes["due_at"] = now_ms() + config.approval_minutes * 60_000
        if result.raw.get("bracket"):
            data["bracket"] = True
        if result.raw.get("unconfirmed"):
            data["unconfirmed"] = True
        price, fx, fees = await self._fill_terms(order, result, config)
        updated = await self._set(
            order,
            status=status,
            broker_order_id=result.broker_order_id or order.broker_order_id,
            filled_qty=result.filled_qty,
            fill_price=price,
            fees=fees,
            fx_rate=fx,
            reason=result.note or order.reason,
            data=data,
            **changes,
        )
        if result.status == "needs_reply":
            await self.feed.emit(
                "order",
                f"{result.note} Approve to confirm, or deny.",
                round_id=order.round_id,
                symbol=order.symbol,
                data={"order_id": order.id},
            )
            return
        if (
            status in {"filled", "partially_filled"}
            and result.filled_qty > order.filled_qty
        ):
            # Only what is new since the last update counts: a platform
            # reports the running total, and adding that again would count
            # a partly filled order twice.
            new_qty = result.filled_qty - order.filled_qty
            new_price = _new_fill_price(
                order.filled_qty, order.fill_price, result.filled_qty, price
            )
            new_fees = max(0.0, fees - order.fees)
            fees_known = result.raw.get("fees_reported") is not False
            basis = str(result.raw.get("basis") or "")
            await self._store.put(
                TradeFill(
                    order_id=order.id,
                    round_id=order.round_id,
                    broker=order.broker,
                    symbol=order.symbol,
                    side=order.side,
                    qty=new_qty,
                    price=new_price,
                    fees=new_fees,
                    fees_known=fees_known,
                    currency=order.currency,
                    basis=basis,
                )
            )
            await self.feed.emit(
                "fill",
                f"Filled: {order.side} {new_qty:g} {order.symbol} at "
                f"{new_price or 0:g} {order.currency}"
                + (
                    f" ({result.filled_qty:g} of {order.qty:g} so far)"
                    if status == "partially_filled"
                    else ""
                )
                + (
                    f" (fees {new_fees:,.2f} {config.currency})"
                    if fees_known
                    else " (fees not reported by the platform)"
                )
                + (
                    " (sent by webhook, not confirmed)"
                    if result.raw.get("unconfirmed")
                    else ""
                )
                + (f"; practice fill from {basis}" if basis else "")
                + ".",
                round_id=order.round_id,
                symbol=order.symbol,
                data={"order": order_view(updated), "fill_qty": new_qty},
            )
            if order.side == "buy":
                await self._decisions.update(
                    order.round_id,
                    status="position_open"
                    if status == "filled"
                    else "partially_filled",
                    data={
                        "prices": {"fill": price},
                        "timing": {"fill": self._clock()},
                        "fill": {"qty": result.filled_qty, "fees": fees},
                    },
                )
                await self._round_status(order.round_id, "traded", "Bought.")
                await self._mark_traded(order.round_id)
                if order.broker != "paper":
                    await self._remember_live_position(
                        updated,
                        new_qty,
                        new_price or price or order.entry_price,
                        new_fees,
                    )
                await self._attach_plan(updated)
            else:
                await self._after_sell(updated, config, sold=new_qty)
        elif status == "rejected":
            await self.feed.emit(
                "error",
                f"{order.symbol} order rejected: {result.note}",
                round_id=order.round_id,
                symbol=order.symbol,
            )

    async def _fill_terms(
        self, order: TradeOrder, result: OrderResult, config: DeskConfig
    ) -> tuple[float | None, float, float]:
        """The fill price in the symbol's own currency, the base currency per
        unit of it, and the fees in the base currency."""
        price = result.fill_price
        fill_currency = str(result.raw.get("currency") or order.currency)
        fee_currency = str(result.raw.get("fee_currency") or fill_currency)
        rate = result.raw.get("fx_rate")
        fx = float(rate) if isinstance(rate, int | float) else order.fx_rate
        fees = result.fees
        if not result.filled_qty:
            return price, fx, fees
        with contextlib.suppress(MarketDataError):
            if price is not None and fill_currency != order.currency:
                price = price * await self._data.fx(fill_currency, order.currency)
            if not isinstance(rate, int | float):
                fx = await self._data.fx(order.currency, config.currency)
            if fees and fee_currency != config.currency:
                fees = fees * await self._data.fx(fee_currency, config.currency)
        return price, fx, fees

    async def _quote_in(
        self, broker: Broker, instrument: Instrument, currency: str
    ) -> Quote | None:
        """The platform's live price (else the market data's), in the
        symbol's own currency so it compares with the decision's."""
        quote = None
        with contextlib.suppress(ServiceError):
            quote = await broker.quote(instrument)
        if quote is None:
            with contextlib.suppress(MarketDataError):
                quote = await self._data.quote(instrument)
        if quote is None or quote.currency == currency:
            return quote
        try:
            rate = await self._data.fx(quote.currency, currency)
        except MarketDataError:
            return None
        return Quote(
            quote.symbol,
            quote.price * rate,
            currency,
            quote.at,
            quote.source,
            quote.bid * rate if quote.bid else None,
            quote.ask * rate if quote.ask else None,
            note=quote.note,
        )

    async def _expire_approvals(self, config: DeskConfig) -> None:
        for order in await self._store.find(
            TradeOrder, where={"status": "awaiting_approval"}
        ):
            if order.due_at and order.due_at < now_ms():
                await self._set(
                    order, status="expired", reason="Nobody approved it in time."
                )
                await self._round_status(order.round_id, "expired", "Approval expired.")
                await self.feed.emit(
                    "order",
                    f"Approval for {order.symbol} expired.",
                    round_id=order.round_id,
                    symbol=order.symbol,
                )

    async def _sync_orders(self, config: DeskConfig) -> None:
        # Practice orders fill on as the market allows (and expire); then
        # every account's orders still working are brought up to date, so a
        # cancellation or expiry is recorded as well as a fill.
        await self._paper(config).tick()
        for order in await self._store.find(TradeOrder):
            if order.status not in {"submitted", "partially_filled"}:
                continue
            broker = self._broker_for(order, config)
            try:
                found = await broker.find(order.client_id)
            except ServiceError as error:
                logger.info("Trading: couldn't check {}: {}", order.symbol, error)
                continue
            if found is not None and (
                found.status != order.status or found.filled_qty != order.filled_qty
            ):
                await self._record(order, found, config)

    async def _watch_positions(self, config: DeskConfig) -> None:
        """Stops and targets the platform doesn't hold itself, on every
        account in use. This runs whether or not the desk is taking new
        trades: stopping, the circuit breaker, and the kill switch never
        leave a position unwatched."""
        for broker in self._brokers_in_use(config):
            await self._watch_on(broker, config)

    async def _watch_on(self, broker: Broker, config: DeskConfig) -> None:
        # The kill switch's "close everything": a holding that couldn't be
        # sold yet (its market was closed, or the sale was refused) is tried
        # again once its market is open, until the owner releases the switch.
        latch = self._state().get("kill")
        closing = isinstance(latch, dict) and bool(latch.get("flatten"))
        for position in await self._store.find(
            TradePosition, where={"broker": broker.id}
        ):
            platform_holds = bool(
                broker.supports_brackets and position.data.get("bracket")
            )
            plan = Plan.read(position.data.get("plan"))
            if not closing and plan is None:
                if platform_holds:
                    continue
                if position.stop_loss is None and position.take_profit is None:
                    continue
            try:
                instrument = parse_symbol(position.symbol)
            except SymbolError:
                continue
            if not self._is_open(instrument.market):
                continue
            if closing:
                await self._exit(position, "the kill switch (close everything)", config)
                continue
            quote = await self._quote_in(broker, instrument, position.currency)
            if quote is None:
                continue
            if plan is not None:
                position, time_up = await self._manage(
                    position, plan, quote.price, move_stop=not platform_holds
                )
                if time_up:
                    await self._exit(position, time_up, config)
                    continue
            if platform_holds:
                continue
            if position.stop_loss is not None and quote.price <= position.stop_loss:
                await self._exit(
                    position, f"the stop-loss ({position.stop_loss:g}) was hit", config
                )
            elif (
                position.take_profit is not None and quote.price >= position.take_profit
            ):
                await self._exit(
                    position,
                    f"the take-profit ({position.take_profit:g}) was reached",
                    config,
                )

    async def _exit(
        self,
        position: TradePosition,
        reason: str,
        config: DeskConfig,
        *,
        round_id: str = "",
        force: bool = False,
    ) -> None:
        """Sell a whole holding. Stops, targets, and the kill switch go
        straight through (a tap could cost more than it saves); a Portfolio
        Manager's sell waits for approval in approve mode."""
        open_sells = [
            order
            for order in await self._store.find(
                TradeOrder, where={"symbol": position.symbol, "side": "sell"}
            )
            if order.status in OPEN_ORDER_STATUSES
        ]
        if open_sells:
            return
        tried = self._exit_tried.get(position.id, 0.0)
        if not force and not round_id and self._clock() - tried < EXIT_RETRY_SECONDS:
            return
        self._exit_tried[position.id] = self._clock()
        if position.data.get("bracket"):
            with contextlib.suppress(SymbolError):
                if not self._is_open(parse_symbol(position.symbol).market):
                    # Nothing can sell until the open: the platform's stop
                    # and target keep guarding it meanwhile.
                    await self.feed.emit(
                        "order",
                        f"{position.symbol}: its market is closed, so the "
                        "platform's stop and target stay in place; the sale "
                        "waits for the open.",
                        symbol=position.symbol,
                    )
                    return
            if not await self._cancel_legs(position, config):
                return
        price = position.avg_price
        with contextlib.suppress(SymbolError, MarketDataError):
            price = (await self._data.quote(parse_symbol(position.symbol))).price
        order = TradeOrder(
            client_id=_client_id(),
            round_id=round_id or position.round_id,
            broker=position.broker,
            mode=config.mode,
            symbol=position.symbol,
            market=position.market,
            side="sell",
            qty=position.qty,
            entry_price=price,
            currency=position.currency,
            status="approved",
            reason=f"Exit: {reason}",
            data={
                "exit": reason,
                "protective": not round_id,
                # How the holding stood when it was sold, for the record
                # (the holding itself is gone once sold).
                "position": {
                    "stop": position.stop_loss,
                    "target": position.take_profit,
                    "plan": position.data.get("plan"),
                    "mae_pct": position.data.get("mae_pct"),
                    "mfe_pct": position.data.get("mfe_pct"),
                },
            },
        )
        await self._store.put(order)
        await self.feed.emit(
            "order",
            f"Selling {position.qty:g} {position.symbol}: {reason}.",
            round_id=order.round_id,
            symbol=position.symbol,
        )
        # Every sell is checked against the account; only a Portfolio
        # Manager's sell waits for a tap in approve mode.
        await self._route(order, config, approved=force or not round_id)

    async def _attach_plan(self, order: TradeOrder) -> None:
        """Keep the plan the desk bought on with the holding, the first time
        it fills: the entry, the first stop, any trailing stop, and the
        holding period (the position manager works from these)."""
        position = await self._store.get(
            TradePosition, f"{order.broker}:{order.symbol}"
        )
        if position is None or isinstance(position.data.get("plan"), dict):
            return
        details = order.data.get("plan")
        details = details if isinstance(details, dict) else {}
        trailing = details.get("trailing_pct")
        days = details.get("holding_days")
        entry = order.fill_price or order.entry_price
        if entry <= 0:
            return
        plan = Plan(
            entry=entry,
            initial_stop=order.stop_loss
            if order.stop_loss is not None and order.stop_loss < entry
            else None,
            trailing_pct=float(trailing) if isinstance(trailing, int | float) else None,
            holding_days=int(days)
            if isinstance(days, int | float) and not isinstance(days, bool)
            else None,
            opened_at=self._clock(),
        )
        await self._store.put(
            position.model_copy(
                update={
                    "data": {
                        **position.data,
                        "plan": plan.view(),
                        "high": entry,
                        "low": entry,
                    },
                    "round_id": position.round_id or order.round_id,
                    "updated_at": now_ms(),
                }
            )
        )

    async def _manage(
        self, position: TradePosition, plan: Plan, price: float, *, move_stop: bool
    ) -> tuple[TradePosition, str]:
        """One look by the position manager: the highest and lowest price
        so far, a stop moved up (never down), and whether the holding
        period is over."""
        high = position.data.get("high")
        low = position.data.get("low")
        step = manage(
            plan,
            price=price,
            stop=position.stop_loss,
            high=float(high) if isinstance(high, int | float) else plan.entry,
            low=float(low) if isinstance(low, int | float) else plan.entry,
            now=self._clock(),
            move_stop=move_stop,
        )
        mae, mfe = step.excursions(plan.entry)
        changed = (
            step.stop != position.stop_loss or step.high != high or step.low != low
        )
        if changed:
            position = position.model_copy(
                update={
                    "stop_loss": step.stop,
                    "data": {
                        **position.data,
                        "high": step.high,
                        "low": step.low,
                        "mae_pct": mae,
                        "mfe_pct": mfe,
                    },
                    "updated_at": now_ms(),
                }
            )
            await self._store.put(position)
        for note in step.notes:
            await self.feed.emit(
                "position",
                f"{position.symbol}: {note}.",
                round_id=position.round_id,
                symbol=position.symbol,
                data={"stop": step.stop, "high": step.high},
            )
        return position, step.exit

    async def _cancel_legs(self, position: TradePosition, config: DeskConfig) -> bool:
        """Before selling a holding whose stop and target sit on the platform
        (a bracket), cancel those two orders: the platform would refuse the
        sell while they hold the shares (or both could fill). False when they
        couldn't be cancelled; the exit is tried again later."""
        try:
            broker = (
                self._paper(config)
                if position.broker == "paper"
                else self._live_broker(position.broker)
            )
            legs = [
                result
                for result in await broker.open_orders()
                if result.symbol == position.symbol and result.raw.get("side") != "buy"
            ]
            for leg in legs:
                await broker.cancel(leg.broker_order_id)
        except (ServiceError, TradingError) as error:
            await self.feed.emit(
                "error",
                f"Couldn't cancel the platform's stop and target for "
                f"{position.symbol} before selling ({error}); FCC tries again "
                "later, and they stay in place meanwhile.",
                symbol=position.symbol,
            )
            return False
        # From here FCC watches the stop and target itself, whatever happens
        # to the sell.
        await self._unbracket(broker, position.symbol)
        return True

    async def _unbracket(self, broker: Broker, symbol: str = "") -> None:
        """The platform no longer holds these positions' stops and targets:
        FCC watches them from now on."""
        for position in await self._store.find(
            TradePosition, where={"broker": broker.id}
        ):
            if position.data.get("bracket") and symbol in {"", position.symbol}:
                await self._store.put(
                    position.model_copy(
                        update={
                            "data": {**position.data, "bracket": False},
                            "updated_at": now_ms(),
                        }
                    )
                )

    async def _after_sell(
        self, order: TradeOrder, config: DeskConfig, *, sold: float
    ) -> None:
        """``sold`` is what this update sold (not the order's running total)."""
        if order.broker != "paper":
            position = await self._store.get(
                TradePosition, f"{order.broker}:{order.symbol}"
            )
            if position is not None:
                left = position.qty - sold
                if left <= 1e-12:
                    await self._store.delete(TradePosition, position.id)
                else:
                    # What is left carries its share of the cost, as on paper.
                    await self._store.put(
                        position.model_copy(
                            update={
                                "qty": left,
                                "cost_base": position.cost_base * left / position.qty,
                                "updated_at": now_ms(),
                            }
                        )
                    )
        still = await self._store.get(TradePosition, f"{order.broker}:{order.symbol}")
        if still is not None:
            return
        buys = [
            other
            for other in await self._store.find(
                TradeOrder,
                where={"symbol": order.symbol, "side": "buy", "broker": order.broker},
            )
            if other.filled_qty > 0
        ]
        opening = max(buys, key=lambda other: other.updated_at, default=None)
        ledger = build_ledger(
            await self._store.find(
                TradeOrder, where={"symbol": order.symbol, "broker": order.broker}
            )
        )
        gain = sum(
            item.gain
            for item in ledger.disposals
            if item.disposed_at >= (opening.updated_at if opening else 0)
        )
        round_record = (
            await self._store.get(TradeRound, opening.round_id)
            if opening and opening.round_id
            else None
        )
        entry = (
            opening.fill_price if opening and opening.fill_price else order.entry_price
        )
        held_days = (
            order.updated_at - (opening.updated_at if opening else order.updated_at)
        ) / DAY_MS
        reason = str(order.data.get("exit") or "the desk sold")
        if opening is not None and opening.round_id:
            await self._decisions.update(
                opening.round_id,
                status="position_closed",
                reason=f"Closed: {reason}",
                pnl=round(gain, 2),
                data={
                    "prices": {"exit_fill": order.fill_price},
                    "timing": {"closed": self._clock()},
                    "result": {
                        "pnl": round(gain, 2),
                        "currency": config.currency,
                        "exit": reason,
                        "entry": entry,
                        "exit_price": order.fill_price,
                        "held_days": round(held_days, 2),
                        **_exit_details(order, opening),
                    },
                },
            )
        setup = ""
        regime = ""
        if round_record is not None:
            setup = str(round_record.data.get("setup") or "")
            regime = str(round_record.data.get("regime") or "")

        async def debrief() -> None:
            await self._debriefs.trade(
                self.config(),
                symbol=order.symbol,
                market=order.market,
                round_record=round_record,
                entry=entry,
                exit_price=order.fill_price or entry,
                gain=gain,
                held_days=held_days,
                reason=reason,
                setup=setup,
                regime=regime,
            )

        self._chores.append(debrief)

    async def _remember_live_position(
        self, order: TradeOrder, qty_new: float, price: float, fees_new: float
    ) -> None:
        """Add one fill (only what is new) to the live position FCC keeps."""
        key = f"{order.broker}:{order.symbol}"
        existing = await self._store.get(TradePosition, key)
        qty = (existing.qty if existing else 0.0) + qty_new
        avg = (
            (existing.avg_price * existing.qty + price * qty_new) / qty
            if existing and qty
            else price
        )
        await self._store.put(
            TradePosition(
                id=key,
                broker=order.broker,
                symbol=order.symbol,
                market=order.market,
                qty=qty,
                avg_price=avg,
                currency=order.currency,
                cost_base=(existing.cost_base if existing else 0.0)
                + qty_new * price * order.fx_rate
                + fees_new,
                stop_loss=order.stop_loss,
                take_profit=order.take_profit,
                round_id=order.round_id,
                data={"bracket": bool(order.data.get("bracket"))},
                opened_at=existing.opened_at if existing else now_ms(),
            )
        )

    # ------------------------------------------------------------ forecasts and debriefs

    async def _scored(self) -> list[TradeForecast]:
        return list(
            await self._store.find(
                TradeForecast,
                where={"status": "scored"},
                order_by="scored_at DESC",
                limit=3000,
            )
        )

    async def _score_forecasts(self, config: DeskConfig) -> None:
        if self._clock() - self._last_score < SCORE_SECONDS:
            return
        self._last_score = self._clock()
        now = now_ms()
        due = [
            forecast
            for forecast in await self._store.find(
                TradeForecast, where={"status": "open"}
            )
            if forecast.due_at <= now
        ]
        if not due:
            return
        scored: list[TradeForecast] = []
        for symbol in sorted({forecast.symbol for forecast in due}):
            try:
                bars = await self._data.bars(parse_symbol(symbol), "1d")
            except SymbolError, MarketDataError, ServiceError:
                bars = []
            for forecast in (f for f in due if f.symbol == symbol):
                found = score(forecast, bars)
                if found is None:
                    if now - forecast.due_at > 5 * DAY_MS:
                        await self._store.put(
                            forecast.model_copy(update={"status": "void"})
                        )
                    continue
                updated = forecast.model_copy(
                    update={
                        "status": "scored",
                        "outcome_move": found.outcome_move,
                        "hit": found.hit,
                        "brier": found.brier,
                        "log_score": found.log_score,
                        "target_first": found.target_first,
                        "scored_at": now,
                    }
                )
                await self._store.put(updated)
                scored.append(updated)
        if scored:
            await self.feed.emit(
                "info",
                f"Scored {len(scored)} forecasts that came due: "
                f"{sum(1 for f in scored if f.hit)} called the direction right.",
            )
            self._chores.append(lambda: self._debriefs.forecasts(self.config(), scored))

    async def _schedule_debriefs(self, config: DeskConfig) -> None:
        state = self._state()
        done = state.get("debriefs")
        done = dict(done) if isinstance(done, dict) else {}
        now = datetime.fromtimestamp(self._clock(), tz=UTC)
        changed = False
        for market in ("asx", "us", "crypto"):
            if not config.markets.get(market):
                continue
            closed = last_close(
                market, now, crypto_hour_utc=config.crypto_debrief_hour_utc
            )
            closed_ms = int(closed.timestamp() * 1000)
            last = done.get(market)
            if isinstance(last, int) and last >= closed_ms:
                continue
            done[market] = closed_ms
            changed = True
            if now - closed > timedelta(hours=DEBRIEF_LATE_HOURS) or last is None:
                continue
            since = int(last) if isinstance(last, int) else closed_ms - DAY_MS
            self._chores.append(self._session_job(market, since))
        weekly_from = state.get("weekly_from")
        if not isinstance(weekly_from, int):
            state["weekly_from"] = now_ms()
            changed = True
        elif now_ms() - weekly_from >= 7 * DAY_MS:
            state["weekly_from"] = now_ms()
            changed = True
            self._chores.append(
                lambda: self._debriefs.weekly(self.config(), since_ms=weekly_from)
            )
        if changed:
            state["debriefs"] = done
            self._save_state(state)

    def _session_job(self, market: str, since: int) -> Callable[[], Awaitable[object]]:
        async def job() -> object:
            config = self.config()
            orders = [
                order
                for order in await self._store.find(
                    TradeOrder, where={"market": market}
                )
                if order.filled_qty > 0 and order.updated_at >= since
            ]
            ledger = build_ledger(orders)
            return await self._debriefs.session(
                config,
                market=market,
                since_ms=since,
                realised=ledger.realised_since(since),
                trades=len(orders),
            )

        return job

    async def debrief_now(self, market: str) -> JsonObject:
        if market not in {"asx", "us", "crypto", "weekly"}:
            raise TradingError("Pick asx, us, crypto, or weekly.")
        if market == "weekly":
            self._chores.append(
                lambda: self._debriefs.weekly(
                    self.config(), since_ms=now_ms() - 7 * DAY_MS
                )
            )
        else:
            self._chores.append(self._session_job(market, now_ms() - DAY_MS))
        if self._round_task is None or self._round_task.done():
            self._round_task = asyncio.ensure_future(self._round())
        return {"queued": market}

    async def accept_suggestion(
        self, debrief_id: str, index: int, *, on_pc: bool
    ) -> JsonObject:
        debrief = await self._store.get(TradeDebrief, debrief_id)
        if debrief is None or debrief.kind != "weekly":
            raise TradingError("That review is gone.")
        found = debrief.data.get("suggestions")
        suggestions = (
            [dict(item) for item in found if isinstance(item, dict)]
            if isinstance(found, list)
            else []
        )
        if not 0 <= index < len(suggestions):
            raise TradingError("That suggestion is gone.")
        item = suggestions[index]
        path = SUGGESTIBLE.get(str(item.get("setting")))
        if path is None:
            raise TradingError("That setting can't be changed from a review.")
        value = item.get("value")
        values: dict[str, object] = (
            {path[0]: value} if len(path) == 1 else {path[0]: {path[1]: value}}
        )
        await self.update_config(values, on_pc=on_pc)
        item["accepted"] = True
        suggestions[index] = item
        data = dict(debrief.data)
        data["suggestions"] = suggestions
        await self._store.put(debrief.model_copy(update={"data": data}))
        return {
            "accepted": True,
            "setting": item.get("setting"),
            "value": item.get("value"),
        }

    # ------------------------------------------------------------ memory

    async def _recall(self, query: str) -> list[str]:
        memory = self._memory()
        found = await memory.recall(MEMORY_AREA, query, limit=4, own_only=True)
        return [entry.text for entry in found]

    async def _remember(self, text: str, tags: list[str]) -> None:
        await self._memory().remember(
            MEMORY_AREA,
            text,
            tags=tags,
            source="trading debrief",
            author="Portfolio Manager",
        )

    async def _mark_traded(self, round_id: str) -> None:
        if not round_id:
            return
        for forecast in await self._store.find(
            TradeForecast, where={"round_id": round_id}
        ):
            if not forecast.traded:
                await self._store.put(forecast.model_copy(update={"traded": True}))

    # ------------------------------------------------------------ platforms

    def _paper(self, config: DeskConfig) -> PaperBroker:
        return PaperBroker(
            self._store,
            self._root / "paper.json",
            self._data,
            currency=config.currency,
            starting_cash=config.paper_cash,
            fee_pct=config.fee_pct,
            min_fee=config.min_fee,
            limits=config.data,
        )

    def _broker(self, config: DeskConfig, market: str = "") -> Broker:
        """The account a market trades on: practice (paper) unless real
        money is switched on, then that market's own account."""
        name = config.broker_for(market)
        if name == "paper":
            return self._paper(config)
        return self._live_broker(name)

    def _brokers_in_use(self, config: DeskConfig) -> list[Broker]:
        """Practice, plus every real account the markets are routed to."""
        found: list[Broker] = [self._paper(config)]
        for name in config.live_brokers():
            with contextlib.suppress(TradingError):
                found.append(self._live_broker(name))
        return found

    def _brokers_with_keys(self, config: DeskConfig) -> list[Broker]:
        """Practice and every platform with saved keys (for the kill switch)."""
        found: list[Broker] = [self._paper(config)]
        for name in self._keys.all():
            spec = BROKERS.get(name)
            if spec is None or spec.factory is None:
                continue
            with contextlib.suppress(TradingError):
                found.append(self._live_broker(name))
        return found

    def _broker_for(self, order: TradeOrder, config: DeskConfig) -> Broker:
        if order.broker == "paper":
            return self._paper(config)
        return self._live_broker(order.broker)

    def _live_broker(self, broker_id: str) -> Broker:
        values = self._keys.values(broker_id)
        fingerprint = json.dumps(values, sort_keys=True)
        cached = self._live.get(broker_id)
        if cached is not None and cached[0] == fingerprint:
            return cached[1]
        try:
            broker = make_broker(
                broker_id, values, data=self._data, transport=self._transport
            )
        except BrokerSetupError as error:
            raise TradingError(str(error)) from error
        self._live[broker_id] = (fingerprint, broker)
        return broker

    async def _positions_of(self, broker: Broker) -> list[Holding]:
        """What the platform holds; for a webhook, what FCC has kept."""
        if getattr(broker, "reports_positions", True):
            return await broker.positions()
        return [
            Holding(record.symbol, record.qty, record.avg_price, record.currency)
            for record in await self._store.find(
                TradePosition, where={"broker": broker.id}
            )
        ]

    async def _holdings(self, broker: Broker) -> list[Holding]:
        try:
            return await self._positions_of(broker)
        except ServiceError as error:
            await self.feed.emit(
                "error", f"Couldn't read holdings on {broker.name}: {error}"
            )
            return []

    async def _position_record(self, broker: Broker, holding: Holding) -> TradePosition:
        found = await self._store.get(TradePosition, f"{broker.id}:{holding.symbol}")
        if found is not None:
            return found
        market = ""
        with contextlib.suppress(SymbolError):
            market = parse_symbol(holding.symbol).market
        return TradePosition(
            id=f"{broker.id}:{holding.symbol}",
            broker=broker.id,
            symbol=holding.symbol,
            market=market,
            qty=holding.qty,
            avg_price=holding.avg_price,
            currency=holding.currency,
        )

    async def _account_picture(
        self, broker: Broker, config: DeskConfig
    ) -> tuple[float, list[Exposure], dict[str, float]]:
        """Equity in the base currency, each holding's value, and quantities."""
        account = await broker.account()
        equity = account.equity * await self._data.fx(account.currency, config.currency)
        exposures: list[Exposure] = []
        held: dict[str, float] = {}
        for holding in await self._positions_of(broker):
            held[holding.symbol] = held.get(holding.symbol, 0.0) + holding.qty
            meme = False
            value = holding.qty * holding.avg_price
            currency = holding.currency
            estimated = True
            with contextlib.suppress(SymbolError, MarketDataError):
                instrument = parse_symbol(holding.symbol)
                meme = instrument.meme
                quote = await self._data.quote(instrument)
                value = holding.qty * quote.price
                currency = quote.currency
                estimated = False
            try:
                value *= await self._data.fx(currency, config.currency)
            except MarketDataError:
                estimated = True
            exposures.append(Exposure(holding.symbol, value, meme, estimated))
        self._mark_equity(broker.id, equity)
        return equity, exposures, held

    def _has_mark(self, broker_id: str) -> bool:
        marks = self._state().get("marks")
        key = f"{broker_id}:{_sydney_day(self._clock())}"
        return isinstance(marks, dict) and key in marks

    def _mark_equity(self, broker_id: str, equity: float) -> None:
        key = f"{broker_id}:{_sydney_day(self._clock())}"
        state = self._state()
        marks = state.get("marks")
        marks = dict(marks) if isinstance(marks, dict) else {}
        if key in marks:
            return
        marks = {
            k: v
            for k, v in marks.items()
            if k >= f"{broker_id}:{_sydney_day(self._clock() - 14 * 86400)}"
            or not k.startswith(broker_id)
        }
        marks[key] = equity
        state["marks"] = marks
        self._save_state(state)

    async def _day(
        self, broker: Broker, config: DeskConfig, equity: float
    ) -> tuple[int, float, dict[str, int]]:
        """Trades today, today's change in percent, and each symbol's last trade."""
        midnight = _sydney_midnight_ms(self._clock())
        trades = 0
        last: dict[str, int] = {}
        for order in await self._store.find(TradeOrder, where={"broker": broker.id}):
            if order.filled_qty <= 0:
                continue
            last[order.symbol] = max(last.get(order.symbol, 0), order.updated_at)
            if order.side == "buy" and order.updated_at >= midnight:
                trades += 1
        marks = self._state().get("marks")
        mark = (
            marks.get(f"{broker.id}:{_sydney_day(self._clock())}")
            if isinstance(marks, dict)
            else None
        )
        change = (
            (equity / mark - 1) * 100
            if isinstance(mark, int | float) and mark > 0
            else 0.0
        )
        return trades, change, last

    # ------------------------------------------------------------ keys

    async def brokers(self) -> list[JsonObject]:
        config = self.config()
        return [
            {
                **spec.view(self._keys.values(spec.id)),
                "verified": bool(config.accounts.get(spec.id)) or spec.id == "paper",
                "ready": spec.id == "paper" or spec.factory is not None,
            }
            for spec in BROKERS.values()
        ]

    async def save_keys(self, broker_id: str, values: Mapping[str, str]) -> JsonObject:
        if broker_id == "paper":
            raise TradingError("The paper account needs no keys.")
        try:
            cleaned = check_values(broker_id, values)
        except BrokerSetupError as error:
            raise TradingError(str(error)) from error
        kept = self._keys.values(broker_id)
        merged = {**kept, **cleaned}
        self._keys.save(broker_id, merged)
        config = self.config()
        if broker_id in config.accounts:
            accounts = dict(config.accounts)
            accounts.pop(broker_id)
            self._save(config.model_copy(update={"accounts": accounts}))
        self._live.pop(broker_id, None)
        await self.feed.emit(
            "info",
            f"Keys saved for {BROKERS[broker_id].name}; verify the account next.",
        )
        return BROKERS[broker_id].view(merged)

    async def remove_keys(self, broker_id: str) -> None:
        self._keys.remove(broker_id)
        self._live.pop(broker_id, None)
        config = self.config()
        accounts = dict(config.accounts)
        accounts.pop(broker_id, None)
        update: dict[str, object] = {"accounts": accounts}
        if config.broker == broker_id and config.live:
            update.update({"mode": "paper", "live_auto_confirmed_at": 0})
        self._save(config.model_copy(update=update))

    async def test_broker(self, broker_id: str) -> JsonObject:
        """Connect and read the account (shown masked) for the owner to check."""
        config = self.config()
        broker = (
            self._paper(config)
            if broker_id == "paper"
            else self._live_broker(broker_id)
        )
        try:
            account = await broker.account()
        except ServiceError as error:
            raise TradingError(f"{broker.name}: {error}") from error
        return {"account": account.view(), "broker": broker.name, "live": broker.live}

    async def confirm_account(self, broker_id: str, fingerprint: str) -> JsonObject:
        """The owner says the account shown is theirs: remember it, so every
        order checks it's still the same account."""
        details = await self.test_broker(broker_id)
        account = details["account"]
        if not isinstance(account, dict) or account.get("fingerprint") != fingerprint:
            raise TradingError("The account changed since it was shown; test again.")
        config = self.config()
        accounts = dict(config.accounts)
        accounts[broker_id] = fingerprint
        self._save(config.model_copy(update={"accounts": accounts}))
        await self.feed.emit("info", f"Account verified on {details['broker']}.")
        return details

    # ------------------------------------------------------------ views

    async def status(self) -> JsonObject:
        config = self.config()
        account: JsonObject = {}
        try:
            broker = self._broker(config)
            cached = self._account_cache
            if (
                cached is not None
                and cached[1] == broker.id
                and self._clock() - cached[0] < ACCOUNT_SECONDS
            ):
                account = cached[2]
            else:
                equity, exposures, _ = await self._account_picture(broker, config)
                raw = await broker.account()
                trades, day_change, _ = await self._day(broker, config, equity)
                account = {
                    **raw.view(),
                    "equity_base": round(equity, 2),
                    "day_change_pct": round(day_change, 3),
                    "trades_today": trades,
                    "invested": round(sum(item.value for item in exposures), 2),
                }
                self._account_cache = (self._clock(), broker.id, account)
            broker_name = broker.name
        except (TradingError, ServiceError, MarketDataError) as error:
            account = {"error": str(error)}
            broker_name = _broker_name(config)
        orders = await self._store.find(
            TradeOrder, order_by="updated_at DESC", limit=200
        )
        waiting = [
            order_view(order)
            for order in orders
            if order.status
            in {"cooling", "awaiting_approval", "submitting", "submitted"}
        ]
        scored = await self._scored()
        seat_records = records(scored)
        now = datetime.fromtimestamp(self._clock(), tz=UTC)
        state = self._state()
        killed = state.get("kill")
        breaker = Trip.read(state.get("breaker"))
        return {
            "running": config.running,
            "live": config.live,
            "alert_only": config.alert_only,
            "kill": dict(killed) if isinstance(killed, dict) else None,
            "breaker": breaker.view() if breaker is not None else None,
            "unmatched": list(self._unmatched.values()),
            "heartbeat_age_s": round(self._clock() - self._heartbeat, 1)
            if self._heartbeat
            else None,
            "lease": self._lease_note,
            "routes": dict(config.routes),
            "looping": self._loop_task is not None and not self._loop_task.done(),
            "busy": self._round_task is not None and not self._round_task.done(),
            "activity": dict(self._activity),
            "mode": config.mode,
            "mode_label": _mode_label(config),
            "broker": config.broker,
            "broker_name": broker_name,
            "currency": config.currency,
            "account": account,
            "orders": waiting,
            "seats": [
                {
                    **seat.model_dump(),
                    "record": seat_records[seat.seat].view(),
                }
                for seat in config.seats
            ],
            "sessions": {
                market: session(market, now).view()
                for market in ("asx", "us", "crypto")
            },
            "next_scan_in": max(
                0, int(config.scan_minutes * 60 - (self._clock() - self._last_scan))
            )
            if config.running
            else None,
            "queued": list(self._requests),
            "data_health": self._data.health(),
            "live_auto_ready": bool(config.live_auto_confirmed_at),
            "verified": dict(config.accounts),
        }

    def pulse(self) -> JsonObject:
        """A light status for the Ops page and the phone (no network)."""
        config = self.config()
        return {
            "running": config.running,
            "mode": config.mode,
            "busy": self._round_task is not None and not self._round_task.done(),
            "activity": dict(self._activity),
        }

    async def events(self, after: int = 0) -> list[JsonObject]:
        return [event_view(event) for event in await self.feed.since(after)]

    async def orders(self, limit: int = 100) -> list[JsonObject]:
        return [
            order_view(order)
            for order in await self._store.find(
                TradeOrder, order_by="created_at DESC", limit=limit
            )
        ]

    async def positions(self) -> list[JsonObject]:
        config = self.config()
        broker = self._broker(config)
        found: list[JsonObject] = []
        for holding in await self._holdings(broker):
            record = await self._store.get(
                TradePosition, f"{broker.id}:{holding.symbol}"
            )
            price = None
            with contextlib.suppress(SymbolError, MarketDataError):
                price = (await self._data.quote(parse_symbol(holding.symbol))).price
            found.append(
                {
                    "symbol": holding.symbol,
                    "qty": holding.qty,
                    "avg_price": holding.avg_price,
                    "currency": holding.currency,
                    "price": price,
                    "change_pct": (price / holding.avg_price - 1) * 100
                    if price and holding.avg_price
                    else None,
                    "stop_loss": record.stop_loss if record else None,
                    "take_profit": record.take_profit if record else None,
                    "cost_base": record.cost_base if record else None,
                }
            )
        return found

    async def decisions(
        self,
        *,
        symbol: str = "",
        status: str = "",
        text: str = "",
        since_ms: int | None = None,
        until_ms: int | None = None,
        limit: int = 100,
    ) -> list[JsonObject]:
        """Decision records, newest first, by symbol, status, words, dates."""
        found = await self._decisions.search(
            symbol=symbol,
            status=status,
            text=text,
            since_ms=since_ms,
            until_ms=until_ms,
            limit=limit,
        )
        return [_decision_summary(item) for item in found]

    async def decision(self, decision_id: str) -> JsonObject:
        found = await self._store.get(TradeDecision, decision_id)
        if found is None:
            raise TradingError("No such decision.")
        return decision_view(found)

    async def audit_trail(
        self,
        *,
        kind: str = "",
        symbol: str = "",
        text: str = "",
        since_ms: int | None = None,
        until_ms: int | None = None,
        limit: int = 200,
    ) -> list[JsonObject]:
        found = await self._decisions.trail(
            kind=kind,
            symbol=symbol,
            text=text,
            since_ms=since_ms,
            until_ms=until_ms,
            limit=limit,
        )
        return [audit_view(item) for item in found]

    async def audit_csv(
        self,
        *,
        kind: str = "",
        symbol: str = "",
        text: str = "",
        since_ms: int | None = None,
        until_ms: int | None = None,
    ) -> str:
        """The audit trail as CSV (one line per entry), for keeping or
        checking elsewhere."""
        rows = await self._decisions.trail(
            kind=kind,
            symbol=symbol,
            text=text,
            since_ms=since_ms,
            until_ms=until_ms,
            limit=5000,
        )
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "time_utc",
                "kind",
                "symbol",
                "round_id",
                "order_id",
                "text",
                "config_version",
                "system_version",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    datetime.fromtimestamp(row.created_at / 1000, tz=UTC).isoformat(
                        timespec="seconds"
                    ),
                    row.kind,
                    row.symbol,
                    row.round_id,
                    row.order_id,
                    row.text,
                    row.config_version,
                    row.system_version,
                ]
            )
        return buffer.getvalue()

    async def rounds(self, limit: int = 30) -> list[JsonObject]:
        return [
            {
                "id": item.id,
                "symbol": item.symbol,
                "market": item.market,
                "status": item.status,
                "consensus": item.consensus,
                "note": item.note,
                "depth": item.depth,
                "created_at": item.created_at,
                "updated_at": item.updated_at,
            }
            for item in await self._store.find(
                TradeRound, order_by="created_at DESC", limit=limit
            )
        ]

    async def round(self, round_id: str) -> JsonObject:
        found = await self._store.get(TradeRound, round_id)
        if found is None:
            raise TradingError("That round is gone.")
        return {
            **found.model_dump(),
            "events": [
                event_view(event) for event in await self.feed.for_round(round_id)
            ],
            "forecasts": [
                f.model_dump()
                for f in await self._store.find(
                    TradeForecast, where={"round_id": round_id}
                )
            ],
        }

    async def forecasts(self, limit: int = 200) -> list[JsonObject]:
        return [
            f.model_dump()
            for f in await self._store.find(
                TradeForecast, order_by="created_at DESC", limit=limit
            )
        ]

    async def seat_stats(self) -> JsonObject:
        scored = await self._scored()
        config = self.config()
        by_market = {
            market: records(scored, market=market) for market in ("asx", "us", "crypto")
        }
        return {
            "seats": [
                {
                    "seat": seat.seat,
                    "name": seat.name,
                    "all": records(scored)[seat.seat].view(),
                    "markets": {
                        market: found[seat.seat].view()
                        for market, found in by_market.items()
                    },
                }
                for seat in config.seats
            ]
        }

    async def debriefs(self, limit: int = 50) -> list[JsonObject]:
        return [
            item.model_dump()
            for item in await self._store.find(
                TradeDebrief, order_by="created_at DESC", limit=limit
            )
        ]

    async def export_csv(self) -> str:
        config = self.config()
        return tax_csv(
            build_ledger(await self._store.find(TradeOrder)), currency=config.currency
        )

    async def summary(self) -> JsonObject:
        ledger = build_ledger(await self._store.find(TradeOrder))
        return ledger.view()

    # ------------------------------------------------------------ helpers

    async def _problem(self, text: str) -> None:
        """Report a problem, but the same one only every ten minutes."""
        last = self._problems.get(text, 0.0)
        if self._clock() - last < PROBLEM_REPEAT_SECONDS:
            return
        self._problems[text] = self._clock()
        logger.warning("Trading: {}", text)
        await self.feed.emit("error", text)

    async def _set(self, order: TradeOrder, **changes: object) -> TradeOrder:
        updated = order.model_copy(update={**changes, "updated_at": now_ms()})
        await self._store.put(updated)
        return updated

    async def _round_status(self, round_id: str, status: str, note: str) -> None:
        if not round_id:
            return
        found = await self._store.get(TradeRound, round_id)
        if found is not None:
            await self._close_round(found, status, note)


def _request(order: TradeOrder, instrument: Instrument) -> OrderRequest:
    return OrderRequest(
        client_id=order.client_id,
        instrument=instrument,
        side=order.side,
        qty=order.qty,
        order_type=order.order_type,
        limit_price=order.limit_price,
        stop_loss=order.stop_loss,
        take_profit=order.take_profit,
        price_currency=order.currency,
    )


def order_view(order: TradeOrder) -> JsonObject:
    view = order.model_dump()
    view["seconds_left"] = (
        max(0, (order.due_at - now_ms()) // 1000) if order.due_at else None
    )
    return view


def _client_id() -> str:
    return f"fcc-{uuid.uuid4().hex[:20]}"


def _float(value: object, default: float) -> float:
    return float(value) if isinstance(value, int | float) else default


def _merge(base: dict[str, object], changes: Mapping[str, object]) -> dict[str, object]:
    merged = dict(base)
    for key, value in changes.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, Mapping):
            merged[key] = _merge(dict(current), value)
        else:
            merged[key] = value
    return merged


def _mode_label(config: DeskConfig) -> str:
    return {
        "paper": "paper",
        "live_approve": "live (you approve each order)",
        "live_auto": "live (automatic within limits)",
    }.get(config.mode, config.mode)


def _broker_name(config: DeskConfig) -> str:
    spec = BROKERS.get("paper" if config.mode == "paper" else config.broker)
    return spec.name if spec is not None else config.broker


def round_seconds(config: DeskConfig, debates: int) -> float:
    """How long one round may run: longer debates get more time."""
    extra = max(0, config.debate_rounds - 2) * EXTRA_DEBATE_ROUND_SECONDS
    return ROUND_SECONDS + extra * max(1, debates)


def _round_trip_pct(config: DeskConfig, quality: QualityReport) -> float:
    """Fees both ways plus the tightest bid/ask spread seen (0.1% when no
    source gave one), in % of the position: the simulations' costs."""
    spreads = [
        snap.spread_pct for snap in quality.snapshots if snap.spread_pct is not None
    ]
    return round(2 * config.fee_pct + (min(spreads) if spreads else 0.1), 4)


def _exit_details(order: TradeOrder, opening: TradeOrder | None) -> JsonObject:
    """What the record keeps about a sale: the plan against what happened,
    the price expected and the one filled, the costs, and how far the trade
    went for and against it while held."""
    held = order.data.get("position")
    held = held if isinstance(held, dict) else {}
    plan = held.get("plan")
    plan = plan if isinstance(plan, dict) else {}
    opened = opening.data.get("plan") if opening is not None else None
    opened = opened if isinstance(opened, dict) else {}
    expected = order.entry_price
    slippage = (
        round((1 - order.fill_price / expected) * 100, 3)
        if order.fill_price and expected
        else None
    )
    return {
        "planned_stop": plan.get("initial_stop"),
        "planned_target": held.get("target"),
        "stop_at_exit": held.get("stop"),
        "planned_holding_days": plan.get("holding_days"),
        "expected_exit_price": expected,
        "exit_slippage_pct": slippage,
        "fees": round(order.fees + (opening.fees if opening is not None else 0.0), 2),
        "mae_pct": held.get("mae_pct"),
        "mfe_pct": held.get("mfe_pct"),
        "thesis": opened.get("thesis", ""),
        "invalidation": opened.get("invalidation", []),
    }


def _sent(order: TradeOrder) -> Sent:
    sent_at = order.data.get("sent_at")
    symbol = order.symbol
    with contextlib.suppress(SymbolError):
        symbol = parse_symbol(order.symbol).symbol
    return Sent(
        client_id=order.client_id,
        symbol=symbol,
        side=order.side,
        qty=order.qty,
        at=float(sent_at)
        if isinstance(sent_at, int | float)
        else order.updated_at / 1000,
        broker_order_id=order.broker_order_id,
    )


def _new_fill_price(
    before_qty: float,
    before_price: float | None,
    total_qty: float,
    total_price: float | None,
) -> float | None:
    """The price of just the new part of a fill, from the running totals the
    platform reports (its average price over everything filled so far)."""
    if total_price is None:
        return None
    new_qty = total_qty - before_qty
    if before_qty <= 0 or before_price is None or new_qty <= 0:
        return total_price
    found = (total_qty * total_price - before_qty * before_price) / new_qty
    return found if found > 0 else total_price


def _decision_summary(record: TradeDecision) -> JsonObject:
    decision = record.data.get("final_decision")
    return {
        "id": record.id,
        "round_id": record.round_id,
        "symbol": record.symbol,
        "market": record.market,
        "mode": record.mode,
        "status": record.status,
        "reason": record.reason,
        "action": decision.get("action") if isinstance(decision, dict) else None,
        "order_id": record.order_id,
        "order_submitted": record.order_submitted,
        "pnl": record.pnl,
        "pack_id": record.pack_id,
        "config_version": record.config_version,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def _decision_data(
    briefing: Briefing,
    quality: QualityReport,
    evidence: JsonObject,
    result: DebateResult,
    now: float,
) -> JsonObject:
    """What the decision record keeps once the debate is over."""
    pack = result.final_pack
    facts: list[JsonObject] = []
    calculations: list[JsonObject] = []
    if pack is not None:
        for item in pack.items:
            row: JsonObject = {
                "ref": item.ref,
                "label": item.label,
                "value": item.value,
                "unit": item.unit,
                "source": item.source,
                "as_of": item.as_of,
                "status": item.status,
            }
            (calculations if item.kind == "calculation" else facts).append(row)
        facts.extend(
            {
                "ref": story.ref,
                "label": "news",
                "value": story.headline,
                "source": story.source,
                "as_of": story.published_at,
                "status": story.status,
            }
            for story in pack.news
        )
    sources = sorted(
        {snap.provider for snap in quality.snapshots}
        | {story.source for story in quality.news if story.usable}
    )
    models = {
        str(call.get("seat")): call.get("model_name")
        for call in result.calls
        if call.get("model_name")
    }
    return {
        "evidence": {
            "first_id": evidence.get("id"),
            "final_id": result.pack_id,
            "digest": evidence.get("digest"),
        },
        "data_sources": list(sources),
        "data_timestamps": {
            snap.provider: snap.timestamp for snap in quality.snapshots
        },
        "facts": facts,
        "calculations": calculations,
        "quality": {
            "score": quality.score,
            "ok": quality.ok,
            "summary": quality.summary(),
        },
        "conflicts": [item.view() for item in quality.conflicts],
        "seat_outputs": {
            "closing": {
                str(seat): view.model_dump() for seat, view in result.closing.items()
            },
            "plan": result.plan.model_dump() if result.plan is not None else None,
            "info_test": result.info_test.view() if result.info_test else None,
            "review": result.review.model_dump() if result.review else None,
            "challenge": result.challenge.model_dump() if result.challenge else None,
            "calls": result.calls,
            "abstained": sorted(set(result.abstained)),
        },
        "models": models,
        "prompt_version": PROMPT_VERSION,
        "final_decision": result.decision.model_dump()
        if result.decision is not None
        else None,
        "blocked": result.blocked,
        "timing": {
            "pack_created": evidence.get("cutoff"),
            "seat_responses": [
                {
                    "stage": call.get("stage"),
                    "seat": call.get("seat"),
                    "at": call.get("at"),
                }
                for call in result.calls
            ],
            "final_decision": now,
        },
        "prices": {"analysis": briefing.price},
    }


def _limits_text(config: DeskConfig) -> str:
    risk = config.risk
    return (
        f"RISK RULES (plain code enforces these): risk {risk.risk_per_trade_pct:g}% of "
        f"equity per trade at the stop; at most {risk.max_position_pct:g}% in one "
        f"position ({risk.meme_position_pct:g}% for a meme coin); orders up to "
        f"{risk.max_order_value:,.0f} {config.currency}; a stop-loss is required; "
        f"minimum reward for risk {config.assessment.min_reward_risk:g} to 1."
    )


def _sydney_day(seconds: float) -> str:
    when = datetime.fromtimestamp(seconds, tz=UTC)
    return (when + timedelta(hours=sydney_offset(when))).strftime("%Y-%m-%d")


def _sydney_midnight_ms(seconds: float) -> int:
    when = datetime.fromtimestamp(seconds, tz=UTC)
    offset = sydney_offset(when)
    local = when + timedelta(hours=offset)
    midnight_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return int((midnight_local - timedelta(hours=offset)).timestamp() * 1000)


def _quote_age_limit(
    config: DeskConfig, instrument: Instrument, *, live: bool
) -> float:
    """How old the order-time price may be. Paper may fall back to delayed
    market data (when allowed), so its limit includes the published delay."""
    limits = config.data
    base = (
        limits.crypto_quote_age_s
        if instrument.market == "crypto"
        else limits.share_quote_age_s
    )
    if live or not limits.allow_delayed_in_paper:
        return base
    delay = PROVIDER_DELAY_MINUTES.get(("Yahoo Finance", instrument.market), 0)
    return base + delay * 60 + (limits.delayed_grace_s if delay else 0.0)
