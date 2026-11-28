from free_claude_code.application.orb.activity import ActivityBoard, overall


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_job_steps_and_fcc_percent_make_one_progress_bar():
    clock = Clock()
    board = ActivityBoard(clock)
    board.update(
        "job-1",
        title="Video notes WftF2zJkvHY",
        step=2,
        steps=6,
        step_name="Downloading",
        status="running",
    )
    board.update("job-1", percent=50, detail="FCC downloading the audio 50%")
    task = board.snapshot()["tasks"][0]
    assert task["overall"] == round((2 + 0.5) / 6 * 100, 1)
    assert task["detail"] == "FCC downloading the audio 50%" and task[
        "title"
    ].startswith("Video notes")
    board.update("job-1", step=3, step_name="Transcribing", percent=None)
    assert board.snapshot()["tasks"][0]["overall"] == 50.0
    board.update("job-1", status="done")
    assert board.snapshot()["tasks"][0]["overall"] == 100.0
    clock.now += 16 * 60  # finished tasks disappear after 15 minutes
    assert board.snapshot()["tasks"] == []


def test_feed_keeps_recent_actions_and_ignores_bad_values():
    board = ActivityBoard(Clock())
    for i in range(50):
        board.note(f"Used tool_{i}", "lmstudio")
    feed = board.snapshot()["feed"]
    assert len(feed) == 12 and feed[-1]["text"] == "Used tool_49"
    key = board.update(None, title="x", status="hacked", step=999, percent=500)
    task = board.snapshot()["tasks"][0]
    assert (
        key.startswith("fcc-") and task["status"] == "running" and task["step"] is None
    )
    assert task["percent"] == 100.0 and overall(task) == 100.0
