"""wshobson/agents comes with FCC: its agents keep the model tier they ask
for (light, everyday, strong), and the Changer's helper team of eight lean
agents is added from it in one click, listed in the Changer's notebook."""

import zipfile
from pathlib import Path

import pytest

from free_claude_code.studio.extensions import (
    AgentDef,
    Extension,
    agent_tier,
    scan,
)
from free_claude_code.studio.models import ChangeProject
from free_claude_code.studio.service import (
    CHANGER_HELPER_TEAM,
    CHANGER_HELPERS,
    HELPER_REPO,
)

VENDORED = Path(__file__).resolve().parents[2] / "vendor" / "repos"


@pytest.mark.parametrize(
    ("model", "tier"),
    [
        ("haiku", "light"),
        ("claude-haiku-5-5", "light"),
        ("sonnet", ""),
        ("inherit", ""),
        ("", ""),
        ("opus", "strong"),
        ("fable", "strong"),
    ],
)
def test_the_model_an_agent_asks_for_becomes_a_tier(model, tier):
    assert agent_tier(model) == tier


def test_the_vendored_copy_holds_the_helper_team_with_its_tiers(tmp_path):
    with zipfile.ZipFile(VENDORED / "wshobson__agents.zip") as archive:
        archive.extractall(tmp_path)
    root = next(tmp_path.iterdir())
    extension = scan(root, base=tmp_path, name="agents")
    by_name = {agent.name: agent for agent in extension.agents}
    assert len(by_name) >= 150
    for source, _ in CHANGER_HELPERS:
        assert source in by_name, source
        assert by_name[source].prompt.strip()
    assert by_name["search-specialist"].tier == "light"
    assert by_name["debugging-toolkit-debugger"].tier == ""
    assert by_name["python-pro"].tier == "strong"
    # Hooks, tool folders and evals stay out; nothing in it is meant to run.
    names = [path.relative_to(root).as_posix() for path in root.rglob("*")]
    assert not any(name.startswith(("tools/", "evals/")) for name in names)
    assert not any("/hooks/" in name for name in names)


def helper_repo(*, enabled: bool = False) -> Extension:
    return Extension(
        id="ext_wshobson",
        name="agents",
        source=HELPER_REPO,
        enabled=enabled,
        agents=[
            AgentDef(
                name=name,
                description=f"The {name}.",
                prompt=f"You are {name}.",
                tier=tier,
            )
            for name, tier in (
                ("debugging-toolkit-debugger", ""),
                ("python-pro", "strong"),
                ("search-specialist", "light"),
                ("ui-designer", ""),
            )
        ],
    )


@pytest.mark.asyncio
async def test_the_helper_team_joins_with_the_model_each_tier_needs(make_studio):
    studio, _ = make_studio(
        [],
        STUDIO_LIGHT_MODEL="groq/llama-3.1-8b-instant",
        STUDIO_STRONG_MODEL="nvidia_nim/nvidia/nemotron-3-ultra-550b-a55b",
    )
    await studio._extensions.save(helper_repo())
    first = await studio.add_changer_helpers()
    assert first["added"] == [
        "debugger",
        "python-pro",
        "ui-designer",
        "search-specialist",
    ]
    models = {agent.name: agent.model for agent in await studio.agents()}
    assert models["search-specialist"] == "groq/llama-3.1-8b-instant"
    assert models["python-pro"] == "nvidia_nim/nvidia/nemotron-3-ultra-550b-a55b"
    assert models["debugger"] == studio.server_model
    repo = next(e for e in await studio._extensions.all() if e.id == "ext_wshobson")
    assert repo.enabled, "adding the team turns the repo on"
    again = await studio.add_changer_helpers()
    assert again["added"] == []


@pytest.mark.asyncio
async def test_tiers_fall_back_to_the_studio_default(make_studio):
    studio, _ = make_studio([])
    await studio._extensions.save(helper_repo(enabled=True))
    await studio.add_changer_helpers()
    assert {
        agent.model
        for agent in await studio.agents()
        if agent.name in CHANGER_HELPER_TEAM
    } == {studio.server_model}


@pytest.mark.asyncio
async def test_without_the_repo_it_says_where_to_add_it(make_studio):
    studio, _ = make_studio([])
    from free_claude_code.studio import StudioError

    with pytest.raises(StudioError, match="Repos that come with FCC"):
        await studio.add_changer_helpers()


@pytest.mark.asyncio
async def test_the_notebook_lists_the_helpers_the_changer_can_hand_parts_to(
    make_studio,
):
    studio, _ = make_studio([])
    await studio._extensions.save(helper_repo(enabled=True))
    await studio.add_changer_helpers()
    await studio._store.put(ChangeProject(request="Fix the page", status="building"))
    text = await studio._notebook_text()
    assert "Team helpers (hand one a separate part with fcc_changer subagent" in text
    assert "debugger: The debugging-toolkit-debugger." in text
    assert "search-specialist" in text
