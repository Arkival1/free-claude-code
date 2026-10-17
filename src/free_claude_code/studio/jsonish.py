"""Read JSON out of model replies that wrap it in prose or fences."""

import json
import re

import json5

from free_claude_code.core.json_types import JsonObject

_FENCED = re.compile(r"```[\w.+-]*[ \t]*\n?(.*?)```", re.DOTALL)
_PYTHON_WORDS = re.compile(r"\b(True|False|None)\b")
_JSON_WORDS = {"True": "true", "False": "false", "None": "null"}


def extract_json(text: str) -> object | None:
    """Return the first JSON object or array embedded in a model reply."""
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = text.find(opener), text.rfind(closer)
        if start < 0 or end <= start:
            continue
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            continue
    return None


def extract_object(text: str) -> JsonObject:
    """Return an embedded JSON object, or an empty mapping."""
    payload = extract_json(text)
    return dict(payload) if isinstance(payload, dict) else {}


def extract_objects(text: str) -> tuple[JsonObject, ...]:
    """Return an embedded JSON array of objects, or an empty tuple."""
    payload = extract_json(text)
    if isinstance(payload, list):
        return tuple(dict(item) for item in payload if isinstance(item, dict))
    if isinstance(payload, dict):
        for value in payload.values():
            if isinstance(value, list) and all(
                isinstance(item, dict) for item in value
            ):
                return tuple(dict(item) for item in value)
    return ()


def clamped_score(value: object, *, default: float = 0.0) -> float:
    """Return a grade coerced into the 0..1 range."""
    if not isinstance(value, int | float | str):
        return default
    try:
        score = float(value)
    except ValueError:
        return default
    if score > 1.0:
        score = score / 100.0 if score <= 100.0 else 1.0
    return max(0.0, min(1.0, score))


def lenient_object(text: str) -> JsonObject:
    """Return the JSON object in a model reply, also reading the near-JSON
    small models write: code fences, trailing commas, single quotes, comments,
    unquoted keys, Python's True/False/None, and a reply cut off before its
    closing brackets."""
    found = extract_object(text)
    if found:
        return found
    for candidate in _candidates(text):
        for source in (candidate, *_repairs(candidate)):
            for spelled in (source, _PYTHON_WORDS.sub(_json_word, source)):
                try:
                    value = json5.loads(spelled)
                except ValueError, TypeError, RecursionError:
                    continue
                if isinstance(value, dict):
                    return dict(value)
    return {}


def cut_off(text: str) -> bool:
    """True when the reply's JSON object never closes: the reply was cut
    off part way, so finishing it would mean guessing."""
    if extract_object(text):
        return False
    candidates = _candidates(text)
    for candidate in candidates:
        stack, in_string, _ = _scan(candidate)
        if not stack and not in_string:
            return False
    return bool(candidates)


def _json_word(found: re.Match[str]) -> str:
    return _JSON_WORDS[found.group(1)]


def _candidates(text: str) -> list[str]:
    found = [block.strip() for block in _FENCED.findall(text) if "{" in block]
    start = text.find("{")
    if start >= 0:
        end = text.rfind("}")
        found.append(text[start : end + 1] if end > start else text[start:])
    return found


def _repairs(text: str) -> list[str]:
    """Ways to finish a reply that was cut off before its closing brackets:
    close the open string and brackets as they are, or first drop the
    half-written last field (back to the last comma outside a string),
    since ``{"a": 1, "b":`` can't be finished."""
    stack, in_string, last_comma = _scan(text)
    if not stack and not in_string:
        return []
    found = [text + ('"' if in_string else "") + "".join(reversed(stack))]
    if last_comma >= 0:
        trimmed = text[:last_comma]
        found.append(trimmed + "".join(reversed(_scan(trimmed)[0])))
    return found


def _scan(text: str) -> tuple[list[str], bool, int]:
    """The closers still owed, whether a string is open, and the last comma."""
    stack: list[str] = []
    in_string = False
    escaped = False
    last_comma = -1
    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            stack.append("}" if char == "{" else "]")
        elif char in "}]" and stack:
            stack.pop()
        elif char == ",":
            last_comma = index
    return stack, in_string, last_comma
