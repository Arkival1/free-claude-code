"""One chat surface over the FCC proxy and over local OpenAI-style servers."""

import contextlib
import json
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol

import httpx

from free_claude_code.core.json_types import JsonObject

from .model_turns import ModelTurns

LOCAL_MODEL_PREFIX = "local/"
"""Model references routed to the configured on-device server."""


class StudioLLMError(RuntimeError):
    """Raised when a model call cannot produce a usable reply."""


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A model's request to run one tool with decoded arguments."""

    id: str
    name: str
    arguments: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """One neutral conversation turn shared by both transports."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None

    @classmethod
    def user(cls, content: str) -> ChatMessage:
        return cls(role="user", content=content)

    @classmethod
    def assistant(cls, content: str) -> ChatMessage:
        return cls(role="assistant", content=content)

    @classmethod
    def system(cls, content: str) -> ChatMessage:
        return cls(role="system", content=content)


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """A tool offered to the model, described once for both wire formats."""

    name: str
    description: str
    parameters: JsonObject


@dataclass(frozen=True, slots=True)
class LLMReply:
    """The complete result of one non-streaming model call."""

    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    model: str = ""
    stop_reason: str = ""
    usage: JsonObject = field(default_factory=dict)


class LLMClient(Protocol):
    """Complete one model call and retain no response resource."""

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        system: str = "",
        tools: Sequence[ToolSpec] = (),
        temperature: float = 0.2,
        max_tokens: int = 1024,
        model: str | None = None,
    ) -> LLMReply: ...


NO_THINK_SWITCH = "/no_think"
_THINKING = re.compile(r"<think>.*?(?:</think>|$)", re.DOTALL | re.IGNORECASE)


def strip_thinking(text: str) -> str:
    """Drop a reasoning model's <think> section, keeping only its answer."""
    lowered = text.lower()
    if "<think>" not in lowered:
        # Some templates open the section in the prompt; keep what follows it.
        end = lowered.rfind("</think>")
        return text[end + len("</think>") :].strip() if end >= 0 else text.strip()
    return _THINKING.sub("", text).strip()


def tool_protocol_instructions(tools: Sequence[ToolSpec]) -> str:
    """Describe the text tool protocol used by models without tool support."""
    if not tools:
        return ""
    lines = [
        "You can use tools. To call one, reply with a single JSON object and "
        "nothing else:",
        '{"tool": "<name>", "arguments": {...}}',
        'When the work is finished, reply with: {"final": "<your answer>"}',
        "To write a file, leave content out of the JSON and put the whole file "
        "in a fenced code block right after it, with no escaping:",
        '{"tool": "write_file", "arguments": {"path": "index.html"}}',
        "```html",
        "<!doctype html>...",
        "```",
        "To use several tools that do not depend on each other, reply with a "
        "JSON array of these objects; they run together, which is faster.",
        "Available tools:",
    ]
    lines.extend(
        f"- {tool.name}: {tool.description}{_arguments_line(tool.parameters)}"
        for tool in tools
    )
    return "\n".join(lines)


def _arguments_line(parameters: Mapping[str, object]) -> str:
    """The arguments in a few words each, e.g. 'path (text, required)'.

    Says what the JSON schema says in about a third fewer tokens, so a local
    model reads the tool list faster.
    """
    properties = parameters.get("properties")
    if not isinstance(properties, Mapping) or not properties:
        return " Arguments: none."
    required = parameters.get("required")
    needed = set(required) if isinstance(required, list) else set()
    parts = []
    for name, spec in properties.items():
        info = spec if isinstance(spec, Mapping) else {}
        kind = _kind(info)
        note = ", required" if name in needed else ""
        about = str(info.get("description") or "").strip().rstrip(".")
        parts.append(f"{name} ({kind}{note})" + (f": {about}" if about else ""))
    return " Arguments: " + "; ".join(parts) + "."


def _kind(info: Mapping[str, object]) -> str:
    choices = info.get("enum")
    if isinstance(choices, list) and choices:
        return "one of " + "|".join(str(choice) for choice in choices)
    kind = info.get("type")
    if kind == "array":
        items = info.get("items")
        inner = _kind(items) if isinstance(items, Mapping) else "value"
        return f"list of {inner}"
    return {
        "string": "text",
        "integer": "whole number",
        "number": "number",
        "boolean": "true/false",
        "object": "object",
    }.get(str(kind), "value")


