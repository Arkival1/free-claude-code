"""PC control: the main AI (Jarvis), thinking on the local model, runs the PC.

Only Jarvis gets the PC tools, and only while his brain is the local model
(LM Studio); advisers never do, whatever model they use (agents.py
``_private_view`` decides each turn). The owner sets the level and can stop
him at any moment:

- off: no PC tools (the default)
- look: list and read files only
- ask: everything else waits for the owner's Approve
- full: runs on its own; risky steps (deleting, installing, running
  programs or scripts) still ask

Stop is a latch: it kills running commands, refuses every PC step and stays
until the owner resumes. Some places are never touched at any level: FCC's
own data and keys, FCC's code (so it can't change its own rules), Windows'
system folders and password stores. These checks read the command's text;
they are a second line, not a sandbox: the Stop button, the levels and a PC
kept for Jarvis are the first.
"""

import asyncio
import json
import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from free_claude_code.core.json_types import JsonObject

PC_RUN = "pc_run"
PC_FILES = "pc_files"
PC_TOOLS = frozenset({PC_RUN, PC_FILES})
# With PC control on, an adviser has the web and the tool list (to suggest
# tools and plugins to Jarvis), nothing else, whatever model it thinks with.
ADVISER_TOOLS = frozenset({"web_search", "web_fetch", "research", "toolshed"})
LEVELS = ("off", "look", "ask", "full")
FILE_ACTIONS = ("list", "read", "write", "append", "mkdir", "move", "delete")
READ_ACTIONS = frozenset({"list", "read"})
MAX_READ_CHARS = 20_000
MAX_WRITE_CHARS = 400_000
MAX_LIST = 300
LOG_KEEP = 2_000

# Never run, at any level: they wreck the PC, its security, or the stop.
_NEVER = re.compile(
    r"\bformat(\.com)?\s+[a-z]:|\bdiskpart\b|\bbcdedit\b|\bvssadmin\b.*\bdelete\b"
    r"|\bcipher\b.*/w|\b(set|add)-mppreference\b|\bnetsh\b.*\bfirewall\b"
    r"|\breg(\.exe)?\s+(add|delete|import)\s+\"?hk(lm|ey_local_machine)"
    r"|\btakeown\b|\bnet\s+(user|localgroup)\b|\bschtasks\b.*/create|\bwevtutil\b.*\bcl\b"
    r"|\bshutdown\b|\b(stop|restart)-computer\b|\bbitlocker|\bmanage-bde\b"
    r"|\b(remove-item|rd|rmdir|del|erase)\b[^|;&]*\b[a-z]:\\?[\"']?\s*($|[|;&])"
    r"|\bset-executionpolicy\b.*\bunrestricted\b.*\b(localmachine)\b"
    r"|\bstop-process\b.*\b(python|uvicorn|fcc)\b|\btaskkill\b.*\b(python|fcc)",
    re.IGNORECASE,
)
# Ask first even at the full level: deleting, installing, running programs,
# scripts or downloaded code, and anything run as administrator.
_RISKY = re.compile(
    r"\b(del|erase|rd|rmdir|remove-item|rm|move-item|mv|ren|rename-item)\b"
    r"|\b(winget|choco|scoop|msiexec)\b|\bpip3?\s+install\b|\bnpm\s+(i|install)\s+(-g|--global)\b"
    r"|\b(invoke-expression|iex)\b|\bset-executionpolicy\b|-verb\s+runas\b"
    r"|\b(invoke-webrequest|iwr|curl|wget)\b.*\|"
    r"|\.(exe|msi|bat|cmd|ps1|vbs|js|jar|scr)\b|\bstart-process\b|\breg(\.exe)?\s+(add|delete|import)\b",
    re.IGNORECASE,
)
# Password stores and keys: never read or written, wherever they are.
_SECRET_PARTS = (
    "login data",
    "logins.json",
    "key4.db",
    "key3.db",
    "cookies",
    "local state",
    ".ssh",
    ".aws",
    ".azure",
    ".gnupg",
    ".git-credentials",
    "credentials",
    "trading-keys",
    ".vault",
    "keepass",
    "1password",
    "bitwarden",
    "lastpass",
)


