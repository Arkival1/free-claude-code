"""Team brains: each agent thinks with its own model, and local models take turns."""

import asyncio

import httpx
import pytest

from free_claude_code.studio.llm import LLMReply
from free_claude_code.studio.model_turns import ModelTurns
from free_claude_code.studio.team_models import (
    match_model,
    model_size,
    parse_model_request,
    suggest_mix,
)
from tests.api.support import create_test_app

from .conftest import tool_reply

TEAM = ["Jarvis", "Builder", "Researcher", "Helper", "Tester", "Guide"]
ON_PC = [
    "local/qwen2.5-coder-7b-instruct",
    "local/qwen2.5-7b-instruct",
    "local/llama-3.2-3b-instruct",
    "local/deepseek-r1-distill-qwen-7b",
    "local/text-embedding-nomic-embed-text-v1.5",
]


@pytest.mark.parametrize(
    ("text", "wanted"),
    [
        ("give the Builder qwen coder", ("Builder", "qwen coder")),
        ("Jarvis, switch the researcher to llama 3.2", ("Researcher", "llama 3.2")),
        ("have Builder use qwen2.5-coder", ("Builder", "qwen2.5-coder")),
        ("the tester should use deepseek", ("Tester", "deepseek")),
        ("use llama for the guide", ("Guide", "llama")),
        ("set Helper's brain to deepseek r1", ("Helper", "deepseek r1")),
        ("put the helper on qwen 7b please", ("Helper", "qwen 7b")),
        ("switch yourself to llama", ("Jarvis", "llama")),
    ],
)
def test_model_requests_are_understood(text, wanted):
    assert parse_model_request(text, TEAM, main="Jarvis") == wanted


@pytest.mark.parametrize(
    "text",
    [
        "Have Builder build a bakery site",
        "make the builder a landing page",
        "give Sam the report",
        "what model do you use?",
    ],
)
def test_other_messages_are_not_model_requests(text):
    pair = parse_model_request(text, TEAM, main="Jarvis")
    assert pair is None or match_model(pair[1], ON_PC) is None


def test_spoken_model_names_find_the_real_model():
    assert match_model("qwen coder", ON_PC) == "local/qwen2.5-coder-7b-instruct"
    assert match_model("qwen 7b", ON_PC) == "local/qwen2.5-7b-instruct"
    assert match_model("llama", ON_PC) == "local/llama-3.2-3b-instruct"
    assert match_model("local/llama-3.2-3b-instruct", ON_PC) == ON_PC[2]
    assert match_model("mistral", ON_PC) is None
    assert match_model("tailwind to build a site", ON_PC) is None
    assert model_size("local/qwen2.5-coder-7b-instruct") == 7.0
    assert model_size("local/phi-mini") is None


def test_a_suggested_mix_fits_each_role():
    team = [
        ("b", "builder"),
        ("t", "tester"),
        ("r", "researcher"),
        ("h", "helper"),
        ("m", "main"),
        ("g", "guide"),
    ]
    mix = suggest_mix(team, ON_PC)
    assert mix["b"] == mix["t"] == "local/qwen2.5-coder-7b-instruct"
    assert mix["h"] == "local/deepseek-r1-distill-qwen-7b"
    assert mix["g"] == "local/llama-3.2-3b-instruct"
    assert mix["r"] == "local/qwen2.5-7b-instruct"
    assert "embed" not in " ".join(mix.values())
    assert suggest_mix(team, []) == {}


def test_a_suggested_mix_uses_what_each_model_can_do():
    team = [("r", "researcher"), ("h", "helper"), ("m", "main")]
    models = ["local/big-chat-14b", "local/qwen3-8b", "local/tiny-4b"]
    blind = suggest_mix(team, models)
    assert blind["r"] == blind["h"] == "local/big-chat-14b"

    mix = suggest_mix(
        team,
        models,
        {
            "local/big-chat-14b": set(),
            "local/qwen3-8b": {"tools", "reasoning"},
            "local/tiny-4b": {"tools"},
        },
    )
    assert mix["r"] == "local/qwen3-8b", "the Researcher gets a model trained for tools"
    assert mix["h"] == "local/qwen3-8b", "a model that reasons suits the Helper"
    assert mix["m"] == "local/qwen3-8b"


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


async def started(turns: ModelTurns, model: str) -> asyncio.Task[None]:
    """Start a call to ``model`` that holds its turn until cancelled."""

    async def call() -> None:
        async with turns.turn(model):
            await asyncio.Event().wait()

    task = asyncio.ensure_future(call())
    await asyncio.sleep(0.05)
    return task


async def stop(task: asyncio.Task[None]) -> None:
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_the_same_model_answers_several_calls_at_once():
    turns = ModelTurns(grace=0)
    first = await started(turns, "coder")
    second = await started(turns, "coder")
    assert turns.working == ("coder",) and not turns.waiting
    await stop(first)
    await stop(second)


