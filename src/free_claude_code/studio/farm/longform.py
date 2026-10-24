"""Two-hour narrated videos to fall asleep to: lore, what-ifs, and theories.

A small local model can't write two hours in one go, so the writer works in
chapters: first an outline, then each chapter on its own with what the
fandom wiki says about it, in a calm voice. Every chapter is kept as soon
as it is written, so a video interrupted halfway carries on from there.
The chapters become scenes of a few sentences each (about 20 seconds), and
the chapter starts become YouTube chapter timestamps.
"""

import re

from free_claude_code.core.json_types import JsonObject

from ..jsonish import extract_json
from .formats import style_of

WORDS_PER_MINUTE = 140
"""A calm sleep-story voice: slower than a short's."""
MIN_MINUTES = 10
MAX_MINUTES = 180
SCENE_WORDS = 50
"""About twenty seconds of narration per picture."""
MAX_SUMMARY = 600

OUTLINE_SYSTEM = (
    "You plan long, calm narrated YouTube videos that people fall asleep to: "
    "the full lore of a show, a what-if followed to its end, or fan theories "
    "explained. Plan chapters in a natural order, each about one era, "
    "character, event, or consequence. Reply with one JSON object only."
)
CHAPTER_SYSTEM = (
    "You narrate long, calm YouTube videos people fall asleep to. Write in a "
    "warm, slow, gentle voice, as if telling a story by a fire: full "
    "sentences, no lists, no headings, no jokes that jolt, no questions to the "
    "viewer, no 'in this video'. Stay true to the show's real lore; when it "
    "is a what-if or a theory, say so plainly. Write only the narration."
)


def clamp_minutes(minutes: int) -> int:
    return max(MIN_MINUTES, min(MAX_MINUTES, int(minutes or 120)))


def chapter_count(minutes: int) -> int:
    """About five minutes a chapter."""
    return max(3, min(36, round(clamp_minutes(minutes) / 5)))


def chapter_words(minutes: int) -> int:
    return round(clamp_minutes(minutes) * WORDS_PER_MINUTE / chapter_count(minutes))


def outline_prompt(
    *, title: str, show: str, style: str, minutes: int, notes: str, lore: str
) -> str:
    chosen = style_of(style)
    count = chapter_count(minutes)
    lines = [
        f"Video: {title}",
        f"About: {show or 'the topic in the title'}",
        f"Kind: {chosen.label}: {chosen.pitch}.",
        f"Length: {clamp_minutes(minutes)} minutes, in {count} chapters.",
    ]
    if notes:
        lines.append(f"Notes from the owner: {notes}")
    if lore:
        lines.append(f"What the fandom wiki says:\n{lore[:3_000]}")
    lines.append(
        'JSON shape: {"title": "a YouTube title under 80 characters", '
        '"chapters": [{"title": "short chapter title", "topic": "what it '
        'covers, with the names a wiki search would find"}]}. Exactly '
        f"{count} chapters."
    )
    return "\n".join(lines)


def parse_outline(
    reply: str, *, count: int, title: str
) -> tuple[str, list[JsonObject]]:
    """The video's title and its chapters, however the model wrote them."""
    payload = extract_json(reply)
    name = title
    rows: list[object] = []
    if isinstance(payload, dict):
        name = str(payload.get("title") or title).strip()[:100] or title
        found = payload.get("chapters")
        rows = found if isinstance(found, list) else []
    elif isinstance(payload, list):
        rows = payload
    chapters: list[JsonObject] = []
    for row in rows:
        if isinstance(row, dict):
            heading = " ".join(str(row.get("title") or "").split())[:80]
            topic = " ".join(str(row.get("topic") or heading).split())[:240]
        else:
            heading = topic = " ".join(str(row).split())[:80]
        if heading:
            chapters.append({"title": heading, "topic": topic})
    if not chapters:
        for line in reply.splitlines():
            heading = re.sub(
                r"^\s*(?:[-*•]|\d+[.):]|chapter\s*\d+[:.-])\s*", "", line, flags=re.I
            )
            heading = heading.strip(' "#*')
            if 2 <= len(heading.split()) <= 14:
                chapters.append({"title": heading[:80], "topic": heading[:240]})
    return name, chapters[:count]


