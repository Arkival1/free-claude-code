"""Whether the computer running Studio can reach the internet right now.

Agents only get web tools while it can: offline, a local model would waste its
steps on searches that cannot work. Any HTTP answer from the probe counts as
online; only a connection failure or timeout counts as offline. Results are
cached so a busy team does not probe on every turn.
"""

import time
from collections.abc import Callable

import httpx
from loguru import logger

PROBE_URL = "https://www.gstatic.com/generate_204"
PROBE_TIMEOUT_SECONDS = 4.0
RECHECK_ONLINE_SECONDS = 60.0
RECHECK_OFFLINE_SECONDS = 15.0


class Connectivity:
    """Remember the last reachability probe and refresh it when stale."""

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        probe_url: str = PROBE_URL,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._transport = transport
        self._probe_url = probe_url
        self._clock = clock
        self._online = True
        self._checked_at: float | None = None

    @property
    def online(self) -> bool:
        """The last known state; assumed online until a probe says otherwise."""
        return self._online

    async def check(self) -> bool:
        """Probe again when the cached answer is stale, then return it."""
        now = self._clock()
        wait = RECHECK_ONLINE_SECONDS if self._online else RECHECK_OFFLINE_SECONDS
        if self._checked_at is not None and now - self._checked_at < wait:
            return self._online
        self._checked_at = now
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=PROBE_TIMEOUT_SECONDS,
                # Honour HTTPS_PROXY for the real network, not for a given one.
                trust_env=self._transport is None,
            ) as client:
                await client.head(self._probe_url)
        except httpx.TransportError as error:
            self._set(False, str(error) or type(error).__name__)
        else:
            self._set(True, "")
        return self._online

    def mark_offline(self, reason: str) -> None:
        """A web tool just failed to connect; stop offering web tools."""
        self._checked_at = self._clock()
        self._set(False, reason)

    def _set(self, online: bool, reason: str) -> None:
        if online != self._online:
            if online:
                logger.info("Studio: internet is back; agents can search again")
            else:
                logger.info(
                    "Studio: internet unreachable ({}); web tools paused", reason
                )
        self._online = online
