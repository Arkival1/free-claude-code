"""The story, written as a cartoon screenplay, and read back however the
local model wrote it.

Each shot is one line (said by the narrator or a character), where it
happens, who is in it and what each one does, and how the camera films it.
A shot that doesn't say keeps the place and the characters of the one
before, as a story does.
"""

import re

from free_claude_code.core.json_types import JsonObject

from ...jsonish import extract_object
from .puppet import ACTIONS
from .scene import CAMERAS
from .stages import PLACES, place_key

MAX_SHOTS = 40
SECONDS_PER_SHOT = 3.2
"""Cartoon shorts cut often: one line, one shot."""

SCREENPLAY_SYSTEM = (
    "You write and direct short animated cartoon stories for TikTok and "
    "YouTube Shorts, like the big history and storytime cartoon accounts: a "
    "narrator tells a gripping true or made-up story while simple cartoon "
    "characters act it out, shot by shot. Hook in the first line, a twist or "
    "payoff at the end, one short sentence per shot. Reply with one JSON "
    "object only."
)

ACTION_NOTES = (
    "stand, talk, walk_in, walk_out, walk, run, point, wave, jump, cheer, cry, "
    "kneel, sit, fall, lie, crawl, punch, scared, dance, think, laugh, bow"
)


def shot_count(seconds: int) -> int:
    return max(4, min(MAX_SHOTS, round(seconds / SECONDS_PER_SHOT)))


def screenplay_prompt(
    *,
    idea: str,
    cast: list[JsonObject],
    seconds: int,
    notes: str,
    facts: str,
    series: str,
) -> str:
    lines = [f"Story: {idea}"]
    if series:
        lines.append(f"Series: {series}")
    if cast:
        lines.append("Characters (use these names exactly):")
        lines += [
            f"- {c.get('name')}: {c.get('description') or 'no notes'}" for c in cast
        ]
    else:
        lines.append(
            "Make up the characters the story needs (2 to 4, with short names)."
        )
    lines.append(f"Length: about {seconds} seconds, {shot_count(seconds)} shots.")
    lines.append(f"Places: {', '.join(PLACES)}.")
    lines.append(f"Actions: {ACTION_NOTES}.")
    lines.append(
        "Camera: wide (everyone), medium NAME, close NAME (their face, for "
        "big feelings), push (creep in), pan."
    )
    if notes:
        lines.append(f"Notes from the owner: {notes}")
    if facts:
        lines.append(f"Facts to use (true):\n{facts}")
    lines.append(
        'JSON shape: {"title": "...", "series": "a short series name", '
        '"shots": [{"place": "hut", "cast": [{"name": "...", "action": '
        '"crawl", "at": "left|center|right", "feel": "sad|happy|angry|'
        'surprised|scared|neutral"}], "camera": "wide", "speaker": '
        '"narrator or a character name", "say": "one sentence"}], '
        '"caption": "1-2 lines", "hashtags": ["#tag"]}'
    )
    return "\n".join(lines)


def _clean(value: object, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit].strip()


_CAMERA = re.compile(r"^\s*(wide|medium|close|push|pan)\b[\s:_-]*(.*)$", re.I)


def camera_of(value: object) -> tuple[str, str]:
    found = _CAMERA.match(str(value or ""))
    if not found:
        return "wide", ""
    return found.group(1).lower(), _clean(found.group(2), 40)


def action_of(value: object) -> str:
    text = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    if text in ACTIONS:
        return text
    for action in ACTIONS:
        if action in text or text.startswith(action[:4]):
            return action
    return {
        "enter": "walk_in",
        "leave": "walk_out",
        "exit": "walk_out",
        "speak": "talk",
        "says": "talk",
        "die": "fall",
        "dies": "fall",
        "sleep": "lie",
        "hit": "punch",
        "fight": "punch",
        "celebrate": "cheer",
        "weep": "cry",
        "sob": "cry",
        "pray": "kneel",
    }.get(text, "stand")


def parse_screenplay(reply: str, *, idea: str, cast_names: list[str]) -> JsonObject:
    """Title, series, and shots (as farm scenes), with the gaps filled."""
    data = extract_object(reply)
    raw = data.get("shots") or data.get("scenes")
    shots: list[JsonObject] = []
    place = "hut"
    previous: list[JsonObject] = []
    known = {name.lower(): name for name in cast_names}
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        say = _clean(item.get("say") or item.get("line") or item.get("narration"), 400)
        if not say:
            continue
        if item.get("place"):
            place = place_key(str(item.get("place")))
        cast: list[JsonObject] = []
        raw_cast = item.get("cast") or item.get("characters")
        for actor in raw_cast if isinstance(raw_cast, list) else []:
            if isinstance(actor, str):
                actor = {"name": actor}
            if not isinstance(actor, dict) or not _clean(actor.get("name"), 40):
                continue
            name = _clean(actor.get("name"), 40)
            cast.append(
                {
                    "name": known.get(name.lower(), name),
                    "action": action_of(actor.get("action")),
                    "at": _clean(actor.get("at"), 20),
                    "feel": _clean(
                        actor.get("feel") or actor.get("feeling"), 20
                    ).lower(),
                }
            )
        if not cast:
            cast = [
                {
                    **actor,
                    "action": "stand"
                    if actor.get("action") in {"walk_in", "walk_out", "fall"}
                    else actor.get("action", "stand"),
                }
                for actor in previous
            ]
        previous = cast[:4]
        camera, focus = camera_of(item.get("camera"))
        speaker = _clean(item.get("speaker"), 40)
        speaker = (
            known.get(speaker.lower(), speaker) if speaker.lower() != "narrator" else ""
        )
        shots.append(
            {
                "say": say,
                "show": " ".join([place, *(str(a["name"]) for a in cast)])[:120],
                "text": "",
                "place": place,
                "cast": cast[:4],
                "camera": camera,
                "focus": focus or speaker,
                "speaker": speaker,
            }
        )
    if not shots:
        # Prose: one shot per sentence, the cast standing in the hut.
        sentences = [
            s for s in re.split(r"(?<=[.!?])\s+", reply) if len(s.split()) >= 3
        ][:MAX_SHOTS]
        cast = [
            {"name": name, "action": "stand", "at": "", "feel": ""}
            for name in cast_names[:3]
        ]
        shots = [
            {
                "say": _clean(s, 400),
                "show": "hut",
                "text": "",
                "place": "hut",
                "cast": cast,
                "camera": "wide" if n % 3 else "push",
                "focus": "",
                "speaker": "",
            }
            for n, s in enumerate(sentences)
        ]
    tags = data.get("hashtags")
    return {
        "title": _clean(data.get("title"), 120) or _clean(idea, 120),
        "series": _clean(data.get("series"), 60),
        "caption": _clean(data.get("caption"), 600) or _clean(idea, 300),
        "hashtags": [str(t) for t in tags] if isinstance(tags, list) else [],
        "shots": shots[:MAX_SHOTS],
    }


__all__ = [
    "CAMERAS",
    "PLACES",
    "SCREENPLAY_SYSTEM",
    "action_of",
    "camera_of",
    "parse_screenplay",
    "screenplay_prompt",
    "shot_count",
]
