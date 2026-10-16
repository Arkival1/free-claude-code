"""Outside calls that survive rate limits, dropped connections, and bad answers.

- Retries wait longer each time, with a little randomness so many callers
  don't retry in step, and honour a server's Retry-After.
- Each host gets a steady rate limit, so Studio stays inside a service's free
  limits instead of being cut off.
- A circuit breaker stops calling a service that keeps failing and tries again
  after a cool-down, so one dead service doesn't slow every loop.
- One pooled client keeps connections open between calls instead of opening a
  new one (and doing a new TLS handshake) every time.
- An order is sent at most once: after a dropped connection it is looked up by
  its own id before anything is sent again.
"""

import asyncio
import contextlib
import email.utils
import random
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
from loguru import logger

RETRY_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
MAX_RETRY_AFTER_SECONDS = 300.0
LOOKUP_PAUSE_SECONDS = 1.0
"""How long to give a service to record an order before looking it up."""
POOL_LIMITS = httpx.Limits(
    max_connections=20, max_keepalive_connections=10, keepalive_expiry=30.0
)


class ServiceError(RuntimeError):
    """An outside service failed; says whether trying again could help."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        transient: bool = False,
        retry_after: float | None = None,
        sent: bool | None = None,
        host: str = "",
    ) -> None:
        super().__init__(message)
        self.status = status
        self.transient = transient
        self.retry_after = retry_after
        self.sent = sent
        """False when the request surely never reached the service, so sending
        it again can't double anything; None when nobody knows."""
        self.host = host


class CircuitOpen(ServiceError):
    """A service failed too often; calls wait out its cool-down."""


def retry_after(response: httpx.Response) -> float | None:
    """Seconds the service asked us to wait (Retry-After as seconds or a date)."""
    milliseconds = response.headers.get("retry-after-ms")
    if milliseconds:
        try:
            return _clamp_wait(float(milliseconds) / 1000)
        except ValueError:
            pass
    value = response.headers.get("retry-after")
    if not value:
        return None
    try:
        return _clamp_wait(float(value))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(value)
    except TypeError, ValueError:
        return None
    return _clamp_wait(when.timestamp() - time.time())


def _clamp_wait(seconds: float) -> float:
    return max(0.0, min(MAX_RETRY_AFTER_SECONDS, seconds))


def status_error(response: httpx.Response, *, what: str = "") -> ServiceError:
    """The error for a 4xx or 5xx answer, with whether to try again."""
    host = response.request.url.host if _has_request(response) else ""
    status = response.status_code
    transient = status in RETRY_STATUSES
    detail = _detail(response)
    return ServiceError(
        f"{what or host} answered {status}" + (f": {detail}" if detail else ""),
        status=status,
        transient=transient,
        retry_after=retry_after(response) if transient else None,
        # A rate-limited request was turned away before anything happened.
        sent=False if status == 429 else None,
        host=host,
    )


def transport_error(error: httpx.TransportError, *, host: str = "") -> ServiceError:
    """The error for a connection that failed, with whether it was ever sent."""
    never_sent = isinstance(
        error, httpx.ConnectError | httpx.ConnectTimeout | httpx.PoolTimeout
    )
    broken = isinstance(error, httpx.UnsupportedProtocol | httpx.LocalProtocolError)
    return ServiceError(
        f"{host or 'The service'} could not be reached: "
        f"{error or type(error).__name__}",
        transient=not broken,
        sent=False if never_sent else None,
        host=host,
    )


def _has_request(response: httpx.Response) -> bool:
    try:
        response.request  # noqa: B018 - raises when the response has no request
    except RuntimeError:
        return False
    return True


def _detail(response: httpx.Response) -> str:
    try:
        text = response.text
    except Exception:
        return ""
    return " ".join(text.split())[:200]


def backoff(
    attempt: int,
    *,
    base: float = 0.5,
    cap: float = 20.0,
    rand: Callable[[], float] = random.random,
) -> float:
    """How long to wait before try number ``attempt + 2``: doubling, jittered."""
    delay = min(cap, base * 2**attempt)
    return delay / 2 + rand() * delay / 2


async def with_retries[T](
    call: Callable[[], Awaitable[T]],
    *,
    attempts: int = 4,
    base: float = 0.5,
    cap: float = 20.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    rand: Callable[[], float] = random.random,
    on_retry: Callable[[int, ServiceError, float], None] | None = None,
) -> T:
    """Call again after transient failures; other failures go straight up."""
    attempts = max(1, attempts)
    for attempt in range(attempts):
        try:
            return await call()
        except CircuitOpen:
            raise
        except ServiceError as error:
            if not error.transient or attempt == attempts - 1:
                raise
            wait = (
                error.retry_after
                if error.retry_after is not None
                else backoff(attempt, base=base, cap=cap, rand=rand)
            )
            if on_retry is not None:
                on_retry(attempt + 1, error, wait)
            await sleep(wait)
    raise AssertionError("with_retries ran no attempts")


