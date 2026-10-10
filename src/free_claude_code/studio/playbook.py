"""Jarvis's playbook: notes that teach a small model when and how to use tools.

One Markdown note per tool says which words call for it and shows an example
call. Before each reply, Studio puts the Rules note and the notes that match
the user's message on that message, so a small model sees one or two worked
examples instead of picking from two dozen tools cold. When a call works,
Studio adds the user's words and the call to that note's Learned list.

The notes are plain Markdown in the Obsidian vault (or in Studio's own folder
until a vault is set), so the user can read and edit how Jarvis works.
"""

import json
import re
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import anyio.to_thread

from .obsidian import KIND_MARKER, frontmatter

PLAYBOOK_FOLDER = "Playbook"
PLAYBOOK_KIND = "playbook"
RULES = "rules"
MATCHES = 2
"""Tool notes put on one message, besides the Rules."""
GUIDE_CHARS = 3_000
RULES_CHARS = 1_200
NOTE_CHARS = 800
LEARNED_KEEP = 5
LEARNED_SHOWN = 2
LEARNED_USER_CHARS = 160
LEARNED_VALUE_CHARS = 120
NEVER_LEARNED = frozenset({"finish"})
WHEN_PREFIX = "When the user says:"
LEARNED_HEADING = "## Learned"
LEARNED_NOTE = "_Studio adds what worked here. Delete any line you don't want._"
GUIDE_HEADER = (
    "Your playbook (notes on how to do this; follow them and copy the "
    "matching example, changing the words):"
)
_NAME = re.compile(r"^[a-z][a-z0-9_]{0,40}$")
_WORD = re.compile(r"[a-z0-9']+")
_STOP = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "be",
        "but",
        "by",
        "can",
        "could",
        "do",
        "for",
        "from",
        "have",
        "he",
        "her",
        "him",
        "his",
        "how",
        "i",
        "if",
        "in",
        "is",
        "it",
        "its",
        "me",
        "my",
        "of",
        "on",
        "or",
        "our",
        "please",
        "she",
        "so",
        "that",
        "the",
        "their",
        "them",
        "then",
        "this",
        "to",
        "us",
        "was",
        "we",
        "what",
        "when",
        "where",
        "which",
        "who",
        "will",
        "with",
        "would",
        "you",
        "your",
    ]
)
OVERLAP = 0.6
"""Share of a learned message's words a new message needs to match it."""
CALCULATE = "calculate"
_SUM = re.compile("\\d\\s*(?:[-+*/x\u00d7\u00f7^]|% of|percent of)\\s*\\d")


class PlaybookError(ValueError):
    """Raised for a note name or text the playbook can't use."""


@dataclass(frozen=True, slots=True)
class Example:
    said: str
    arguments: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class Starter:
    tool: str
    title: str
    when: tuple[str, ...]
    examples: tuple[Example, ...]
    tips: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlaybookNote:
    tool: str
    path: Path
    text: str
    """The whole note, frontmatter included."""
    when: tuple[str, ...]
    learned: tuple[tuple[str, str], ...]
    """(user's words, the call) pairs, oldest first."""

    @property
    def body(self) -> str:
        return _split(self.text)[1]


RULES_TEXT = """# Rules

How to use what you are given:
- A Studio note on the user's message is fresh and true. When it says a job is already done or handed out, don't do it again: tell the user what happened.
- "Earlier in this conversation" lines are real past messages. Read them before asking the user to repeat anything.
- Memory lines are facts saved before. Use them, but the user's newest message wins.
- Group chat posts that start "Done:" or "Couldn't finish:" are your team's reports. Explain them in plain words.

How to use tools:
- When a playbook note below matches, call that tool: reply with only its JSON, copying the example and changing the words.
- Don't ask "shall I?" or "are you ready?". Just do it, unless the user must choose something.
- After a tool answers, reply with {"final": "..."} in a few sentences.
- Never make up results. If a tool failed, say what failed.
"""


def _x(said: str, **arguments: object) -> Example:
    return Example(said, arguments)


