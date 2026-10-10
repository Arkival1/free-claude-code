"""OpenAI Chat Completions on top of the Messages pipeline.

Most AI tools (Cursor, Continue, Cline, Roo, Aider, OpenCode, Zed, Open WebUI,
LibreChat, Goose, ...) speak OpenAI's ``/v1/chat/completions``. A request is
turned into a Messages request, runs through the same routing, providers, and
optimizations as Claude Code's, and the answer (one JSON reply or Anthropic
server-sent events) is turned back into Chat Completions JSON or chunks.
"""

import codecs
import json
import time
import uuid
from collections.abc import (
    AsyncGenerator,
    AsyncIterable,
    AsyncIterator,
    Mapping,
)
from typing import Any

from free_claude_code.application.errors import InvalidRequestError
from free_claude_code.core.anthropic import MessagesRequest

FINISH_REASONS = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
    "pause_turn": "stop",
    "refusal": "content_filter",
}
JSON_ONLY_NOTE = "Reply with one valid JSON value only, with no other text."


def completion_id() -> str:
    return f"chatcmpl-{uuid.uuid4().hex[:24]}"


# ------------------------------------------------------------------ requests


def to_messages_request(body: Mapping[str, Any]) -> MessagesRequest:
    """A Chat Completions request as a Messages request."""
    model = body.get("model")
    if not isinstance(model, str) or not model.strip():
        raise InvalidRequestError("model is required.")
    raw = body.get("messages")
    if not isinstance(raw, list) or not raw:
        raise InvalidRequestError("messages must be a non-empty list.")
    n = body.get("n")
    if isinstance(n, int) and n > 1:
        raise InvalidRequestError("Only n=1 is supported.")

    system: list[str] = []
    messages: list[dict[str, Any]] = []
    for index, message in enumerate(raw):
        if not isinstance(message, Mapping):
            raise InvalidRequestError(f"messages[{index}] must be an object.")
        role = message.get("role")
        if role in {"system", "developer"}:
            text = _text_of(message.get("content"))
            if text:
                system.append(text)
            continue
        if role == "user":
            _append(messages, "user", _user_blocks(message.get("content")))
        elif role == "assistant":
            _append(messages, "assistant", _assistant_blocks(message))
        elif role in {"tool", "function"}:
            tool_id = message.get("tool_call_id") or message.get("name") or ""
            _append(
                messages,
                "user",
                [
                    {
                        "type": "tool_result",
                        "tool_use_id": str(tool_id),
                        "content": _text_of(message.get("content")) or "(empty)",
                    }
                ],
            )
        else:
            raise InvalidRequestError(
                f"messages[{index}] has an unknown role {role!r}."
            )
    if not messages:
        raise InvalidRequestError("messages needs at least one user message.")

    note = _format_note(body.get("response_format"))
    if note:
        system.append(note)
    request: dict[str, Any] = {
        "model": model.strip(),
        "messages": messages,
        "stream": bool(body.get("stream")),
    }
    if system:
        request["system"] = "\n\n".join(system)
    limit = body.get("max_completion_tokens") or body.get("max_tokens")
    if isinstance(limit, int) and not isinstance(limit, bool) and limit > 0:
        request["max_tokens"] = limit
    for name in ("temperature", "top_p"):
        value = body.get(name)
        if isinstance(value, int | float) and not isinstance(value, bool):
            request[name] = value
    stop = body.get("stop")
    if isinstance(stop, str) and stop:
        request["stop_sequences"] = [stop]
    elif isinstance(stop, list):
        request["stop_sequences"] = [s for s in stop if isinstance(s, str) and s]
    tools = _tools(body.get("tools") or body.get("functions"))
    if tools:
        request["tools"] = tools
        choice = _tool_choice(body.get("tool_choice") or body.get("function_call"))
        if choice is not None:
            request["tool_choice"] = choice
    return MessagesRequest.model_validate(request)


def _append(messages: list[dict[str, Any]], role: str, blocks: list[dict]) -> None:
    """Add blocks, joining a turn to the one before it when the role repeats."""
    if not blocks:
        return
    if messages and messages[-1]["role"] == role:
        messages[-1]["content"].extend(blocks)
    else:
        messages.append({"role": role, "content": list(blocks)})


def _text_of(content: object) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, Mapping) and part.get("type") in {"text", "input_text"}
        )
    return str(content)


