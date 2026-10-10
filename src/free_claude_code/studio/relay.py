"""The relay: one job passed through the team's repos, one after another.

"Make a website for my bakery" goes to LCC's own agent for the job first (the
Builder), then to each repo in the relay's order: the agent from that repo
that fits the job best takes the project as the last agent left it, improves
it its own way, and hands it on, until the last one finishes. Nothing runs at
the same time; each stage waits for the one before.

Repos with agents give one of their agents. Repos with only skills (taste-skill's
design rules, say) give a stage too: LCC's agent for the job reads that skill
and applies it. The repos the user put first run on every job; the others run
when they have something for that kind of job (a security repo for a website
does not), so a relay stays a sensible length.
"""

import json
import os
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from .extensions import AgentDef, Extension, Skill

RELAY_SKILL_KINDS = frozenset({"skill", "readme"})
"""What a stage can apply from a repo: its skills, or for a guide or a list,
its README."""
MAX_LEGS = 12
"""Repo stages in one relay at most (LCC's own first stage not counted)."""
Mode = Literal["always", "fits", "off"]

# ------------------------------------------------------------------ job kinds

JOB_WORDS: dict[str, tuple[str, ...]] = {
    "site": (
        "website",
        "web site",
        "webpage",
        "web page",
        "landing page",
        "homepage",
        "home page",
        "site",
        "storefront",
    ),
    "app": (
        "app",
        "apps",
        "application",
        "dashboard",
        "tool",
        "extension",
        "plugin",
        "bot",
        "backend",
        "cli",
        "program",
        "software",
    ),
    "game": ("game",),
    "research": ("research", "look up", "find out", "compare", "investigate"),
    "writing": ("blog", "article", "newsletter", "copy", "essay", "story", "post"),
    "finance": (
        "finance",
        "financial",
        "stock",
        "stocks",
        "invest",
        "investing",
        "investment",
        "budget",
        "pricing",
        "valuation",
        "revenue",
        "crypto",
    ),
    "video": ("video", "youtube", "shorts", "reel", "montage"),
    "security": (
        "security",
        "secure",
        "vulnerability",
        "vulnerabilities",
        "pentest",
        "penetration",
        "owasp",
    ),
    "science": ("science", "scientific", "biology", "chemistry", "protein", "genome"),
    "data": ("data", "dataset", "csv", "sql", "database", "analytics"),
    "ai": ("agent", "agents", "llm", "rag", "chatbot", "mcp", "prompt"),
    "diagram": ("diagram", "flowchart"),
    "learning": ("learn", "roadmap", "course", "tutorial"),
    "hosting": ("host", "hosting", "deploy", "domain", "free tier"),
    "design": ("design", "redesign", "ui", "ux", "beautiful", "modern", "style"),
    "api": ("api", "apis"),
    "ideas": ("idea", "ideas"),
}
"""Words that say what kind of job a message is."""

PICK_WORDS: dict[str, tuple[str, ...]] = {
    "site": (
        "frontend-developer",
        "ui-designer",
        "design-taste-frontend",
        "website",
        "web",
        "frontend",
        "landing",
        "ui",
        "ux",
        "seo",
        "accessibility",
    ),
    "app": (
        "fullstack-developer",
        "frontend-developer",
        "fullstack",
        "frontend",
        "app",
        "javascript",
        "typescript",
        "react",
        "backend",
    ),
    "game": ("game-developer", "game", "javascript"),
    "research": ("research-analyst", "researcher", "research", "market", "search"),
    "writing": ("content-writer", "writer", "content", "copywriter", "editor"),
    "finance": ("financial-analyst", "financial", "finance", "investment", "equity"),
    "video": ("video", "youtube", "shorts", "montage", "clip"),
    "security": ("security", "penetration", "pentest", "owasp", "vulnerabilit"),
    "science": ("scientific", "science"),
    "data": ("data-analyst", "data", "analyst", "sql", "database"),
    "ai": ("ai-engineer", "llm", "agent", "prompt", "memory"),
    "diagram": ("diagram",),
    "learning": ("roadmap", "course", "learn"),
    "hosting": ("deploy", "hosting", "free"),
    "design": ("design-taste-frontend", "ui-designer", "design", "ui", "ux"),
    "api": ("api", "apis"),
    "ideas": ("ideas", "idea"),
}
"""Words in an agent's or skill's name that fit each kind of job, best first."""