_OPENING = re.compile(r'\[\s*\{\s*"(?:tool|name)"|\{\s*"(?:tool|final|name)"')
_FENCE = re.compile(r"```([\w.+#-]*)[ \t]*\n(.*?)\n?[ \t]*```", re.DOTALL)
_ESCAPE = re.compile(r'\\(["\\/bfnrt]|u[0-9a-fA-F]{4})')
_ESCAPED = {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
# Small models often put real line breaks inside JSON strings; accept them.
_LENIENT = json.JSONDecoder(strict=False)
FILE_TOOLS = frozenset({"write_file"})
"""Tools whose file text may come in a code block after the JSON."""


def parse_tool_directives(text: str) -> tuple[tuple[ToolCall, ...], str | None]:
    """Return every tool call in a text-protocol reply, or its final answer.

    One JSON value is read exactly where it starts, so code that follows it
    (a stylesheet's braces, say) never spoils it. A write_file call may leave
    out "content" and put the file in a fenced code block after the JSON,
    which spares a small model from escaping a whole web page.
    """
    calls, final, end = _first_directive(text)
    if final is not None:
        return (), final
    if not calls:
        salvaged = _salvaged_write(text)
        return ((salvaged,) if salvaged is not None else ()), None
    return _with_fenced_content(calls, text[end:]), None


def parse_tool_directive(text: str) -> tuple[ToolCall | None, str | None]:
    """Return the first text-protocol tool call, a final answer, or neither."""
    calls, final = parse_tool_directives(text)
    return (calls[0] if calls else None), final


def unreadable_tool_call(text: str) -> bool:
    """True when a reply tried to call a tool but it could not be read."""
    stripped = strip_thinking(text).strip()
    if not stripped:
        return False
    calls, final = parse_tool_directives(stripped)
    if calls or final is not None:
        return False
    return bool(re.search(r'"(?:tool|arguments)"\s*:', stripped))


def _first_directive(text: str) -> tuple[list[ToolCall], str | None, int]:
    for match in _OPENING.finditer(text):
        try:
            value, end = _LENIENT.raw_decode(text, match.start())
        except ValueError:
            continue
        if isinstance(value, dict) and isinstance(value.get("final"), str):
            return [], value["final"], end
        items = value if isinstance(value, list) else [value]
        seed = text[match.start() : end]
        calls = [
            call
            for index, item in enumerate(items)
            if (call := _directive_call(item, f"{index}:{seed}")) is not None
        ]
        if calls:
            return calls, None, end
    return [], None, -1


def _directive_call(payload: object, seed: str) -> ToolCall | None:
    if not isinstance(payload, dict):
        return None
    name = payload.get("tool") or payload.get("name")
    if not isinstance(name, str) or not name:
        return None
    arguments = payload.get("arguments") or payload.get("input") or {}
    return ToolCall(
        id=f"text_{abs(hash(seed)) % 10**8}",
        name=name,
        arguments=arguments if isinstance(arguments, dict) else {},
    )


def _with_fenced_content(calls: list[ToolCall], after: str) -> tuple[ToolCall, ...]:
    """Fill write_file calls from the code blocks that follow the JSON."""
    blocks = [
        body
        for language, body in _FENCE.findall(after)
        if language.lower() != "json" and body.strip()
    ]
    filled: list[ToolCall] = []
    for call in calls:
        content = call.arguments.get("content")
        wants = call.name in FILE_TOOLS and (
            not isinstance(content, str)
            or not content.strip()
            or (blocks and len(blocks[0]) > len(content))
        )
        if wants and blocks:
            call = ToolCall(
                id=call.id,
                name=call.name,
                arguments={**call.arguments, "content": blocks.pop(0)},
            )
        filled.append(call)
    return tuple(filled)


def _salvaged_write(text: str) -> ToolCall | None:
    """Recover a write_file call whose JSON is broken, when it is complete.

    Small models often leave quotes in HTML unescaped. When the call names
    the tool and a path and its content runs to the closing braces, the file
    text is taken as written; a reply cut off part way is not guessed at.
    """
    if not re.search(r'"(?:tool|name)"\s*:\s*"write_file"', text):
        return None
    path = re.search(r'"path"\s*:\s*"([^"\n]+)"', text)
    opening = re.search(r'"content"\s*:\s*"', text)
    if path is None or opening is None:
        return None
    body = text[opening.end() :]
    closing = re.search(
        r'"\s*(?:,\s*"(?:path|append)"\s*:\s*(?:"[^"\n]*"|true|false)\s*)?\}\s*\}'
        r"\s*(?:```)?\s*$",
        body,
    )
    if closing is None:
        return None
    content = _ESCAPE.sub(_unescape, body[: closing.start()])
    return ToolCall(
        id=f"text_{abs(hash(text)) % 10**8}",
        name="write_file",
        arguments={"path": path.group(1), "content": content},
    )


def _unescape(found: re.Match[str]) -> str:
    code = found.group(1)
    if code.startswith("u"):
        return chr(int(code[1:], 16))
    return _ESCAPED.get(code, code)


def _decoded_arguments(raw: object) -> JsonObject:
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


class ProxyLLM:
    """Anthropic-shaped calls into the local FCC proxy and its providers."""

    def __init__(
        self,
        *,
        base_url: str,
        token: str = "",
        default_model: str,
        timeout: float = 180.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._default_model = default_model
        self._timeout = timeout
        self._transport = transport

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        system: str = "",
        tools: Sequence[ToolSpec] = (),
        temperature: float = 0.2,
        max_tokens: int = 1024,
        model: str | None = None,
    ) -> LLMReply:
        payload: JsonObject = {
            "model": model or self._default_model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": _anthropic_messages(messages),
        }
        carried_system = "\n\n".join(
            [text for text in (system,) if text]
            + [item.content for item in messages if item.role == "system"]
        )
        if carried_system:
            payload["system"] = carried_system
        if tools:
            payload["tools"] = [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.parameters,
                }
                for tool in tools
            ]
        headers = {
            "content-type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        if self._token:
            headers["x-api-key"] = self._token
        body = await _post_json(
            f"{self._base_url}/v1/messages",
            payload,
            headers=headers,
            timeout=self._timeout,
            transport=self._transport,
        )
        return _anthropic_reply(body)


class LocalOpenAILLM:
    """OpenAI chat-completions calls into a local runtime such as llama.cpp."""

    def __init__(
        self,
        *,
        base_url: str | Callable[[], str],
        api_key: str = "",
        default_model: str = "",
        timeout: float = 300.0,
        transport: httpx.AsyncBaseTransport | None = None,
        fast: Callable[[], bool] = lambda: True,
    ) -> None:
        # A function lets the address follow settings: LM Studio's, or the
        # built-in engine's when that is switched on.
        self._address = base_url
        self._api_key = api_key
        self.speeds: dict[str, dict[str, float]] = {}
        """The last reply's speed for each model, when the runtime reports it."""
        self._default_model = default_model
        self._timeout = timeout
        self._transport = transport
        self._fast = fast

    @property
    def _base_url(self) -> str:
        address = self._address
        text = address if isinstance(address, str) else address()
        return text.rstrip("/")

    async def list_models(self) -> tuple[str, ...]:
        """Ask the local runtime which models it is serving."""
        headers = {}
        if self._api_key:
            headers["authorization"] = f"Bearer {self._api_key}"
        async with httpx.AsyncClient(timeout=5.0, transport=self._transport) as client:
            try:
                response = await client.get(f"{self._base_url}/models", headers=headers)
            except httpx.HTTPError as error:
                raise LocalModelsUnavailable(
                    f"No local model server at {self._base_url}: {error}"
                ) from error
        if response.status_code >= 400:
            raise LocalModelsUnavailable(
                f"The local model server answered {response.status_code}."
            )
        try:
            body = response.json()
        except ValueError as error:
            raise LocalModelsUnavailable(
                "The local model server sent bad JSON."
            ) from error
        rows = body.get("data") if isinstance(body, dict) else None
        if not isinstance(rows, list):
            return ()
        return tuple(
            str(row["id"])
            for row in rows
            if isinstance(row, dict) and isinstance(row.get("id"), str)
        )

    async def loaded_models(self) -> tuple[str, ...] | None:
        """Chat models loaded in memory right now, when the runtime says so.

        LM Studio lists every downloaded model on /v1/models but marks the
        loaded ones on its /api/v0/models; other runtimes return None here.
        """
        root = self._base_url.removesuffix("/v1")
        headers = {}
        if self._api_key:
            headers["authorization"] = f"Bearer {self._api_key}"
        body = None
        try:
            async with httpx.AsyncClient(
                timeout=5.0, transport=self._transport
            ) as client:
                # LM Studio marks loaded models here; llama.cpp's router mode
                # gives each model a status on /models instead.
                for path in ("/api/v0/models", "/models"):
                    response = await client.get(f"{root}{path}", headers=headers)
                    if response.status_code < 400:
                        body = response.json()
                        break
        except httpx.HTTPError, ValueError:
            return None
        rows = body.get("data") if isinstance(body, dict) else None
        if not isinstance(rows, list):
            return None
        loaded: list[str] = []
        known = False
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str):
                continue
            status = row.get("status")
            state = row.get("state") or (
                status.get("value") if isinstance(status, dict) else None
            )
            known = known or state is not None
            if state == "loaded" and row.get("type") != "embeddings":
                loaded.append(row["id"])
        return tuple(loaded) if known else None

    def _request(
        self,
        messages: Sequence[ChatMessage],
        *,
        system: str,
        tools: Sequence[ToolSpec],
        temperature: float,
        max_tokens: int,
        model: str | None,
        stream: bool,
    ) -> tuple[JsonObject, dict[str, str]]:
        fast = self._fast()
        # Tool instructions never change between turns and the system prompt
        # ends with this turn's memory, so this order keeps the longest part
        # identical and the runtime reuses its cached reading of it.
        prelude = "\n\n".join(
            part
            for part in (
                tool_protocol_instructions(tools),
                system,
                NO_THINK_SWITCH if fast else "",
            )
            if part
        )
        wire: list[JsonObject] = []
        if prelude:
            wire.append({"role": "system", "content": prelude})
        wire.extend(_text_protocol_messages(messages))
        payload: JsonObject = {
            "model": model or self._default_model,
            "messages": wire,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
            "cache_prompt": True,
        }
        if fast:
            # Reasoning models (Qwen3, DeepSeek-R1 distills) otherwise write a
            # long hidden "thinking" pass before every answer.
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        headers = {"content-type": "application/json"}
        if self._api_key:
            headers["authorization"] = f"Bearer {self._api_key}"
        return payload, headers

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        system: str = "",
        tools: Sequence[ToolSpec] = (),
        temperature: float = 0.2,
        max_tokens: int = 1024,
        model: str | None = None,
    ) -> LLMReply:
        payload, headers = self._request(
            messages,
            system=system,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model,
            stream=False,
        )
        body = await _post_json(
            f"{self._base_url}/chat/completions",
            payload,
            headers=headers,
            timeout=self._timeout,
            transport=self._transport,
        )
        self._note_speed(str(payload.get("model") or ""), body.get("timings"))
        return _text_protocol_reply(_openai_reply(body), tools)

    def _note_speed(self, model: str, timings: object) -> None:
        """Keep the runtime's own speed report for Model Control."""
        if not model or not isinstance(timings, dict):
            return
        wanted = ("prompt_per_second", "predicted_per_second", "predicted_n")
        speed = {
            key: float(value)
            for key in wanted
            if isinstance(value := timings.get(key), (int, float))
        }
        if speed:
            self.speeds[model] = speed

    async def complete_streaming(
        self,
        messages: Sequence[ChatMessage],
        *,
        on_text: Callable[[str], None],
        system: str = "",
        tools: Sequence[ToolSpec] = (),
        temperature: float = 0.2,
        max_tokens: int = 1024,
        model: str | None = None,
    ) -> LLMReply:
        """Complete one call, reporting the visible reply as it is written."""
        payload, headers = self._request(
            messages,
            system=system,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            model=model,
            stream=True,
        )
        return await self._stream(payload, headers, tools, on_text)

    async def _stream(
        self,
        payload: JsonObject,
        headers: Mapping[str, str],
        tools: Sequence[ToolSpec],
        on_text: Callable[[str], None],
    ) -> LLMReply:
        text: list[str] = []
        finish = ""
        served = ""
        shown = ""
        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport
        ) as client:
            try:
                async with client.stream(
                    "POST",
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                ) as response:
                    if response.status_code >= 400:
                        detail = (await response.aread()).decode("utf-8", "replace")
                        raise StudioLLMError(
                            f"Model endpoint returned {response.status_code}: "
                            f"{detail[:400]}"
                        )
                    if "text/event-stream" not in response.headers.get(
                        "content-type", ""
                    ):
                        # Some runtimes ignore stream=true; take the whole answer.
                        try:
                            body = json.loads(await response.aread())
                        except ValueError as error:
                            raise StudioLLMError(
                                "Model endpoint returned malformed JSON."
                            ) from error
                        if not isinstance(body, dict):
                            raise StudioLLMError("Model endpoint returned no reply.")
                        self._note_speed(
                            str(payload.get("model") or ""), body.get("timings")
                        )
                        return _text_protocol_reply(_openai_reply(body), tools)
                    async for line in response.aiter_lines():
                        chunk = _stream_chunk(line)
                        if chunk is None:
                            continue
                        served = str(chunk.get("model") or served)
                        if "timings" in chunk:
                            self._note_speed(
                                str(payload.get("model") or served), chunk["timings"]
                            )
                        choices = chunk.get("choices")
                        first = (
                            choices[0] if isinstance(choices, list) and choices else {}
                        )
                        if not isinstance(first, dict):
                            continue
                        finish = str(first.get("finish_reason") or finish)
                        delta = first.get("delta")
                        piece = (
                            delta.get("content") if isinstance(delta, dict) else None
                        )
                        if isinstance(piece, str) and piece:
                            text.append(piece)
                            visible = visible_reply("".join(text))
                            if visible != shown:
                                shown = visible
                                on_text(visible)
            except httpx.HTTPError as error:
                raise StudioLLMError(f"Model endpoint unreachable: {error}") from error
        body = {
            "model": served,
            "choices": [
                {
                    "message": {"content": "".join(text)},
                    "finish_reason": finish,
                }
            ],
        }
        return _text_protocol_reply(_openai_reply(body), tools)


