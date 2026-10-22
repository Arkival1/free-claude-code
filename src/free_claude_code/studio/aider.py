"""Aider as a helper coder: one job, in one project folder, with no keys.

Aider (``aider-chat``, Apache 2.0, https://github.com/Aider-AI/aider) is a
command-line coding assistant that edits the files it is given. FCC doesn't
bundle or install it: the owner installs it once (``uv tool install
aider-chat``) and then agents can hand it a job. FCC runs it:

- only in a project folder or the Changer's copy, never the running app;
- with an empty home folder and none of the owner's keys: it talks to FCC's
  own OpenAI-style address (server models, through FCC's routing) or to the
  model server on this PC, so it never sees a provider key;
- with git, commits, shell commands, link reading, linting, tests, analytics
  and update checks off, and its history files outside the project;
- after the same Ask/Auto approval as any command an agent runs.
"""

import asyncio
import os
import re
import shutil
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .commands import kill_tree, scrubbed_environment

AIDER_SECONDS = 900.0
MAX_AIDER_FILES = 12
MAX_AIDER_OUTPUT = 4000
MAX_AIDER_MESSAGE = 8000
AIDER_INSTALL = (
    "Aider isn't installed on this PC. FCC doesn't bundle it; to use it, run "
    "once: uv tool install aider-chat (or: pipx install aider-chat), then "
    "restart FCC."
)
SKIP_DIRS = frozenset(
    {".git", ".venv", "venv", "node_modules", "__pycache__", ".aider.tags.cache.v4"}
)
_OWN_VARIABLES = ("AIDER_", "OPENAI_", "ANTHROPIC_", "LITELLM_", "GEMINI_")
"""Settings of the owner's own Aider or AI tools that would change the job."""
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
JOB_NOTE = (
    "Do this job in the files listed. Match the style of the code around "
    "your change, write complete code (no placeholders or TODOs), and keep "
    "changes small and focused. Don't touch other files unless the job needs "
    "a new one."
)


class AiderError(RuntimeError):
    """The job can't be given to Aider as asked."""


@dataclass(frozen=True, slots=True)
class AiderJob:
    folder: Path
    message: str
    files: tuple[str, ...]
    model: str
    """The wire model id at ``base_url``."""
    base_url: str
    api_key: str
    edit_format: str = "diff"


@dataclass(slots=True)
class AiderResult:
    code: int
    output: str
    timed_out: bool = False
    changed: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)

    @property
    def touched(self) -> list[str]:
        return [*self.changed, *self.added, *self.deleted]


def find_aider() -> str | None:
    """Aider's program: on PATH, or where ``uv tool``/``pipx`` put it."""
    found = shutil.which("aider")
    if found:
        return found
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    for folder in (home / ".local" / "bin", home / ".local" / "pipx" / "bin"):
        for name in ("aider.exe", "aider"):
            candidate = folder / name
            if candidate.is_file():
                return str(candidate)
    return None


def job_files(folder: Path, raw: Sequence[str]) -> tuple[str, ...]:
    """The files Aider may edit: relative paths inside the folder, at most
    MAX_AIDER_FILES, none in .git or a virtual environment."""
    root = folder.resolve()
    chosen: list[str] = []
    for item in raw:
        relative = str(item).strip().replace("\\", "/")
        while relative.startswith("./"):
            relative = relative[2:]
        if not relative:
            continue
        path = (root / relative).resolve()
        parts = Path(relative).parts
        if (
            Path(relative).is_absolute()
            or ".." in parts
            or not path.is_relative_to(root)
            or path == root
            or SKIP_DIRS & set(parts)
        ):
            raise AiderError(f"{item}: give a file inside the project.")
        if path.is_dir():
            raise AiderError(f"{item} is a folder; name the files to change.")
        if relative not in chosen:
            chosen.append(relative)
    if not chosen:
        raise AiderError("Name the files Aider should change (files: [...]).")
    if len(chosen) > MAX_AIDER_FILES:
        raise AiderError(
            f"Give Aider at most {MAX_AIDER_FILES} files at a time; split the job."
        )
    return tuple(chosen)


def aider_command(aider: str, job: AiderJob, scratch: Path) -> list[str]:
    """The command: one message, no git, no shell, no extras, history kept
    in ``scratch`` (outside the project)."""
    return [
        aider,
        "--model",
        f"openai/{job.model}",
        "--edit-format",
        job.edit_format,
        "--message-file",
        str(scratch / "job.txt"),
        "--yes-always",
        "--no-git",
        "--no-auto-commits",
        "--no-gitignore",
        "--no-analytics",
        "--no-check-update",
        "--no-suggest-shell-commands",
        "--no-detect-urls",
        "--no-auto-lint",
        "--no-auto-test",
        "--no-pretty",
        "--no-stream",
        "--no-fancy-input",
        "--no-show-model-warnings",
        "--no-restore-chat-history",
        "--map-tokens",
        "0",
        "--timeout",
        "300",
        "--env-file",
        str(scratch / "none.env"),
        "--input-history-file",
        str(scratch / "input.history"),
        "--chat-history-file",
        str(scratch / "chat.history.md"),
        "--",
        *job.files,
    ]