KIND_ORDER = tuple(JOB_WORDS)
"""The kinds of job, most telling first: a website about stocks is a website."""

GENERIC = frozenset(
    [
        "make",
        "build",
        "create",
        "want",
        "need",
        "please",
        "could",
        "would",
        "some",
        "with",
        "that",
        "this",
        "from",
        "into",
        "for",
        "the",
        "and",
        "app",
        "apps",
        "site",
        "website",
        "page",
        "my",
        "your",
        "our",
        "new",
        "simple",
        "small",
        "nice",
        "good",
        "can",
        "you",
        "me",
        "it",
        "a",
        "an",
        "of",
        "to",
        "in",
        "on",
    ]
)


def job_kinds(text: str) -> set[str]:
    """The kinds of job a message asks for: site, app, research, finance, ..."""
    lowered = " ".join(text.lower().split())
    return {
        kind
        for kind, words in JOB_WORDS.items()
        if any(re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", lowered) for w in words)
    }


# ------------------------------------------------------------------ repos


@dataclass(frozen=True, slots=True)
class RepoRole:
    kinds: frozenset[str]
    """The kinds of job it has something for; '*' is every job."""
    always: bool = False
    """Runs on every relay (the repos the user put first)."""
    picks: Mapping[str, str] = field(default_factory=dict)
    """Which of its agents to use for a kind of job; 'default' otherwise."""


ANY = frozenset({"*"})
AI = frozenset({"ai"})
KNOWN: dict[str, RepoRole] = {
    "voltagent/awesome-claude-code-subagents": RepoRole(
        ANY,
        always=True,
        picks={
            "site": "frontend-developer",
            "app": "fullstack-developer",
            "game": "game-developer",
            "research": "research-analyst",
            "writing": "content-marketer",
            "finance": "quant-analyst",
            "default": "code-reviewer",
        },
    ),
    "openhands/software-agent-sdk": RepoRole(ANY, always=True),
    "foundationagents/metagpt": RepoRole(
        ANY,
        always=True,
        picks={
            "site": "MetaGPT Product Manager",
            "app": "MetaGPT QA Engineer",
            "game": "MetaGPT QA Engineer",
            "default": "MetaGPT Product Manager",
        },
    ),
    "ai4finance-foundation/finrobot": RepoRole(
        ANY,
        always=True,
        picks={
            "finance": "Financial Analyst",
            "data": "Finance Data Analyst",
            "default": "Financial Analyst",
        },
    ),
    "crewaiinc/crewai": RepoRole(
        ANY,
        always=True,
        picks={
            "site": "crewAI Content Writer",
            "research": "crewAI Reporting Analyst",
            "writing": "crewAI Content Editor",
            "default": "crewAI Content Editor",
        },
    ),
    "leonxlnx/taste-skill": RepoRole(
        frozenset({"site", "app", "game", "design"}),
        picks={"default": "design-taste-frontend"},
    ),
    "openhands/openhands": RepoRole(AI),
    "florinpop17/app-ideas": RepoRole(frozenset({"ideas"})),
    "nilbuild/developer-roadmap": RepoRole(frozenset({"learning"})),
    "ossu/computer-science": RepoRole(frozenset({"learning"})),
    "vectorize-io/hindsight": RepoRole(AI),
    "google/ax": RepoRole(AI),
    "paperclipai/paperclip": RepoRole(AI),
    "stablyai/orca": RepoRole(AI),
    "agent-substrate/substrate": RepoRole(AI),
    "calesthio/openmontage": RepoRole(frozenset({"video"})),
    "aishwaryanr/awesome-generative-ai-guide": RepoRole(frozenset({"ai", "learning"})),
    "volcengine/openviking": RepoRole(AI),
    "ai-boost/awesome-harness-engineering": RepoRole(AI),
    "mukul975/anthropic-cybersecurity-skills": RepoRole(frozenset({"security"})),
    "cathrynlavery/diagram-design": RepoRole(frozenset({"diagram"})),
    "k-dense-ai/scientific-agent-skills": RepoRole(frozenset({"science"})),
    "rohitg00/agentmemory": RepoRole(AI),
    "steven2358/awesome-generative-ai": RepoRole(AI),
    "usestrix/strix": RepoRole(frozenset({"security"})),
    "public-apis/public-apis": RepoRole(frozenset({"api"})),
    "ripienaar/free-for-dev": RepoRole(frozenset({"hosting"})),
    "langflow-ai/langflow": RepoRole(AI),
    "supermemoryai/supermemory": RepoRole(AI),
    "letta-ai/letta": RepoRole(AI),
    "letta-ai/letta-code": RepoRole(AI),
    "ultraworkers/claw-code": RepoRole(AI),
    "anil-matcha/ai-youtube-shorts-generator": RepoRole(frozenset({"video"})),
    "milanm/devops-roadmap": RepoRole(frozenset({"learning", "hosting"})),
    "rudra496/devroadmaps": RepoRole(frozenset({"learning"})),
}
"""What each repo that comes with FCC is for. A repo the user adds is matched
by the names of its agents and skills instead."""

FIRST_REPOS = (
    "VoltAgent/awesome-claude-code-subagents",
    "OpenHands/software-agent-sdk",
    "FoundationAgents/MetaGPT",
    "AI4Finance-Foundation/FinRobot",
    "crewAIInc/crewAI",
)
"""The relay's first repos, in the order the user asked for."""


def repo_key(name: str) -> str:
    return name.strip().lower()


# ------------------------------------------------------------------ settings


@dataclass(slots=True)
class RelayStage:
    repo: str
    """The repo's owner/name, as Studio lists it."""
    mode: Mode = "fits"
    agent: str = ""
    """An agent (or skill) of the repo always used; '' picks one for the job."""


@dataclass(slots=True)
class RelaySettings:
    on: bool = True
    """Websites, apps, and games go through the relay on their own."""
    first: str = ""
    """LCC's agent that starts every relay; '' picks the one for the job."""
    stages: list[RelayStage] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def default_mode(repo: str) -> Mode:
    role = KNOWN.get(repo_key(repo))
    return "always" if role is not None and role.always else "fits"


def arranged(saved: RelaySettings, installed: Sequence[str]) -> RelaySettings:
    """The saved order for repos still installed, then repos added since:
    the first repos in their order, then the rest as they were added."""
    present = {repo_key(name): name for name in installed}
    stages = [
        RelayStage(present[repo_key(s.repo)], s.mode, s.agent)
        for s in saved.stages
        if repo_key(s.repo) in present
    ]
    known = {repo_key(stage.repo) for stage in stages}
    first = [present[repo_key(n)] for n in FIRST_REPOS if repo_key(n) in present]
    for name in [*first, *installed]:
        if repo_key(name) not in known:
            known.add(repo_key(name))
            stages.append(RelayStage(name, default_mode(name)))
    return RelaySettings(on=saved.on, first=saved.first, stages=stages)


class RelayStore:
    """The relay's order and switches, in one small file."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> RelaySettings:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError, ValueError:
            return RelaySettings()
        if not isinstance(data, dict):
            return RelaySettings()
        stages = []
        for row in data.get("stages") or []:
            if isinstance(row, dict) and row.get("repo"):
                mode = row.get("mode")
                stages.append(
                    RelayStage(
                        str(row["repo"]),
                        mode if mode in {"always", "fits", "off"} else "fits",
                        str(row.get("agent") or ""),
                    )
                )
        return RelaySettings(
            on=bool(data.get("on", True)),
            first=str(data.get("first") or ""),
            stages=stages,
        )

    def save(self, settings: RelaySettings) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(json.dumps(settings.to_json(), indent=1), encoding="utf-8")
        os.replace(temporary, self._path)


# ------------------------------------------------------------------ picking


@dataclass(frozen=True, slots=True)
class Leg:
    """One repo's stage of a relay: one of its agents, or LCC's agent for the
    job applying one of its skills."""

    repo: str
    agent: AgentDef | None = None
    skill: Skill | None = None

    @property
    def name(self) -> str:
        if self.agent is not None:
            return self.agent.name
        return self.skill.name if self.skill is not None else ""


def _tokens(name: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", name.lower()) if t]


def _goal_words(goal: str) -> set[str]:
    return {
        w
        for w in re.findall(r"[a-z0-9]+", goal.lower())
        if len(w) > 2 and w not in GENERIC
    }


def fit(name: str, goal: str, kinds: Iterable[str]) -> float:
    """How well a name fits the job: the job's own words in it count most,
    then a word that fits the kind of job (the earlier in its list, the
    better)."""
    tokens = _tokens(name)
    joined = "-".join(tokens)
    score = 3.0 * len(_goal_words(goal) & set(tokens))
    best = 0.0
    for kind in kinds:
        words = PICK_WORDS.get(kind, ())
        for rank, word in enumerate(words):
            hit = (
                word in joined
                if "-" in word
                else any(
                    t == word or (len(word) >= 5 and t.startswith(word)) for t in tokens
                )
            )
            if hit:
                best = max(best, 2.0 + (len(words) - rank) / 100)
                break
    return score + best


def choose(
    extension: Extension,
    stage: RelayStage,
    goal: str,
    kinds: set[str],
) -> Leg | None:
    """The agent or skill a repo gives this job, or None when it has nothing
    for it."""
    agents = list(extension.agents)
    skills = [s for s in extension.skills if s.kind in RELAY_SKILL_KINDS]
    if stage.agent:
        wanted = stage.agent.casefold()
        for agent in agents:
            if agent.name.casefold() == wanted:
                return Leg(extension.name, agent=agent)
        for skill in skills:
            if skill.name.casefold() == wanted:
                return Leg(extension.name, skill=skill)
    role = KNOWN.get(repo_key(extension.name))
    fits_job = role is not None and ("*" in role.kinds or bool(role.kinds & kinds))
    if stage.mode == "fits" and role is not None and not fits_job:
        return None
    # A named pick for this kind of job, then the best-fitting name.
    if role is not None and fits_job:
        for kind in [*sorted(kinds, key=KIND_ORDER.index), "default"]:
            named = role.picks.get(kind)
            if named is None:
                continue
            found = next((a for a in agents if a.name == named), None)
            if found is not None:
                return Leg(extension.name, agent=found)
            skill = next((s for s in skills if s.name == named), None)
            if skill is not None:
                return Leg(extension.name, skill=skill)
    scored_agents = sorted(
        ((fit(a.name, goal, kinds), i, a) for i, a in enumerate(agents)),
        key=lambda item: (-item[0], item[1]),
    )
    scored_skills = sorted(
        ((fit(s.name, goal, kinds), i, s) for i, s in enumerate(skills)),
        key=lambda item: (-item[0], item[1]),
    )
    best_agent = scored_agents[0] if scored_agents else None
    best_skill = scored_skills[0] if scored_skills else None
    # A repo FCC doesn't know needs a strong match: a word of the job and a
    # word for the kind of job.
    needed = 0.0 if stage.mode == "always" else (2.0 if role is not None else 5.0)
    if best_agent is not None and best_agent[0] >= max(needed, 0.0001):
        return Leg(extension.name, agent=best_agent[2])
    if best_skill is not None and best_skill[0] >= max(needed, 0.0001):
        return Leg(extension.name, skill=best_skill[2])
    if stage.mode == "always":
        if agents:
            return Leg(extension.name, agent=agents[0])
        if skills:
            return Leg(extension.name, skill=skills[0])
    return None


def plan_legs(
    goal: str,
    settings: RelaySettings,
    extensions: Sequence[Extension],
    *,
    kinds: set[str] | None = None,
) -> list[Leg]:
    """Each repo's stage for this job, in the relay's order."""
    kinds = job_kinds(goal) if kinds is None else kinds
    by_name = {repo_key(e.name): e for e in extensions}
    legs: list[Leg] = []
    for stage in settings.stages:
        extension = by_name.get(repo_key(stage.repo))
        if stage.mode == "off" or extension is None:
            continue
        leg = choose(extension, stage, goal, kinds)
        if leg is not None:
            legs.append(leg)
        if len(legs) >= MAX_LEGS:
            break
    return legs


def leg_task(leg: Leg, goal: str) -> str:
    """What one repo's stage is asked to do."""
    repo = leg.repo
    if leg.agent is not None:
        about = leg.agent.description.strip().rstrip(".")
        return (
            f"As {leg.agent.name} from {repo} ({about[:200]}): take the work so far "
            f"on '{goal}' and make it better your way."
        )
    skill = leg.skill.name if leg.skill is not None else ""
    if leg.skill is not None and leg.skill.kind == "readme":
        return (
            f"Use {repo}'s guide for the work so far on '{goal}': read it first "
            f"with the skill tool (action read, name '{skill}'), then change the "
            "project with what fits from it."
        )
    return (
        f"Apply the '{skill}' skill from {repo} to the work so far on '{goal}': "
        f"read it first with the skill tool (action read, name '{skill}'), then "
        "change the project to follow it."
    )