def _text_protocol_reply(reply: LLMReply, tools: Sequence[ToolSpec]) -> LLMReply:
    """Turn a text-protocol directive in a local reply into a tool call."""
    if reply.tool_calls or not tools:
        return reply
    calls, final = parse_tool_directives(reply.text)
    if calls:
        return LLMReply(
            text="",
            tool_calls=calls,
            model=reply.model,
            stop_reason="tool_use",
            usage=reply.usage,
        )
    if final is not None:
        return LLMReply(
            text=final,
            model=reply.model,
            stop_reason=reply.stop_reason,
            usage=reply.usage,
        )
    return reply


def _stream_chunk(line: str) -> JsonObject | None:
    """Decode one server-sent event line of a streamed completion."""
    if not line.startswith("data:"):
        return None
    data = line[len("data:") :].strip()
    if not data or data == "[DONE]":
        return None
    try:
        chunk = json.loads(data)
    except ValueError:
        return None
    return chunk if isinstance(chunk, dict) else None


_FINAL_OPEN = re.compile(r'^\s*\{\s*"final"\s*:\s*"', re.DOTALL)


def visible_reply(text: str) -> str:
    """The part of a reply still being written that a person should see.

    Hidden thinking is dropped, a tool call in progress shows nothing, and a
    text-protocol final answer shows its words as they arrive.
    """
    text = strip_thinking(text)
    opened = _FINAL_OPEN.match(text)
    if opened:
        body = text[opened.end() :]
        body = re.sub(r'"\s*\}?\s*$', "", body)
        return body.replace("\\n", "\n").replace('\\"', '"').strip()
    if text.lstrip().startswith(("{", "[", "```")):
        return ""
    return text


