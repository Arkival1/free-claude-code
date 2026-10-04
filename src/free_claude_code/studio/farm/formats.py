"""What the farm makes: video styles, and the prompts that write them.

Every style is a faceless short: a voice reads the script over pictures,
with big captions that light up word by word. The writer is the team's local
model, so the prompts ask for small JSON and the parsers cope with prose.
"""

import re
from dataclasses import dataclass

from free_claude_code.core.json_types import JsonObject

from ..jsonish import extract_json, extract_object
from ..memory import keywords

WORDS_PER_SECOND = 2.6
"""How fast the voice reads: about 155 words a minute."""
MIN_SECONDS = 10
MAX_SECONDS = 90
MAX_SCENES = 14
MAX_SAY = 240
MAX_HASHTAGS = 12


@dataclass(frozen=True, slots=True)
class Style:
    key: str
    label: str
    pitch: str
    """What one video of this style is, for the writer."""
    example: str
    """An idea in this style, for the idea board."""


STYLES: tuple[Style, ...] = (
    Style(
        "facts",
        "Fact list",
        "a numbered list of surprising facts, one per scene, the best one last",
        "5 facts about the deep sea that sound fake",
    ),
    Style(
        "story",
        "Story time",
        "a gripping short story told in the first person with a twist at the end",
        "I found a door in my basement that wasn't there yesterday",
    ),
    Style(
        "motivation",
        "Motivation",
        "a punchy motivational talk: a hard truth, why it matters, one action",
        "Nobody is coming to save you, and that's good news",
    ),
    Style(
        "tips",
        "Quick tips",
        "practical tips that each save time or money, one per scene",
        "3 phone settings you should turn off today",
    ),
    Style(
        "ai_art",
        "AI art reel",
        "a visual showcase: each scene is a striking picture with a short line",
        "What every planet would look like as a city",
    ),
    Style(
        "explainer",
        "Explainer",
        "explain one thing simply, step by step, ending with the 'aha'",
        "Why planes don't fly in a straight line",
    ),
    Style(
        "news",
        "What's new",
        "the latest news in the niche, quick and clear, with why it matters",
        "This week's biggest AI updates in 30 seconds",
    ),
)
STYLE_BY_KEY = {style.key: style for style in STYLES}
PLATFORMS = {
    "instagram": "Instagram Reels",
    "tiktok": "TikTok",
    "youtube": "YouTube Shorts",
}
LOOKS = ("bold", "clean", "neon", "cinema")
VISUALS = ("photos", "ai", "text")

WRITER_SYSTEM = (
    "You write scripts for faceless short videos (Reels, TikTok, Shorts). The "
    "first line is a hook that stops the scroll in under 2 seconds: a bold "
    "claim, a question, or a number. Short spoken sentences, no filler, no "
    "emojis in the spoken lines, nothing made up when it is about real facts. "
    "Reply with one JSON object only."
)
IDEAS_SYSTEM = (
    "You come up with ideas for faceless short videos that people watch to "
    "the end and share. Each idea is one specific title, under 12 words. "
    "Reply with a JSON array of strings only."
)


def style_of(key: str) -> Style:
    return STYLE_BY_KEY.get(key, STYLES[0])


def clamp_seconds(seconds: int) -> int:
    return max(MIN_SECONDS, min(MAX_SECONDS, int(seconds or 30)))


def scene_count(seconds: int) -> int:
    """About one scene every five seconds."""
    return max(3, min(MAX_SCENES, round(clamp_seconds(seconds) / 5)))


def word_budget(seconds: int) -> int:
    return round(clamp_seconds(seconds) * WORDS_PER_SECOND)


def ideas_prompt(
    *, niche: str, style: str, platform: str, count: int, notes: str, trends: str
) -> str:
    chosen = style_of(style)
    lines = [
        f"Niche: {niche or 'anything people love to watch'}",
        f"Style: {chosen.label}: {chosen.pitch}.",
        f"Platform: {PLATFORMS.get(platform, PLATFORMS['instagram'])}",
        f'Example idea: "{chosen.example}"',
    ]
    if notes:
        lines.append(f"Notes from the owner: {notes}")
    if trends:
        lines.append(f"What people search and post about now:\n{trends}")
    lines.append(f"Write {count} new, different ideas as a JSON array of strings.")
    return "\n".join(lines)


