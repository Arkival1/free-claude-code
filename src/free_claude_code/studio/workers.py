"""Background work that stays light on the PC.

Each kind of background job runs in its own lane with a small limit: web
searches and page reads, market data, model calls on this PC (one at a time,
so the graphics card isn't asked to juggle models), model calls to a server,
and number crunching in a thread. A busy loop never floods the network, the
graphics card, or the processor. Low-priority jobs wait while the processor is
busy with something the owner is doing, but never for long. Low-power mode
halves every lane. The Ops page shows what each lane is doing.
"""

import asyncio
import itertools
import time
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field

import anyio.to_thread

from free_claude_code.core.json_types import JsonObject

from .system_monitor import CpuWindow

DEFAULT_LANES: Mapping[str, int] = {
    "web": 4,
    "data": 4,
    "model_local": 1,
    "model_server": 3,
    "cpu": 1,
}
QUIET_CHECK_SECONDS = 2.0
"""How long a low-priority job waits before looking at the processor again."""
MAX_QUIET_WAIT_SECONDS = 30.0
"""A low-priority job never waits longer than this for a quiet processor."""
RECENT_JOBS = 50


@dataclass(slots=True)
class _Lane:
    limit: int
    running: int = 0
    done: int = 0
    failed: int = 0
    total_ms: float = 0.0
    waiters: list[asyncio.Future[None]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _Job:
    lane: str
    label: str
    started: float


class WorkerPool:
    """Lanes with small limits, a quiet-processor wait, and live stats."""

    def __init__(
        self,
        *,
        lanes: Mapping[str, int] = DEFAULT_LANES,
        low_power: Callable[[], bool] = lambda: False,
        busy_percent: Callable[[], float] = lambda: 85.0,
        cpu: Callable[[], float | None] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._lanes = {name: _Lane(max(1, limit)) for name, limit in lanes.items()}
        self._low_power = low_power
        self._busy_percent = busy_percent
        self._cpu = cpu or CpuWindow().percent
        self._clock = clock
        self._sleep = sleep
        self._ids = itertools.count(1)
        self._running: dict[int, _Job] = {}
        self._recent: deque[JsonObject] = deque(maxlen=RECENT_JOBS)
        self._quiet_waits = 0

    def limit(self, lane: str) -> int:
        """How many jobs the lane runs at once right now."""
        base = self._lane(lane).limit
        return max(1, base // 2) if self._low_power() else base

    @asynccontextmanager
    async def lane(
        self, name: str, *, label: str = "", low_priority: bool = False
    ) -> AsyncIterator[None]:
        """Hold one of the lane's places while the block runs."""
        state = self._lane(name)
        if low_priority:
            await self._wait_for_quiet()
        await self._acquire(name, state)
        job_id = next(self._ids)
        job = _Job(name, label or name, self._clock())
        self._running[job_id] = job
        ok = False
        try:
            yield
            ok = True
        finally:
            # Nothing here awaits, so a cancelled job always gives its place back.
            elapsed = (self._clock() - job.started) * 1000
            self._running.pop(job_id, None)
            state.total_ms += elapsed
            if ok:
                state.done += 1
            else:
                state.failed += 1
            self._recent.append(
                {
                    "lane": name,
                    "label": job.label,
                    "ms": round(elapsed),
                    "ok": ok,
                }
            )
            state.running -= 1
            self._wake(name, state)

    async def run[T](
        self,
        name: str,
        work: Callable[[], Awaitable[T]],
        *,
        label: str = "",
        low_priority: bool = False,
    ) -> T:
        """Run one async job in a lane."""
        async with self.lane(name, label=label, low_priority=low_priority):
            return await work()

    async def run_sync[T](
        self, work: Callable[[], T], *, label: str = "", low_priority: bool = True
    ) -> T:
        """Run blocking number crunching in a thread, in the cpu lane."""
        async with self.lane("cpu", label=label, low_priority=low_priority):
            return await anyio.to_thread.run_sync(work)

    def stats(self) -> JsonObject:
        """What every lane is doing, for the Ops page."""
        now = self._clock()
        return {
            "low_power": self._low_power(),
            "busy_percent": self._busy_percent(),
            "quiet_waits": self._quiet_waits,
            "lanes": [
                {
                    "name": name,
                    "limit": self.limit(name),
                    "running": state.running,
                    "waiting": len(state.waiters),
                    "done": state.done,
                    "failed": state.failed,
                    "avg_ms": (
                        round(state.total_ms / (state.done + state.failed))
                        if state.done + state.failed
                        else 0
                    ),
                }
                for name, state in self._lanes.items()
            ],
            "running": [
                {
                    "lane": job.lane,
                    "label": job.label,
                    "seconds": round(now - job.started, 1),
                }
                for job in self._running.values()
            ],
            "recent": list(self._recent)[-20:],
        }

    def _lane(self, name: str) -> _Lane:
        state = self._lanes.get(name)
        if state is None:
            raise KeyError(f"No worker lane called {name!r}.")
        return state

    async def _acquire(self, name: str, state: _Lane) -> None:
        while state.running >= self.limit(name):
            waiter: asyncio.Future[None] = asyncio.get_running_loop().create_future()
            state.waiters.append(waiter)
            try:
                await waiter
            except asyncio.CancelledError:
                with suppress(ValueError):
                    state.waiters.remove(waiter)
                if waiter.done() and not waiter.cancelled():
                    # Woken, then cancelled before taking the place: pass it on.
                    self._wake(name, state)
                raise
            with suppress(ValueError):
                state.waiters.remove(waiter)
        state.running += 1

    def _wake(self, name: str, state: _Lane) -> None:
        free = self.limit(name) - state.running
        for waiter in tuple(state.waiters):
            if free <= 0:
                break
            if not waiter.done():
                waiter.set_result(None)
                free -= 1

    async def _wait_for_quiet(self) -> None:
        waited = 0.0
        while waited < MAX_QUIET_WAIT_SECONDS:
            busy = self._cpu()
            if busy is None or busy < self._busy_percent():
                return
            self._quiet_waits += 1
            await self._sleep(QUIET_CHECK_SECONDS)
            waited += QUIET_CHECK_SECONDS
