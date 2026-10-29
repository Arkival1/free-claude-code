"""When the PC's own models are off (LM Studio closed), an agent set to one
thinks with the server model instead, sealed like any server agent, so its
memory never reaches the server (owner, 6.106)."""

import pytest

from free_claude_code.studio.llm import LLMReply, StudioLLMError

from .conftest import ScriptedLLM, tool_reply
from .test_private_memory import everything_sent, is_sealed, team

OFF = {"reachable": False, "models": []}
ON = {"reachable": True, "models": ["local/qwen2.5-coder-7b"]}


async def builder_on_this_pc(make_studio, monkeypatch, status, **settings):
    studio, model, agents = await team(
        make_studio,
        **{
            "STUDIO_LOCAL_BACKUP": True,
            "NVIDIA_NIM_API_KEY": "test-only-key",
            **settings,
        },
    )

    async def local_status():
        return status

    monkeypatch.setattr(studio, "_local_status", local_status)
    (builder,) = await studio.assign_models(
        {agents["Builder"].id: "local/qwen2.5-coder-7b"}
    )
    chat = await studio.create_chat(agent_id=builder.id)
    await studio.send(chat.id, "what colours does the bakery use?")
    return studio, model.calls[-1]


@pytest.mark.asyncio
async def test_the_server_model_takes_over_when_lm_studio_is_off(
    make_studio, monkeypatch
):
    studio, call = await builder_on_this_pc(make_studio, monkeypatch, OFF)
    assert "test-model" in str(call["model"])
    assert is_sealed(call), "a server model is sealed like any server agent"
    assert call["memory"] == ""
    assert "Biscuit" not in everything_sent(call)
    await studio.shutdown()


@pytest.mark.asyncio
async def test_a_running_pc_model_keeps_the_job(make_studio, monkeypatch):
    studio, call = await builder_on_this_pc(make_studio, monkeypatch, ON)
    assert "qwen2.5-coder-7b" in str(call["model"])
    assert not is_sealed(call)
    assert "teal and gold" in str(call["memory"])
    await studio.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "settings",
    [{"STUDIO_LOCAL_BACKUP": False}, {"NVIDIA_NIM_API_KEY": ""}],
    ids=["switched off", "no server key"],
)
async def test_no_backup_without_the_switch_or_a_key(
    make_studio, monkeypatch, settings
):
    studio, call = await builder_on_this_pc(make_studio, monkeypatch, OFF, **settings)
    assert "qwen2.5-coder-7b" in str(call["model"])
    await studio.shutdown()


@pytest.mark.asyncio
async def test_a_local_agent_off_pc_counts_as_a_server_agent(make_studio, monkeypatch):
    """While LM Studio is off, the briefing, the delegation lists and the seal
    all treat the stand-in agent as the server agent it is for now."""
    studio, _, agents = await team(
        make_studio,
        **{"STUDIO_LOCAL_BACKUP": True, "NVIDIA_NIM_API_KEY": "test-only-key"},
    )
    (builder,) = await studio.assign_models(
        {agents["Builder"].id: "local/qwen2.5-coder-7b"}
    )
    status = dict(ON)

    async def local_status():
        return status

    monkeypatch.setattr(studio, "_local_status", local_status)
    assert not await studio.is_private_from(builder)
    status.update(OFF)
    assert await studio.is_private_from(builder)
    await studio.shutdown()


@pytest.mark.asyncio
async def test_a_failing_pc_model_never_hands_memory_to_a_server_model(
    make_studio, monkeypatch
):
    """Mid-job, a local agent's conversation can hold the user's memory (it
    recalled it); if its model then fails, the job is not moved to the main
    AI's server model."""
    holder: list[ScriptedLLM] = []
    local_calls: list[int] = []

    def answer(system: str, prompt: str):
        if "qwen2.5-coder-7b" not in str(holder[0].calls[-1]["model"]):
            return LLMReply(text="Done.")
        local_calls.append(1)
        if len(local_calls) == 1:
            return tool_reply("recall", {"query": "bakery colours dog"})
        raise StudioLLMError("LM Studio crashed")

    studio, model, agents = await team(
        make_studio, answer, STUDIO_MAIN_AGENT_MODEL="nvidia_nim/test-model"
    )
    holder.append(model)

    async def local_status():
        return ON

    monkeypatch.setattr(studio, "_local_status", local_status)
    (builder,) = await studio.assign_models(
        {agents["Builder"].id: "local/qwen2.5-coder-7b"}
    )
    assert not await studio.is_private_from(builder)
    await studio.run_agent_task(
        builder, "What colours does the bakery use?", site_id=None, parent_chat_id=None
    )
    assert len(local_calls) >= 2, "the PC model recalled, then failed"
    to_server = [c for c in model.calls if "test-model" in str(c["model"])]
    assert all("Biscuit" not in everything_sent(c) for c in to_server)
    await studio.shutdown()
