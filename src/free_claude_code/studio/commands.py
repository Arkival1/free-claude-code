"""Shell commands agents run inside their project, with the user's say-so."""

import asyncio
import os
import signal
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .models import CommandRequest, now_ms
from .store import StudioStore

APPROVAL_TIMEOUT_SECONDS = 600.0
MAX_OUTPUT_CHARS = 20_000
MAX_COMMAND_CHARS = 2_000
_SECRET_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "AUTH")


class CommandError(RuntimeError):
    """Raised when a command request cannot be made or decided."""


@dataclass(frozen=True, slots=True)
class CommandResult:
    """What running (or refusing) one command produced."""

    request: CommandRequest
    text: str


def scrubbed_environment(source: Mapping[str, str] | None = None) -> dict[str, str]:
    """Copy the environment without anything that looks like a credential.

    Agent-run code gets PATH and friends, but not the provider keys FCC holds.
    """
    env = dict(os.environ if source is None else source)
    return {
        key: value
        for key, value in env.items()
        if not any(marker in key.upper() for marker in _SECRET_MARKERS)
    }


async def execute(command: str, *, cwd: Path, timeout: float) -> tuple[int, str, bool]:
    """Run one shell command; return exit code, output tail, and timeout flag."""
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
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout)
        timed_out = False
    except TimeoutError:
        await _kill_tree(process, windows=windows)
        stdout = b""
        if process.stdout is not None:
            try:
                stdout = await asyncio.wait_for(process.stdout.read(), 5)
            except TimeoutError:
                stdout = b""
        timed_out = True
    text = stdout.decode("utf-8", "replace")
    if len(text) > MAX_OUTPUT_CHARS:
        text = "…(earlier output trimmed)\n" + text[-MAX_OUTPUT_CHARS:]
    code = process.returncode if process.returncode is not None else -1
    return code, text, timed_out


async def _kill_tree(process: asyncio.subprocess.Process, *, windows: bool) -> None:
    """Stop a command and everything it started (npm, dev servers, ...)."""
    if process.returncode is not None:
        return
    if windows:
        await asyncio.to_thread(
            subprocess.run,
            ["taskkill", "/T", "/F", "/PID", str(process.pid)],
            capture_output=True,
            check=False,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
    try:
        await asyncio.wait_for(process.wait(), 10)
    except TimeoutError:
        process.kill()


class CommandBroker:
    """Queue agent commands for approval, run approved ones, and record both."""

    def __init__(self, *, store: StudioStore) -> None:
        self._store = store
        self._waiting: dict[str, asyncio.Future[bool]] = {}

    async def request(
        self,
        *,
        agent_id: str,
        agent_name: str,
        chat_id: str,
        site_id: str,
        command: str,
        cwd: Path,
        policy: str,
        timeout: float,
    ) -> CommandResult:
        """Ask for (or skip) approval, run the command, and report the outcome."""
        cleaned = command.strip()
        if not cleaned:
            raise CommandError("A command is required.")
        if len(cleaned) > MAX_COMMAND_CHARS:
            raise CommandError("That command is too long.")
        if policy not in {"ask", "auto"}:
            raise CommandError("Running commands is turned off in Studio settings.")
        request = CommandRequest.model_validate(
            {
                "agent_id": agent_id,
                "chat_id": chat_id,
                "site_id": site_id,
                "command": cleaned,
                "status": "pending" if policy == "ask" else "approved",
            }
        )
        if policy == "ask":
            # Register the wait before the request is visible: pending() expires
            # any stored request nobody is waiting on, so a poll landing between
            # the two would otherwise expire this one.
            future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
            self._waiting[request.id] = future
            try:
                await self._store.put(request)
                await self._store.append_message(
                    chat_id=chat_id,
                    role="event",
                    text=f"{agent_name} wants to run: {cleaned}",
                    author="studio",
                    data={
                        "kind": "approval",
                        "request_id": request.id,
                        "command": cleaned,
                    },
                )
                approved = await asyncio.wait_for(future, APPROVAL_TIMEOUT_SECONDS)
            except TimeoutError:
                expired = await self._set(request, status="expired")
                return CommandResult(
                    expired, "Nobody approved the command in time, so it did not run."
                )
            finally:
                self._waiting.pop(request.id, None)
            if not approved:
                denied = await self._store.require(CommandRequest, request.id)
                return CommandResult(
                    denied, "The user denied this command. Try another approach or ask."
                )
        else:
            await self._store.put(request)
        cwd.mkdir(parents=True, exist_ok=True)
        code, output, timed_out = await execute(cleaned, cwd=cwd, timeout=timeout)
        ran = await self._set(
            await self._store.require(CommandRequest, request.id),
            status="ran",
            exit_code=code,
            output=output,
        )
        note = f" (stopped after {int(timeout)}s)" if timed_out else ""
        await self._store.append_message(
            chat_id=chat_id,
            role="event",
            text=f"$ {cleaned}\nexit {code}{note}",
            author="studio",
            data={"kind": "command_ran", "request_id": request.id, "exit_code": code},
        )
        header = f"exit code {code}{note}"
        return CommandResult(ran, f"{header}\n{output}".rstrip())

    async def decide(self, request_id: str, *, approve: bool) -> CommandRequest:
        """Record the user's decision and wake the waiting agent."""
        request = await self._store.require(CommandRequest, request_id)
        if request.status != "pending":
            raise CommandError(f"This command is already {request.status}.")
        future = self._waiting.get(request_id)
        if future is None:
            await self._set(request, status="expired")
            raise CommandError("That request expired; the agent is no longer waiting.")
        updated = await self._set(request, status="approved" if approve else "denied")
        if not future.done():
            future.set_result(approve)
        return updated

    async def pending(self) -> tuple[CommandRequest, ...]:
        """Return requests still waiting for the user, newest first."""
        waiting = await self._store.find(
            CommandRequest, where={"status": "pending"}, order_by="created_at DESC"
        )
        live = [item for item in waiting if item.id in self._waiting]
        for stale in (item for item in waiting if item.id not in self._waiting):
            await self._set(stale, status="expired")
        return tuple(live)

    async def _set(self, request: CommandRequest, **values: object) -> CommandRequest:
        updated = request.model_copy(update={**values, "decided_at": now_ms()})
        await self._store.put(updated)
        return updated
