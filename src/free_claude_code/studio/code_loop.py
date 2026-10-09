"""The Coder and the Tester take turns on one job until it works.

The Coder codes for as long as the job needs. The Tester then tests it, fixes
the small bugs itself, and hands the rest back with a numbered list. The
Coder fixes those, and the Tester checks again, for a few rounds or until the
Tester says it works.
"""

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .models import Agent, AgentRun

ROUNDS = 3
_VERDICT = re.compile(
    r"verdict\s*[:\-]\s*\**\s*(works\s+with\s+issues|works|broken)", re.I
)
_FIRST_WORDS = 600
REPORT_CHARS = 6_000

type RunTask = Callable[[Agent, str], Awaitable[AgentRun]]


@dataclass(frozen=True, slots=True)
class LoopRound:
    number: int
    coder: AgentRun
    tester: AgentRun | None
    verdict: str


@dataclass(frozen=True, slots=True)
class LoopOutcome:
    goal: str
    rounds: tuple[LoopRound, ...]

    @property
    def verdict(self) -> str:
        return self.rounds[-1].verdict if self.rounds else "unknown"

    @property
    def last_coder(self) -> AgentRun:
        return self.rounds[-1].coder

    def summary(self, coder: str, tester: str) -> str:
        """What happened, round by round, for the main AI to explain."""
        lines = [f"{coder} and {tester} worked on: {self.goal[:300]}"]
        for item in self.rounds:
            coded = _short(item.coder.result or item.coder.error or item.coder.status)
            lines.append(f"Round {item.number}: {coder} {item.coder.status}: {coded}")
            if item.tester is not None:
                tested = _short(
                    item.tester.result or item.tester.error or item.tester.status
                )
                lines.append(f"  {tester} ({item.verdict}): {tested}")
        ending = {
            "works": f"{tester} says it works.",
            "issues": f"{tester} says it works, with issues left to polish.",
            "broken": f"{tester} still found it broken after {len(self.rounds)} round(s).",
            "stopped": "The work stopped before it was finished.",
        }.get(self.verdict, f"{tester} gave no clear verdict.")
        lines.append(ending)
        return "\n".join(lines)


def _short(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= _FIRST_WORDS else text[:_FIRST_WORDS].rstrip() + "…"


def verdict(report: str) -> str:
    """works, issues, broken, or unknown, from the Tester's report."""
    found = _VERDICT.search(report or "")
    if found is None:
        return "unknown"
    said = " ".join(found.group(1).lower().split())
    return {"works": "works", "works with issues": "issues"}.get(said, "broken")


def coder_task(goal: str, project: str) -> str:
    return (
        f"Code this in the '{project}' project: {goal}\n"
        "Take as long as it needs: plan with update_plan, write every file, run "
        "it and its tests with test_code or run_command, and fix what fails "
        "before you finish. The Tester checks your work next, so finish with a "
        "short note of what you built, how to run it, and anything unfinished."
    )


def tester_task(goal: str, project: str, number: int) -> str:
    return (
        f"Round {number}: test the '{project}' project. The job was: {goal}\n"
        "Read the code, run it and its tests, and try what real users do. Fix "
        "small bugs yourself with edit_file (a typo, a wrong name, a missing "
        "check). Report in this shape, the verdict first:\n"
        "Verdict: works, works with issues, or broken.\n"
        "Fixed: what you fixed yourself.\n"
        "Bugs: numbered, most serious first, each with the file, the steps to "
        "reproduce it, and the exact fix, for the Coder to do."
    )


def fix_task(goal: str, project: str, report: str, number: int) -> str:
    return (
        f"Round {number}: fix the bugs the Tester found in the '{project}' project.\n"
        f"The job: {goal}. Fix every bug in the Tester's report below, run it "
        "again to check, and finish with what you changed.\n\n"
        f"Tester's report:\n{report[:REPORT_CHARS]}"
    )


_LEAD = re.compile(
    r"^\s*(?:please\s+)?(?:code|build|make|create|write|program|develop)\s+"
    r"(?:me\s+|us\s+)?(?:a|an|the|my|our|some)?\s*",
    re.I,
)


_CALLED = re.compile(
    r"\b(?:called|named|titled)\s+[\"'“]?([A-Za-z0-9][\w' &-]{1,40}?)[\"'”]?"
    r"(?=\s*(?:[:.,;!?(]|\s(?:that|which|with|where|for|to|and|in)\b|$))",
    re.IGNORECASE,
)


def project_name(goal: str) -> str:
    """'code me a snake game in python' becomes 'Snake game in python';
    'make an app called Tip Calculator: ...' becomes 'Tip Calculator'."""
    called = _CALLED.search(goal)
    if called:
        return called.group(1).strip()
    words = _LEAD.sub("", goal).split()[:5]
    name = " ".join(words).strip(" .,!?")
    return name[:1].upper() + name[1:] if name else "New project"


async def code_and_test(
    *,
    coder: Agent,
    tester: Agent,
    goal: str,
    project: str,
    run: RunTask,
    rounds: int = ROUNDS,
) -> LoopOutcome:
    """Coder, then Tester, then back to the Coder, until it works."""
    done: list[LoopRound] = []
    coded = await run(coder, coder_task(goal, project))
    for number in range(1, max(1, rounds) + 1):
        if coded.status != "succeeded":
            done.append(LoopRound(number, coded, None, "stopped"))
            break
        tested = await run(tester, tester_task(goal, project, number))
        said = verdict(tested.result or "")
        if tested.status != "succeeded":
            said = "stopped"
        done.append(LoopRound(number, coded, tested, said))
        if said in {"works", "stopped"} or number == rounds:
            break
        coded = await run(
            coder, fix_task(goal, project, tested.result or "", number + 1)
        )
    return LoopOutcome(goal=goal, rounds=tuple(done))
