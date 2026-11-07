"""Take turns on a small GPU when agents think with different local models.

A card with 8 GB holds one mid-sized model at a time. When the Builder uses
one model and Jarvis another, letting both call at once makes the runtime
unload and reload models on every step. Turns keep one model working while
it is busy, switch when it goes quiet, and never make anyone wait forever.
Models the runtime already has loaded side by side run together.
"""

import asyncio
import contextlib
import time
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

PATIENCE_SECONDS = 60.0
"""A model waiting this long gets the next turn even if the other stays busy."""
GRACE_SECONDS = 3.0
"""The model that just worked keeps its turn this long, between an agent's steps."""
LOADED_CACHE_SECONDS = 2.0
POLL_SECONDS = 0.25


class ModelTurns:
    """Let local models take turns instead of pushing each other out of memory."""

    def __init__(
        self,
        *,
        loaded: Callable[[], Awaitable[tuple[str, ...] | None]] | None = None,
        patience: float = PATIENCE_SECONDS,
        grace: float = GRACE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._loaded = loaded
        self._patience = patience
        self._grace = grace
        self._clock = clock
        self._active: Counter[str] = Counter()
        self._waiting: dict[object, tuple[str, float]] = {}
        self._last: str | None = None
        self._idle_since = clock()
        self._wake = asyncio.Event()
        self._loaded_cache: tuple[float, tuple[str, ...] | None] | None = None

    @property
    def working(self) -> tuple[str, ...]:
        """Models answering right now."""
        return tuple(model for model, count in self._active.items() if count > 0)

    @property
    def waiting(self) -> tuple[str, ...]:
        """Models waiting for their turn, longest waiting first."""
        ordered = sorted(self._waiting.values(), key=lambda pair: pair[1])
        return tuple(dict.fromkeys(model for model, _ in ordered))

    @asynccontextmanager
    async def turn(self, model: str) -> AsyncIterator[None]:
        """Hold a turn for one call to ``model``."""
        await self._acquire(model)
        try:
            yield
        finally:
            self._release(model)

    async def _acquire(self, model: str) -> None:
        token = object()
        since = self._clock()
        self._waiting[token] = (model, since)
        try:
            while True:
                # Ask the runtime what it holds only when that could let us in.
                if self._may_start(model, since, None) or self._may_start(
                    model, since, await self._loaded_now()
                ):
                    self._active[model] += 1
                    self._last = model
                    return
                wake = self._wake
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(wake.wait(), POLL_SECONDS)
        finally:
            self._waiting.pop(token, None)

    def _release(self, model: str) -> None:
        self._active[model] -= 1
        if self._active[model] <= 0:
            del self._active[model]
        if not self._active:
            self._idle_since = self._clock()
        self._wake.set()
        self._wake = asyncio.Event()

    def _may_start(
        self, model: str, since: float, loaded: tuple[str, ...] | None
    ) -> bool:
        now = self._clock()
        others = [started for name, started in self._waiting.values() if name != model]
        overdue = any(now - started >= self._patience for started in others)
        if self._active[model] > 0 or (loaded is not None and model in loaded):
            # Already in memory: no swap is needed, unless someone waited too long.
            return not overdue
        if self._active:
            return False
        if model == self._last:
            return not overdue
        waited = now - since
        if (
            self._last is not None
            and now - self._idle_since < self._grace
            and waited < self._patience
        ):
            return False
        return all(since <= started for started in others)

    async def _loaded_now(self) -> tuple[str, ...] | None:
        if self._loaded is None:
            return None
        now = self._clock()
        cached = self._loaded_cache
        if cached is None or now - cached[0] >= LOADED_CACHE_SECONDS:
            cached = (now, await self._loaded())
            self._loaded_cache = cached
        return cached[1]