STARTERS: tuple[Starter, ...] = (
    Starter(
        "ask_agent",
        "Give one agent a job",
        (
            "research",
            "look up",
            "find out",
            "look into",
            "search for",
            "build",
            "make a website",
            "make an app",
            "make me a",
            "fix the",
            "test the",
            "ask the",
            "tell the",
            "get the",
            "researcher",
            "builder",
            "helper",
            "tester",
        ),
        (
            _x(
                "find out the best budget gpu",
                agent="Researcher",
                task="Find the best budget GPU for 1080p gaming, with prices and sources.",
                background=True,
            ),
            _x(
                "make me a landing page for my bakery",
                agent="Builder",
                task="Build a one-page website for the user's bakery.",
                project="bakery",
                background=True,
            ),
        ),
        (
            "Researcher finds things online, Builder makes websites and apps, "
            "Helper plans and filters, Tester checks a project.",
            "Put everything the agent needs in task; it can't see this chat.",
            "Use background true so the user isn't kept waiting.",
        ),
    ),
    Starter(
        "code_and_test",
        "Coding job for the Coder and Tester",
        (
            "code me",
            "code a",
            "write a script",
            "write code",
            "write a program",
            "build an app",
            "make an app",
            "make a game",
            "make a hud",
            "build a tool",
            "program",
            "coder",
            "bot",
            "script",
        ),
        (
            _x(
                "code me a snake game in python",
                goal="A snake game in Python with arrow keys, score, and restart.",
            ),
        ),
        (
            "Websites go to the Builder with ask_agent; code_and_test is for apps, "
            "games, scripts, tools, bots, and HUDs.",
        ),
    ),
    Starter(
        "skill",
        "Skills added from GitHub",
        ("skill", "skills", "use the skill", "how do i", "guide for", "playbook for"),
        (
            _x("what skills do you have", action="list"),
            _x("use the pdf skill", action="read", name="pdf"),
        ),
        ("List first, then read the one that fits and follow it.",),
    ),
    Starter(
        "mcp",
        "MCP tool servers",
        (
            "mcp",
            "mcp server",
            "tool server",
            "my files",
            "database",
            "browser",
            "connector",
            "zapier",
            "email",
            "inbox",
            "discord",
        ),
        (
            _x("what mcp servers are on", action="servers"),
            _x(
                "check my inbox",
                action="call",
                server="email",
                tool="read_inbox",
                arguments={"count": 5},
            ),
            _x(
                "list the files in my documents with the files server",
                action="call",
                server="files",
                tool="list_directory",
                arguments={"path": "C:/Users/me/Documents"},
            ),
        ),
        (
            "Look at a server's tools (action tools) before calling one.",
            "Connected services (Connectors page) are servers too: email, "
            "webhook, zapier, github, and the rest.",
        ),
    ),
    Starter(
        "team_plan",
        "A bigger job planned for the whole team",
        (
            "the whole team",
            "team up",
            "team plan",
            "get the team",
            "have the team",
            "plan the job",
            "step by step",
            "all of you",
        ),
        (
            _x(
                "get the team to research budget gpus and build a comparison site",
                goal=(
                    "Research the best budget GPUs (prices, speed, power) and "
                    "build a comparison website from what is found, then test it."
                ),
                project="gpu-compare",
            ),
        ),
        (
            "It splits the job into steps for the right agents and runs them in "
            "order, each handed what the steps before it produced; it reports "
            "here when done. One agent's job goes to ask_agent instead.",
        ),
    ),
    Starter(
        "team_task",
        "Several agents talking it through in one room",
        ("together", "as a team", "everyone work on", "talk it through"),
        (
            _x(
                "have researcher and builder work on a gpu comparison site together",
                agents=["Researcher", "Builder"],
                goal="Research budget GPUs, then build a comparison website.",
                project="gpu-compare",
            ),
        ),
        ("The first agent named leads.",),
    ),
    Starter(
        "team_status",
        "What the team is doing",
        (
            "what is the team doing",
            "what are they doing",
            "status",
            "progress",
            "is it done",
            "are they done",
            "done yet",
            "finished yet",
            "how is it going",
            "any update",
            "what did they find",
        ),
        (_x("is the researcher done yet"),),
        ("Use it before answering any question about progress.",),
    ),
    Starter(
        "stop_agent",
        "Stop an agent's work",
        ("stop", "cancel", "halt", "never mind the"),
        (_x("stop the builder", agent="Builder"),),
        ("Only when the user asks to stop.",),
    ),
    Starter(
        "research",
        "Deep research yourself",
        ("deep research", "in depth", "ten sources", "10 sources", "reddit", "youtube"),
        (
            _x(
                "do deep research on the best budget gpus with reddit and youtube",
                question="What are the best budget GPUs for 1080p gaming right now?",
            ),
        ),
        ("For a quick look-up, web_search is faster.",),
    ),
    Starter(
        "ask_helper",
        "Think it through with the Helper",
        (
            "brainstorm",
            "help me plan",
            "plan this",
            "ideas for",
            "what should i do",
            "next steps",
        ),
        (
            _x(
                "help me plan a youtube channel",
                request="Plan how to start a YouTube channel: steps for the first month.",
            ),
        ),
        (),
    ),
    Starter(
        "web_search",
        "Quick web search",
        ("search", "google", "look up", "latest", "news", "price of", "who is"),
        (_x("what's the latest news on the rtx 5060", query="RTX 5060 news"),),
        ("Then web_fetch the best link if the titles aren't enough.",),
    ),
    Starter(
        "web_fetch",
        "Read one web page",
        ("open this link", "read this page", "what does this page say", "http", "www."),
        (_x("what does https://example.com say", url="https://example.com"),),
        (),
    ),
    Starter(
        "remember",
        "Save a fact",
        ("remember", "don't forget that", "note that", "keep in mind", "my name is"),
        (_x("remember that my shop opens at 9", text="The user's shop opens at 9am."),),
        ("Write the fact as a full sentence about the user.",),
    ),
    Starter(
        "recall",
        "Look in memory",
        ("do you remember", "what did i tell you", "what's my", "what is my", "recall"),
        (_x("what time does my shop open", query="shop opening time"),),
        (),
    ),
    Starter(
        "conversation",
        "Find something said earlier",
        (
            "earlier",
            "you said",
            "i said",
            "i told you",
            "last time",
            "scroll back",
            "first message",
        ),
        (_x("what did i say earlier about the logo", query="logo"),),
        ("scope all also searches earlier chats.",),
    ),
    Starter(
        "learn",
        "Teach yourself a subject",
        ("learn", "study", "teach yourself", "get good at", "become an expert"),
        (
            _x(
                "learn electrical engineering",
                topic="electrical engineering",
                depth="normal",
            ),
        ),
        ("It runs in the background; tell the user it started.",),
    ),
    Starter(
        "knowledge",
        "What the team already learned",
        ("what did you learn", "your notes on", "lesson", "study guide", "knowledge"),
        (_x("what did you learn about ohm's law", query="Ohm's law"),),
        ("Check it before researching a subject the team studied.",),
    ),
    Starter(
        "agent_model",
        "Which model an agent uses",
        (
            "which model",
            "what model",
            "switch model",
            "change model",
            "use the model",
            "brain",
        ),
        (
            _x("which models are the agents using"),
            _x(
                "put the researcher on qwen3.5-4b",
                agent="Researcher",
                model="qwen3.5-4b",
            ),
        ),
        (),
    ),
    Starter(
        "manage_agent",
        "Control an agent",
        (
            "turn on",
            "turn off",
            "every tool",
            "all tools",
            "show the agents",
            "show me the agents",
        ),
        (
            _x("show me the agents", action="show"),
            _x("give the builder every tool", action="every_tool_on", agent="Builder"),
        ),
        (),
    ),
    Starter(
        "weather",
        "Weather",
        (
            "weather",
            "forecast",
            "rain",
            "temperature outside",
            "is it cold",
            "is it hot",
        ),
        (_x("will it rain in sydney tomorrow", place="Sydney", days=2),),
        (),
    ),
    Starter(
        "study_video",
        "Study a YouTube video",
        (
            "watch this video",
            "study this video",
            "youtube.com",
            "youtu.be",
            "notes on this video",
        ),
        (
            _x(
                "study this video https://youtu.be/abc123",
                url="https://youtu.be/abc123",
            ),
        ),
        (),
    ),
    Starter(
        "video_notes",
        "Videos already studied",
        ("that video", "the video about", "video notes", "videos you watched"),
        (_x("what did that video say about soldering", query="soldering"),),
        (),
    ),
    Starter(
        "todo",
        "To-do list and reminders",
        (
            "remind me",
            "reminder",
            "to-do",
            "todo",
            "to do list",
            "add to my list",
            "my list",
            "don't let me forget",
        ),
        (
            _x(
                "remind me to call mum at 5pm",
                action="add",
                text="Call mum",
                due="at 17:00",
            ),
            _x("what's on my list", action="list"),
        ),
        (
            "due only when the user says a time, like 'in 20 minutes' or "
            "'tomorrow 9am'; never copy a time from an example.",
        ),
    ),
    Starter(
        "calculate",
        "Exact maths",
        (
            "calculate",
            "how much is",
            "divided by",
            "multiplied by",
            "percent of",
            "% of",
            "square root",
        ),
        (_x("what's 15% of 80", expression="15% of 80"),),
        ("Never do sums in your head; use this.",),
    ),
    Starter(
        "list_projects",
        "The user's projects",
        (
            "my projects",
            "my websites",
            "my apps",
            "list projects",
            "which projects",
            "the website you made",
        ),
        (_x("show my projects"),),
        (),
    ),
    Starter(
        "system_status",
        "How the PC is doing",
        (
            "cpu",
            "ram",
            "memory use",
            "disk",
            "is lm studio running",
            "pc status",
            "how is my pc",
            "internet",
        ),
        (_x("how is my pc doing"),),
        (),
    ),
    Starter(
        "app_help",
        "How the app works",
        (
            "how do i",
            "where is",
            "settings",
            "button",
            "why isn't",
            "why won't",
            "set up",
            "doesn't work",
            "not working",
        ),
        (
            _x(
                "how do i change jarvis's voice",
                question="How do I change Jarvis's voice?",
            ),
        ),
        (),
    ),
    Starter(
        "list_photos",
        "The user's business photos",
        ("my photos", "photos of my", "pictures of my", "my pictures"),
        (_x("use my shop photos", query="shop"),),
        (),
    ),
    Starter(
        "lab",
        "The Lab",
        (
            "lab",
            "mix",
            "chemical",
            "formula",
            "formulate",
            "react",
            "experiment",
            "battery",
            "alloy",
        ),
        (
            _x("make shampoo in the lab", action="make", request="shampoo"),
            _x(
                "mix vinegar and baking soda",
                action="mix",
                items=[
                    {"id": "vinegar", "amount": 50},
                    {"id": "baking soda", "amount": 50},
                ],
            ),
        ),
        ("The Lab refuses anything dangerous; tell the user if it does.",),
    ),
    Starter(
        "farm",
        "The Content Farm",
        (
            "reel",
            "reels",
            "tiktok",
            "shorts",
            "content farm",
            "faceless",
            "video ideas",
            "channel about",
            "sleep video",
            "lore video",
            "cartoon",
            "music edit",
        ),
        (
            _x(
                "make 3 reels about black holes",
                action="make",
                topic="black holes",
                count=3,
            ),
            _x("give me 5 video ideas", action="ideas", count=5),
            _x(
                "start a channel about gym motivation",
                action="channel",
                topic="gym motivation",
            ),
            _x(
                "make a 2 hour sleep video about the entire lore of Breaking Bad",
                action="make",
                topic="the entire lore of Breaking Bad",
                long=True,
                minutes=120,
            ),
            _x(
                "make a cartoon about the king who couldn't walk",
                action="make",
                topic="the king who couldn't walk",
                kind="cartoon",
            ),
            _x("make a music edit", action="make", kind="edit"),
        ),
        (
            "Videos are made in the background; say how many are on the way.",
            "Cartoons use the characters on the Characters tab; music edits need "
            "a song and clips in the Media library.",
            "queue shows what is ready to post, with times.",
        ),
    ),
)
STARTER_TOOLS = frozenset(starter.tool for starter in STARTERS)