def chapter_prompt(
    *,
    title: str,
    show: str,
    style: str,
    chapter: JsonObject,
    number: int,
    total: int,
    words: int,
    lore: str,
    before: str,
    notes: str,
) -> str:
    chosen = style_of(style)
    lines = [
        f"Video: {title}",
        f"About: {show or 'the topic in the title'}",
        f"Kind: {chosen.label}: {chosen.pitch}.",
        f"Chapter {number} of {total}: {chapter.get('title')}",
        f"This chapter covers: {chapter.get('topic')}",
        f"Write about {words} words of calm narration for this chapter only.",
    ]
    if number == 1:
        lines.append(
            "Open the whole video gently: say what tonight's story is, then begin."
        )
    if number == total:
        lines.append("Close the whole video softly, wishing the listener a good sleep.")
    if before:
        lines.append(f"The story so far, in brief: {before}")
    if notes:
        lines.append(f"Notes from the owner: {notes}")
    if lore:
        lines.append(f"What the fandom wiki says (true lore to use):\n{lore[:4_000]}")
    return "\n".join(lines)


_HEADING = re.compile(r"^\s*(?:#+\s*|chapter\s+\d+\b.*$|\*\*.*\*\*\s*$)", re.I)
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'])")


def clean_narration(text: str) -> str:
    """The chapter's prose without headings, lists, or notes to the writer."""
    lines = []
    for line in text.replace("\r", "").split("\n"):
        stripped = line.strip()
        if (
            not stripped
            or _HEADING.match(stripped)
            or stripped.startswith(("{", "```"))
        ):
            continue
        lines.append(re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", stripped))
    return " ".join(" ".join(lines).split())


def summary(text: str) -> str:
    """The chapter's first and last sentences, so the next chapter follows on."""
    sentences = _SENTENCE.split(text)
    if len(sentences) <= 2:
        return text[:MAX_SUMMARY]
    return f"{sentences[0]} … {sentences[-1]}"[:MAX_SUMMARY]


def scenes_from(
    text: str, *, chapter: int, words: int = SCENE_WORDS
) -> list[JsonObject]:
    """Sentences grouped into scenes of about `words` words each."""
    scenes: list[JsonObject] = []
    current: list[str] = []
    count = 0
    for sentence in _SENTENCE.split(text):
        sentence = sentence.strip()
        if not sentence:
            continue
        current.append(sentence)
        count += len(sentence.split())
        if count >= words:
            scenes.append(_scene(" ".join(current), chapter))
            current, count = [], 0
    if current:
        if scenes and count < words // 3:
            scenes[-1]["say"] = f"{scenes[-1]['say']} {' '.join(current)}"
        else:
            scenes.append(_scene(" ".join(current), chapter))
    return scenes


def _scene(say: str, chapter: int) -> JsonObject:
    names = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*", say)
    show = " ".join(dict.fromkeys(name for name in names if len(name) > 3))[:80]
    return {"say": say, "show": show, "text": "", "chapter": chapter}


def stamp(seconds: float) -> str:
    whole = int(seconds)
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def youtube_description(
    *, title: str, show: str, chapters: list[tuple[float, str]], tags: list[str]
) -> str:
    """A description with chapter timestamps, which YouTube turns into chapters."""
    lines = [
        f"{title}",
        "",
        f"Get comfortable: tonight we go through {show or 'the story'}, slowly and "
        "calmly, from the beginning. Perfect for falling asleep, relaxing, or "
        "just learning the lore.",
        "",
        "Chapters",
    ]
    for start, heading in chapters:
        lines.append(f"{stamp(start)} {heading}")
    if tags:
        lines += ["", " ".join(tags)]
    return "\n".join(lines)
