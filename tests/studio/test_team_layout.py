"""Jarvis, the Guide, and the Helper think on this PC; the rest on a server."""

import pytest

from free_claude_code.studio.models import StudioFlag
from free_claude_code.studio.service import TEAM_LAYOUT_FLAG


@pytest.mark.asyncio
async def test_a_new_team_starts_with_the_layout(make_studio):
    studio, _ = make_studio([], STUDIO_MAIN_AGENT_MODEL="local/jarvis-8b")
    await studio.ensure_defaults()
    models = {agent.name: agent.model for agent in await studio.agents()}
    assert models["Jarvis"] == "local/jarvis-8b"
    assert models["Helper"] == "local/jarvis-8b"
    for name in ("Builder", "Researcher", "Tester"):
        assert models[name] == "nvidia_nim/test-model", name


@pytest.mark.asyncio
async def test_an_older_team_moves_once_and_keeps_later_choices(make_studio):
    studio, _ = make_studio([], STUDIO_MAIN_AGENT_MODEL="local/jarvis-8b")
    await studio.ensure_defaults()
    agents = {agent.name: agent for agent in await studio.agents()}
    # As an older version left it: the Builder on this PC, the Helper on a server.
    await studio.update_agent(agents["Builder"].id, {"model": "local/coder-7b"})
    await studio.update_agent(agents["Helper"].id, {"model": "nvidia_nim/test-model"})
    await studio._store.delete(StudioFlag, TEAM_LAYOUT_FLAG)

    await studio.ensure_defaults()
    models = {agent.name: agent.model for agent in await studio.agents()}
    assert models["Builder"] == "nvidia_nim/test-model"
    assert models["Helper"] == "local/jarvis-8b"

    # Switching a model afterwards sticks.
    await studio.update_agent(agents["Builder"].id, {"model": "local/coder-7b"})
    await studio.ensure_defaults()
    assert (await studio.agent(agents["Builder"].id)).model == "local/coder-7b"
