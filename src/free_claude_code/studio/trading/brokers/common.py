"""Small helpers every platform adapter shares."""

import re
import time
from collections.abc import Callable, Mapping
from urllib.parse import urlsplit

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


MONEY_MOVES = re.compile(
    r"withdraw|transfer|payout|/send\b|/sends?/|walletsend|/transactions\b"
    r"|api[-_]?keys?\b|/permissions\b",
    re.IGNORECASE,
)
"""Calls that move money out of an account or change a key's rights."""


def forbid_money_moves(method: str, url: str) -> None:
    """FCC trades and reads, nothing else: a call that could withdraw,
    transfer, send money or change a key's permissions is refused before it
    leaves this PC. (Reading a key's own permissions is allowed.)"""
    path = urlsplit(url).path
    if method.upper() == "GET" and path.rstrip("/").endswith("key_permissions"):
        return
    if MONEY_MOVES.search(path):
        raise ServiceError(
            f"FCC never moves money or changes key rights; refused {method} {path}.",
            transient=False,
            sent=False,
        )


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
        guard=forbid_money_moves,
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
