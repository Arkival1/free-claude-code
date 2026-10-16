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
import json
import os
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from loguru import logger

from free_claude_code.core.json_types import JsonObject

from ..connectors import ConnectorStore
from ..memory import MemoryService
from ..models import now_ms
from ..resilience import ServiceError, Web, submit_once
from ..search import StudioSearch
from ..store import StudioStore
from ..workers import WorkerPool
from .assessment import Holdings, recheck, resize, risk_report, risk_round
from .briefing import Briefing, build_briefing
from .brokers.base import Broker, Holding, OrderRequest, OrderResult
from .brokers.catalog import ensure_catalog
from .brokers.paper import PaperBroker
from .brokers.registry import BROKERS, BrokerSetupError, check_values, make_broker
from .config import LIVE_AUTO_PHRASE, DeskConfig, DeskConfigStore
from .data import (
    DATA_LIMITS,
    MarketData,
    MarketDataError,
    Quote,
    quote_snapshot,
    sizing_snapshot,
)
from .debate import Debate, DebateResult
from .debrief import SUGGESTIBLE, Debriefs
from .evidence import EvidencePack, PortfolioFacts, build_pack
from .forecasts import due_at, records, score
from .indicators import true_ranges
from .information import PROVIDER_DELAY_MINUTES, NewsItem, QuoteSnapshot
from .instruments import Instrument, SymbolError, parse_symbol, universe
from .ledger import build_ledger, tax_csv
from .log import Feed, event_view
from .news import judge
from .precheck import pre_trade_check
from .providers.news import NewsFeeds
from .quality import QualityCheck, QualityReport, assess, failed_report, profile_of
from .records import (
    OPEN_ORDER_STATUSES,
    TradeDebrief,
    TradeForecast,
    TradeOrder,
    TradePosition,
    TradeRound,
)
from .research import DeskResearch, ReadPage
from .risk import Exposure, risk_gate, size_position
from .scanner import Candidate, scan
from .seats import Decision, Forecast, Think
from .sessions import last_close, session, sydney_offset

TICK_SECONDS = 10.0
ASKED = "asked by you"
"""The tag on a debate the owner asked for."""
SCORE_SECONDS = 300.0
ACCOUNT_SECONDS = 30.0
DEBRIEF_LATE_HOURS = 12.0
"""A session debrief more than this late (Studio was closed) is skipped."""
ROUND_SECONDS = 45 * 60.0
"""A round still going after this long is stopped."""
MEMORY_AREA = "trading:desk"
EXIT_RETRY_SECONDS = 600.0
"""A stop or target exit the checks blocked is tried again after this."""
PROBLEM_REPEAT_SECONDS = 600.0
"""The same problem goes to the feed at most this often."""
DAY_MS = 86_400_000


