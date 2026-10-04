"""Read a Content Farm job out of what the user says.

'make 3 reels about black holes', 'give me 5 video ideas for spacefacts',
'start a channel about gym motivation', 'make a 2 hour sleep video about the
entire lore of Breaking Bad'. In the farm's own chat a plainer 'make one
about sharks' is enough; elsewhere the words must name videos, reels,
shorts, TikToks, or the farm, so 'make me a website' never lands here.
"""

import re
from dataclasses import dataclass

_NUMBERS = {
    "a": 1,
    "an": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "some": 3,
    "a few": 3,
    "a couple of": 2,
}
_COUNT = r"(?P<count>\d{1,2}|a couple of|a few|an?|one|two|three|four|five|six|seven|eight|nine|ten|some)?"
_THINGS = r"(?:videos?|reels?|shorts?|tik ?toks?|clips?|posts?|content)"
_LONG = re.compile(
    r"\b(?:\d+(?:\.\d+)?\s*(?:-\s*)?(?:hours?|hrs?)(?:[- ]long)?|an?\s+hour[- ]long|"
    r"hour[- ]long|long[- ]?form|long|to\s+(?:fall\s+a)?sleep\s+to|sleep|"
    r"entire\s+lore|full\s+lore|whole\s+lore)\b",
    re.I,
)
_LONG_SIZE = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:-\s*)?(?:hours?|hrs?)(?:[- ]long)?\s*", re.I
)
_LEAD = r"^\s*(?:(?:hey|ok|okay)\s+)?(?:jarvis[,\s]+)?(?:please\s+)?(?:can you\s+|could you\s+)?"
_MAKE = re.compile(
    _LEAD
    + r"(?:make|create|produce|render|generate|do|farm)\s+(?:me\s+|us\s+)?"
    + _COUNT
    + r"\s*(?:new\s+|more\s+|faceless\s+|viral\s+|short\s+|long\s+|sleep\s+|lore\s+|"
    + r"what[- ]if\s+|\d+(?:\.\d+)?\s*(?:-\s*)?(?:hours?|hrs?)(?:[- ]long)?\s+|"
    + r"hour[- ]long\s+)*"
    + _THINGS
    + r"(?:\s+(?:about|on|for)\s+(?P<topic>.+))?$",
    re.I,
)
_LOOSE_MAKE = re.compile(
    _LEAD
    + r"(?:make|create|produce|do)\s+(?:me\s+)?"
    + _COUNT
    + r"\s*(?:one|more)?\s*(?:about|on)\s+(?P<topic>.+)$",
    re.I,
)
_IDEAS = re.compile(
    _LEAD
    + r"(?:give me|get me|come up with|think of|brainstorm|find|list|write)\s+"
    + _COUNT
    + r"\s*(?:new\s+|more\s+|viral\s+)*(?:"
    + _THINGS
    + r"\s+)?ideas?(?:\s+(?:about|on|for)\s+(?P<topic>.+))?$",
    re.I,
)
_CHANNEL = re.compile(
    _LEAD
    + r"(?:start|make|create|set up|open|add)\s+(?:me\s+)?(?:a\s+|an\s+|another\s+|new\s+)*"
    + r"(?:content farm|faceless|reels?|tik ?tok|youtube|shorts|instagram)?\s*"
    + r"(?:channel|account|page|farm)\s+(?:about|on|for)\s+(?P<topic>.+)$",
    re.I,
)
_IN_FARM = re.compile(
    r"\s*\b(?:in|on|at|for|with)\s+the\s+(?:content\s+)?farm\b\s*", re.I
)
_FOR_CHANNEL = re.compile(r"\s+for\s+(?P<channel>@?[\w.]+)\s*$", re.I)
_FARM_WORDS = re.compile(
    r"\b(?:reels?|shorts|tik ?toks?|content farm|the farm|faceless|"
    r"videos?\s+(?:about|on|for)|video ideas?|sleep videos?|lore videos?)\b",
    re.I,
)


@dataclass(frozen=True, slots=True)
class FarmJob:
    action: str
    """make, ideas, or channel."""
    topic: str = ""
    count: int = 1
    channel: str = ""
    long: bool = False
    """A two-hour video to fall asleep to, rather than a short."""
    minutes: int = 0
    """How long, when the user said ('a 3 hour video')."""


def _count(raw: str | None, default: int) -> int:
    if not raw:
        return default
    raw = raw.strip().lower()
    number = int(raw) if raw.isdigit() else _NUMBERS.get(raw, default)
    return max(1, min(10, number))


def _topic(raw: str | None) -> tuple[str, str]:
    """The topic, and a channel named with 'for @name' at the end."""
    text = (raw or "").strip(" \t\n,;:.!?")
    channel = ""
    found = _FOR_CHANNEL.search(text)
    if found and re.search(r"^@|[_.]", found.group("channel")):
        channel = found.group("channel")
        text = text[: found.start()]
    return text.strip(" ,;:.!?"), channel.lstrip("@")


def _minutes(text: str) -> int:
    found = re.search(r"(\d+(?:\.\d+)?)\s*(?:-\s*)?(?:hours?|hrs?)", text, re.I)
    return round(float(found.group(1)) * 60) if found else 0


def farm_job(text: str, *, in_farm: bool) -> FarmJob | None:
    said = " ".join(text.split())
    if not said or said.endswith("?"):
        return None
    job = _job(said, in_farm=in_farm)
    if job is None or job.action == "channel":
        return job
    if _LONG.search(said):
        topic = _LONG_SIZE.sub("", job.topic).strip(" ,;:.!") or job.topic
        return FarmJob(
            job.action,
            topic=topic,
            count=job.count,
            channel=job.channel,
            long=True,
            minutes=_minutes(said),
        )
    return job


def _job(said: str, *, in_farm: bool) -> FarmJob | None:
    named = in_farm or bool(_FARM_WORDS.search(said))
    said = _IN_FARM.sub(" ", said).strip(" ,;:.!")
    found = _CHANNEL.match(said)
    if found and named:
        topic, _ = _topic(found.group("topic"))
        return FarmJob("channel", topic=topic) if topic else None
    found = _IDEAS.match(said)
    if found and named:
        topic, channel = _topic(found.group("topic"))
        return FarmJob(
            "ideas", topic=topic, count=_count(found.group("count"), 5), channel=channel
        )
    found = _MAKE.match(said)
    if found and named:
        topic, channel = _topic(found.group("topic"))
        return FarmJob(
            "make", topic=topic, count=_count(found.group("count"), 1), channel=channel
        )
    found = _LOOSE_MAKE.match(said) if in_farm else None
    if found:
        topic, channel = _topic(found.group("topic"))
        return FarmJob(
            "make", topic=topic, count=_count(found.group("count"), 1), channel=channel
        )
    return None
