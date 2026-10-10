"""Read direct orders for the team out of what the user tells the main AI."""

import re
from collections.abc import Sequence
from dataclasses import dataclass

_VERBS = r"have|tell|ask|send|let|order|instruct|call|use|ping|get"
_TO_VERBS = r"get|need|want|would like|'d like"
_ANYONE = (
    r"an agent|another agent|one of the agents|one of my agents|someone|somebody|"
    r"one of them|an ai|another ai"
)
_DOING = (
    r"(?:find|look|search|research|check|compare|make|build|write|fix|plan|test|"
    r"go|create|design|get|show|give|study|read|figure|google)"
)


def _addressing(main: str) -> str:
    """'Hey Jarvis, please' before a sentence that is really for an agent."""
    name = rf"(?:{re.escape(main.strip())}\s*[,:!]?\s+)?" if main.strip() else ""
    return rf"(?:(?:hey|ok|okay)\s+)?{name}(?:please\s+)?"


_POLITE = re.compile(r"^(?:(?:please|pls|then|and|also|now|to|go)\b|,|\s)+", re.I)
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


def parse_orders(text: str, names: Sequence[str], main: str = "") -> list[Order]:
    """Find orders like 'have Builder make a page' or '@Researcher look into X'."""
    team = sorted({name for name in names if name.strip()}, key=len, reverse=True)
    if not team or not text.strip():
        return []
    who = "|".join(re.escape(name) for name in team)
    # "the Builder's opinion" talks about an agent; it gives it no job.
    target = rf"(?:the\s+)?@?(?P<name>{who})\b(?!['\u2019]s)|(?P<anyone>{_ANYONE})"
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
        # "Researcher find cheap TVs": a name, then something to do
        re.compile(
            rf"(?:^|(?<=[.!?\n]\s)|(?<=[.!?\n]))\s*(?P<name>{who})\s+(?={_DOING}\b)",
            re.I,
        ),
        # "can the Researcher look up ..." asked as a sentence of its own
        re.compile(
            rf"(?:^|(?<=[.!?\n]\s)|(?<=[.!?\n]))\s*{_addressing(main)}"
            rf"(?:can|could|would|will)\s+(?:the\s+)?@?(?P<name>{who})\b(?!['\u2019]s)\s+"
            r"(?=\S+\s+\S)",
            re.I,
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


_ASKING = (
    r"^\s*(?:(?:hey|ok|okay|yo)\s+)?{main}"
    r"(?:(?:please|pls)\s+)?"
    r"(?:(?:can|could|would|will)\s+you\s+(?:please\s+)?|i\s+(?:want|need)\s+you\s+to\s+)?"
)
_ON_THE_WEB = re.compile(
    r"(?:go\s+(?:on|onto|to)\s+(?:the\s+)?(?:web|internet)|go\s+online|get\s+online|"
    r"get\s+on\s+the\s+(?:web|internet)|hop\s+online)\s+(?:and|to)\s+|"
    r"use\s+the\s+(?:web|internet)\s+to\s+",
    re.I,
)
_LOOK_IT_UP = re.compile(
    r"(?:do\s+(?:some\s+|a\s+bit\s+of\s+)?research|research|look\s+(?:up|into)|"
    r"search|google|browse|find\s+out|"
    r"find\s+(?:me\s+)?(?:info|information|sources|articles|reviews|videos)|"
    r"find\s+(?:me\s+)?(?:the\s+|some\s+)?(?:best|cheapest|top|good|cheap|latest|newest)|"
    r"check\s+(?:online|the\s+(?:web|internet)))\b",
    re.I,
)
_LOOK_FOR = re.compile(r"(?:look|hunt|shop)\s+(?:around\s+)?for\b", re.I)
_ONLINE = re.compile(
    r"\b(?:online|on\s+the\s+(?:web|internet|net)|on\s+google)\b", re.I
)
_NOT_THE_WEB = re.compile(
    r"\b(?:my|your|our)\s+(?:memory|notes|files|chats?|projects?|photos)\b|"
    r"\b(?:memory|obsidian|the\s+project|this\s+project|the\s+code)\b",
    re.I,
)

# "look into it": what "it" is lives in the conversation, so the main AI
# answers that one itself.
_VAGUE = re.compile(r"^\S+(?:\s+\S+)?\s+(?:it|that|this|them|those)$", re.I)


def web_request(text: str, main: str = "") -> str:
    """The job in 'research X' or 'go on the web and find X', said to the
    main AI without naming an agent; empty when it isn't one.

    The Researcher takes these, so a small model on this PC never has to
    choose to hand them on (or try the research itself)."""
    name = rf"(?:{re.escape(main)}\s*[,:!]?\s+)?" if main.strip() else ""
    lead = re.match(_ASKING.format(main=name), text, re.I)
    rest = text[lead.end() if lead else 0 :]
    web = _ON_THE_WEB.match(rest)
    if web:
        rest = rest[web.end() :]
    elif not _LOOK_IT_UP.match(rest) and not (
        _LOOK_FOR.match(rest) and _ONLINE.search(rest)
    ):
        return ""
    task = _clean(rest).rstrip("?")
    if len(task.split()) < 2 or _NOT_THE_WEB.search(task) or _VAGUE.search(task):
        return ""
    return task


_YES_WORDS = frozenset(
    [
        "yes",
        "yeah",
        "yep",
        "yup",
        "ya",
        "yea",
        "yess",
        "yesss",
        "sure",
        "ok",
        "okay",
        "k",
        "y",
        "go",
        "ahead",
        "do",
        "it",
        "start",
        "begin",
        "ready",
        "im",
        "i'm",
        "i",
        "am",
        "lets",
        "let's",
        "please",
        "sounds",
        "good",
        "for",
        "absolutely",
        "definitely",
        "of",
        "course",
        "right",
        "now",
    ]
)
_YES_CORE = frozenset(
    [
        "yes",
        "yeah",
        "yep",
        "yup",
        "ya",
        "yea",
        "yess",
        "yesss",
        "sure",
        "ok",
        "okay",
        "k",
        "y",
        "go",
        "start",
        "begin",
        "ready",
        "absolutely",
        "definitely",
    ]
)
_OFFER_LEAD = re.compile(
    r"^(?:(?:shall|should|can|may)\s+i\s+|(?:do\s+you\s+want|would\s+you\s+like|"
    r"want)\s+me\s+to\s+|i\s+can\s+)",
    re.I,
)


def called_agent(text: str, names: Sequence[str], main: str = "") -> str:
    """The agent in 'call the Researcher' said with no job yet, or ''."""
    team = sorted({name for name in names if name.strip()}, key=len, reverse=True)
    if not team:
        return ""
    who = "|".join(re.escape(name) for name in team)
    bare = re.match(
        rf"^\s*{_addressing(main)}(?:can\s+you\s+|could\s+you\s+)?"
        r"(?:call|get|ping|summon|bring|wake|fetch|ask|contact)\s+(?:up\s+|in\s+)?"
        rf"(?:the\s+)?@?(?P<name>{who})(?:\s+(?:up|in|for\s+me|please))?\s*[.!?]*\s*$",
        text,
        re.I,
    )
    return _canonical(bare["name"], team) if bare else ""


_NOT_A_JOB = re.compile(
    r"^\s*(?:no|nope|nah|never\s*mind|nevermind|cancel|stop|forget\s+it)\b", re.I
)


def is_job(text: str, main: str = "") -> bool:
    """Whether a reply could be the job for an agent just called."""
    return (
        len(text.split()) >= 2 and not is_yes(text, main) and not _NOT_A_JOB.match(text)
    )


def is_yes(text: str, main: str = "") -> bool:
    """'yes', 'yeah go ahead', 'ok I'm ready': a go-ahead and nothing more."""
    words = re.findall(r"[a-z']+", text.casefold())
    if main.strip():
        words = [word for word in words if word != main.casefold()]
    return (
        0 < len(words) <= 6
        and all(word in _YES_WORDS for word in words)
        and any(word in _YES_CORE for word in words)
    )


def offered_orders(question: str, names: Sequence[str]) -> list[Order]:
    """The jobs the main AI offered in 'Shall I have the Researcher look into
    X?' or 'Do you want me to research X?', so a 'yes' can start them."""
    found = [
        Order(order.agent, task)
        for order in parse_orders(question, names)
        if (task := order.task.rstrip("?").strip()) and not _VAGUE.search(task)
    ]
    if found:
        return found
    for sentence in re.split(r"(?<=[.!?])\s+", question):
        lead = _OFFER_LEAD.match(sentence.strip())
        if lead is None:
            continue
        task = web_request(sentence.strip()[lead.end() :])
        if task:
            return [Order("", task)]
    return []


_MAKE_SOMETHING = re.compile(
    r"(?:make|build|create|design|code|write)\s+(?:me\s+|us\s+)?(?:a|an|the|my|our)?\s*"
    r"(?:[\w'-]+\s+){0,5}?"
    r"(?:website|web\s*site|site|web\s*page|webpage|landing\s+page|home\s*page|"
    r"app|web\s*app|game|portfolio|blog|online\s+store|store\s+page)\b",
    re.I,
)


def build_request(text: str, main: str = "") -> str:
    """The job in 'make me a Spider-Man website', said to the main AI with no
    agent named; empty when it isn't one. The Builder takes these, so a small
    model never tries to write the files itself."""
    name = rf"(?:{re.escape(main)}\s*[,:!]?\s+)?" if main.strip() else ""
    lead = re.match(_ASKING.format(main=name), text, re.I)
    rest = text[lead.end() if lead else 0 :]
    if not _MAKE_SOMETHING.match(rest):
        return ""
    task = _clean(rest).rstrip("?")
    return task if len(task.split()) >= 3 else ""


_CODE_SOMETHING = re.compile(
    r"(?:make|build|create|code|write|program|develop)\s+(?:me\s+|us\s+)?"
    r"(?:a|an|the|my|our|some)?\s*(?:[\w'+#.-]+\s+){0,5}?"
    r"(?:app|apps|application|program|script|tool|bot|game|api|cli|extension|"
    r"plugin|backend|server|library|function|calculator|timer|tracker|dashboard|"
    r"hud|code)\b",
    re.I,
)
_SITE_WORDS = re.compile(
    r"\b(?:website|web\s*site|site|web\s*page|webpage|landing\s+page|home\s*page|"
    r"portfolio|blog|online\s+store|store\s+page)\b",
    re.I,
)


def code_request(text: str, main: str = "") -> str:
    """The job in 'code me a snake game' or 'build a todo app', said to the
    main AI with no agent named; empty for websites (the Builder's) and for
    anything else. The Coder and the Tester take these."""
    name = rf"(?:{re.escape(main)}\s*[,:!]?\s+)?" if main.strip() else ""
    lead = re.match(_ASKING.format(main=name), text, re.I)
    rest = text[lead.end() if lead else 0 :]
    if not _CODE_SOMETHING.match(rest) or _SITE_WORDS.search(rest):
        return ""
    task = _clean(rest).rstrip("?")
    return task if len(task.split()) >= 3 else ""


_TEAM_JOB = re.compile(
    r"(?:"
    r"(?:get|have|let|use)\s+(?:the\s+)?(?:whole\s+|entire\s+)?team\s+(?:to\s+)?"
    r"|team\s+up\s+(?:to|on|and)\s+"
    r"|(?:make|start|run|draw\s+up|come\s+up\s+with|write)\s+a\s+team\s+plan\s+"
    r"(?:to|for)\s+"
    r"|(?:make|start|run)\s+a\s+plan\s+for\s+the\s+(?:whole\s+)?team\s+to\s+"
    r"|(?:all\s+of\s+you|everyone|every\s+agent)\s*,?\s+(?:work\s+together\s+(?:to|on)\s+)?"
    r")(?P<job>.+)",
    re.I | re.S,
)


def plan_request(text: str, main: str = "") -> str:
    """The job in 'get the team to build a bakery site', 'team up on X', or
    'make a team plan to X': work for several agents, run as a team plan.
    Empty for anything else ('plan my week' is the Helper's)."""
    name = rf"(?:{re.escape(main)}\s*[,:!]?\s+)?" if main.strip() else ""
    lead = re.match(_ASKING.format(main=name), text, re.I)
    found = _TEAM_JOB.match(text[lead.end() if lead else 0 :].strip())
    if not found:
        return ""
    job = _clean(found.group("job")).rstrip("?.!")
    return job if len(job.split()) >= 3 else ""


ROUTED_ROLES = {
    "researcher": "finds things out on the web: research, prices, reviews, news, comparisons",
    "builder": "builds and fixes websites, apps, games, and code",
    "helper": "plans, brainstorms, organizes, and turns ideas into next steps",
    "tester": "tests and reviews what was built and reports bugs",
    "coder": "codes apps, games, scripts, tools, and bots for a long time",
    "lab": "makes products, mixes chemicals, and builds circuits in the Lab",
    "farm": "makes faceless short videos (reels, TikToks, Shorts) in the Content Farm",
}
_ROUTE_WORD = re.compile(r"[A-Za-z][\w -]*")


def worth_routing(text: str, main: str = "") -> bool:
    """A message that could be a job: not a 'yes', a 'no', or a few words."""
    return (
        len(text.split()) >= 3 and not is_yes(text, main) and not _NOT_A_JOB.match(text)
    )


def route_prompt(team: Sequence[tuple[str, str]], main: str) -> str:
    """Ask a small model one easy thing: who should do this?"""
    lines = [
        f"You decide who handles the user's message for {main}'s team.",
        "Agents:",
        *(
            f"- {name}: {ROUTED_ROLES[role]}"
            for name, role in team
            if role in ROUTED_ROLES
        ),
        f"- none: {main} answers himself. Use none for greetings and chat, "
        f"questions about {main}, the team or this app, opinions, simple facts "
        "he already knows, maths, the time, the weather, reminders, to-do "
        "lists, and memory.",
        "Reply with exactly one word: an agent's name, or none.",
    ]
    return "\n".join(lines)


def routed_agent(reply: str, team: Sequence[tuple[str, str]]) -> str:
    """The agent a one-word routing reply names, or ''."""
    found = _ROUTE_WORD.search(reply.strip().strip("*`\"'"))
    if found is None:
        return ""
    word = found.group(0).split()[0].strip("-").casefold()
    for name, role in team:
        if role in ROUTED_ROLES and word in {name.casefold(), role}:
            return name
    return ""


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