class LocalModelsUnavailable(StudioLLMError):
    """Raised when the local runtime cannot be asked what it serves."""


class StudioModelRouter:
    """Route each model reference to the transport that can serve it."""

    def __init__(self, *, proxy: LLMClient, local: LLMClient) -> None:
        self._proxy = proxy
        self._local = local
        self._stand_in: Callable[[str], Awaitable[str | None]] | None = None
        self._turns_on: Callable[[], bool] = lambda: False
        self._prepare_local: Callable[[], Awaitable[None]] | None = None
        self.turns = ModelTurns(loaded=self.loaded_local_models)

    def before_local(self, prepare: Callable[[], Awaitable[None]]) -> None:
        """Run ``prepare`` before every local call, e.g. to start the engine."""
        self._prepare_local = prepare

    def local_speeds(self) -> dict[str, dict[str, float]]:
        """The last reply speed of each local model, when the runtime says."""
        speeds = getattr(self._local, "speeds", None)
        return dict(speeds) if isinstance(speeds, dict) else {}

    def use_turns(self, enabled: Callable[[], bool]) -> None:
        """Make local models take turns when ``enabled()`` says so."""
        self._turns_on = enabled

    def use_stand_in(self, pick: Callable[[str], Awaitable[str | None]]) -> None:
        """Let a local model answer for a server model that cannot be reached."""
        self._stand_in = pick

    async def loaded_local_models(self) -> tuple[str, ...] | None:
        """Return the local models loaded in memory, when the runtime knows."""
        loaded = getattr(self._local, "loaded_models", None)
        if loaded is None:
            return None
        return await loaded()

    async def local_models(self) -> tuple[str, ...]:
        """Return the model ids the local runtime serves right now."""
        lister = getattr(self._local, "list_models", None)
        if lister is None:
            return ()
        return await lister()

    def client_for(self, model: str) -> tuple[LLMClient, str]:
        """Return the client and the wire model id for one Studio reference."""
        if model.startswith(LOCAL_MODEL_PREFIX):
            return self._local, model[len(LOCAL_MODEL_PREFIX) :]
        return self._proxy, model

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        model: str,
        system: str = "",
        tools: Sequence[ToolSpec] = (),
        temperature: float = 0.2,
        max_tokens: int = 1024,
        on_text: Callable[[str], None] | None = None,
    ) -> LLMReply:
        """Complete one call with the transport owning the given model.

        With on_text, a runtime that can stream reports the reply as it is
        written, so people see words appear instead of waiting for all of it.
        """
        if self._stand_in is not None:
            model = await self._stand_in(model) or model
        client, wire_model = self.client_for(model)
        if self._prepare_local is not None and model.startswith(LOCAL_MODEL_PREFIX):
            await self._prepare_local()
        turn = (
            self.turns.turn(wire_model)
            if model.startswith(LOCAL_MODEL_PREFIX) and self._turns_on()
            else contextlib.nullcontext()
        )
        async with turn:
            streaming = getattr(client, "complete_streaming", None)
            if on_text is not None and streaming is not None:
                return await streaming(
                    messages,
                    on_text=on_text,
                    system=system,
                    tools=tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    model=wire_model,
                )
            return await client.complete(
                messages,
                system=system,
                tools=tools,
                temperature=temperature,
                max_tokens=max_tokens,
                model=wire_model,
            )


