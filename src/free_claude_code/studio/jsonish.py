"""Read JSON out of model replies that wrap it in prose or fences."""

import json

from free_claude_code.core.json_types import JsonObject


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
