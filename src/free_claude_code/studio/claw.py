"""Claw Code on this PC: built from FCC's own copy, run through FCC.

FCC keeps Claw Code's source under ``vendor/claw-code`` (upstream publishes
no release binaries). Studio unpacks it into its own folder, builds the
``claw`` command with the user's Rust toolchain, and opens it in a terminal
connected to the FCC proxy, so it thinks with the models FCC is set to use,
local ones included. Nothing comes from GitHub, so it keeps working if the
original repo is deleted.
"""

import asyncio
import contextlib
import hashlib
import os
import shlex
import shutil
import subprocess
import sys
import threading
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from free_claude_code.core.json_types import JsonObject

VENDOR = Path(__file__).resolve().parents[3] / "vendor" / "claw-code"
COMMIT = "08106b0"
SOURCE_ZIP = f"claw-code-src-{COMMIT}.zip"
BUILD_COMMAND = ("build", "--release", "--locked", "-p", "rusty-claude-cli")
BUILD_TIMEOUT = 90 * 60
LOG_LINES = 60
RUST_HELP = (
    "Claw Code is built with Rust. Install it once from https://rustup.rs "
    "(on Windows run rustup-init.exe and accept the Visual Studio build tools "
    "it offers), then press Build again."
)


class ClawError(RuntimeError):
    """Raised when Claw Code can't be built or opened."""


def binary_name() -> str:
    return "claw.exe" if sys.platform == "win32" else "claw"


def find_cargo() -> str | None:
    """Rust's cargo: on PATH, or where rustup puts it."""
    found = shutil.which("cargo")
    if found:
        return found
    home = Path(os.environ.get("CARGO_HOME") or Path.home() / ".cargo")
    candidate = home / "bin" / ("cargo.exe" if sys.platform == "win32" else "cargo")
    return str(candidate) if candidate.is_file() else None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def expected_checksum(vendor: Path) -> str:
    sums = vendor / "SHA256SUMS"
    for line in sums.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == SOURCE_ZIP:
            return parts[0].lower()
    raise ClawError(f"{SOURCE_ZIP} has no checksum in {sums.name}.")


def unpack(archive: Path, target: Path) -> Path:
    """Unpack the source into target (safely: no paths outside it) and return
    the Rust workspace folder."""
    target.mkdir(parents=True, exist_ok=True)
    root = target.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            path = (root / member.filename).resolve()
            if not path.is_relative_to(root):
                raise ClawError(f"Unsafe path in the source zip: {member.filename}")
            if member.is_dir():
                path.mkdir(parents=True, exist_ok=True)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(bundle.read(member))
    workspace = root / "claw-code" / "rust"
    if not (workspace / "Cargo.toml").is_file():
        raise ClawError("The Claw Code source zip has no Rust workspace.")
    return workspace


@dataclass(slots=True)
class BuildState:
    state: str = "idle"
    """idle, building, built, or failed."""
    error: str = ""
    log: list[str] = field(default_factory=list)

    def add(self, line: str) -> None:
        line = line.rstrip()
        if line:
            self.log = [*self.log[-(LOG_LINES - 1) :], line]


Runner = Callable[[Sequence[str], Path, BuildState], int]
"""Run a build command in a folder, adding its output to the state's log;
returns the exit code (runs on a thread)."""


def run_logged(command: Sequence[str], cwd: Path, state: BuildState) -> int:
    with subprocess.Popen(
        list(command),
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
    ) as process:
        # Reading the output blocks until cargo ends, so a timer stops a build
        # that hangs (a stuck download, a locked registry).
        stopped = threading.Event()

        def stop() -> None:
            stopped.set()
            process.kill()

        timer = threading.Timer(BUILD_TIMEOUT, stop)
        timer.start()
        try:
            assert process.stdout is not None
            for line in process.stdout:
                state.add(line)
            code = process.wait()
        finally:
            timer.cancel()
        if stopped.is_set():
            state.add("The build took too long and was stopped.")
            return 1
        return code