async def _post_json(
    url: str,
    payload: JsonObject,
    *,
    headers: Mapping[str, str],
    timeout: float,
    transport: httpx.AsyncBaseTransport | None,
) -> JsonObject:
    async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
        try:
            response = await client.post(url, json=payload, headers=dict(headers))
        except httpx.HTTPError as error:
            raise StudioLLMError(f"Model endpoint unreachable: {error}") from error
        if response.status_code >= 400:
            raise StudioLLMError(
                f"Model endpoint returned {response.status_code}: {response.text[:400]}"
            )
        try:
            body = response.json()
        except ValueError as error:
            raise StudioLLMError("Model endpoint returned malformed JSON.") from error
    if not isinstance(body, dict):
        raise StudioLLMError("Model endpoint returned an unexpected payload.")
    return body


def _anthropic_messages(messages: Sequence[ChatMessage]) -> list[JsonObject]:
    wire: list[JsonObject] = []
    for message in messages:
        if message.role == "system":
            continue
        if message.role == "tool":
            wire.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": message.tool_call_id or "",
                            "content": message.content,
                        }
                    ],
                }
            )
            continue
        blocks: list[JsonObject] = []
        if message.content:
            blocks.append({"type": "text", "text": message.content})
        blocks.extend(
            {
                "type": "tool_use",
                "id": call.id,
                "name": call.name,
                "input": dict(call.arguments),
            }
            for call in message.tool_calls
        )
        if not blocks:
            blocks.append({"type": "text", "text": ""})
        wire.append({"role": message.role, "content": blocks})
    return wire


