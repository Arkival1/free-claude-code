"""The position manager: highest and lowest prices, a stop that moves to
the entry at +1R and trails the high, never down, and the time exit."""

from free_claude_code.studio.trading.positions import DAY_S, Plan, manage

NOW = 1_800_000_000.0


def plan(**extra: object) -> Plan:
    values: dict[str, object] = {
        "entry": 100.0,
        "initial_stop": 95.0,
        "trailing_pct": None,
        "holding_days": 5,
        "opened_at": NOW,
    }
    values.update(extra)
    found = Plan.read(values)
    assert found is not None
    return found


def test_the_stop_moves_to_the_entry_once_up_by_what_it_risked():
    step = manage(plan(), price=104.0, stop=95.0, high=100, low=100, now=NOW)
    assert step.stop == 95.0 and not step.notes
    step = manage(plan(), price=105.0, stop=95.0, high=104, low=99, now=NOW)
    assert step.stop == 100.0 and "entry" in step.notes[0]
    assert step.excursions(100.0) == (-1.0, 5.0)


def test_a_trailing_stop_follows_the_high_and_never_comes_down():
    trailing = plan(trailing_pct=3.0)
    step = manage(trailing, price=110.0, stop=95.0, high=100, low=100, now=NOW)
    assert step.stop == 110.0 * 0.97
    lower = manage(trailing, price=104.0, stop=step.stop, high=110, low=100, now=NOW)
    assert lower.stop == step.stop and not lower.notes


def test_a_stop_held_by_the_platform_is_left_alone():
    step = manage(
        plan(trailing_pct=3.0),
        price=120.0,
        stop=95.0,
        high=100,
        low=100,
        now=NOW,
        move_stop=False,
    )
    assert step.stop == 95.0 and step.high == 120.0


def test_the_holding_period_ends_with_a_time_exit():
    assert manage(plan(), price=101, stop=95, high=101, low=99, now=NOW).exit == ""
    late = manage(plan(), price=101, stop=95, high=101, low=99, now=NOW + 5 * DAY_S)
    assert "holding period (5 days)" in late.exit


def test_a_broken_plan_is_ignored_rather_than_guessed():
    assert Plan.read({"entry": 0, "opened_at": NOW}) is None
    assert Plan.read("nonsense") is None
    odd = Plan.read({"entry": 100, "opened_at": NOW, "initial_stop": 120})
    assert odd is not None and odd.initial_stop is None