def _user_blocks(content: object) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    if not isinstance(content, list):
        return []
    blocks: list[dict[str, Any]] = []
    for part in content:
        if not isinstance(part, Mapping):
            continue
        kind = part.get("type")
        if kind in {"text", "input_text"}:
            text = str(part.get("text", ""))
            if text:
                blocks.append({"type": "text", "text": text})
        elif kind == "image_url":
            image = _image(part.get("image_url"))
            if image is not None:
                blocks.append(image)
        else:
            blocks.append(
                {"type": "text", "text": f"[{kind} attachment not supported]"}
            )
    return blocks


def _image(value: object) -> dict[str, Any] | None:
    url = value.get("url") if isinstance(value, Mapping) else value
    if not isinstance(url, str) or not url:
        return None
    if url.startswith("data:") and ";base64," in url:
        head, data = url[5:].split(";base64,", 1)
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": head or "image/png",
                "data": data,
            },
        }
    return {"type": "image", "source": {"type": "url", "url": url}}


def _assistant_blocks(message: Mapping[str, Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    text = _text_of(message.get("content"))
    if text:
        blocks.append({"type": "text", "text": text})
    calls = message.get("tool_calls")
    legacy = message.get("function_call")
    if not calls and isinstance(legacy, Mapping):
        calls = [{"id": legacy.get("name"), "function": legacy}]
    for number, call in enumerate(calls or []):
        if not isinstance(call, Mapping):
            continue
        function = call.get("function") or {}
        if not isinstance(function, Mapping):
            continue
        blocks.append(
            {
                "type": "tool_use",
                "id": str(call.get("id") or f"call_{number}"),
                "name": str(function.get("name", "")),
                "input": _arguments(function.get("arguments")),
            }
        )
    return blocks


def _arguments(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except ValueError:
            return {"_raw": value}
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    return {}


def _tools(raw: object) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    tools: list[dict[str, Any]] = []
    for tool in raw:
        if not isinstance(tool, Mapping):
            continue
        function = tool.get("function", tool)
        if not isinstance(function, Mapping) or not function.get("name"):
            continue
        schema = function.get("parameters")
        tools.append(
            {
                "name": str(function["name"]),
                "description": str(function.get("description") or ""),
                "input_schema": dict(schema)
                if isinstance(schema, Mapping)
                else {"type": "object", "properties": {}},
            }
        )
    return tools


def _tool_choice(raw: object) -> dict[str, Any] | None:
    if raw in {None, "auto"}:
        return {"type": "auto"} if raw == "auto" else None
    if raw == "none":
        return {"type": "none"}
    if raw in {"required", "any"}:
        return {"type": "any"}
    if isinstance(raw, Mapping):
        function = raw.get("function", raw)
        if isinstance(function, Mapping) and function.get("name"):
            return {"type": "tool", "name": str(function["name"])}
    return None


def _format_note(raw: object) -> str:
    if not isinstance(raw, Mapping):
        return ""
    kind = raw.get("type")
    if kind == "json_object":
        return JSON_ONLY_NOTE
    if kind == "json_schema":
        schema = raw.get("json_schema")
        shape = schema.get("schema") if isinstance(schema, Mapping) else None
        if shape:
            return (
                f"{JSON_ONLY_NOTE} It must match this JSON schema:\n{json.dumps(shape)}"
            )
        return JSON_ONLY_NOTE
    return ""


# ----------------------------------------------------------------- responses


def to_completion(message: Mapping[str, Any], *, model: str, cid: str) -> dict:
    """A finished Messages reply as one Chat Completions object."""
    text: list[str] = []
    thinking: list[str] = []
    calls: list[dict[str, Any]] = []
    for block in message.get("content") or []:
        if not isinstance(block, Mapping):
            continue
        kind = block.get("type")
        if kind == "text":
            text.append(str(block.get("text", "")))
        elif kind == "thinking":
            thinking.append(str(block.get("thinking", "")))
        elif kind == "tool_use":
            calls.append(
                {
                    "id": str(block.get("id", "")),
                    "type": "function",
                    "function": {
                        "name": str(block.get("name", "")),
                        "arguments": json.dumps(block.get("input") or {}),
                    },
                }
            )
    reply: dict[str, Any] = {"role": "assistant", "content": "".join(text) or None}
    if calls:
        reply["tool_calls"] = calls
    if thinking:
        reply["reasoning_content"] = "".join(thinking)
    usage = message.get("usage") or {}
    return {
        "id": cid,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": reply,
                "finish_reason": FINISH_REASONS.get(
                    str(message.get("stop_reason")), "stop"
                ),
            }
        ],
        "usage": _usage(usage),
    }


def _usage(usage: object) -> dict[str, int]:
    usage = usage if isinstance(usage, Mapping) else {}
    prompt = int(usage.get("input_tokens") or 0) + int(
        usage.get("cache_read_input_tokens") or 0
    )
    done = int(usage.get("output_tokens") or 0)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": done,
        "total_tokens": prompt + done,
    }