@dataclass(frozen=True, slots=True)
class Decision:
    """What happens to one PC step: run, ask the owner, or refuse (why)."""

    verdict: str  # "auto" | "ask" | "deny"
    reason: str = ""


class PcControl:
    """The owner's switches for Jarvis's hands on this PC, and their guards."""

    def __init__(
        self,
        *,
        data_root: Path,
        protected: tuple[Path, ...] = (),
        home: Path | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._data_root = data_root.resolve()
        self._state_path = data_root / "pc-control.json"
        self._log_path = data_root / "pc-control-log.jsonl"
        self._home = (home or Path.home()).resolve()
        system = [
            os.environ.get(name)
            for name in (
                "SystemRoot",
                "ProgramFiles",
                "ProgramFiles(x86)",
                "ProgramData",
            )
        ]
        self._system = tuple(Path(item).resolve() for item in system if item)
        self._protected = (self._data_root, *(path.resolve() for path in protected))
        self._clock = clock
        self._running: set[asyncio.subprocess.Process] = set()
        state = self._read_state()
        level = state.get("level")
        self._level = level if isinstance(level, str) and level in LEVELS else "off"
        self._stopped = state.get("stopped") is True
        saved = state.get("roots")
        roots = (
            [Path(item) for item in saved if isinstance(item, str)]
            if isinstance(saved, list)
            else []
        )
        self._roots = tuple(root.resolve() for root in roots) or (self._home,)

    # ── the owner's switches ──────────────────────────────────────────────

    @property
    def level(self) -> str:
        return self._level

    @property
    def stopped(self) -> bool:
        return self._stopped

    @property
    def roots(self) -> tuple[Path, ...]:
        return self._roots

    @property
    def active(self) -> bool:
        """Whether Jarvis has PC tools at all this turn."""
        return self._level != "off" and not self._stopped

    def set_level(self, level: str) -> None:
        if level not in LEVELS:
            raise ValueError(f"Level must be one of {', '.join(LEVELS)}.")
        self._level = level
        self._save()
        self.log("owner", f"level set to {level}")

    def set_roots(self, roots: list[str]) -> None:
        cleaned = tuple(
            Path(item).expanduser().resolve() for item in roots if str(item).strip()
        )
        if not cleaned:
            raise ValueError("Give at least one folder.")
        for root in cleaned:
            if self._protected_reason(root):
                raise ValueError(f"{root} can't be one of Jarvis's folders.")
        self._roots = cleaned
        self._save()
        self.log("owner", "folders: " + ", ".join(str(root) for root in cleaned))

    async def stop(self) -> int:
        """The Stop button: refuse every PC step and kill what's running."""
        self._stopped = True
        self._save()
        killed = 0
        for process in list(self._running):
            if process.returncode is None:
                await _kill_tree(process)
                killed += 1
        self.log("owner", f"STOP (killed {killed} running)")
        return killed

    def resume(self) -> None:
        self._stopped = False
        self._save()
        self.log("owner", "resumed")

    def state(self) -> JsonObject:
        return {
            "level": self._level,
            "stopped": self._stopped,
            "active": self.active,
            "roots": [str(root) for root in self._roots],
            "running": sum(
                1 for process in self._running if process.returncode is None
            ),
        }

    # ── deciding ──────────────────────────────────────────────────────────

    def decide(self, tool: str, arguments: Mapping[str, object]) -> Decision:
        """Run, ask or refuse one PC step at the current level."""
        if self._stopped:
            return Decision(
                "deny",
                "The owner pressed Stop. PC control is paused until they resume it.",
            )
        if self._level == "off":
            return Decision("deny", "PC control is off.")
        if tool == PC_FILES:
            action = str(arguments.get("action", ""))
            if action not in FILE_ACTIONS:
                return Decision(
                    "deny", f"action must be one of {', '.join(FILE_ACTIONS)}."
                )
            for key in ("path", "to"):
                if key in arguments and arguments[key] not in (None, ""):
                    reason = self.path_reason(
                        str(arguments[key]), write=action not in READ_ACTIONS
                    )
                    if reason:
                        return Decision("deny", reason)
            if action in READ_ACTIONS:
                return Decision("auto")
            if self._level == "look":
                return Decision("deny", "PC control is at Look: reading only.")
            if self._level == "ask" or action in {"delete", "move"}:
                return Decision("ask")
            return Decision("auto")
        if tool == PC_RUN:
            command = str(arguments.get("command", ""))
            if self._level == "look":
                return Decision("deny", "PC control is at Look: no commands.")
            reason = self.command_reason(command)
            if reason:
                return Decision("deny", reason)
            cwd = arguments.get("cwd")
            if cwd:
                reason = self.path_reason(str(cwd), write=False)
                if reason:
                    return Decision("deny", reason)
            if self._level == "ask" or _RISKY.search(command):
                return Decision("ask")
            return Decision("auto")
        return Decision("deny", f"{tool} isn't a PC tool.")

    def command_reason(self, command: str) -> str:
        text = command.strip()
        if not text:
            return "A command is required."
        if _NEVER.search(text):
            return "That command is never allowed (it could wreck the PC, its security or the Stop button)."
        lowered = text.lower()
        for path in self._protected:
            if str(path).lower() in lowered:
                return "That command touches FCC's own data or code, which Jarvis never changes."
        if any(part in lowered for part in (".fcc", *_SECRET_PARTS)):
            return "That command touches keys or passwords, which Jarvis never touches."
        return ""

    def path_reason(self, raw: str, *, write: bool) -> str:
        try:
            path = Path(raw).expanduser()
            path = (path if path.is_absolute() else self._roots[0] / path).resolve()
        except OSError, RuntimeError, ValueError:
            return "That path isn't valid."
        reason = self._protected_reason(path)
        if reason:
            return reason
        if write and any(_inside(path, system) for system in self._system):
            return "Windows' system folders are read-only for Jarvis."
        if not any(_inside(path, root) for root in self._roots):
            return "That's outside Jarvis's folders: " + ", ".join(
                str(root) for root in self._roots
            )
        return ""

    def _protected_reason(self, path: Path) -> str:
        if any(_inside(path, protected) for protected in self._protected):
            return "That's FCC's own data or code, which Jarvis never touches."
        lowered = str(path).lower()
        if any(part in lowered for part in _SECRET_PARTS):
            return "That's a key or password store, which Jarvis never touches."
        return ""

    def resolve(self, raw: str) -> Path:
        path = Path(raw).expanduser()
        return (path if path.is_absolute() else self._roots[0] / path).resolve()

    # ── doing ─────────────────────────────────────────────────────────────

    async def execute(
        self, command: str, *, cwd: Path, timeout: float
    ) -> tuple[int, str, bool]:
        """Run one command, tracked so Stop can kill it."""
        from .commands import MAX_OUTPUT_CHARS, scrubbed_environment

        windows = os.name == "nt"
        process = await asyncio.create_subprocess_shell(
            command,
            cwd=str(cwd),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=scrubbed_environment(),
            start_new_session=not windows,
        )
        self._running.add(process)
        try:
            try:
                stdout, _ = await asyncio.wait_for(process.communicate(), timeout)
                timed_out = False
            except TimeoutError:
                await _kill_tree(process)
                stdout, timed_out = b"", True
        finally:
            self._running.discard(process)
        text = stdout.decode("utf-8", "replace")
        if len(text) > MAX_OUTPUT_CHARS:
            text = "…(earlier output trimmed)\n" + text[-MAX_OUTPUT_CHARS:]
        if self._stopped:
            text += "\n(Stopped by the owner.)"
        return (
            (process.returncode if process.returncode is not None else -1),
            text,
            timed_out,
        )

    def files(self, arguments: Mapping[str, object]) -> str:
        """Do one pc_files action (already decided and approved)."""
        action = str(arguments.get("action", ""))
        path = self.resolve(str(arguments.get("path", "")))
        if action == "list":
            if not path.is_dir():
                return f"{path} isn't a folder."
            rows = []
            for item in sorted(
                path.iterdir(),
                key=lambda entry: (not entry.is_dir(), entry.name.lower()),
            )[:MAX_LIST]:
                if self._protected_reason(item.resolve()):
                    continue
                size = "" if item.is_dir() else f" ({item.stat().st_size:,} bytes)"
                rows.append(f"{item.name}{'/' if item.is_dir() else ''}{size}")
            return "\n".join(rows) or f"{path} is empty."
        if action == "read":
            if not path.is_file():
                return f"There's no file at {path}."
            text = path.read_text(encoding="utf-8", errors="replace")
            return text[:MAX_READ_CHARS] + (
                "\n…(cut off)" if len(text) > MAX_READ_CHARS else ""
            )
        if action in {"write", "append"}:
            content = str(arguments.get("content", ""))
            if len(content) > MAX_WRITE_CHARS:
                return "That's too much to write at once."
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open(
                "a" if action == "append" else "w", encoding="utf-8"
            ) as handle:
                handle.write(content)
            return f"{'Added to' if action == 'append' else 'Wrote'} {path} ({len(content):,} characters)."
        if action == "mkdir":
            path.mkdir(parents=True, exist_ok=True)
            return f"Made the folder {path}."
        if action == "move":
            target = self.resolve(str(arguments.get("to", "")))
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(target))
            return f"Moved {path} to {target}."
        if action == "delete":
            if path.is_dir():
                shutil.rmtree(path)
            elif path.exists():
                path.unlink()
            else:
                return f"There's nothing at {path}."
            return f"Deleted {path}."
        return f"Unknown action {action}."

    # ── the activity log ──────────────────────────────────────────────────

    def log(self, who: str, text: str, **extra: object) -> None:
        entry = {
            "at": int(self._clock() * 1000),
            "who": who,
            "text": text[:2000],
            **extra,
        }
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry) + "\n")
        except OSError:
            pass

    def recent(self, limit: int = 100) -> list[JsonObject]:
        try:
            lines = self._log_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        if len(lines) > LOG_KEEP:
            self._log_path.write_text(
                "\n".join(lines[-LOG_KEEP:]) + "\n", encoding="utf-8"
            )
        rows: list[JsonObject] = []
        for line in lines[-limit:]:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        return rows

    def _read_state(self) -> JsonObject:
        try:
            value = json.loads(self._state_path.read_text(encoding="utf-8"))
        except OSError, ValueError:
            return {}
        return value if isinstance(value, dict) else {}

    def _save(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(
            json.dumps(
                {
                    "level": self._level,
                    "stopped": self._stopped,
                    "roots": [str(root) for root in self._roots],
                }
            ),
            encoding="utf-8",
        )


def _inside(path: Path, folder: Path) -> bool:
    try:
        path.relative_to(folder)
    except ValueError:
        return False
    return True


async def _kill_tree(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    if os.name == "nt":
        await asyncio.to_thread(
            subprocess.run,
            ["taskkill", "/T", "/F", "/PID", str(process.pid)],
            capture_output=True,
            check=False,
        )
    else:
        try:
            os.killpg(process.pid, 9)
        except ProcessLookupError, PermissionError:
            process.kill()
    try:
        await asyncio.wait_for(process.wait(), 10)
    except TimeoutError:
        process.kill()