def _call(tool: str, arguments: Mapping[str, object]) -> str:
    return json.dumps({"tool": tool, "arguments": dict(arguments)}, ensure_ascii=False)


def starter_text(starter: Starter) -> str:
    """The note Studio writes for one tool the first time."""
    lines = [
        frontmatter(
            {
                KIND_MARKER: PLAYBOOK_KIND,
                "tool": starter.tool,
                "tags": ["fcc-studio", "playbook"],
            }
        ),
        "",
        f"# {starter.title} ({starter.tool})",
        "",
        f"{WHEN_PREFIX} {', '.join(starter.when)}",
        "",
        "## Examples",
    ]
    for example in starter.examples:
        lines += [
            f"User: {example.said}",
            f"Jarvis: {_call(starter.tool, example.arguments)}",
            "",
        ]
    if starter.tips:
        lines += ["## Tips", *(f"- {tip}" for tip in starter.tips), ""]
    lines += [LEARNED_HEADING, LEARNED_NOTE, ""]
    return "\n".join(lines)


def rules_text() -> str:
    return "\n".join(
        [
            frontmatter(
                {
                    KIND_MARKER: PLAYBOOK_KIND,
                    "tool": RULES,
                    "tags": ["fcc-studio", "playbook"],
                }
            ),
            "",
            RULES_TEXT,
        ]
    )


