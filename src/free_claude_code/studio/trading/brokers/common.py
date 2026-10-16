"""Small helpers every platform adapter shares."""

import time
from collections.abc import Callable, Mapping

import httpx

from ...resilience import HostLimit, ServiceError, Web
from ..instruments import Instrument


def number(value: object, default: float = 0.0) -> float:
    """A number from an API field that may be a string, a number, or missing."""
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", ""))
        except ValueError:
            return default
    return default


def text(value: object) -> str:
    return "" if value is None else str(value)


def obj(value: object) -> dict[str, object]:
    """The value as a JSON object, or an empty one."""
    return (
        {str(key): item for key, item in value.items()}
        if isinstance(value, Mapping)
        else {}
    )


def items(value: object) -> list[dict[str, object]]:
    """The value as a list of JSON objects, skipping anything else."""
    if not isinstance(value, list):
        return []
    return [obj(item) for item in value if isinstance(item, Mapping)]


def coin(instrument: Instrument) -> str:
    """The coin's own code: BTC for BTC, DOGE for DOGE."""
    return instrument.symbol.upper()


def make_web(
    transport: httpx.AsyncBaseTransport | None,
    host: str,
    *,
    per_second: float,
    burst: int = 2,
    verify: bool | str = True,
    timeout: float = 20.0,
) -> Web:
    """A pooled client paced for one platform's published limits."""
    return Web(
        transport=transport,
        limits={host: HostLimit(per_second, burst)},
        default_limit=HostLimit(per_second, burst),
        user_agent="FCC-Studio trading desk",
        verify=verify,
        timeout=timeout,
        breaker_failures=4,
        breaker_cooldown=60.0,
    )


class Nonce:
    """An always-increasing nonce (milliseconds, bumped if called twice in one)."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._last = 0

    def __call__(self) -> int:
        value = max(int(self._clock() * 1000), self._last + 1)
        self._last = value
        return value


def refused(what: str, detail: object) -> ServiceError:
    return ServiceError(f"{what} refused the request: {detail}", transient=False)