class TradingError(ValueError):
    """Something asked of the desk can't be done; the message says why."""


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
        self._research = DeskResearch(search=search, read_page=read_page)
        self._news = NewsFeeds(self._web, wall=clock)
        self._debriefs = Debriefs(
            store=store, feed=self.feed, think=think, remember=self._remember
        )
        self._loop_task: asyncio.Task[None] | None = None
        self._round_task: asyncio.Task[None] | None = None
        self._requests: list[str] = []
        self._chores: list[Callable[[], Awaitable[object]]] = []
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
        if wanted.mode != current.mode or wanted.broker != current.broker:
            wanted = self._check_mode(current, wanted, on_pc=on_pc, confirm=confirm)
        self._save(wanted)
        changed = sorted(key for key in values if key not in {"accounts", "running"})
        await self.feed.emit(
            "info", f"Settings changed: {', '.join(changed) or 'none'}."
        )
        return wanted

    def _check_mode(
        self, current: DeskConfig, wanted: DeskConfig, *, on_pc: bool, confirm: str
    ) -> DeskConfig:
        if wanted.mode == "paper":
            return wanted.model_copy(update={"live_auto_confirmed_at": 0})
        if not on_pc:
            raise TradingError("Live trading can only be switched on from the PC.")
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
        self._save(config.model_copy(update={"running": True}))
        self._ensure_loop()
        await self.feed.emit(
            "info",
            f"Desk started in {_mode_label(config)} mode on {_broker_name(config)}.",
        )
        return await self.status()

    async def stop(self) -> JsonObject:
        config = self.config()
        self._save(config.model_copy(update={"running": False}))
        await self._cancel_tasks()
        await self.feed.emit("info", "Desk stopped. Nothing new will be traded.")
        return await self.status()

    async def kill(self, *, flatten: bool = False) -> JsonObject:
        """Stop everything: the loop, every waiting order, and (with flatten)
        sell every holding at market."""
        await self.stop()
        config = self.config()
        cancelled = 0
        for order in await self._store.find(TradeOrder):
            if order.status in {"cooling", "awaiting_approval", "approved"}:
                await self._set(order, status="cancelled", reason="Kill switch.")
                cancelled += 1
        broker = self._broker(config)
        try:
            for result in await broker.open_orders():
                with contextlib.suppress(ServiceError):
                    await broker.cancel(result.broker_order_id)
                    cancelled += 1
        except ServiceError as error:
            await self.feed.emit(
                "error", f"Couldn't list open orders to cancel: {error}"
            )
        sold = 0
        if flatten:
            for holding in await self._holdings(broker):
                position = await self._position_record(broker, holding)
                await self._exit(position, "the kill switch", config, force=True)
                sold += 1
        await self.feed.emit(
            "info",
            f"Kill switch: {cancelled} orders cancelled"
            + (f", {sold} holdings sold" if flatten else "")
            + ".",
        )
        return await self.status()

    async def resume(self) -> None:
        """At start-up: carry on paper trading; never resume live by itself."""
        config = self.config()
        if not config.running:
            return
        if config.live:
            self._save(config.model_copy(update={"running": False}))
            await self.feed.emit(
                "info",
                "Live trading was paused when FCC restarted. Press Start to carry on.",
            )
            return
        await self._reconcile()
        self._ensure_loop()
        await self.feed.emit("info", "Paper trading resumed after a restart.")

    async def close(self) -> None:
        await self._cancel_tasks()
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
        """Orders cut off mid-send when FCC closed: ask the platform what
        happened to each, by its own id."""
        config = self.config()
        for order in await self._store.find(TradeOrder, where={"status": "submitting"}):
            broker = self._broker_for(order, config)
            try:
                found = await broker.find(order.client_id)
            except ServiceError as error:
                await self.feed.emit(
                    "error", f"Couldn't check {order.symbol} order: {error}"
                )
                continue
            if found is None:
                await self._set(
                    order, status="failed", reason="Never reached the platform."
                )
            else:
                await self._record(order, found, config)

    # ------------------------------------------------------------ the loop

    async def _loop(self) -> None:
        while True:
            try:
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
            self._finish_cooling,
            self._expire_approvals,
            self._sync_orders,
            self._watch_positions,
            self._score_forecasts,
            self._schedule_debriefs,
        ):
            try:
                await step(config)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.opt(exception=True).debug("Trading desk step failed")
                await self._problem(
                    f"{step.__name__.strip('_').replace('_', ' ')}: {error}"
                )
        now = self._clock()
        due = now - self._last_scan >= config.scan_minutes * 60
        free = self._round_task is None or self._round_task.done()
        if free and (self._requests or self._chores or (config.running and due)):
            if due and config.running:
                self._last_scan = now
            self._round_task = asyncio.ensure_future(self._round())

    async def _round(self) -> None:
        """One round: chores first (debriefs), then requests, then a scan."""
        try:
            async with asyncio.timeout(ROUND_SECONDS):
                while self._chores:
                    chore = self._chores.pop(0)
                    try:
                        await chore()
                    except asyncio.CancelledError:
                        raise
                    except Exception as error:
                        logger.exception("Trading debrief failed")
                        await self.feed.emit("error", f"A debrief failed: {error}")
                config = self.config()
                if self._requests:
                    symbol = self._requests.pop(0)
                    await self._debate_symbol(symbol, config)
                elif config.running:
                    await self._scan_and_debate(config)
        except TimeoutError:
            await self.feed.emit("error", "A round ran too long and was stopped.")
        finally:
            self._activity = {}

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

    async def _scan_and_debate(self, config: DeskConfig) -> None:
        broker = self._broker(config)
        markets = broker.markets()
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
        holdings = await self._holdings(broker)
        held = {holding.symbol for holding in holdings}
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

    async def _debate_symbol(self, symbol: str, config: DeskConfig) -> None:
        try:
            instrument = parse_symbol(symbol)
        except SymbolError as error:
            await self.feed.emit("error", str(error))
            return
        broker = self._broker(config)
        held = {holding.symbol for holding in await self._holdings(broker)}
        await self._consider(
            Candidate(instrument, 0.0, (ASKED,), held=instrument.symbol in held),
            config,
        )

    async def _consider(self, candidate: Candidate, config: DeskConfig) -> None:
        instrument = candidate.instrument
        record = TradeRound(
            symbol=instrument.symbol, market=instrument.market, depth=config.depth
        )
        await self._store.put(record)
        self._activity = {
            "stage": "Briefing",
            "symbol": instrument.symbol,
            "seat": 0,
            "round_id": record.id,
            "since": now_ms(),
        }
        broker = self._broker(config)
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
        )
        result = await debate.run()
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
        }
        record = record.model_copy(update={"consensus": result.consensus, "data": data})
        decision = result.decision
        if decision is None or decision.action == "hold":
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
        await self._buy(record, briefing, result, decision, config, quality)

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
        broker = self._broker(config)
        live = config.mode != "paper" and broker.live
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
        broker = self._broker(config)
        portfolio = await self._portfolio_facts(broker, config)
        fx: tuple[str, float, float | None] | None = None
        if instrument.currency and instrument.currency != config.currency:
            with contextlib.suppress(MarketDataError):
                rate = await self._data.fx(instrument.currency, config.currency)
                fx = (f"{config.currency} per {instrument.currency}", rate, None)
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
            day_change_pct=day_change,
        )

    async def _close_round(self, record: TradeRound, status: str, note: str) -> None:
        await self._store.put(
            record.model_copy(
                update={"status": status, "note": note[:500], "updated_at": now_ms()}
            )
        )

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
        broker = self._broker(config)
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
        cooling = (
            config.assessment.cooling_crypto_minutes
            if instrument.market in {"crypto", "dex"}
            else config.assessment.cooling_stocks_minutes
        )
        assessment.cooling_minutes = cooling
        data = dict(record.data)
        data["assessment"] = assessment.view()
        record = record.model_copy(update={"data": data})
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
                "assessment": assessment.view(),
                "consensus": result.consensus,
                "confidence": decision.confidence,
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
        for order in await self._store.find(TradeOrder, where={"status": "cooling"}):
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
        order = await self._set(order, status="submitting")
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
            await self.feed.emit(
                "fill",
                f"Filled: {order.side} {result.filled_qty:g} {order.symbol} at "
                f"{price or 0:g} {order.currency} (fees {fees:,.2f} {config.currency})"
                + (
                    " (sent by webhook, not confirmed)"
                    if result.raw.get("unconfirmed")
                    else ""
                )
                + ".",
                round_id=order.round_id,
                symbol=order.symbol,
                data={"order": order_view(updated)},
            )
            if order.side == "buy":
                await self._round_status(order.round_id, "traded", "Bought.")
                await self._mark_traded(order.round_id)
                if order.broker != "paper":
                    await self._remember_live_position(updated)
            else:
                await self._after_sell(updated, config)
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
        paper = self._paper(config)
        for result in await paper.tick():
            order = await self._order_by_client(result.client_id)
            if order is not None:
                await self._record(order, result, config)
        for order in await self._store.find(TradeOrder):
            if (
                order.status not in {"submitted", "partially_filled"}
                or order.broker == "paper"
            ):
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
        """Stops and targets the platform doesn't hold itself."""
        broker = self._broker(config)
        if not config.running:
            return
        for position in await self._store.find(
            TradePosition, where={"broker": broker.id}
        ):
            if broker.supports_brackets and position.data.get("bracket"):
                continue
            if position.stop_loss is None and position.take_profit is None:
                continue
            try:
                instrument = parse_symbol(position.symbol)
            except SymbolError:
                continue
            if not self._is_open(instrument.market):
                continue
            quote = await self._quote_in(broker, instrument, position.currency)
            if quote is None:
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
            data={"exit": reason, "protective": not round_id},
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

    async def _after_sell(self, order: TradeOrder, config: DeskConfig) -> None:
        if order.broker != "paper":
            position = await self._store.get(
                TradePosition, f"{order.broker}:{order.symbol}"
            )
            if position is not None:
                left = position.qty - order.filled_qty
                if left <= 1e-12:
                    await self._store.delete(TradePosition, position.id)
                else:
                    await self._store.put(
                        position.model_copy(
                            update={"qty": left, "updated_at": now_ms()}
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

    async def _remember_live_position(self, order: TradeOrder) -> None:
        key = f"{order.broker}:{order.symbol}"
        existing = await self._store.get(TradePosition, key)
        qty = (existing.qty if existing else 0.0) + order.filled_qty
        price = order.fill_price or order.entry_price
        avg = (
            (existing.avg_price * existing.qty + price * order.filled_qty) / qty
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
                + order.filled_qty * price * order.fx_rate
                + order.fees,
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
        )

    def _broker(self, config: DeskConfig) -> Broker:
        if config.mode == "paper" or config.broker == "paper":
            return self._paper(config)
        return self._live_broker(config.broker)

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
            with contextlib.suppress(SymbolError, MarketDataError):
                instrument = parse_symbol(holding.symbol)
                meme = instrument.meme
                quote = await self._data.quote(instrument)
                value = holding.qty * quote.price
                currency = quote.currency
            with contextlib.suppress(MarketDataError):
                value *= await self._data.fx(currency, config.currency)
            exposures.append(Exposure(holding.symbol, value, meme))
        self._mark_equity(broker.id, equity)
        return equity, exposures, held

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
        return {
            "running": config.running,
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

    async def _order_by_client(self, client_id: str) -> TradeOrder | None:
        found = await self._store.find(
            TradeOrder, where={"client_id": client_id}, limit=1
        )
        return found[0] if found else None

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
