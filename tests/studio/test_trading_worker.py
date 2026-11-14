"""The desk's reliability: one desk at a time, retried jobs, step timing,
and measures from its own records."""

from free_claude_code.studio.trading.records import TradeOrder, TradeRound
from free_claude_code.studio.trading.worker import (
    JOB_TRIES,
    Job,
    Lease,
    Steps,
    metrics,
)


def test_only_one_fcc_holds_the_desk_until_its_lease_lapses(tmp_path):
    now = [1000.0]
    first = Lease(tmp_path / "desk.lease", "first", lambda: now[0])
    second = Lease(tmp_path / "desk.lease", "second", lambda: now[0])
    assert first.take() == ""
    assert "another FCC" in second.take()
    now[0] += 30
    assert first.take() == ""
    assert second.take()
    # The first stopped renewing: after a minute the second may run it.
    now[0] += 61
    assert second.take() == ""
    assert first.take()
    second.release()
    assert first.take() == ""


async def nothing() -> None:
    return None


def test_a_failed_job_waits_longer_each_time_then_is_set_aside():
    job = Job(nothing)
    assert job.failed("boom", 0.0) and job.due == 120.0
    assert job.failed("boom", 200.0) and job.due == 200.0 + 240.0
    assert not job.failed("boom", 500.0)
    assert job.tries == JOB_TRIES and job.errors == ["boom"] * 3


def test_each_step_keeps_its_time_and_last_error():
    steps = Steps()
    steps.record("sync orders", 0.2, at=1.0)
    steps.record("sync orders", 0.5, error="timed out", at=2.0)
    view = steps.view()["sync orders"]
    assert isinstance(view, dict)
    assert view["runs"] == 2 and view["failures"] == 1
    assert view["slowest_ms"] == 500.0 and view["last_error"] == "timed out"


def test_measures_come_from_the_records_and_nothing_is_made_up():
    assert metrics([], [], []) == {}
    rounds = [
        TradeRound(symbol="BTC", status="held", created_at=0, updated_at=60_000),
        TradeRound(symbol="ETH", status="running", created_at=0, updated_at=1),
    ]
    orders = [
        TradeOrder(
            client_id="a",
            symbol="BTC",
            qty=1,
            entry_price=100.0,
            fill_price=100.5,
            filled_qty=1,
            fees=1.0,
            status="filled",
        ),
        TradeOrder(client_id="b", symbol="ETH", qty=1, status="rejected"),
        TradeOrder(client_id="c", symbol="SOL", qty=1, status="cooling"),
    ]
    found = metrics(rounds, orders, [])
    assert found["cycle_seconds_median"] == 60.0
    assert found["orders_sent"] == 2
    assert found["fill_rate_pct"] == 50.0 and found["reject_rate_pct"] == 50.0
    assert found["slippage_pct_average"] == 0.5 and found["fees_total"] == 1.0