class ClawCode:
    """Build Claw Code from FCC's copy and open it connected to FCC."""

    def __init__(
        self,
        root: Path,
        *,
        vendor: Path = VENDOR,
        cargo: Callable[[], str | None] = find_cargo,
        runner: Runner = run_logged,
    ) -> None:
        self._root = root
        self._vendor = vendor
        self._cargo = cargo
        self._runner = runner
        self.build_state = BuildState()
        self._task: asyncio.Task[None] | None = None

    @property
    def binary(self) -> Path:
        return self._root / "bin" / binary_name()

    @property
    def archive(self) -> Path:
        return self._vendor / SOURCE_ZIP

    def bundled(self) -> bool:
        try:
            return self.archive.is_file() and sha256(self.archive) == expected_checksum(
                self._vendor
            )
        except OSError, ClawError:
            return False

    def status(self) -> JsonObject:
        built = self.binary.is_file()
        state = self.build_state.state
        if state == "idle" and built:
            state = "built"
        return {
            "bundled": self.bundled(),
            "commit": COMMIT,
            "rust": self._cargo() is not None,
            "built": built,
            "binary": str(self.binary) if built else "",
            "state": state,
            "error": self.build_state.error,
            "log": self.build_state.log[-20:],
            "rust_help": RUST_HELP,
        }

    def start_build(self) -> JsonObject:
        """Build in the background; the status shows how it is going."""
        if self._task is not None and not self._task.done():
            return self.status()
        if not self.bundled():
            raise ClawError(
                "FCC's copy of Claw Code is missing or damaged: reinstall FCC "
                "(vendor/claw-code)."
            )
        cargo = self._cargo()
        if cargo is None:
            raise ClawError(RUST_HELP)
        self.build_state = BuildState(state="building")
        self._task = asyncio.get_running_loop().create_task(self._build(cargo))
        return self.status()

    async def wait(self) -> None:
        if self._task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _build(self, cargo: str) -> None:
        state = self.build_state
        try:
            source = self._root / f"src-{COMMIT}"
            state.add(f"Unpacking Claw Code ({COMMIT}) from FCC's copy…")
            workspace = await asyncio.to_thread(unpack, self.archive, source)
            state.add("Building with cargo (the first build takes a few minutes)…")
            code = await asyncio.to_thread(
                self._runner, (cargo, *BUILD_COMMAND), workspace, state
            )
            built = workspace / "target" / "release" / binary_name()
            if code != 0 or not built.is_file():
                raise ClawError(
                    f"cargo stopped with code {code}: see the log for the reason."
                )
            self.binary.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(shutil.copy2, built, self.binary)
            state.state = "built"
            state.add(f"Built: {self.binary}")
        except (ClawError, OSError, zipfile.BadZipFile) as error:
            state.state = "failed"
            state.error = str(error)
            state.add(str(error))
            logger.info("Studio: Claw Code build failed: {}", error)

    def open_terminal(self, folder: Path) -> list[str]:
        """Open Claw Code in a new terminal window, working in folder."""
        if not self.binary.is_file():
            raise ClawError("Build Claw Code first.")
        if not folder.is_dir():
            raise ClawError(f"There is no folder at {folder}.")
        launch = [sys.executable, "-m", "free_claude_code.cli.launchers.claw"]
        command = terminal_command(launch, folder)
        subprocess.Popen(command, cwd=folder)
        return command


def terminal_command(launch: Sequence[str], folder: Path) -> list[str]:
    """A command that opens a visible terminal window running launch."""
    if sys.platform == "win32":
        return ["cmd", "/c", "start", "Claw Code", "cmd", "/k", *launch]
    if sys.platform == "darwin":
        return [
            "osascript",
            "-e",
            "on run argv",
            "-e",
            'tell application "Terminal" to do script "cd " & quoted form of '
            '(item 1 of argv) & " && " & (item 2 of argv)',
            "-e",
            "end run",
            str(folder),
            shlex.join(launch),
        ]
    # Each terminal's own way of running a command with its arguments.
    for terminal, flag in (
        ("gnome-terminal", "--"),
        ("konsole", "-e"),
        ("xfce4-terminal", "-x"),
        ("xterm", "-e"),
        ("x-terminal-emulator", "-e"),
    ):
        found = shutil.which(terminal)
        if found:
            return [found, flag, *launch]
    raise ClawError("No terminal app found: run fcc-claw in a terminal instead.")
