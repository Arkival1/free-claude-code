"""FCC Phone: pair a phone with this PC, share memory, and lend it the PC's brain.

The phone app runs on its own (its own agents, memory, and AI); pairing only
adds a link. A pairing code shown on the PC is typed into the phone once and
traded for a secret the phone keeps; this PC stores only its hash. After that
the phone sends its memories here, gets the PC's team memory back, and can
think with the main AI's model on this PC.
"""

import asyncio
import hashlib
import json
import os
import secrets
import shutil
import time
from collections.abc import Callable, Sequence

from free_claude_code.core.json_types import JsonObject, JsonValue

from .llm import ChatMessage, LLMReply, ToolCall, ToolSpec
from .models import PhoneLink, now_ms
from .store import StudioStore

PAIR_SECONDS = 600
"""How long a pairing code works."""
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
"""No 0/O or 1/I/L, so a code read off a screen is typed right."""
MAX_WRONG_CODES = 10
"""Wrong codes in a row before every waiting code is cancelled."""
MAX_SYNC = 500
"""Memories one sync may send."""
MAX_MEMORY_CHARS = 2_000
MAX_PULL = 1_000
"""Newest PC memories sent back to the phone."""
MAX_MESSAGES = 80
MAX_PROMPT_CHARS = 80_000
MAX_TOOLS = 24
MAX_REPLY_TOKENS = 1_500
PHONE_TAG = "phone"
"""Tag on memories that came from a phone."""


_TAILSCALE_PROGRAMS = (
    "tailscale",
    r"C:\Program Files\Tailscale\tailscale.exe",
    "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
)


async def tailscale_address(*, timeout: float = 4.0) -> str | None:
    """This PC's https://….ts.net address when Tailscale runs here, else None.

    A phone app on another https origin can only reach this PC over HTTPS,
    and ``tailscale serve`` gives it exactly that address.
    """
    for program in _TAILSCALE_PROGRAMS:
        if os.sep in program and not os.path.exists(program):
            continue
        if os.sep not in program and shutil.which(program) is None:
            continue
        try:
            process = await asyncio.create_subprocess_exec(
                program,
                "status",
                "--json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                stdin=asyncio.subprocess.DEVNULL,
            )
            output, _ = await asyncio.wait_for(process.communicate(), timeout)
        except OSError, TimeoutError:
            continue
        try:
            status = json.loads(output or b"{}")
        except ValueError:
            continue
        me = status.get("Self") if isinstance(status, dict) else None
        name = str(me.get("DNSName") or "").rstrip(".") if isinstance(me, dict) else ""
        if name:
            return f"https://{name}"
    return None


class PhoneLinkError(Exception):
    """A phone request that can't be carried out, in plain words."""


class PhoneAuthError(PhoneLinkError):
    """The phone's secret is missing, wrong, or its link was removed."""


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def clean_code(code: str) -> str:
    """'abcd 2345', 'ABCD-2345' and 'abcd2345' are the same code."""
    return "".join(ch for ch in code.upper() if ch in CODE_ALPHABET)


