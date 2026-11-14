"""Tasks on FCC Phone: a job the PC's team plans and works through, step by
step, as the phone watches (like Manus, but on the owner's own PC).

The PC runs the job as a team plan, with every tool, plugin, subagent and
repo agent it has; the phone gets a small view of it and, when it's done,
the files it made (text, and pictures as data), to open in the phone's
Projects.
"""

import base64

from free_claude_code.core.json_types import JsonObject, JsonValue

STEP_RESULT_CHARS = 1500
"""How much of one step's result the phone gets (its models are small)."""
SUMMARY_CHARS = 4000
FILE_CHARS = 300_000
"""The biggest single file sent to the phone."""
FILES_CHARS = 1_500_000
"""All of a task's files together, at most."""
TEXT_TYPES = ("text/", "application/json", "application/javascript", "image/svg+xml")
PICTURE_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")
"""Pictures the phone keeps (as data: addresses, about a third bigger)."""


def task_view(plan: JsonObject) -> JsonObject:
    """A plan as the phone shows it: its goal, status and steps, trimmed."""
    steps = plan.get("steps")
    rows = [
        {
            "id": step.get("id"),
            "agent": step.get("agent"),
            "do": str(step.get("do") or "")[:400],
            "status": step.get("status"),
            "result": str(step.get("result") or "")[:STEP_RESULT_CHARS],
            "source": step.get("source") or "",
        }
        for step in (steps if isinstance(steps, list) else [])
        if isinstance(step, dict)
    ]
    return {
        "id": plan.get("id"),
        "goal": str(plan.get("goal") or "")[:600],
        "kind": plan.get("kind"),
        "status": plan.get("status"),
        "running": bool(plan.get("running")),
        "steps": rows,
        "done_steps": sum(row["status"] == "done" for row in rows),
        "summary": str(plan.get("summary") or "")[:SUMMARY_CHARS],
        "has_files": bool(plan.get("site_id")),
        "created_at": plan.get("created_at"),
        "updated_at": plan.get("updated_at"),
    }


def is_text(content_type: str) -> bool:
    return content_type.startswith(TEXT_TYPES)


def is_picture(content_type: str) -> bool:
    return content_type.startswith(PICTURE_TYPES)


def pick_files(rows: list[tuple[str, str, int]]) -> tuple[list[str], list[str]]:
    """Which files (path, content type, size) go to the phone, and which are
    left out (other binaries, or past the size limits). Text comes first so
    a big picture never pushes a page out."""
    sent: list[str] = []
    left: list[str] = []
    total = 0
    ordered = sorted(rows, key=lambda row: not is_text(row[1]))
    for path, content_type, size in ordered:
        weight = size if is_text(content_type) else size * 4 // 3
        if (
            not (is_text(content_type) or is_picture(content_type))
            or weight > FILE_CHARS
            or total + weight > FILES_CHARS
        ):
            left.append(path)
            continue
        total += weight
        sent.append(path)
    return sent, left


def as_text(content_type: str, body: bytes) -> str:
    """A file as the phone keeps it: text as it is, a picture as data."""
    if is_picture(content_type):
        return f"data:{content_type.split(';')[0]};base64,{base64.b64encode(body).decode('ascii')}"
    return body.decode("utf-8", errors="replace")


def files_view(name: str, files: dict[str, str], left_out: list[str]) -> JsonObject:
    shown: dict[str, JsonValue] = dict(files)
    return {"name": name, "files": shown, "left_out": list(left_out)}
