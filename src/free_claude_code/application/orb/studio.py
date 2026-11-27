"""Process-wide orb state: the brain, the tools and the speech inbox."""

import itertools
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .brain import OrbBrain, OrbReply
from .toolbox import McpToolbox

SKILLS_DIR = Path(__file__).resolve().parent / "skills"
SAY_LIMIT = 4000


def bundled_skills() -> str:
    """All skill files shipped inside the package, joined for the system prompt."""
    texts = [p.read_text(encoding="utf-8") for p in sorted(SKILLS_DIR.glob("*.md"))]
    return "\n\n".join(t.strip() for t in texts if t.strip())


class SpeechInbox:
    """Text other programs (JARVIS in LM Studio) want the orb to say aloud."""

    def __init__(self, keep: int = 50) -> None:
        self._items: deque[dict[str, Any]] = deque(maxlen=keep)
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def say(self, text: str, source: str = "jarvis") -> int:
        item = {
            "id": next(self._ids),
            "text": text.strip()[:SAY_LIMIT],
            "source": source[:40],
            "at": time.time(),
        }
        with self._lock:
            self._items.append(item)
        return item["id"]

    def after(self, last_id: int) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(i) for i in self._items if i["id"] > last_id]

    @property
    def last_id(self) -> int:
        with self._lock:
            return self._items[-1]["id"] if self._items else 0


class OrbStudio:
    """Lazily builds the brain the first time the orb is used."""

    def __init__(
        self,
        base_url_provider: Callable[[], str],
        *,
        toolbox_factory: Callable[[], Any] = McpToolbox.from_lmstudio,
        brain_factory: Callable[..., OrbBrain] = OrbBrain,
    ) -> None:
        self._base_url_provider = base_url_provider
        self._toolbox_factory = toolbox_factory
        self._brain_factory = brain_factory
        self._brain: OrbBrain | None = None
        self._toolbox: Any = None
        self._lock = threading.Lock()
        self.inbox = SpeechInbox()
        self.state = "idle"
        self.last_error = ""

    def brain(self) -> OrbBrain:
        with self._lock:
            if self._brain is None:
                self._toolbox = self._toolbox_factory()
                self._brain = self._brain_factory(
                    base_url=self._base_url_provider(),
                    toolbox=self._toolbox,
                    skills=bundled_skills(),
                )
            return self._brain

    def ask(self, text: str) -> OrbReply:
        self.state = "thinking"
        try:
            reply = self.brain().ask(text)
            self.last_error = ""
            return reply
        except Exception as exc:
            self.last_error = str(exc)
            raise
        finally:
            self.state = "idle"

    def set_model(self, model: str | None) -> None:
        self.brain().model = model or None

    def reload_tools(self) -> None:
        brain = self.brain()
        reload = getattr(brain.toolbox, "reload", None)
        if callable(reload):
            reload()

    def status(self) -> dict[str, Any]:
        brain = self._brain
        toolbox = self._toolbox
        return {
            "state": self.state,
            "started": brain is not None,
            "model": brain.model if brain else None,
            "base_url": self._base_url_provider(),
            "servers": list(getattr(toolbox, "server_names", []) or []),
            "tool_problems": list(getattr(toolbox, "problems", []) or [])[-5:],
            "turns": sum(1 for m in brain.history if m["role"] == "user")
            if brain
            else 0,
            "has_memory": bool(brain and brain.memory_note),
            "last_error": self.last_error,
            "last_say_id": self.inbox.last_id,
        }

    def close(self) -> None:
        with self._lock:
            close = getattr(self._toolbox, "close", None)
            if callable(close):
                close()
            self._brain = None
            self._toolbox = None