def script_prompt(
    *,
    idea: str,
    niche: str,
    style: str,
    platform: str,
    seconds: int,
    call_to_action: str,
    notes: str,
    facts: str = "",
) -> str:
    chosen = style_of(style)
    scenes = scene_count(seconds)
    lines = [
        f"Video: {idea}",
        f"Niche: {niche or 'general'}",
        f"Style: {chosen.label}: {chosen.pitch}.",
        f"Platform: {PLATFORMS.get(platform, PLATFORMS['instagram'])}",
        f"Length: {clamp_seconds(seconds)} seconds, about {word_budget(seconds)} "
        f"spoken words in {scenes} scenes.",
    ]
    if call_to_action:
        lines.append(f"End with this call to action: {call_to_action}")
    if notes:
        lines.append(f"Notes from the owner: {notes}")
    if facts:
        lines.append(f"Facts to use (true, from the web):\n{facts}")
    lines.append(
        'JSON shape: {"title": "...", "scenes": [{"say": "the spoken line", '
        '"show": "2-5 words describing the picture", "text": "up to 4 big words '
        'on screen, or empty"}], "caption": "the post caption, 1-2 lines", '
        '"hashtags": ["#tag", "..."]}. The first scene\'s "say" is the hook.'
    )
    return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class Scene:
    say: str
    show: str
    text: str = ""

    def to_json(self) -> JsonObject:
        return {"say": self.say, "show": self.show, "text": self.text}


@dataclass(frozen=True, slots=True)
class Script:
    title: str
    scenes: tuple[Scene, ...]
    caption: str
    hashtags: tuple[str, ...]

    @property
    def hook(self) -> str:
        return self.scenes[0].say if self.scenes else self.title

    @property
    def words(self) -> int:
        return sum(len(scene.say.split()) for scene in self.scenes)

    def to_json(self) -> JsonObject:
        return {
            "title": self.title,
            "hook": self.hook,
            "scenes": [scene.to_json() for scene in self.scenes],
            "caption": self.caption,
            "hashtags": list(self.hashtags),
        }


def _clean(text: object, limit: int) -> str:
    return " ".join(str(text or "").split())[:limit].strip()


_TAG = re.compile(r"#?([A-Za-z0-9_]{2,40})")


def clean_hashtags(raw: object, extra: tuple[str, ...] = ()) -> tuple[str, ...]:
    """#tags, no repeats, the channel's own first."""
    words: list[str] = list(extra)
    if isinstance(raw, list):
        words += [str(item) for item in raw]
    elif isinstance(raw, str):
        words += raw.replace(",", " ").split()
    tags: dict[str, str] = {}
    for word in words:
        found = _TAG.fullmatch(word.strip())
        if found:
            tags.setdefault(found.group(1).lower(), "#" + found.group(1))
    return tuple(tags.values())[:MAX_HASHTAGS]


def _show_for(line: str, idea: str) -> str:
    words = keywords(line)[:4] or keywords(idea)[:4]
    return " ".join(words) or idea[:40]


_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_LEAD = re.compile(r"^\s*(?:[-*•]|\d+[.)]|scene\s*\d+\s*[:.-])\s*", re.I)


