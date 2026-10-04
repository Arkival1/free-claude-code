"""Whether Claude Code's subagents (the Task tool) may run in the background.

By default every Task call is kept in the foreground, which works with every
provider. With Allow Background Subagents on, the model's choice is kept, so
several subagents can run at once in the background. The API layer sets this
from the settings on each request.
"""

from typing import Any

_background_allowed = False


def allow_background_subagents(allowed: bool) -> None:
    global _background_allowed
    _background_allowed = allowed


def background_subagents_allowed() -> bool:
    return _background_allowed


def normalize_task_arguments(arguments: dict[str, Any]) -> None:
    """Keep a Task call in the foreground unless background is allowed."""
    if _background_allowed:
        return
    if arguments.get("run_in_background") is not False:
        arguments["run_in_background"] = False