def error_to_openai(content: object, status: int) -> dict[str, Any]:
    """An error reply from the Messages pipeline in OpenAI's shape."""
    inner = content.get("error") if isinstance(content, Mapping) else None
    if isinstance(inner, Mapping):
        message = str(inner.get("message") or "Request failed.")
        kind = str(inner.get("type") or "api_error")
    elif isinstance(content, Mapping) and "detail" in content:
        message, kind = str(content["detail"]), "invalid_request_error"
    else:
        message, kind = f"Request failed ({status}).", "api_error"
    return {"error": {"message": message, "type": kind, "param": None, "code": None}}


def _chunk(
    cid: str, model: str, created: int, delta: dict, finish: str | None
) -> bytes:
    body = {
        "id": cid,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    return f"data: {json.dumps(body, ensure_ascii=False)}\n\n".encode()


async def to_chunks(
    source: AsyncIterable[object],
    *,
    model: str,
    cid: str,
    include_usage: bool = False,
) -> AsyncGenerator[bytes]:
    """Anthropic server-sent events as Chat Completions chunks, then [DONE]."""
    created = int(time.time())
    usage: dict[str, Any] = {}
    tools: dict[int, int] = {}
    finish: str | None = None
    yield _chunk(cid, model, created, {"role": "assistant", "content": ""}, None)
    try:
        async for event in _events(source):
            kind = event.get("type")
            if kind == "message_start":
                message = event.get("message") or {}
                usage.update(message.get("usage") or {})
            elif kind == "content_block_start":
                block = event.get("content_block") or {}
                if block.get("type") == "tool_use":
                    number = len(tools)
                    tools[int(event.get("index", 0))] = number
                    yield _chunk(
                        cid,
                        model,
                        created,
                        {
                            "tool_calls": [
                                {
                                    "index": number,
                                    "id": str(block.get("id", "")),
                                    "type": "function",
                                    "function": {
                                        "name": str(block.get("name", "")),
                                        "arguments": "",
                                    },
                                }
                            ]
                        },
                        None,
                    )
            elif kind == "content_block_delta":
                delta = event.get("delta") or {}
                step = delta.get("type")
                if step == "text_delta" and delta.get("text"):
                    yield _chunk(cid, model, created, {"content": delta["text"]}, None)
                elif step == "thinking_delta" and delta.get("thinking"):
                    yield _chunk(
                        cid,
                        model,
                        created,
                        {"reasoning_content": delta["thinking"]},
                        None,
                    )
                elif step == "input_json_delta":
                    number = tools.get(int(event.get("index", 0)))
                    if number is not None and delta.get("partial_json"):
                        yield _chunk(
                            cid,
                            model,
                            created,
                            {
                                "tool_calls": [
                                    {
                                        "index": number,
                                        "function": {
                                            "arguments": delta["partial_json"]
                                        },
                                    }
                                ]
                            },
                            None,
                        )
            elif kind == "message_delta":
                stop = (event.get("delta") or {}).get("stop_reason")
                if stop:
                    finish = FINISH_REASONS.get(str(stop), "stop")
                usage.update(event.get("usage") or {})
            elif kind == "error":
                error = error_to_openai(event, 500)
                yield f"data: {json.dumps(error)}\n\n".encode()
                yield b"data: [DONE]\n\n"
                return
        yield _chunk(cid, model, created, {}, finish or "stop")
        if include_usage:
            body = {
                "id": cid,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [],
                "usage": _usage(usage),
            }
            yield f"data: {json.dumps(body)}\n\n".encode()
        yield b"data: [DONE]\n\n"
    finally:
        close = getattr(source, "aclose", None)
        if close is not None:
            await close()


async def _events(source: AsyncIterable[object]) -> AsyncIterator[dict[str, Any]]:
    """The JSON data of each server-sent event."""
    buffer = ""
    # A character split across two pieces is decoded once both have come.
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    async for piece in source:
        if isinstance(piece, bytes | bytearray | memoryview):
            buffer += decoder.decode(bytes(piece))
        else:
            buffer += str(piece)
        buffer = buffer.replace("\r\n", "\n")
        while "\n\n" in buffer:
            raw, buffer = buffer.split("\n\n", 1)
            event = _parse(raw)
            if event is not None:
                yield event
    event = _parse(buffer)
    if event is not None:
        yield event


def _parse(raw: str) -> dict[str, Any] | None:
    data = "\n".join(
        line[5:].lstrip() for line in raw.split("\n") if line.startswith("data:")
    )
    if not data or data == "[DONE]":
        return None
    try:
        parsed = json.loads(data)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None
