"""How the main agent hands work to the rest of the team."""

import re
from collections.abc import Sequence
from typing import Protocol

from free_claude_code.core.json_types import JsonObject

from .models import Agent, AgentRun, Chat, SiteProject
from .rooms import RoomOutcome
from .sites import slugify
from .store import StudioStore
from .tools import HELPER_ROLE, MAIN_ROLE, RESEARCHER_ROLE, ToolContext, ToolOutcome

MAX_REPORT_CHARS = 2_000
RESEARCH_LAB = "Research lab"
_BUILD_WORDS = re.compile(
    r"\b(build|make|create|website|site|app|page|landing|code|script|game)\b",
    re.IGNORECASE,
)
_NOT_DELEGABLE_ROLES = frozenset({MAIN_ROLE, "guide"})


class CrewHost(Protocol):
    """The Studio operations the crew runs its hand-offs through."""

    async def agents(self) -> tuple[Agent, ...]:
        """Return every agent."""
        ...

    async def sites(self) -> tuple[SiteProject, ...]:
        """Return every project workspace."""
        ...

    async def create_site(
        self, *, name: str, description: str = "", agent_id: str | None = None
    ) -> SiteProject:
        """Create a project workspace."""
        ...

    async def run_agent_task(
        self,
        agent: Agent,
        goal: str,
        *,
        site_id: str | None,
        parent_chat_id: str | None,
    ) -> tuple[AgentRun, Chat]:
        """Run one agent task to completion."""
        ...

    async def run_team_task(
        self, agents: Sequence[Agent], goal: str, *, site_id: str | None
    ) -> tuple[Chat, RoomOutcome]:
        """Run one goal in a new room until the agents settle."""
        ...

    async def start_agent_task(
        self,
        agent: Agent,
        goal: str,
        *,
        site_id: str | None,
        parent_chat_id: str | None,
    ) -> AgentRun:
        """Start one agent task in the background and return at once."""
        ...