class RateLimit:
    """A steady pace with a small burst (the generic cell rate algorithm).

    Each caller reserves the next free slot before it waits, so callers in
    parallel never take the same slot and no lock is needed.
    """

    def __init__(
        self,
        per_second: float,
        *,
        burst: int = 1,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._interval = 1.0 / max(per_second, 1e-6)
        self._tolerance = self._interval * (max(1, burst) - 1)
        self._clock = clock
        self._sleep = sleep
        self._next = 0.0

    def reserve(self) -> float:
        """Take the next slot and return how long to wait for it."""
        now = self._clock()
        arrival = max(self._next, now)
        self._next = arrival + self._interval
        return max(0.0, arrival - self._tolerance - now)

    async def take(self) -> None:
        wait = self.reserve()
        if wait > 0:
            await self._sleep(wait)


class CircuitBreaker:
    """Stop calling a failing service for a while, then let one call test it."""

    def __init__(
        self,
        *,
        failures: int = 5,
        cooldown: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = max(1, failures)
        self._cooldown = cooldown
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None
        self._testing = False

    @property
    def state(self) -> str:
        if self._opened_at is None:
            return "closed"
        if self._clock() - self._opened_at < self._cooldown:
            return "open"
        return "half_open"

    def check(self, host: str = "") -> None:
        """Raise CircuitOpen while the service is resting."""
        if self._opened_at is None:
            return
        rested = self._clock() - self._opened_at
        name = host or "The service"
        if rested < self._cooldown:
            wait = self._cooldown - rested
            raise CircuitOpen(
                f"{name} failed {self._failures} times in a row; "
                f"trying again in {wait:.0f} s.",
                retry_after=wait,
                host=host,
            )
        if self._testing:
            raise CircuitOpen(
                f"{name} is being tested after failing; try again shortly.",
                retry_after=1.0,
                host=host,
            )
        self._testing = True

    def record(self, ok: bool) -> None:
        if ok:
            self._failures = 0
            self._opened_at = None
            self._testing = False
            return
        self._failures += 1
        was_testing, self._testing = self._testing, False
        if was_testing or self._failures >= self._limit:
            self._opened_at = self._clock()


@dataclass(frozen=True, slots=True)
class HostLimit:
    """A host's pace: calls a second, and how many may go at once."""

    per_second: float
    burst: int = 1


class Web:
    """One pooled HTTP client that keeps to each host's limits and retries
    idempotent calls; order placement passes retry=False and uses
    ``submit_once`` instead."""

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        limits: Mapping[str, HostLimit] | None = None,
        default_limit: HostLimit = HostLimit(5.0, 5),
        timeout: float = 20.0,
        attempts: int = 3,
        breaker_failures: int = 5,
        breaker_cooldown: float = 60.0,
        user_agent: str = "FCC-Studio",
        verify: bool | str = True,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._transport = transport
        self._limits = dict(limits or {})
        self._default_limit = default_limit
        self._timeout = timeout
        self._attempts = attempts
        self._breaker_failures = breaker_failures
        self._breaker_cooldown = breaker_cooldown
        self._user_agent = user_agent
        self._verify = verify
        self._clock = clock
        self._sleep = sleep
        self._client: httpx.AsyncClient | None = None
        self._client_loop: asyncio.AbstractEventLoop | None = None
        self._rates: dict[str, RateLimit] = {}
        self._breakers: dict[str, CircuitBreaker] = {}

    def client(self) -> httpx.AsyncClient:
        """The pooled client for the running event loop."""
        loop = asyncio.get_running_loop()
        if (
            self._client is None
            or self._client.is_closed
            or self._client_loop is not loop
        ):
            self._client = httpx.AsyncClient(
                transport=self._transport,
                timeout=self._timeout,
                limits=POOL_LIMITS,
                headers={"user-agent": self._user_agent},
                follow_redirects=True,
                verify=self._verify,
                # Honour HTTPS_PROXY for the real network, not for a given one.
                trust_env=self._transport is None,
            )
            self._client_loop = loop
        return self._client

    def breaker(self, host: str) -> CircuitBreaker:
        found = self._breakers.get(host)
        if found is None:
            found = CircuitBreaker(
                failures=self._breaker_failures,
                cooldown=self._breaker_cooldown,
                clock=self._clock,
            )
            self._breakers[host] = found
        return found

    def health(self) -> dict[str, str]:
        """Each host's breaker state, for the Ops page."""
        return {host: breaker.state for host, breaker in self._breakers.items()}

    def _rate(self, host: str) -> RateLimit:
        found = self._rates.get(host)
        if found is None:
            limit = self._limits.get(host, self._default_limit)
            found = RateLimit(
                limit.per_second,
                burst=limit.burst,
                clock=self._clock,
                sleep=self._sleep,
            )
            self._rates[host] = found
        return found

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, object] | None = None,
        json: object = None,
        content: bytes | str | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
        retry: bool = True,
        what: str = "",
    ) -> httpx.Response:
        """Send one request; 4xx/5xx and dropped connections raise ServiceError."""
        host = urlsplit(url).hostname or ""

        async def once() -> httpx.Response:
            breaker = self.breaker(host)
            breaker.check(host)
            await self._rate(host).take()
            try:
                response = await self.client().request(
                    method,
                    url,
                    params=_query(params),
                    json=json,
                    content=content,
                    headers=dict(headers or {}),
                    timeout=timeout
                    if timeout is not None
                    else httpx.USE_CLIENT_DEFAULT,
                )
            except httpx.TransportError as error:
                failure = transport_error(error, host=what or host)
                breaker.record(not failure.transient)
                raise failure from error
            if response.status_code >= 400:
                failure = status_error(response, what=what)
                # A 401 or 404 means the service is up; only outages count.
                breaker.record(not failure.transient)
                raise failure
            breaker.record(True)
            return response

        if not retry:
            return await once()
        return await with_retries(
            once,
            attempts=self._attempts,
            sleep=self._sleep,
            on_retry=lambda attempt, error, wait: logger.info(
                "Studio: {} (try {} again in {:.1f} s)", error, attempt + 1, wait
            ),
        )

    async def get_json(
        self,
        url: str,
        *,
        params: Mapping[str, object] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | None = None,
        what: str = "",
    ) -> object:
        """GET and read the JSON body; a body that isn't JSON raises."""
        response = await self.request(
            "GET", url, params=params, headers=headers, timeout=timeout, what=what
        )
        return read_json(response, what=what)

    async def aclose(self) -> None:
        client, self._client = self._client, None
        if client is not None and not client.is_closed:
            # A client made on an event loop that has since closed can't close.
            with contextlib.suppress(RuntimeError):
                await client.aclose()