def _split(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end < 0:
        return {}, text
    values: dict[str, str] = {}
    for line in text[4:end].splitlines():
        key, separator, value = line.partition(":")
        if separator:
            values[key.strip()] = value.strip()
    return values, text[end + 4 :].lstrip("\n")


def parse_note(path: Path, text: str) -> PlaybookNote | None:
    """A note Studio can use, or None for any other Markdown in the folder."""
    values, body = _split(text)
    tool = (values.get("tool") or "").strip().lower()
    if not tool and values.get(KIND_MARKER) == PLAYBOOK_KIND:
        tool = path.stem.lower()
    if not _NAME.match(tool):
        return None
    when: list[str] = []
    for line in body.splitlines():
        if line.strip().lower().startswith(WHEN_PREFIX.lower()):
            rest = line.strip()[len(WHEN_PREFIX) :]
            when += [part.strip().lower() for part in rest.split(",") if part.strip()]
    return PlaybookNote(tool, path, text, tuple(when), tuple(_learned(body)))


def _learned(body: str) -> list[tuple[str, str]]:
    start = body.find(LEARNED_HEADING)
    if start < 0:
        return []
    pairs: list[tuple[str, str]] = []
    said: str | None = None
    for line in body[start + len(LEARNED_HEADING) :].splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            break
        if stripped.startswith("User:"):
            said = stripped[5:].strip()
        elif stripped.startswith("Jarvis:") and said is not None:
            pairs.append((said, stripped[7:].strip()))
            said = None
    return pairs


def _words(text: str) -> set[str]:
    return {
        word
        for word in _WORD.findall(text.lower())
        if word not in _STOP and len(word) > 1
    }


def _said(text: str) -> str:
    return " ".join(text.split())[:LEARNED_USER_CHARS]


def _says(phrase: str, lowered: str) -> bool:
    """The phrase as whole words ('% of' still matches '17% of')."""
    before = r"(?<!\w)" if phrase[:1].isalnum() else ""
    after = r"(?!\w)" if phrase[-1:].isalnum() else ""
    return re.search(f"{before}{re.escape(phrase)}{after}", lowered) is not None


def score(note: PlaybookNote, text: str) -> int:
    """How well one note fits a message: 1 plus its word count for each
    trigger phrase (so 'every tool' beats 'builder'), 3 for a message like
    one it learned from, and 3 for a sum when it is the calculate note."""
    lowered = " ".join(text.lower().split())
    phrases = {*note.when, note.tool, note.tool.replace("_", " ")}
    points = sum(
        1 + len(phrase.split())
        for phrase in phrases
        if phrase and _says(phrase, lowered)
    )
    if note.tool == CALCULATE and _SUM.search(lowered):
        points += 3
    words = _words(text)
    for said, _ in note.learned:
        known = _words(said)
        if known and len(known & words) / len(known) >= OVERLAP:
            points += 3
            break
    return points


def _short(text: str) -> str:
    """A note as the model reads it: no frontmatter, no trigger line, no
    blank lines, and only the newest learned examples."""
    _, body = _split(text)
    head, _, _ = body.partition(LEARNED_HEADING)
    lines = [
        line.rstrip()
        for line in head.splitlines()
        if line.strip() and not line.strip().lower().startswith(WHEN_PREFIX.lower())
    ]
    return "\n".join(lines)


def guide_text(
    notes: list[PlaybookNote],
    text: str,
    *,
    rules_only: bool = False,
    tool: str = "",
) -> str:
    """The Rules, then the notes that fit this message best (none when
    Studio already did the job, so the model isn't pushed to do it again).
    With ``tool``, that tool's note is the one shown: Studio already knows
    which tool the message is for."""
    rules = next((note for note in notes if note.tool == RULES), None)
    ranked = sorted(
        (
            (1 if note.tool == tool else score(note, text), index, note)
            for index, note in enumerate(notes)
            if note.tool != RULES and (not tool or note.tool == tool)
        ),
        key=lambda item: (-item[0], item[1]),
    )
    parts = [_clip(_short(rules.text), RULES_CHARS)] if rules else []
    best = ranked[0][0] if ranked else 0
    for points, _, note in [] if rules_only else ranked[:MATCHES]:
        if points <= 0 or points < best:
            # A weaker second match (a 'builder' in a status question) would
            # only tempt a small model into the wrong tool.
            break
        shown = _short(note.text)
        learned = note.learned[-LEARNED_SHOWN:]
        if learned:
            shown += "\nWorked before:\n" + "\n".join(
                f"User: {said}\nJarvis: {call}" for said, call in learned
            )
        parts.append(_clip(shown, NOTE_CHARS))
    if not parts:
        return ""
    return _clip(f"{GUIDE_HEADER}\n" + "\n\n".join(parts), GUIDE_CHARS)


def _clip(text: str, limit: int) -> str:
    """Whole lines up to the limit, never half a sentence or half a call."""
    if len(text) <= limit:
        return text
    kept: list[str] = []
    used = 0
    for line in text.splitlines():
        if used + len(line) + 1 > limit:
            break
        kept.append(line)
        used += len(line) + 1
    return "\n".join(kept)


HANDOFF_TOOLS = frozenset(
    {
        "ask_agent",
        "team_task",
        "team_plan",
        "ask_helper",
        "research",
        "web_search",
        "web_fetch",
    }
)
"""Tools whose job an agent can take; any other match is the main AI's own."""


def own_tool(notes: list[PlaybookNote], text: str) -> str:
    """The main AI's own tool a message best matches ('todo', 'calculate'),
    or '' when the best match is a job for an agent or nothing fits."""
    best, tool = 0, ""
    for note in notes:
        if note.tool == RULES:
            continue
        points = score(note, text)
        if points > best:
            best, tool = points, note.tool
    return "" if tool in HANDOFF_TOOLS else tool


def starter_notes() -> list[PlaybookNote]:
    """Studio's starting notes, read without touching the disk."""
    found = [parse_note(Path(f"{s.tool}.md"), starter_text(s)) for s in STARTERS]
    return [note for note in found if note is not None]


def _trimmed(value: object) -> object:
    if isinstance(value, str) and len(value) > LEARNED_VALUE_CHARS:
        return value[:LEARNED_VALUE_CHARS].rstrip() + "…"
    if isinstance(value, list):
        return [_trimmed(item) for item in value[:6]]
    if isinstance(value, dict):
        return {key: _trimmed(item) for key, item in value.items()}
    return value


def with_learned(note_text: str, said: str, call: str) -> str:
    """The note with one more worked example, the oldest dropped past
    LEARNED_KEEP. Everything above the Learned list stays as the user left it."""
    head, heading, tail = note_text.partition(LEARNED_HEADING)
    if not heading:
        head, tail = note_text.rstrip() + "\n\n", ""
    pairs = [
        pair
        for pair in _learned(LEARNED_HEADING + tail)
        if pair[0].lower() != said.lower()
    ]
    pairs.append((said, call))
    pairs = pairs[-LEARNED_KEEP:]
    after = ""
    rest = tail.split("\n## ", 1)
    if len(rest) == 2:
        after = "\n## " + rest[1]
    lines = [LEARNED_HEADING, LEARNED_NOTE, ""]
    for user, jarvis in pairs:
        lines += [f"User: {user}", f"Jarvis: {jarvis}", ""]
    return (
        head.rstrip()
        + "\n\n"
        + "\n".join(lines)
        + after.rstrip()
        + ("\n" if after else "")
    )


class Playbook:
    """The playbook folder: the vault's when one is set, else Studio's own."""

    def __init__(self, folder: Path, *, seed_from: Path | None = None) -> None:
        self._folder = folder
        # Studio's own folder, copied into a new vault so nothing learned is lost.
        self._seed_from = seed_from

    @property
    def folder(self) -> Path:
        return self._folder

    async def notes(self) -> list[PlaybookNote]:
        return await anyio.to_thread.run_sync(self._notes)

    def _ensure(self) -> None:
        folder = self._folder
        if folder.is_dir() and any(folder.glob("*.md")):
            return
        folder.mkdir(parents=True, exist_ok=True)
        seed = self._seed_from
        if (
            seed is not None
            and seed != folder
            and seed.is_dir()
            and any(seed.glob("*.md"))
        ):
            for path in seed.glob("*.md"):
                shutil.copy2(path, folder / path.name)
            return
        (folder / "Rules.md").write_text(rules_text(), encoding="utf-8")
        for starter in STARTERS:
            (folder / f"{starter.tool}.md").write_text(
                starter_text(starter), encoding="utf-8"
            )

    def _notes(self) -> list[PlaybookNote]:
        self._ensure()
        found: list[PlaybookNote] = []
        seen: set[str] = set()
        for path in sorted(self._folder.glob("*.md")):
            note = parse_note(path, path.read_text(encoding="utf-8", errors="replace"))
            if note is not None and note.tool not in seen:
                seen.add(note.tool)
                found.append(note)
        return found

    async def guide(
        self, text: str, *, rules_only: bool = False, tool: str = ""
    ) -> str:
        return guide_text(await self.notes(), text, rules_only=rules_only, tool=tool)

    async def learn(
        self, tool: str, said: str, arguments: Mapping[str, object]
    ) -> bool:
        """Add a call that worked to its tool's note; False when there is no
        note for it (the user deleted it, or it is not a playbook tool)."""
        said = _said(said)
        if tool in NEVER_LEARNED or not said:
            return False
        call = _call(tool, {key: _trimmed(value) for key, value in arguments.items()})

        def work() -> bool:
            note = next((note for note in self._notes() if note.tool == tool), None)
            if note is None:
                return False
            if any(
                user.lower() == said.lower() and old == call
                for user, old in note.learned
            ):
                return False
            note.path.write_text(with_learned(note.text, said, call), encoding="utf-8")
            return True

        return await anyio.to_thread.run_sync(work)

    async def read(self, tool: str) -> PlaybookNote:
        note = next((note for note in await self.notes() if note.tool == tool), None)
        if note is None:
            raise PlaybookError(f"There is no playbook note for {tool}.")
        return note

    async def save(self, tool: str, text: str) -> PlaybookNote:
        """Replace one note with the user's text, keeping the tool it is for."""
        note = await self.read(tool)
        if not text.strip():
            raise PlaybookError("A playbook note can't be empty; delete lines instead.")
        values, _ = _split(text)
        if (values.get("tool") or "").strip().lower() != tool:
            # Edited without its header: put Studio's back so the note still counts.
            _, body = _split(text)
            text = "\n".join(
                [
                    frontmatter(
                        {
                            KIND_MARKER: PLAYBOOK_KIND,
                            "tool": tool,
                            "tags": ["fcc-studio", "playbook"],
                        }
                    ),
                    "",
                    body.lstrip(),
                ]
            )

        def work() -> None:
            note.path.write_text(
                text if text.endswith("\n") else text + "\n", encoding="utf-8"
            )

        await anyio.to_thread.run_sync(work)
        return await self.read(tool)

    async def reset(self, tool: str) -> PlaybookNote:
        """Put Studio's starting note back for one tool (or the Rules)."""
        if tool == RULES:
            text = rules_text()
            name = "Rules.md"
        else:
            starter = next((item for item in STARTERS if item.tool == tool), None)
            if starter is None:
                raise PlaybookError(f"Studio has no starting note for {tool}.")
            text = starter_text(starter)
            name = f"{tool}.md"
        existing = next(
            (note for note in await self.notes() if note.tool == tool), None
        )
        path = existing.path if existing is not None else self._folder / name

        def work() -> None:
            path.write_text(text, encoding="utf-8")

        await anyio.to_thread.run_sync(work)
        return await self.read(tool)
