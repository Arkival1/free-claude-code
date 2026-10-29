"""Background lanes: small limits, low-power mode, a quiet-processor wait."""

import asyncio
from typing import Any

import pytest

from free_claude_code.studio import system_monitor
from free_claude_code.studio.system_monitor import CpuWindow, parse_gpus
from free_claude_code.studio.workers import MAX_QUIET_WAIT_SECONDS, WorkerPool


def data(value: object) -> Any:
    """Read JSON-shaped results without narrowing every level."""
    return value


@pytest.mark.asyncio
async def test_a_lane_runs_no_more_than_its_limit():
    pool = WorkerPool(lanes={"web": 2}, cpu=lambda: None)
    running = 0
    most = 0
    gate = asyncio.Event()

    async def job() -> None:
        nonlocal running, most
        async with pool.lane("web", label="search"):
            running += 1
            most = max(most, running)
            await gate.wait()
            running -= 1

    jobs = [asyncio.create_task(job()) for _ in range(5)]
    await asyncio.sleep(0.01)
    assert most == 2
    stats = data(pool.stats())
    assert stats["lanes"][0]["running"] == 2
    assert stats["lanes"][0]["waiting"] == 3
    assert [job["label"] for job in stats["running"]] == ["search", "search"]
    gate.set()
    await asyncio.gather(*jobs)
    assert most == 2
    assert data(pool.stats())["lanes"][0]["done"] == 5


@pytest.mark.asyncio
async def test_low_power_halves_every_lane():
    low = False
    pool = WorkerPool(lanes={"data": 4, "model_local": 1}, low_power=lambda: low)
    assert pool.limit("data") == 4
    low = True
    assert pool.limit("data") == 2
    assert pool.limit("model_local") == 1
    with pytest.raises(KeyError, match="No worker lane"):
        pool.limit("nope")


@pytest.mark.asyncio
async def test_a_cancelled_waiter_never_keeps_a_place():
    pool = WorkerPool(lanes={"model_local": 1}, cpu=lambda: None)
    holding = asyncio.Event()
    release = asyncio.Event()

    async def holder() -> None:
        async with pool.lane("model_local"):
            holding.set()
            await release.wait()

    async def waiter() -> None:
        async with pool.lane("model_local"):
            await asyncio.sleep(10)

    first = asyncio.create_task(holder())
    await holding.wait()
    second = asyncio.create_task(waiter())
    await asyncio.sleep(0)
    # Wake the waiter and cancel it in the same breath.
    release.set()
    await asyncio.sleep(0)
    second.cancel()
    await first
    with pytest.raises(asyncio.CancelledError):
        await second
    ran = []

    async def third() -> None:
        async with pool.lane("model_local"):
            ran.append(True)

    await asyncio.wait_for(third(), timeout=1)
    assert ran == [True]
    assert data(pool.stats())["lanes"][0]["running"] == 0


@pytest.mark.asyncio
async def test_failures_are_counted_and_the_place_comes_back():
    pool = WorkerPool(lanes={"cpu": 1}, cpu=lambda: None)

    async def broken() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await pool.run("cpu", broken, label="crunch")
    assert await pool.run("cpu", lambda: asyncio.sleep(0, "ok")) == "ok"
    lane = data(pool.stats())["lanes"][0]
    assert (lane["done"], lane["failed"], lane["running"]) == (1, 1, 0)
    assert data(pool.stats())["recent"][0] == {
        "lane": "cpu",
        "label": "crunch",
        "ms": data(pool.stats())["recent"][0]["ms"],
        "ok": False,
    }


@pytest.mark.asyncio
async def test_low_priority_work_waits_for_a_quiet_processor():
    readings = iter([97.0, 92.0, 40.0])
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    pool = WorkerPool(
        lanes={"web": 1},
        cpu=lambda: next(readings),
        busy_percent=lambda: 85.0,
        sleep=sleep,
    )
    async with pool.lane("web", low_priority=True):
        pass
    assert len(waits) == 2
    assert data(pool.stats())["quiet_waits"] == 2
    # Normal-priority work never waits for the processor.
    async with pool.lane("web"):
        pass
    assert len(waits) == 2


@pytest.mark.asyncio
async def test_low_priority_work_never_starves():
    waits: list[float] = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    pool = WorkerPool(lanes={"web": 1}, cpu=lambda: 99.0, sleep=sleep)
    async with pool.lane("web", low_priority=True):
        pass
    assert sum(waits) == pytest.approx(MAX_QUIET_WAIT_SECONDS)


@pytest.mark.asyncio
async def test_number_crunching_runs_in_a_thread():
    pool = WorkerPool(cpu=lambda: None)
    assert await pool.run_sync(lambda: sum(range(10)), label="sum") == 45
    assert data(pool.stats())["recent"][-1]["lane"] == "cpu"


def test_each_cpu_window_measures_its_own_span():
    times = iter([(100, 1000), (150, 1100), (300, 1300)])
    now = [0.0]
    window = CpuWindow(times=lambda: next(times), clock=lambda: now[0])
    assert window.percent() is None
    now[0] = 2.0
    assert window.percent() == 50.0
    # Asked again too soon: the last reading, not a near-empty window.
    now[0] = 2.5
    assert window.percent() == 50.0
    now[0] = 5.0
    assert window.percent() == 25.0


def test_nvidia_smi_lines_are_read():
    text = "NVIDIA GeForce RTX 3060 Laptop GPU, 37, 2048, 6144, 54\nbad line\n"
    assert parse_gpus(text) == [
        {
            "name": "NVIDIA GeForce RTX 3060 Laptop GPU",
            "load": 37.0,
            "memory_used_gb": 2.0,
            "memory_gb": 6.0,
            "memory": 33.3,
            "temperature": 54.0,
        }
    ]
    assert parse_gpus("") is None
    assert system_monitor.gpus(run=lambda _: None) is None
    assert (
        data(system_monitor.gpus(run=lambda _: "Card, [N/A], 1024, 2048, 40"))[0][
            "load"
        ]
        is None
    )
