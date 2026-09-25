"""Read direct orders for the team out of what the user tells the main AI."""

import re
from collections.abc import Sequence
from dataclasses import dataclass

_VERBS = r"have|tell|ask|send|let|order|instruct"
_TO_VERBS = r"get|need|want|would like|'d like"
_ANYONE = (
    r"an agent|another agent|one of the agents|one of my agents|someone|somebody|"
    r"one of them|an ai|another ai"
)
_POLITE = re.compile(r"^(?:please|pls|then|and|also|now|to|go|,|\s)+", re.I)
_TRAILING = re.compile(
    r"[\s,;]*(?:please|pls|for me|thanks|thank you)?[\s.!,;]*$", re.I
)
_STOP_TASK = re.compile(r"^(?:to\s+)?(?:stop|cancel|quit|halt|pause)\b", re.I)
_STOP_WORDS = r"stop|cancel|halt|abort"
_BUILD = re.compile(
    r"\b(build|make|create|code|write|fix|website|site|app|page|game|script|"
    r"program|html|css|javascript|python|project|file|bug)\b",
    re.I,
)
_RESEARCH = re.compile(
    r"\b(research|look into|look up|find|search|compare|investigate|learn|what|"
    r"which|why|how|best|reviews?|sources|video|youtube|reddit|study)\b",
    re.I,
)
_TESTS = re.compile(
    r"\b(test|tests|testing|check|review|bugs?|qa|broken|try out|find problems)\b",
    re.I,
)
_IDEAS = re.compile(r"\b(ideas?|brainstorm|plan|organi[sz]e|think|suggest)\b", re.I)


@dataclass(frozen=True, slots=True)
class Order:
    """One job the user told the main AI to give an agent."""

    agent: str
    """The agent's name, or empty when the user left the choice to the main AI."""
    task: str
    stop: bool = False


@dataclass(frozen=True, slots=True)
class _Start:
    at: int
    end: int
    agent: str
    stop: bool = False


def parse_orders(text: str, names: Sequence[str]) -> list[Order]:
    """Find orders like 'have Builder make a page' or '@Researcher look into X'."""
    team = sorted({name for name in names if name.strip()}, key=len, reverse=True)
    if not team or not text.strip():
        return []
    who = "|".join(re.escape(name) for name in team)
    target = rf"(?:the\s+)?@?(?P<name>{who})\b|(?P<anyone>{_ANYONE})"
    patterns = (
        # "have Builder make ...", "can you ask the Researcher to ..."
        re.compile(rf"\b(?:{_VERBS})\s+(?:{target})\s*(?:,\s*)?(?:to\s+)?", re.I),
        # "I need the Researcher to ...", "get an agent to ..."
        re.compile(rf"(?:\b|(?<='))(?:{_TO_VERBS})\s+(?:{target})\s+to\s+", re.I),
        # "@Builder make ..." anywhere
        re.compile(rf"(?:^|(?<=\s))@(?P<name>{who})\b[\s,:]*", re.I),
        # "Builder, make ..." or "Builder: make ..." at the start of a sentence
        re.compile(
            rf"(?:^|(?<=[.!?\n]\s)|(?<=[.!?\n]))\s*(?P<name>{who})\s*[,:]\s+", re.I
        ),
    )
    stop = re.compile(
        rf"\b(?:{_STOP_WORDS})\s+(?:what\s+)?(?:the\s+)?(?P<name>{who})\b(?:'s)?"
        r"(?:\s+(?:task|job|work|build|research|is doing))?",
        re.I,
    )
    starts: list[_Start] = []
    for pattern in patterns:
        for match in pattern.finditer(text):
            name = match.groupdict().get("name") or ""
            starts.append(_Start(match.start(), match.end(), _canonical(name, team)))
    starts.extend(
        _Start(match.start(), match.end(), _canonical(match["name"], team), stop=True)
        for match in stop.finditer(text)
    )
    starts = _first_per_position(starts)
    orders: list[Order] = []
    for index, start in enumerate(starts):
        end = starts[index + 1].at if index + 1 < len(starts) else len(text)
        task = _clean(text[start.end : end])
        if start.stop or _STOP_TASK.match(task):
            if start.agent:
                orders.append(Order(agent=start.agent, task="", stop=True))
            continue
        if len(task.split()) < 2 and not start.agent:
            continue
        if task:
            orders.append(Order(agent=start.agent, task=_as_instruction(task)))
    return orders


def pick_agent(task: str, team: Sequence[tuple[str, str]]) -> str:
    """Choose who should do a job the user left open: (name, role) pairs."""
    by_role: dict[str, str] = {}
    for name, role in team:
        by_role.setdefault(role, name)
    if _TESTS.search(task) and "tester" in by_role:
        return by_role["tester"]
    if _IDEAS.search(task) and "helper" in by_role:
        return by_role["helper"]
    if _BUILD.search(task) and "builder" in by_role:
        return by_role["builder"]
    if _RESEARCH.search(task) and "researcher" in by_role:
        return by_role["researcher"]
    for role in ("builder", "researcher", "helper", "agent", "assistant"):
        if role in by_role:
            return by_role[role]
    return team[0][0] if team else ""


def _canonical(name: str, team: Sequence[str]) -> str:
    wanted = name.casefold()
    return next((member for member in team if member.casefold() == wanted), "")


def _first_per_position(starts: list[_Start]) -> list[_Start]:
    """Keep one order start per place in the text, in reading order."""
    kept: list[_Start] = []
    for start in sorted(starts, key=lambda item: (item.at, -item.end)):
        if kept and start.at < kept[-1].end:
            continue
        kept.append(start)
    return kept


def _as_instruction(task: str) -> str:
    """'know I like short answers' and 'that the menu is blue' pass a message on."""
    said = re.match(r"^(?:know|that)\s+(?:that\s+)?(.+)$", task, re.I | re.S)
    if said:
        return f"The user wants you to know: {said.group(1)}"
    return task


def _clean(task: str) -> str:
    task = _POLITE.sub("", task.strip())
    task = re.sub(
        r"\s+(?:and|then|also|and then|and also)$", "", task.strip(), flags=re.I
    )
    task = _TRAILING.sub("", task)
    return task.strip()