@pytest.mark.asyncio
async def test_another_model_waits_until_the_first_is_idle():
    turns = ModelTurns(grace=0)
    coder = await started(turns, "coder")
    chat = await started(turns, "chat")
    assert turns.working == ("coder",) and turns.waiting == ("chat",)
    await stop(coder)
    await asyncio.sleep(0.3)
    assert turns.working == ("chat",) and not turns.waiting
    await stop(chat)


@pytest.mark.asyncio
async def test_the_last_model_keeps_its_turn_between_steps():
    clock = Clock()
    turns = ModelTurns(grace=3.0, clock=clock)
    step = await started(turns, "coder")
    other = await started(turns, "chat")
    await stop(step)
    assert turns.waiting == ("chat",), "the Builder's next step comes first"
    next_step = await started(turns, "coder")
    assert turns.working == ("coder",)
    await stop(next_step)
    clock.now += 3.5
    await asyncio.sleep(0.3)
    assert turns.working == ("chat",), "once it goes quiet, the other model goes"
    await stop(other)


@pytest.mark.asyncio
async def test_nobody_waits_forever():
    clock = Clock()
    turns = ModelTurns(grace=0, patience=60, clock=clock)
    busy = await started(turns, "coder")
    waiting = await started(turns, "chat")
    clock.now += 61
    blocked = await started(turns, "coder")
    assert turns.waiting == ("chat", "coder"), "new coder calls queue behind chat"
    await stop(busy)
    await asyncio.sleep(0.3)
    assert turns.working == ("chat",)
    await stop(waiting)
    await asyncio.sleep(0.3)
    assert turns.working == ("coder",)
    await stop(blocked)


@pytest.mark.asyncio
async def test_models_loaded_side_by_side_run_together():
    async def loaded():
        return ("coder", "chat")

    turns = ModelTurns(loaded=loaded, grace=0)
    coder = await started(turns, "coder")
    chat = await started(turns, "chat")
    assert set(turns.working) == {"coder", "chat"}
    await stop(coder)
    await stop(chat)


def with_models_on_pc(studio, models=ON_PC):
    async def local_models():
        return {"base_url": "http://lm", "reachable": True, "models": models}

    studio.local_models = local_models


@pytest.mark.asyncio
async def test_each_agent_gets_its_own_model(make_studio):
    studio, _ = make_studio([])
    await studio.ensure_defaults()
    with_models_on_pc(studio)
    agents = {a.name: a for a in await studio.agents()}

    changed = await studio.assign_models(
        {
            agents["Builder"].id: "local/qwen2.5-coder-7b-instruct",
            agents["Researcher"].id: "local/qwen2.5-7b-instruct",
            agents["Helper"].id: agents["Helper"].model,
        }
    )

    assert {agent.name for agent in changed} == {"Builder", "Researcher"}
    brains = await studio.team_models()
    rows = {row["name"]: row for row in brains["agents"]}
    assert rows["Builder"]["model"] == "local/qwen2.5-coder-7b-instruct"
    assert rows["Builder"]["using"] == "local/qwen2.5-coder-7b-instruct"
    assert rows["Builder"]["note"] == ""
    builder = next(a for a in await studio.agents() if a.name == "Builder")
    assert builder.local_only
    suggested = await studio.suggest_team_models()
    assert suggested[agents["Builder"].id] == "local/qwen2.5-coder-7b-instruct"
    with pytest.raises(Exception, match="Pick a model"):
        await studio.assign_models({agents["Builder"].id: " "})


@pytest.mark.asyncio
async def test_a_missing_model_says_which_one_is_used_instead(make_studio):
    studio, _ = make_studio([])
    await studio.ensure_defaults()
    with_models_on_pc(studio, ["local/qwen2.5-7b-instruct"])
    builder = next(a for a in await studio.agents() if a.name == "Builder")
    await studio.assign_models({builder.id: "local/gone-model-7b"})

    rows = {row["name"]: row for row in (await studio.team_models())["agents"]}

    assert rows["Builder"]["using"] == "local/qwen2.5-7b-instruct"
    assert "gone-model-7b isn't available" in rows["Builder"]["note"]
    console = await studio.main_console()
    member = next(m for m in console["team"] if m["name"] == "Builder")
    assert member["using"] == "local/qwen2.5-7b-instruct" and member["local"]


@pytest.mark.asyncio
async def test_a_picked_main_model_is_not_undone_by_the_setting(make_studio):
    studio, _ = make_studio([], STUDIO_MAIN_AGENT_MODEL="local/qwen2.5-7b-instruct")
    main = await studio.main_agent()
    assert main.model == "local/qwen2.5-7b-instruct"

    await studio.assign_models({main.id: "local/llama-3.2-3b-instruct"})

    assert (await studio.main_agent()).model == "local/llama-3.2-3b-instruct"