def _text_protocol_messages(messages: Sequence[ChatMessage]) -> list[JsonObject]:
    """Render tool use as plain turns that any local chat template accepts.

    Local runtimes get tools through the text protocol, and many chat
    templates reject ``tool`` roles or two turns in a row from one side, so
    calls become the JSON the model wrote and results become user turns.
    """
    names: dict[str, str] = {}
    wire: list[JsonObject] = []

    def add(role: str, content: str) -> None:
        if wire and wire[-1]["role"] == role:
            wire[-1]["content"] = f"{wire[-1]['content']}\n\n{content}"
        else:
            wire.append({"role": role, "content": content})

    for message in messages:
        if message.role == "system":
            continue
        if message.role == "tool":
            name = names.get(message.tool_call_id or "", "the tool")
            add("user", f"Result of {name}:\n{message.content}")
            continue
        parts = [message.content] if message.content else []
        directives = [
            {"tool": call.name, "arguments": dict(call.arguments)}
            for call in message.tool_calls
        ]
        for call in message.tool_calls:
            names[call.id] = call.name
        if len(directives) == 1:
            parts.append(json.dumps(directives[0]))
        elif directives:
            parts.append(json.dumps(directives))
        add(message.role, "\n".join(parts))
    return wire


def _openai_messages(messages: Sequence[ChatMessage]) -> list[JsonObject]:
    wire: list[JsonObject] = []
    for message in messages:
        if message.role == "tool":
            wire.append(
                {
                    "role": "tool",
                    "tool_call_id": message.tool_call_id or "",
                    "content": message.content,
                }
            )
            continue
        entry: JsonObject = {"role": message.role, "content": message.content}
        if message.tool_calls:
            entry["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments),
                    },
                }
                for call in message.tool_calls
            ]
        wire.append(entry)
    return wire


