"""When the PC's own models are off (LM Studio closed), an agent set to one
thinks with the server model instead, sealed like any server agent, so its
memory never reaches the server (owner, 6.106)."""

import pytest

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