class PhoneLinks:
    """Pairing codes and the phones paired with this PC."""

    def __init__(
        self, store: StudioStore, *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._store = store
        self._clock = clock
        self._codes: dict[str, float] = {}
        self._wrong = 0

    def new_code(self) -> str:
        """A fresh single-use code, shown on the PC as ABCD-2345."""
        self._forget_old()
        raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        self._codes[raw] = self._clock() + PAIR_SECONDS
        return f"{raw[:4]}-{raw[4:]}"

    def _forget_old(self) -> None:
        now = self._clock()
        for code, expires in list(self._codes.items()):
            if expires <= now:
                del self._codes[code]

    async def pair(self, code: str, name: str) -> tuple[PhoneLink, str]:
        """Trade a code for a link and the secret only the phone keeps."""
        self._forget_old()
        raw = clean_code(code)
        if raw not in self._codes:
            self._wrong += 1
            if self._wrong >= MAX_WRONG_CODES:
                # Someone may be guessing: every waiting code stops working.
                self._codes.clear()
                self._wrong = 0
            raise PhoneLinkError(
                "That pairing code didn't work. Make a new one on the PC "
                "(More, Connect your phone) and type it within 10 minutes."
            )
        del self._codes[raw]
        self._wrong = 0
        token = secrets.token_urlsafe(32)
        link = PhoneLink(
            name=" ".join(name.split())[:60] or "Phone", token_hash=token_hash(token)
        )
        await self._store.put(link)
        return link, token

    async def check(self, token: str) -> PhoneLink:
        """The link this secret belongs to, or PhoneAuthError."""
        if not token:
            raise PhoneAuthError("This phone isn't paired with the PC.")
        found = await self._store.find(
            PhoneLink, where={"token_hash": token_hash(token)}
        )
        if not found:
            raise PhoneAuthError(
                "The PC doesn't know this phone any more. Pair it again."
            )
        link = found[0]
        now = now_ms()
        if now - link.last_seen > 60_000:
            link = link.model_copy(update={"last_seen": now, "updated_at": now})
            await self._store.put(link)
        return link

    async def links(self) -> tuple[PhoneLink, ...]:
        return await self._store.find(PhoneLink, order_by="created_at ASC")

    async def unlink(self, link_id: str) -> bool:
        return await self._store.delete(PhoneLink, link_id)

    async def note_sync(self, link: PhoneLink, stored: int) -> PhoneLink:
        now = now_ms()
        updated = link.model_copy(
            update={
                "last_sync": now,
                "last_seen": now,
                "memories_in": link.memories_in + stored,
                "updated_at": now,
            }
        )
        await self._store.put(updated)
        return updated


def link_view(link: PhoneLink) -> JsonObject:
    return link.model_dump(exclude={"token_hash"})


def incoming_memories(raw: JsonValue) -> list[tuple[str, str]]:
    """(agent name, text) for each memory a phone sent, capped and cleaned."""
    if not isinstance(raw, list):
        raise PhoneLinkError("Send memories as a list.")
    if len(raw) > MAX_SYNC:
        raise PhoneLinkError(f"Send at most {MAX_SYNC} memories at a time.")
    found: list[tuple[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()[:MAX_MEMORY_CHARS]
        agent = " ".join(str(item.get("agent") or "Phone").split())[:40] or "Phone"
        if text:
            found.append((agent, text))
    return found


def chat_messages(raw: JsonValue) -> list[ChatMessage]:
    """OpenAI-style messages from the phone as Studio's neutral turns."""
    if not isinstance(raw, list) or not raw:
        raise PhoneLinkError("Send at least one message.")
    if len(raw) > MAX_MESSAGES:
        raise PhoneLinkError(f"Send at most {MAX_MESSAGES} messages.")
    turns: list[ChatMessage] = []
    size = 0
    for item in raw:
        if not isinstance(item, dict):
            raise PhoneLinkError("Each message needs a role and content.")
        role = item.get("role")
        content = item.get("content")
        text = content if isinstance(content, str) else ""
        size += len(text)
        if role == "user":
            turns.append(ChatMessage.user(text))
        elif role == "assistant":
            turns.append(
                ChatMessage(
                    role="assistant",
                    content=text,
                    tool_calls=_tool_calls(item.get("tool_calls")),
                )
            )
        elif role == "tool":
            turns.append(
                ChatMessage(
                    role="tool",
                    content=text,
                    tool_call_id=str(item.get("tool_call_id") or ""),
                )
            )
        else:
            raise PhoneLinkError(f"Unknown message role {role!r}.")
    if size > MAX_PROMPT_CHARS:
        raise PhoneLinkError("That conversation is too long to send in one go.")
    return turns


def _tool_calls(raw: JsonValue) -> tuple[ToolCall, ...]:
    if not isinstance(raw, list):
        return ()
    calls: list[ToolCall] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        function = item.get("function")
        if not isinstance(function, dict):
            continue
        arguments = function.get("arguments")
        parsed: JsonValue = arguments
        if isinstance(arguments, str):
            try:
                parsed = json.loads(arguments or "{}")
            except ValueError:
                parsed = {}
        calls.append(
            ToolCall(
                id=str(item.get("id") or ""),
                name=str(function.get("name") or ""),
                arguments=parsed if isinstance(parsed, dict) else {},
            )
        )
    return tuple(calls)


def tool_specs(raw: JsonValue) -> list[ToolSpec]:
    """OpenAI-style function tools from the phone."""
    if raw is None:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_TOOLS:
        raise PhoneLinkError(f"Send at most {MAX_TOOLS} tools.")
    specs: list[ToolSpec] = []
    for item in raw:
        function = item.get("function") if isinstance(item, dict) else None
        if not isinstance(function, dict) or not function.get("name"):
            continue
        parameters = function.get("parameters")
        specs.append(
            ToolSpec(
                name=str(function["name"])[:64],
                description=str(function.get("description") or "")[:1_000],
                parameters=parameters
                if isinstance(parameters, dict)
                else {"type": "object", "properties": {}},
            )
        )
    return specs


def reply_json(reply: LLMReply) -> JsonObject:
    calls: Sequence[JsonValue] = [
        {"id": call.id, "name": call.name, "arguments": call.arguments}
        for call in reply.tool_calls
    ]
    return {"text": reply.text, "tool_calls": list(calls), "model": reply.model}