def aider_env(job: AiderJob, scratch: Path) -> dict[str, str]:
    """No keys from FCC's environment, no settings of the owner's own Aider,
    an empty home folder, and only the address and key of the model."""
    env = {
        name: value
        for name, value in scrubbed_environment().items()
        if not name.upper().startswith(_OWN_VARIABLES)
    }
    env.update(
        {
            "HOME": str(scratch),
            "USERPROFILE": str(scratch),
            "OPENAI_API_BASE": job.base_url,
            "OPENAI_API_KEY": job.api_key,
            "NO_COLOR": "1",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    return env


def shown_command(job: AiderJob) -> str:
    """What the owner is asked to approve."""
    return (
        f"aider --model openai/{job.model} --message-file job.txt "
        f"{' '.join(job.files)}  (no git, no shell commands, no keys)"
    )


def snapshot(folder: Path) -> dict[str, tuple[int, int]]:
    """Each file's size and change time, to tell what Aider changed."""
    found: dict[str, tuple[int, int]] = {}
    root = folder.resolve()
    for current, dirs, files in os.walk(root):
        dirs[:] = [name for name in dirs if name not in SKIP_DIRS]
        for name in files:
            path = Path(current) / name
            try:
                stat = path.stat()
            except OSError:
                continue
            found[path.relative_to(root).as_posix()] = (stat.st_size, stat.st_mtime_ns)
    return found


async def run_aider(
    job: AiderJob, *, aider: str, timeout: float = AIDER_SECONDS
) -> AiderResult:
    """Run one job and say which files it changed."""
    scratch = Path(tempfile.mkdtemp(prefix="fcc-aider-"))
    try:
        (scratch / "job.txt").write_text(
            f"{JOB_NOTE}\n\n{job.message.strip()[:MAX_AIDER_MESSAGE]}",
            encoding="utf-8",
        )
        (scratch / "none.env").write_text("", encoding="utf-8")
        before = await asyncio.to_thread(snapshot, job.folder)
        own = {path.name for path in job.folder.iterdir()}
        windows = os.name == "nt"
        try:
            process = await asyncio.create_subprocess_exec(
                *aider_command(aider, job, scratch),
                cwd=str(job.folder),
                env=aider_env(job, scratch),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=not windows,
            )
        except OSError as error:
            return AiderResult(code=127, output=f"Aider didn't start: {error}")
        timed_out = False
        try:
            raw, _ = await asyncio.wait_for(process.communicate(), timeout)
        except TimeoutError:
            await kill_tree(process, windows=windows)
            raw, timed_out = b"", True
        _tidy(job.folder, own)
        after = await asyncio.to_thread(snapshot, job.folder)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    output = _ANSI.sub("", raw.decode("utf-8", "replace")).strip()
    if len(output) > MAX_AIDER_OUTPUT:
        output = "…(earlier output trimmed)\n" + output[-MAX_AIDER_OUTPUT:]
    if timed_out:
        output = f"Stopped after {int(timeout)} seconds.\n{output}".strip()
    code = process.returncode if process.returncode is not None else -1
    return AiderResult(
        code=code,
        output=output,
        timed_out=timed_out,
        changed=sorted(
            n for n in before.keys() & after.keys() if before[n] != after[n]
        ),
        added=sorted(after.keys() - before.keys()),
        deleted=sorted(before.keys() - after.keys()),
    )


def _tidy(folder: Path, own: set[str]) -> None:
    """Remove Aider's own files (.aider*) it left in the project."""
    for path in folder.iterdir():
        if path.name.startswith(".aider") and path.name not in own:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)


def report(result: AiderResult) -> str:
    """The tool's answer to the agent."""
    lines = [
        f"Aider finished (exit {result.code}"
        f"{', timed out' if result.timed_out else ''})."
    ]
    for label, names in (
        ("Changed", result.changed),
        ("Added", result.added),
        ("Deleted", result.deleted),
    ):
        if names:
            lines.append(f"{label}: {', '.join(names[:20])}")
    if not result.touched:
        lines.append("No file changed.")
    else:
        lines.append(
            "Read the changed files and check them before you finish: Aider's "
            "work is a draft until it passes the checks."
        )
    if result.output:
        lines.append(f"Aider's output:\n{result.output}")
    return "\n".join(lines)