class Crew:
    """Resolve names and projects, run the hand-off, and report back."""

    def __init__(
        self, *, store: StudioStore, host: CrewHost, helper_pipeline: bool = True
    ) -> None:
        self._store = store
        self._host = host
        self._helper_pipeline = helper_pipeline

    async def ask_agent(
        self,
        context: ToolContext,
        *,
        agent: str,
        task: str,
        project: str,
        background: bool = False,
    ) -> ToolOutcome:
        """Run one task on another agent and report its result."""
        worker = await self._resolve(agent, caller_id=context.agent_id)
        site = await self._project(
            context,
            project,
            task=task,
            builds="write_file" in worker.tools,
            owner=worker,
        )
        if background:
            started = await self._host.start_agent_task(
                worker,
                task,
                site_id=site.id if site else context.site_id,
                parent_chat_id=context.chat_id,
            )
            lines = [
                f"{worker.name} is working on it in the background and will "
                "report here when done."
            ]
            if site is not None:
                lines.append(f"Project: {site.name}")
            return ToolOutcome(
                text="\n".join(lines),
                data={
                    "tool": "ask_agent",
                    "agent_id": worker.id,
                    "agent": worker.name,
                    "run_id": started.id,
                    "chat_id": started.chat_id,
                    "site_id": started.site_id,
                    "status": started.status,
                    "background": True,
                },
            )
        run, chat = await self._host.run_agent_task(
            worker,
            task,
            site_id=site.id if site else context.site_id,
            parent_chat_id=context.chat_id,
        )
        report = (run.result or run.error or "(no report)").strip()
        lines = [f"{worker.name} {run.status} after {run.step} steps: {report}"]
        if site is not None:
            lines.append(f"Project: {site.name}")
        return ToolOutcome(
            text="\n".join(lines)[:MAX_REPORT_CHARS],
            data={
                "tool": "ask_agent",
                "agent_id": worker.id,
                "agent": worker.name,
                "run_id": run.id,
                "chat_id": chat.id,
                "site_id": run.site_id,
                "status": run.status,
            },
            failed=run.status != "succeeded",
        )

    async def team_task(
        self,
        context: ToolContext,
        *,
        agents: Sequence[str],
        goal: str,
        project: str,
    ) -> ToolOutcome:
        """Run one goal with several agents in a room and report the result."""
        members: list[Agent] = []
        for name in agents:
            member = await self._resolve(name, caller_id=context.agent_id)
            if all(existing.id != member.id for existing in members):
                members.append(member)
        site = await self._project(
            context,
            project,
            task=goal,
            builds=any("write_file" in member.tools for member in members),
            owner=members[0],
        )
        room, outcome = await self._host.run_team_task(
            members, goal, site_id=site.id if site else context.site_id
        )
        if outcome.completed:
            report = f"Done: {outcome.summary}"
        else:
            report = await self._latest_words(room)
            report = f"Not finished yet after {outcome.turns} turns. {report}".strip()
        names = ", ".join(member.name for member in members)
        lines = [f"Team ({names}) in room '{room.title}': {report}"]
        if site is not None:
            lines.append(f"Project: {site.name}")
        return ToolOutcome(
            text="\n".join(lines)[:MAX_REPORT_CHARS],
            data={
                "tool": "team_task",
                "room_id": room.id,
                "chat_id": room.id,
                "agents": [member.name for member in members],
                "site_id": site.id if site else context.site_id,
                "completed": outcome.completed,
            },
            failed=not outcome.completed,
        )

    async def consult(self, context: ToolContext, *, question: str) -> ToolOutcome:
        """Have the Researcher look something up for another agent."""
        researchers = [
            agent
            for agent in await self._host.agents()
            if agent.role == RESEARCHER_ROLE
            and not agent.archived
            and agent.id != context.agent_id
        ]
        if not researchers:
            raise ValueError(
                "The team has no researcher. Add one with the + button and "
                "the researcher role."
            )
        researcher = researchers[0]
        lab = await self._lab(researcher)
        run, chat = await self._host.run_agent_task(
            researcher,
            f"{context.agent_name} asks: {question}",
            site_id=lab.id,
            parent_chat_id=context.chat_id,
        )
        report = (run.result or run.error or "(no answer)").strip()
        text = f"{researcher.name} answered: {report}"
        data: JsonObject = {
            "tool": "ask_researcher",
            "agent_id": researcher.id,
            "agent": researcher.name,
            "run_id": run.id,
            "chat_id": chat.id,
            "status": run.status,
        }
        helper = await self._teammate(HELPER_ROLE, exclude=context.agent_id)
        if self._helper_pipeline and helper is not None and run.status == "succeeded":
            # The Helper filters the findings into something the asker can act on.
            advice, helped = await self._advise(
                helper, context, request=question, material=report
            )
            text = (
                f"{researcher.name} found: {report[:900]}\n\n"
                f"{helper.name}'s plan: {advice}"
            )
            data |= {"helper_run_id": helped.id, "helper_chat_id": helped.chat_id}
        return ToolOutcome(
            text=text[: MAX_REPORT_CHARS * 2],
            data=data,
            failed=run.status != "succeeded",
        )

    async def help(
        self, context: ToolContext, *, request: str, material: str
    ) -> ToolOutcome:
        """Have the Helper turn a request and material into next steps."""
        helper = await self._teammate(HELPER_ROLE, exclude=context.agent_id)
        if helper is None:
            raise ValueError(
                "The team has no helper. Add one with the + button and the helper role."
            )
        advice, run = await self._advise(
            helper, context, request=request, material=material
        )
        return ToolOutcome(
            text=f"{helper.name} suggests: {advice}"[: MAX_REPORT_CHARS * 2],
            data={
                "tool": "ask_helper",
                "agent_id": helper.id,
                "agent": helper.name,
                "run_id": run.id,
                "chat_id": run.chat_id,
                "status": run.status,
            },
            failed=run.status != "succeeded",
        )

    async def _advise(
        self, helper: Agent, context: ToolContext, *, request: str, material: str
    ) -> tuple[str, AgentRun]:
        work = await self._work_context(context)
        brief = [f"{context.agent_name} needs help: {request}"]
        if work:
            brief.append(f"What {context.agent_name} is working on: {work}")
        if material:
            brief.append(f"Material to work from:\n{material[:6_000]}")
        run, _ = await self._host.run_agent_task(
            helper,
            "\n\n".join(brief),
            site_id=context.site_id,
            parent_chat_id=context.chat_id,
        )
        return (run.result or run.error or "(no advice)").strip(), run

    async def _work_context(self, context: ToolContext) -> str:
        """What the asking agent is trying to finish, from its task or chat."""
        runs = await self._store.find(
            AgentRun,
            where={"chat_id": context.chat_id},
            order_by="created_at DESC",
            limit=1,
        )
        if runs:
            return runs[0].goal[:600]
        transcript = await self._store.transcript(context.chat_id, limit=12)
        asked = [message for message in transcript if message.role == "user"]
        return asked[-1].text[:600] if asked else ""

    async def _teammate(self, role: str, *, exclude: str) -> Agent | None:
        return next(
            (
                agent
                for agent in await self._host.agents()
                if agent.role == role and not agent.archived and agent.id != exclude
            ),
            None,
        )

    async def _lab(self, researcher: Agent) -> SiteProject:
        wanted = RESEARCH_LAB.casefold()
        for site in await self._host.sites():
            if site.name.casefold() == wanted:
                return site
        return await self._host.create_site(
            name=RESEARCH_LAB,
            description="Where the researcher tests code before recommending it.",
            agent_id=researcher.id,
        )

    async def _resolve(self, name: str, *, caller_id: str) -> Agent:
        wanted = name.strip().lstrip("@").strip().casefold()
        team = [
            agent
            for agent in await self._host.agents()
            if not agent.archived
            and agent.id != caller_id
            and agent.role not in _NOT_DELEGABLE_ROLES
        ]
        exact = [agent for agent in team if agent.name.casefold() == wanted]
        if exact:
            return exact[0]
        partial = [agent for agent in team if agent.name.casefold().startswith(wanted)]
        if wanted and len(partial) == 1:
            return partial[0]
        names = ", ".join(agent.name for agent in team) or "nobody"
        raise ValueError(f"No agent called {name!r} on the team. Team: {names}.")

    async def _project(
        self,
        context: ToolContext,
        project: str,
        *,
        task: str,
        builds: bool,
        owner: Agent,
    ) -> SiteProject | None:
        name = project.strip()
        if not name and owner.role == RESEARCHER_ROLE and not context.site_id:
            return await self._lab(owner)
        if not name:
            # Build work needs somewhere to write files; small models often
            # forget the optional project, so give the work a home.
            if context.site_id or not builds or not _BUILD_WORDS.search(task):
                return None
            name = _title_from(task)
        wanted = name.casefold()
        slug = slugify(name)
        for site in await self._host.sites():
            if site.name.casefold() == wanted or site.slug == slug:
                return site
        return await self._host.create_site(
            name=name, description=task[:200], agent_id=owner.id
        )

    async def _latest_words(self, room: Chat) -> str:
        transcript = await self._store.transcript(room.id, limit=6)
        spoken = [
            f"{message.author}: {message.text.strip()[:300]}"
            for message in transcript
            if message.role == "assistant" and message.text.strip()
        ]
        return " | ".join(spoken[-2:])


def _title_from(task: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", task)
    return " ".join(words[:5]).strip() or "New project"