def plain_script(idea: str, text: str, *, seconds: int) -> Script:
    """A script from a reply that isn't JSON: its sentences become scenes."""
    lines = [
        _LEAD.sub("", line).strip(' "')
        for line in text.replace("\r", "").split("\n")
        if line.strip() and not line.strip().startswith(("{", "}", "```"))
    ]
    sentences = [
        part.strip()
        for line in lines
        for part in _SENTENCE.split(line)
        if len(part.strip().split()) >= 2
    ]
    if not sentences:
        sentences = [idea]
    wanted = scene_count(seconds)
    per = max(1, -(-len(sentences) // wanted))
    scenes = tuple(
        Scene(
            say=_clean(" ".join(sentences[at : at + per]), MAX_SAY),
            show=_show_for(" ".join(sentences[at : at + per]), idea),
        )
        for at in range(0, len(sentences), per)
    )[:MAX_SCENES]
    return Script(
        title=_clean(idea, 120),
        scenes=scenes,
        caption=_clean(idea, 300),
        hashtags=(),
    )


def parse_script(
    reply: str, *, idea: str, seconds: int, channel_tags: tuple[str, ...] = ()
) -> Script:
    """The writer's script, however tidy its JSON was."""
    data = extract_object(reply)
    raw_scenes = data.get("scenes")
    scenes: list[Scene] = []
    if isinstance(raw_scenes, list):
        for item in raw_scenes:
            if isinstance(item, dict):
                say = _clean(
                    item.get("say") or item.get("line") or item.get("voiceover"),
                    MAX_SAY,
                )
                if not say:
                    continue
                show = _clean(item.get("show") or item.get("visual"), 120)
                scenes.append(
                    Scene(
                        say=say,
                        show=show or _show_for(say, idea),
                        text=_clean(item.get("text") or item.get("on_screen"), 40),
                    )
                )
            elif isinstance(item, str) and item.strip():
                scenes.append(
                    Scene(say=_clean(item, MAX_SAY), show=_show_for(item, idea))
                )
    if not scenes:
        fallback = plain_script(idea, reply, seconds=seconds)
        return Script(
            title=fallback.title,
            scenes=fallback.scenes,
            caption=fallback.caption,
            hashtags=clean_hashtags([], channel_tags),
        )
    hook = _clean(data.get("hook"), MAX_SAY)
    if hook and hook.lower() not in scenes[0].say.lower():
        scenes.insert(0, Scene(say=hook, show=scenes[0].show, text=""))
    return Script(
        title=_clean(data.get("title"), 120) or _clean(idea, 120),
        scenes=tuple(scenes[:MAX_SCENES]),
        caption=_clean(data.get("caption"), 600) or _clean(idea, 300),
        hashtags=clean_hashtags(data.get("hashtags"), channel_tags),
    )


def script_from_json(data: JsonObject) -> Script:
    """A script kept on a post, back as a Script."""
    raw = data.get("scenes")
    scenes = tuple(
        Scene(
            say=_clean(item.get("say"), MAX_SAY),
            show=_clean(item.get("show"), 120),
            text=_clean(item.get("text"), 40),
        )
        for item in (raw if isinstance(raw, list) else [])
        if isinstance(item, dict) and str(item.get("say") or "").strip()
    )
    tags = data.get("hashtags")
    return Script(
        title=_clean(data.get("title"), 120),
        scenes=scenes,
        caption=_clean(data.get("caption"), 600),
        hashtags=tuple(str(tag) for tag in tags) if isinstance(tags, list) else (),
    )


_IDEA_LEAD = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")


def parse_ideas(reply: str, *, count: int) -> list[str]:
    """Ideas from a JSON array, or from a numbered list."""
    payload = extract_json(reply)
    found: list[str] = []
    if isinstance(payload, dict):
        payload = payload.get("ideas") or next(
            (value for value in payload.values() if isinstance(value, list)), []
        )
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                item = item.get("title") or item.get("idea") or ""
            found.append(_clean(item, 140).strip('"'))
    if not any(found):
        found = [
            _IDEA_LEAD.sub("", line).strip(' "')
            for line in reply.split("\n")
            if _IDEA_LEAD.match(line)
        ]
    seen: dict[str, str] = {}
    for idea in found:
        if len(idea.split()) >= 2:
            seen.setdefault(idea.lower(), idea)
    return list(seen.values())[: max(1, count)]


def full_caption(script: Script, call_to_action: str = "") -> str:
    """What to paste under the video: caption, call to action, then #tags."""
    parts = [script.caption]
    if call_to_action and call_to_action.lower() not in script.caption.lower():
        parts.append(call_to_action)
    if script.hashtags:
        parts.append(" ".join(script.hashtags))
    return "\n\n".join(part for part in parts if part)
