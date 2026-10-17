"""The relay: one job passed through the team's repos, one after another.

"Make a website for my bakery" goes to LCC's own agent for the job first (the
Builder), then to each repo in the relay's order: the agent from that repo
that fits the job best takes the project as the last agent left it, improves
it its own way, and hands it on, until the last one finishes. Nothing runs at
the same time; each stage waits for the one before.

Only repos with agents trained for that kind of job take part, and each gives
every one of its agents trained for it, one turn each: a website gets
awesome-claude-code-subagents' ui-designer, frontend-developer, seo-specialist,
and accessibility-tester, but no finance or security agent. Repos with only
skills (taste-skill's design rules, say) give a stage too: LCC's agent for the
job reads that skill and applies it. A repo's agent joins the team when its
stage starts, after LCC's own agent has had the job, and goes back on the
shelf when the relay ends. For a website, app, or game, LCC's agent checks the
finished work last and fixes what the stages broke.
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
MAX_LEGS = 24
"""Repo stages in one relay at most (LCC's own first and last not counted)."""
CHECKED_KINDS = frozenset({"site", "app", "game"})
"""Jobs whose finished project LCC's agent checks at the end of a relay."""
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
    "lab": (
        "lab",
        "laboratory",
        "experiment",
        "formulate",
        "formulation",
        "chemical",
        "chemicals",
        "compound",
        "reaction",
        "circuit",
    ),
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
    "lab": ("experimental-design", "scientific", "chemistry", "experiment", "lab"),
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
    """The kinds of job it has agents or skills trained for."""
    picks: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    """Its agents (or skills) trained for each kind of job, in the order they
    take their turns; 'default' for the other kinds it fits."""


AI = frozenset({"ai"})
BUILDS = frozenset({"site", "app", "game", "design"})
KNOWN: dict[str, RepoRole] = {
    "voltagent/awesome-claude-code-subagents": RepoRole(
        frozenset(
            {
                *BUILDS,
                "lab",
                "science",
                "research",
                "writing",
                "finance",
                "data",
                "security",
                "ai",
                "api",
            }
        ),
        picks={
            "site": (
                "ui-designer",
                "frontend-developer",
                "seo-specialist",
                "accessibility-tester",
            ),
            "app": (
                "ui-designer",
                "fullstack-developer",
                "qa-expert",
                "accessibility-tester",
            ),
            "game": ("game-developer", "ui-designer", "qa-expert"),
            "design": ("ui-designer", "ux-researcher"),
            "lab": ("scientific-literature-researcher", "data-scientist"),
            "science": ("scientific-literature-researcher", "data-scientist"),
            "research": ("research-analyst", "market-researcher"),
            "writing": ("content-marketer", "content-quality-editor"),
            "finance": ("quant-analyst", "risk-manager"),
            "data": ("data-analyst", "data-scientist"),
            "security": ("security-auditor", "penetration-tester"),
            "ai": ("ai-engineer", "llm-architect"),
            "api": ("api-designer", "backend-developer"),
        },
    ),
    "openhands/software-agent-sdk": RepoRole(
        frozenset({"site", "app", "game", "api"}),
        picks={"default": ("OpenHands Engineer",)},
    ),
    "foundationagents/metagpt": RepoRole(
        frozenset({"site", "app", "game", "api"}),
        picks={
            "site": ("MetaGPT QA Engineer",),
            "app": ("MetaGPT Architect", "MetaGPT Engineer", "MetaGPT QA Engineer"),
            "game": ("MetaGPT Engineer", "MetaGPT QA Engineer"),
            "default": ("MetaGPT Architect", "MetaGPT Engineer"),
        },
    ),
    "ai4finance-foundation/finrobot": RepoRole(
        frozenset({"finance", "data"}),
        picks={
            "finance": ("Financial Analyst",),
            "data": ("Finance Data Analyst",),
        },
    ),
    "crewaiinc/crewai": RepoRole(
        frozenset({"site", "writing", "research"}),
        picks={
            "site": ("crewAI Content Writer",),
            "research": ("crewAI Senior Data Researcher", "crewAI Reporting Analyst"),
            "writing": (
                "crewAI Content Planner",
                "crewAI Content Writer",
                "crewAI Content Editor",
            ),
        },
    ),
    "leonxlnx/taste-skill": RepoRole(
        BUILDS,
        picks={
            "site": ("high-end-visual-design",),
            "default": ("design-taste-frontend",),
        },
    ),
    "openhands/openhands": RepoRole(
        frozenset({"site", "app", "ai"}),
        picks={
            "site": ("frontend-development",),
            "app": ("frontend-development", "e2e-testing"),
        },
    ),
    "paperclipai/paperclip": RepoRole(
        frozenset({"site", "app", "design", "ai"}),
        picks={
            "site": ("design-critique",),
            "app": ("design-critique",),
            "design": ("wireframe", "design-critique"),
        },
    ),
    "florinpop17/app-ideas": RepoRole(frozenset({"ideas"})),
    "nilbuild/developer-roadmap": RepoRole(frozenset({"learning"})),
    "ossu/computer-science": RepoRole(frozenset({"learning"})),
    "vectorize-io/hindsight": RepoRole(AI),
    "google/ax": RepoRole(AI),
    "stablyai/orca": RepoRole(AI),
    "agent-substrate/substrate": RepoRole(AI),
    "calesthio/openmontage": RepoRole(frozenset({"video"})),
    "aishwaryanr/awesome-generative-ai-guide": RepoRole(frozenset({"ai", "learning"})),
    "volcengine/openviking": RepoRole(AI),
    "ai-boost/awesome-harness-engineering": RepoRole(AI),
    "mukul975/anthropic-cybersecurity-skills": RepoRole(frozenset({"security"})),
    "cathrynlavery/diagram-design": RepoRole(frozenset({"diagram"})),
    "k-dense-ai/scientific-agent-skills": RepoRole(
        frozenset({"science", "lab"}),
        picks={"lab": ("experimental-design",)},
    ),
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
"""What each repo that comes with FCC is trained for, and which of its agents
take turns for each kind of job. A repo the user adds is matched by the names
of its agents and skills instead."""

FIRST_REPOS = (
    "VoltAgent/awesome-claude-code-subagents",
    "OpenHands/software-agent-sdk",
    "FoundationAgents/MetaGPT",
    "AI4Finance-Foundation/FinRobot",
    "crewAIInc/crewAI",
)
"""The relay's first repos, in the order the user asked for (each still joins
only a job it has agents trained for)."""


def repo_key(name: str) -> str:
    return name.strip().lower()


# ------------------------------------------------------------------ settings


@dataclass(slots=True)
class RelayStage:
    repo: str
    """The repo's owner/name, as Studio lists it."""
    mode: Mode = "fits"
    use: list[str] = field(default_factory=list)
    """The repo's agents (or skills) always used, each taking its own turn in
    this order; empty picks the one that fits the job."""


@dataclass(slots=True)
class RelaySettings:
    on: bool = True
    """Websites, apps, and games go through the relay on their own."""
    first: str = ""
    """LCC's agent that starts every relay; '' picks the one for the job."""
    stages: list[RelayStage] = field(default_factory=list)
    check: bool = True
    """LCC's first agent checks a finished website, app, or game last."""

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def default_mode(repo: str) -> Mode:
    """Every repo joins only the jobs it has agents trained for, until the
    user sets it to every job or off."""
    return "fits"


def arranged(saved: RelaySettings, installed: Sequence[str]) -> RelaySettings:
    """The saved order for repos still installed, then repos added since:
    the first repos in their order, then the rest as they were added."""
    present = {repo_key(name): name for name in installed}
    stages = [
        RelayStage(present[repo_key(s.repo)], s.mode, list(s.use))
        for s in saved.stages
        if repo_key(s.repo) in present
    ]
    known = {repo_key(stage.repo) for stage in stages}
    first = [present[repo_key(n)] for n in FIRST_REPOS if repo_key(n) in present]
    for name in [*first, *installed]:
        if repo_key(name) not in known:
            known.add(repo_key(name))
            stages.append(RelayStage(name, default_mode(name)))
    return RelaySettings(
        on=saved.on, first=saved.first, stages=stages, check=saved.check
    )


def used(row: Mapping[str, object]) -> list[str]:
    """The agents a saved or sent stage names: a list in "use", or one name in
    "agent" (as relays saved before several were allowed)."""
    names = row.get("use")
    if not isinstance(names, list):
        names = [row.get("agent")]
    picked: list[str] = []
    for name in names:
        text = str(name or "").strip()
        if text and text not in picked:
            picked.append(text)
    return picked


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
                        used(row),
                    )
                )
        return RelaySettings(
            on=bool(data.get("on", True)),
            first=str(data.get("first") or ""),
            stages=stages,
            check=bool(data.get("check", True)),
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
    role = KNOWN.get(repo_key(extension.name))
    fits_job = role is not None and bool(role.kinds & kinds)
    if stage.mode == "fits" and role is not None and not fits_job:
        return None
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


def named_leg(extension: Extension, name: str) -> Leg | None:
    """The repo's agent, or else its skill, with this name."""
    wanted = name.casefold()
    for agent in extension.agents:
        if agent.name.casefold() == wanted:
            return Leg(extension.name, agent=agent)
    for skill in extension.skills:
        if skill.kind in RELAY_SKILL_KINDS and skill.name.casefold() == wanted:
            return Leg(extension.name, skill=skill)
    return None


def stage_legs(
    extension: Extension, stage: RelayStage, goal: str, kinds: set[str]
) -> list[Leg]:
    """A repo's turns in this relay: each agent the user picked, in order;
    else each of its agents trained for this kind of job; else the one whose
    name fits the job best."""
    picked = [leg for name in stage.use if (leg := named_leg(extension, name))]
    if picked:
        return picked
    role = KNOWN.get(repo_key(extension.name))
    if role is not None:
        fits = role.kinds & kinds
        if not fits and stage.mode != "always":
            return []
        for kind in [*sorted(fits, key=KIND_ORDER.index), "default"]:
            trained = [
                leg
                for name in role.picks.get(kind, ())
                if (leg := named_leg(extension, name))
            ]
            if trained:
                return trained
    leg = choose(extension, stage, goal, kinds)
    return [] if leg is None else [leg]


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
        legs += stage_legs(extension, stage, goal, kinds)
        if len(legs) >= MAX_LEGS:
            break
    return legs[:MAX_LEGS]


def check_task(goal: str) -> str:
    """What LCC's agent is asked to do last: check the finished work."""
    return (
        f"Final check of '{goal}' after every stage: run check_project, and "
        "polish_check for web pages, then fix everything they report and "
        "anything broken or unfinished (links that go nowhere, stray text, parts "
        "the stylesheet doesn't style, pictures that aren't shown). Keep the "
        "content and the stages' work; don't start over."
    )


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