def _anthropic_reply(body: JsonObject) -> LLMReply:
    content = body.get("content")
    texts: list[str] = []
    calls: list[ToolCall] = []
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            text_value = block.get("text")
            if block.get("type") == "text" and isinstance(text_value, str):
                texts.append(text_value)
            elif block.get("type") == "tool_use":
                calls.append(
                    ToolCall(
                        id=str(block.get("id", "")),
                        name=str(block.get("name", "")),
                        arguments=_decoded_arguments(block.get("input")),
                    )
                )
    usage = body.get("usage")
    return LLMReply(
        text="".join(texts).strip(),
        tool_calls=tuple(calls),
        model=str(body.get("model", "")),
        stop_reason=str(body.get("stop_reason") or ""),
        usage=dict(usage) if isinstance(usage, dict) else {},
    )


def _openai_reply(body: JsonObject) -> LLMReply:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise StudioLLMError("Model endpoint returned no choices.")
    first = choices[0]
    message = first.get("message") if isinstance(first, dict) else None
    if not isinstance(message, dict):
        raise StudioLLMError("Model endpoint returned no message.")
    raw_calls = message.get("tool_calls")
    calls: list[ToolCall] = []
    if isinstance(raw_calls, list):
        calls.extend(
            ToolCall(
                id=str(call.get("id") or f"call_{index}"),
                name=str(function.get("name", "")),
                arguments=_decoded_arguments(function.get("arguments")),
            )
            for index, call in enumerate(raw_calls)
            if isinstance(call, dict)
            and isinstance(function := call.get("function"), dict)
        )
    content = message.get("content")
    usage = body.get("usage")
    return LLMReply(
        text=strip_thinking(content) if isinstance(content, str) else "",
        tool_calls=tuple(calls),
        model=str(body.get("model", "")),
        stop_reason=str(first.get("finish_reason") or "")
        if isinstance(first, dict)
        else "",
        usage=dict(usage) if isinstance(usage, dict) else {},
    )
