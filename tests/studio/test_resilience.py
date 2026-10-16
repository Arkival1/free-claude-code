"""Outside calls: retries, rate limits, breakers, safe orders, and messy JSON."""

import email.utils
import time

import httpx
import pytest

from free_claude_code.studio.jsonish import lenient_object
from free_claude_code.studio.resilience import (
    CircuitBreaker,
    CircuitOpen,
    HostLimit,
    RateLimit,
    ServiceError,
    Web,
    retry_after,
    status_error,
    submit_once,
    transport_error,
    with_retries,
)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(round(seconds, 3))
        self.now += seconds


def response(status: int, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(
        status,
        headers=headers or {},
        text="slow down",
        request=httpx.Request("GET", "https://api.example.test/x"),
    )


def test_retry_after_reads_seconds_dates_and_milliseconds():
    assert retry_after(response(429, {"retry-after": "7"})) == 7.0
    assert retry_after(response(429, {"retry-after-ms": "1500"})) == 1.5
    assert retry_after(response(429, {"retry-after": "100000"})) == 300.0
    soon = email.utils.formatdate(time.time() + 30, usegmt=True)
    assert 25 <= (retry_after(response(503, {"retry-after": soon})) or 0) <= 30
    assert retry_after(response(429, {"retry-after": "whenever"})) is None
    assert retry_after(response(429)) is None


def test_errors_say_whether_trying_again_can_help():
    limited = status_error(response(429, {"retry-after": "2"}))
    assert limited.transient and limited.sent is False and limited.retry_after == 2.0
    assert "api.example.test answered 429: slow down" in str(limited)
    outage = status_error(response(503))
    assert outage.transient and outage.sent is None
    denied = status_error(response(401))
    assert not denied.transient
    never = transport_error(httpx.ConnectError("refused"), host="api.example.test")
    assert never.transient and never.sent is False
    lost = transport_error(httpx.ReadTimeout("slow"), host="api.example.test")
    assert lost.transient and lost.sent is None


@pytest.mark.asyncio
async def test_transient_failures_are_retried_with_growing_waits():
    clock = Clock()
    calls = 0

    async def flaky() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ServiceError("busy", transient=True, retry_after=3.0)
        if calls == 2:
            raise ServiceError("busy", transient=True)
        return "ok"

    assert await with_retries(flaky, sleep=clock.sleep, rand=lambda: 1.0) == "ok"
    # Retry-After first, then the doubling backoff (0.5 s * 2 for try 2).
    assert clock.slept == [3.0, 1.0]

    async def refused() -> str:
        raise ServiceError("bad key", transient=False)

    with pytest.raises(ServiceError, match="bad key"):
        await with_retries(refused, sleep=clock.sleep)

    async def down() -> str:
        raise ServiceError("down", transient=True)

    clock.slept.clear()
    with pytest.raises(ServiceError, match="down"):
        await with_retries(down, attempts=3, sleep=clock.sleep, rand=lambda: 0.0)
    assert len(clock.slept) == 2


@pytest.mark.asyncio
async def test_rate_limits_space_calls_after_a_burst():
    clock = Clock()
    limit = RateLimit(2.0, burst=2, clock=clock, sleep=clock.sleep)
    for _ in range(4):
        await limit.take()
    # Two go at once, then one every half second.
    assert clock.slept == [0.5, 0.5]


def test_a_breaker_rests_a_failing_service_then_tests_it():
    clock = Clock()
    breaker = CircuitBreaker(failures=3, cooldown=60, clock=clock)
    for _ in range(3):
        breaker.check("data.test")
        breaker.record(False)
    assert breaker.state == "open"
    with pytest.raises(CircuitOpen, match="trying again in 60 s"):
        breaker.check("data.test")
    clock.now += 61
    assert breaker.state == "half_open"
    breaker.check("data.test")
    with pytest.raises(CircuitOpen, match="being tested"):
        breaker.check("data.test")
    breaker.record(False)
    assert breaker.state == "open"
    clock.now += 61
    breaker.check("data.test")
    breaker.record(True)
    assert breaker.state == "closed"
    breaker.check("data.test")


@pytest.mark.asyncio
async def test_the_pooled_client_retries_paces_and_reads_json():
    clock = Clock()
    seen: list[str] = []
    answers = iter(
        [
            httpx.Response(503),
            httpx.Response(429, headers={"retry-after": "4"}),
            httpx.Response(200, json={"price": 101.5}),
            httpx.Response(200, text="<html>consent</html>"),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return next(answers)

    web = Web(
        transport=httpx.MockTransport(handler),
        limits={"quotes.test": HostLimit(1.0)},
        clock=clock,
        sleep=clock.sleep,
    )
    body = await web.get_json(
        "https://quotes.test/q", params={"symbol": "BHP.AX", "skip": None, "live": True}
    )
    assert body == {"price": 101.5}
    assert seen[0] == "https://quotes.test/q?symbol=BHP.AX&live=true"
    assert 4.0 in clock.slept
    with pytest.raises(ServiceError, match="isn't JSON"):
        await web.get_json("https://quotes.test/q", what="Yahoo")
    await web.aclose()


@pytest.mark.asyncio
async def test_a_dead_service_trips_the_breaker():
    clock = Clock()
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("refused", request=request)

    web = Web(
        transport=httpx.MockTransport(handler),
        attempts=1,
        breaker_failures=2,
        clock=clock,
        sleep=clock.sleep,
    )
    for _ in range(2):
        with pytest.raises(ServiceError, match="could not be reached"):
            await web.get_json("https://down.test/")
    with pytest.raises(CircuitOpen):
        await web.get_json("https://down.test/")
    assert calls == 2
    assert web.health() == {"down.test": "open"}
    await web.aclose()


class Orders:
    """A broker that loses answers on the way back."""

    def __init__(self, failures: list[ServiceError | None]) -> None:
        self.failures = failures
        self.placed: list[str] = []
        self.book: dict[str, str] = {}
        self.lookups = 0

    async def place(self) -> str:
        failure = self.failures.pop(0) if self.failures else None
        if failure is not None and failure.sent is False:
            raise failure
        self.placed.append("ord-1")
        self.book["cid-1"] = "ord-1"
        if failure is not None:
            raise failure
        return "ord-1"

    async def find(self) -> str | None:
        self.lookups += 1
        return self.book.get("cid-1")


@pytest.mark.asyncio
async def test_an_order_never_sent_is_simply_sent_again():
    clock = Clock()
    broker = Orders([ServiceError("refused", transient=True, sent=False)])
    assert await submit_once(broker.place, broker.find, sleep=clock.sleep) == "ord-1"
    assert broker.placed == ["ord-1"] and broker.lookups == 0


@pytest.mark.asyncio
async def test_a_lost_answer_is_looked_up_instead_of_ordering_twice():
    clock = Clock()
    broker = Orders([ServiceError("timed out", transient=True)])
    assert await submit_once(broker.place, broker.find, sleep=clock.sleep) == "ord-1"
    assert broker.placed == ["ord-1"]
    assert broker.lookups == 1


@pytest.mark.asyncio
async def test_an_order_that_never_landed_is_sent_again_after_the_lookup():
    clock = Clock()
    calls = 0

    async def place() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ServiceError("bad gateway", transient=True, status=502)
        return "ord-2"

    async def find() -> str | None:
        return None

    assert await submit_once(place, find, sleep=clock.sleep) == "ord-2"
    assert calls == 2


@pytest.mark.asyncio
async def test_an_unconfirmed_order_is_never_sent_again():
    clock = Clock()
    calls = 0

    async def place() -> str:
        nonlocal calls
        calls += 1
        raise ServiceError("reset", transient=True)

    async def find() -> str | None:
        raise ServiceError("still down", transient=True)

    with pytest.raises(ServiceError, match="not sent again"):
        await submit_once(place, find, sleep=clock.sleep)
    assert calls == 1


@pytest.mark.asyncio
async def test_a_duplicate_refusal_means_the_first_order_landed():
    clock = Clock()
    book: dict[str, str] = {}
    calls = 0

    async def place() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ServiceError("refused", transient=True, sent=False)
        book["cid"] = "ord-3"
        raise ServiceError("client_order_id must be unique", status=422)

    async def find() -> str | None:
        return book.get("cid")

    assert await submit_once(place, find, sleep=clock.sleep) == "ord-3"


def test_near_json_from_small_models_is_read():
    assert lenient_object('Sure! {"stance": "buy", "p_up": 0.6,}') == {
        "stance": "buy",
        "p_up": 0.6,
    }
    assert lenient_object("```json\n{'stance': 'hold', ok: True, x: None}\n```") == {
        "stance": "hold",
        "ok": True,
        "x": None,
    }
    assert lenient_object('{"a": 1, "b": [1, 2') == {"a": 1, "b": [1, 2]}
    assert lenient_object('{"a": 1, "note": "cut of') == {"a": 1, "note": "cut of"}
    assert lenient_object('{"a": 1, "b":') == {"a": 1}
    assert lenient_object("no json here") == {}