@pytest.mark.asyncio
async def test_telling_jarvis_switches_an_agents_model(make_studio):
    studio, model = make_studio(["Done, the Builder uses Qwen Coder now."])
    await studio.ensure_defaults()
    with_models_on_pc(studio)

    await studio.main_say("Give the Builder qwen coder", background=False)

    builder = next(a for a in await studio.agents() if a.name == "Builder")
    assert builder.model == "local/qwen2.5-coder-7b-instruct"
    chat = await studio.main_chat()
    notes = [m for m in await studio.transcript(chat.id) if m.author == "agent_model"]
    assert notes[0].text == "Builder now thinks with qwen2.5-coder-7b-instruct."
    assert not await studio.runs(), "it is not handed to the Builder as a job"
    assert "It is done" in str(model.calls[-1]["studio_note"])


@pytest.mark.asyncio
async def test_jarvis_uses_the_agent_model_tool(make_studio):
    replies = iter(
        [
            tool_reply("agent_model", {}),
            tool_reply(
                "agent_model",
                {"agent": "the researcher", "model": "llama"},
                call_id="c2",
            ),
            tool_reply(
                "agent_model", {"agent": "Helper", "model": "gpt9"}, call_id="c3"
            ),
            LLMReply(text="The Researcher uses Llama now."),
        ]
    )

    def respond(system: str, prompt: str):
        if "the user's main AI" in system:
            return next(replies)
        return LLMReply(text="Goal:\n- Chat")

    studio, _ = make_studio(respond)
    await studio.ensure_defaults()
    with_models_on_pc(studio)

    await studio.main_say("what models is the team on?", background=False)

    chat = await studio.main_chat()
    listed, switched, missing = [
        m for m in await studio.transcript(chat.id) if m.role == "tool"
    ][-3:]
    assert "- Builder: " in listed.text
    assert "Models on this PC: qwen2.5-coder-7b-instruct" in listed.text
    assert switched.text == "Researcher now thinks with llama-3.2-3b-instruct."
    assert "No model matches 'gpt9'" in missing.text
    main = await studio.main_agent()
    assert "agent_model" in main.tools


class SlowLocal:
    """A local runtime that answers only when told to."""

    def __init__(self) -> None:
        self.go = asyncio.Event()
        self.models: list[str | None] = []

    async def complete(self, messages, *, model=None, **_):
        self.models.append(model)
        await self.go.wait()
        return LLMReply(text="ok")


@pytest.mark.asyncio
async def test_local_models_take_turns_through_the_router(make_studio):
    from free_claude_code.studio.llm import ChatMessage, StudioModelRouter

    slow = SlowLocal()
    router = StudioModelRouter(proxy=slow, local=slow)
    router.use_turns(lambda: True)
    router.turns = ModelTurns(grace=0)
    ask = [ChatMessage.user("hi")]
    coder = asyncio.ensure_future(router.complete(ask, model="local/coder-7b"))
    await asyncio.sleep(0.05)
    chat = asyncio.ensure_future(router.complete(ask, model="local/chat-8b"))
    await asyncio.sleep(0.05)

    assert slow.models == ["coder-7b"], "the second model waits its turn"
    assert router.turns.waiting == ("chat-8b",)
    slow.go.set()
    await asyncio.gather(coder, chat)
    assert slow.models == ["coder-7b", "chat-8b"]


@pytest.mark.asyncio
async def test_team_brains_through_the_routes(make_studio):
    studio, _ = make_studio([])
    await studio.ensure_defaults()
    with_models_on_pc(studio)
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        try:
            brains = (await client.get("/studio/api/team-models")).json()
            names = [row["name"] for row in brains["agents"]]
            assert "Builder" in names and "Jarvis" in names
            assert brains["turns"] is True and isinstance(brains["server"], list)
            builder = next(r for r in brains["agents"] if r["name"] == "Builder")
            suggested = (await client.get("/studio/api/team-models/suggest")).json()
            assert (
                suggested["assignments"][builder["id"]]
                == "local/qwen2.5-coder-7b-instruct"
            )
            saved = await client.post(
                "/studio/api/team-models",
                json={"assignments": {builder["id"]: "local/qwen2.5-7b-instruct"}},
            )
            assert saved.json() == {"changed": [builder["id"]]}
            empty = await client.post(
                "/studio/api/team-models", json={"assignments": {}}
            )
            assert empty.status_code == 422
            missing = await client.post(
                "/studio/api/team-models", json={"assignments": {"agt_nope": "x"}}
            )
            assert missing.status_code == 404
        finally:
            await studio.shutdown()
            await app.state.services.admin.close()