def read_json(response: httpx.Response, *, what: str = "") -> object:
    """The response's JSON, or a ServiceError naming who sent something else."""
    try:
        return response.json()
    except ValueError as error:
        host = response.request.url.host if _has_request(response) else ""
        raise ServiceError(
            f"{what or host or 'The service'} sent a reply that isn't JSON "
            f"({_detail(response)[:80]!r}).",
            status=response.status_code,
            host=host,
        ) from error


def _query(params: Mapping[str, object] | None) -> dict[str, str] | None:
    if params is None:
        return None
    return {
        key: ("true" if value is True else "false" if value is False else str(value))
        for key, value in params.items()
        if value is not None
    }


async def submit_once[T](
    place: Callable[[], Awaitable[T]],
    find: Callable[[], Awaitable[T | None]],
    *,
    attempts: int = 3,
    base: float = 1.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    rand: Callable[[], float] = random.random,
) -> T:
    """Send an order at most once, even when the connection drops mid-send.

    A request that was refused or never left is simply sent again. When the
    answer is lost on its way back (a timeout, a dropped connection, a server
    error) the order may already exist, so it is looked up by its client id
    first, and only sent again when the service says it has no such order. If
    the lookup itself can't get an answer, nothing is sent again.
    """
    attempts = max(1, attempts)
    for attempt in range(attempts):
        try:
            return await place()
        except CircuitOpen:
            raise
        except ServiceError as error:
            if not error.transient:
                if attempt > 0:
                    # A second send refused as a duplicate: the first one landed.
                    found = await _look_up(find, sleep=sleep)
                    if found is not None:
                        return found
                raise
            if error.sent is not False:
                found = await _look_up(find, sleep=sleep)
                if found is not None:
                    return found
            if attempt == attempts - 1:
                raise
            wait = (
                error.retry_after
                if error.retry_after is not None
                else backoff(attempt, base=base, rand=rand)
            )
            await sleep(wait)
    raise AssertionError("submit_once ran no attempts")


async def _look_up[T](
    find: Callable[[], Awaitable[T | None]],
    *,
    sleep: Callable[[float], Awaitable[None]],
    tries: int = 3,
) -> T | None:
    await sleep(LOOKUP_PAUSE_SECONDS)
    last: ServiceError | None = None
    for attempt in range(tries):
        try:
            return await find()
        except CircuitOpen as error:
            last = error
            break
        except ServiceError as error:
            last = error
            if not error.transient:
                break
            await sleep(backoff(attempt))
    raise ServiceError(
        "Couldn't confirm whether the order went through, so it was not sent "
        f"again. Check the platform before retrying ({last}).",
        transient=False,
        host=last.host if last is not None else "",
    )
