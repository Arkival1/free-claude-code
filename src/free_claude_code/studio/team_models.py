"""Team brains: a different model for each agent.

Helpers to match a spoken model name to a real one, understand "give the
Builder qwen coder", and suggest a sensible mix from the models on this PC.
"""

import re
from collections.abc import Collection, Mapping, Sequence

from .llm import LOCAL_MODEL_PREFIX

_CODER = re.compile(
    r"coder|codestral|devstral|starcoder|codegemma|codellama|deepseek-code|granite-code",
    re.I,
)
_THINKER = re.compile(r"(?:^|[-_/ ])r1\b|qwq|reason|thinking|magistral", re.I)
_NOT_CHAT = re.compile(r"embed|vision-only|whisper|rerank", re.I)
_SIZE = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*b(?![a-z])", re.I)

_LEAD = re.compile(
    r"^\s*(?:(?:hey\s+)?jarvis[,:!]?\s*)?(?:(?:can|could|would|will) you\s+|please\s+)*",
    re.I,
)
_TAIL = re.compile(
    r"(?:\s+(?:please|for me|now|instead|from now on|"
    r"as (?:its|his|her|their|your) (?:brain|model)))*[.!?]*\s*$",
    re.I,
)
_FORMS = (
    (
        r"(?:give|set|switch|change|move|put|make)",
        r"(?:(?:brain|model)\s+)?(?:to use|to|onto|on|over to|with|the model)",
    ),
    (r"give", r""),
    (r"(?:let|have|make)", r"(?:use|think with|run on)"),
)
_SELF = {"yourself", "you", "your", "your own"}


def model_label(model: str) -> str:
    """'qwen2.5-coder-7b-instruct' for 'local/qwen2.5-coder-7b-instruct'."""
    return model.removeprefix(LOCAL_MODEL_PREFIX)


def model_size(model: str) -> float | None:
    """Billions of parameters from the name, when it says: 7 for '...-7b-...'."""
    found = _SIZE.findall(model_label(model))
    return float(found[-1]) if found else None


def model_kind(model: str) -> str:
    """'coder', 'thinker', or 'general', from the model's name."""
    name = model_label(model)
    if _CODER.search(name):
        return "coder"
    if _THINKER.search(name):
        return "thinker"
    return "general"


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z]+|\d+(?:\.\d+)?", text.lower())


def match_model(text: str, available: Sequence[str]) -> str | None:
    """The available model a spoken name means, or None when none fits.

    Every word said must appear in the model's id: 'qwen coder' finds
    'local/qwen2.5-coder-7b-instruct'. The shortest match wins.
    """
    wanted = text.strip().strip("'\"").strip()
    if not wanted:
        return None
    for model in available:
        if wanted.lower() in {model.lower(), model_label(model).lower()}:
            return model
    words = [
        word
        for word in _words(wanted)
        if word not in {"the", "model", "local", "a", "an", "one", "brain", "on", "pc"}
    ]
    if not words:
        return None
    fits = [
        model
        for model in available
        if all(word in model_label(model).lower() for word in words)
    ]
    return min(fits, key=len) if fits else None


def find_agent_name(
    text: str, names: Sequence[str], *, main: str | None = None
) -> str | None:
    """The team member a spoken name means: 'the builder' finds 'Builder'."""
    wanted = re.sub(r"^(?:the|my|our)\s+", "", text.strip(), flags=re.I)
    wanted = re.sub(r"(?:'s)?(?:\s+(?:agent|brain|model))?$", "", wanted, flags=re.I)
    wanted = wanted.casefold()
    if main and wanted in _SELF:
        return main
    return next((name for name in names if name.casefold() == wanted), None)


def _split(
    rest: str, connector: str, names: Sequence[str], main: str | None
) -> tuple[str, str] | None:
    words = rest.split()
    for count in range(1, min(4, len(words))):
        agent = find_agent_name(" ".join(words[:count]), names, main=main)
        if agent is None:
            continue
        model = " ".join(words[count:])
        if connector:
            joined = re.match(rf"{connector}\s+(.+)$", model, re.I)
            if joined is None:
                continue
            model = joined.group(1)
        if model:
            return agent, model
    return None


def parse_model_request(
    text: str, names: Sequence[str], *, main: str | None = None
) -> tuple[str, str] | None:
    """('Builder', 'qwen coder') from 'give the Builder qwen coder'.

    Only names on the team count, so 'have Builder use Tailwind to build a
    site' still reads as a model request here; the caller checks the model
    is real before acting on it.
    """
    body = _TAIL.sub("", _LEAD.sub("", text.strip(), count=1))
    for verb, connector in _FORMS:
        found = re.match(rf"{verb}\s+(.+)$", body, re.I)
        if found and (pair := _split(found.group(1), connector, names, main)):
            return pair
    found = re.match(r"(.+?)\s+should\s+(?:use|think with|run on)\s+(.+)$", body, re.I)
    if found and (agent := find_agent_name(found.group(1), names, main=main)):
        return agent, found.group(2)
    found = re.match(r"use\s+(.+?)\s+for\s+(.+)$", body, re.I)
    if found and (agent := find_agent_name(found.group(2), names, main=main)):
        return agent, found.group(1)
    return None


def suggest_mix(
    team: Sequence[tuple[str, str]],
    available: Sequence[str],
    abilities: Mapping[str, Collection[str]] | None = None,
) -> dict[str, str]:
    """A starting mix of models for (agent id, role) pairs.

    Coding models go to the Builder and Tester, the biggest general model to
    the Researcher, a reasoning model (when there is one) to the Helper, a
    mid-sized general model to the main AI so it answers quickly, and the
    smallest to the Guide. ``abilities`` (model to "tools", "reasoning",
    "vision") comes from the models' own files: where known, models trained
    for tools go to the agents that use tools most.
    """
    models = [model for model in available if not _NOT_CHAT.search(model)]
    if not models:
        return {}
    known = abilities or {}

    def size(model: str) -> float:
        return model_size(model) or 7.0

    def prefer(candidates: list[str], ability: str) -> list[str]:
        able = [m for m in candidates if ability in known.get(m, ())]
        return able or candidates

    by_size = sorted(models, key=size)
    general = prefer(
        [m for m in by_size if model_kind(m) == "general"] or by_size, "tools"
    )
    coders = prefer([m for m in by_size if model_kind(m) == "coder"], "tools")
    thinkers = [
        m
        for m in by_size
        if model_kind(m) == "thinker" or "reasoning" in known.get(m, ())
    ]
    biggest = general[-1]
    middle = general[(len(general) - 1) // 2] if len(general) > 2 else general[-1]
    picks: Mapping[str, str] = {
        "builder": coders[-1] if coders else biggest,
        "tester": coders[-1] if coders else biggest,
        "researcher": biggest,
        "helper": thinkers[-1] if thinkers else biggest,
        "main": middle,
        "guide": by_size[0],
    }
    return {agent_id: picks.get(role, biggest) for agent_id, role in team}
