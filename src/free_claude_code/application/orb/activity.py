"""What JARVIS is doing right now: task progress bars and a live action feed.

JARVIS (in LM Studio or the orb) reports its jobs and tool calls here; FCC adds
the real download and transcription percentages it measures itself. The orb
page polls this to show a progress bar at all times. Kept in memory only.
"""

import itertools
import threading
import time
from collections import deque
from typing import Any

MAX_TASKS = 12
FEED_SIZE = 40
_STATUSES = frozenset({"running", "waiting", "done", "failed", "cancelled", "stale"})


def _text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


class ActivityBoard:
    def __init__(self, clock: Any = time.time) -> None:
        self._clock = clock
        self._tasks: dict[str, dict[str, Any]] = {}
        self._feed: deque[dict[str, Any]] = deque(maxlen=FEED_SIZE)
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def note(self, text: str, source: str = "jarvis") -> None:
        """One line in the live feed, e.g. 'Using job_status'."""
        item = {
            "at": self._clock(),
            "text": _text(text, 160),
            "source": _text(source, 20),
        }
        with self._lock:
            self._feed.append(item)

    def update(self, task_id: str | None = None, **fields: Any) -> str:
        """Create or update a task. Unknown fields are ignored."""
        now = self._clock()
        with self._lock:
            key = _text(task_id, 64) or f"fcc-{next(self._ids)}"
            task = self._tasks.get(key)
            if task is None:
                task = {
                    "id": key,
                    "title": "Task",
                    "source": "jarvis",
                    "status": "running",
                    "step": None,
                    "steps": None,
                    "step_name": "",
                    "detail": "",
                    "percent": None,
                    "log": [],
                    "started": now,
                }
                self._tasks[key] = task
            for name in ("title", "source", "step_name", "detail"):
                if fields.get(name) is not None:
                    task[name] = _text(fields[name], 200)
            if fields.get("status") in _STATUSES:
                task["status"] = fields["status"]
            for name in ("step", "steps"):
                value = fields.get(name)
                if isinstance(value, int) and 0 <= value <= 50:
                    task[name] = value
            if "percent" in fields:
                value = fields["percent"]
                task["percent"] = (
                    None if value is None else max(0.0, min(100.0, float(value)))
                )
            if isinstance(fields.get("log"), list):
                task["log"] = [_text(line, 200) for line in fields["log"][-6:]]
            task["updated"] = now
            self._trim(now)
            return key

    def snapshot(self) -> dict[str, Any]:
        now = self._clock()
        with self._lock:
            self._trim(now)
            tasks = sorted(self._tasks.values(), key=lambda t: -t["updated"])
            return {
                "now": now,
                "tasks": [{**t, "overall": overall(t)} for t in tasks],
                "feed": list(self._feed)[-12:],
            }

    def _trim(self, now: float) -> None:
        for key, task in list(self._tasks.items()):
            finished = task["status"] in {"done", "failed", "cancelled", "stale"}
            if finished and now - task["updated"] > 15 * 60:
                del self._tasks[key]
        while len(self._tasks) > MAX_TASKS:
            oldest = min(self._tasks.values(), key=lambda t: t["updated"])
            del self._tasks[oldest["id"]]


def overall(task: dict[str, Any]) -> float | None:
    """0-100 for the whole task, or None when progress is unknown."""
    if task["status"] == "done":
        return 100.0
    step, steps, percent = task.get("step"), task.get("steps"), task.get("percent")
    if isinstance(step, int) and isinstance(steps, int) and steps > 0:
        inside = (percent or 0.0) / 100.0
        return round(min(100.0, (step + inside) / steps * 100.0), 1)
    return percent
