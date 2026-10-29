"""The guide knows every page, says where to tap, and spots what is wrong."""

import re
from pathlib import Path

import pytest

from free_claude_code.studio.guide import (
    GUIDE_TOPICS,
    GuideAssistant,
    GuideState,
    diagnose,
    knowledge_text,
    match_topics,
    offline_answer,
)

from .conftest import tool_reply
from .test_stand_in import FakeLocal, build

STUDIO_JS = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "free_claude_code"
    / "api"
    / "studio_static"
    / "studio.js"
)


def test_every_topic_says_where_it_is_and_opens_a_real_page():
    pages = set(re.findall(r'case "([a-z]+)":', STUDIO_JS.read_text()))
    for topic in GUIDE_TOPICS:
        assert topic.where, topic.title
        if topic.route:
            assert topic.route.startswith("/studio#"), topic.title
            assert topic.route.removeprefix("/studio#") in pages, topic.title


@pytest.mark.parametrize(
    ("question", "title"),
    [
        ("what can this app do?", "What Studio can do"),
        ("how do I set up lm studio", "Setting up LM Studio"),
        ("why is it so slow", "Making replies faster"),
        ("how do i make an app", "Building apps and websites"),
        ("how do i change jarvis model", "Choosing Jarvis's brain"),
        ("mic not working", "Voice and talk mode"),
        ("how do I watch an agent work", "Agents at work"),
        ("how do I get the desktop icon", "Desktop app on Windows"),
        ("what does ATTENTION mean", "Troubleshooting"),
        ("where are the settings", "Settings"),
        ("how do I let agents run npm", "Commands and approvals"),
    ],
)
def test_everyday_questions_find_the_right_topic(question, title):
    assert title in [topic.title for topic in match_topics(question)]


def test_the_whole_app_is_in_the_knowledge():
    text = knowledge_text()
    for name in ("CHOOSE BRAIN", "AGENTS AT WORK", "Teach a skill", "Where:"):
        assert name in text


def test_problems_are_found_with_their_fix():
    state = GuideState(
        main_model="local/qwen-4b",
        local_url="http://localhost:1234/v1",
        local_reachable=False,
        approvals=2,
        web_online=False,
        voice_speak="builtin",
        voice_ready=False,
        last_error="Timed out.",
    )

    problems = diagnose(state)

    titles = [problem.title for problem in problems]
    assert titles[0] == "Local models are offline"
    assert "Start Server" in problems[0].fix
    assert problems[0].route == "/studio#models"
    assert "2 commands waiting for you" in titles
    assert "This PC is offline" in titles
    assert "The voice is not downloaded yet" in titles
    assert "The last reply failed" in titles
    assert diagnose(GuideState()) == ()


def test_a_server_model_without_a_key_is_named():
    problems = diagnose(
        GuideState(main_model="nvidia_nim/some-model", main_model_ready=False)
    )

    assert problems[0].title == "Jarvis's model has no key"
    assert "CHOOSE BRAIN" in problems[0].fix


def test_asking_whats_wrong_starts_with_the_problem():
    state = GuideState(main_model="local/x", local_reachable=False)
    state = GuideState(
        main_model="local/x", local_reachable=False, problems=diagnose(state)
    )

    answer = offline_answer("why is nothing working?", state)

    assert answer.text.startswith("Right now: **Local models are offline.**")
    assert answer.links[0].route == "/studio#models"
    assert answer.links[0].label == "Models"
    assert answer.suggestions


def test_answers_offer_follow_up_questions_and_pages():
    answer = offline_answer("how do I set up lm studio", GuideState())

    assert "Developer tab" in answer.text
    assert "*Where:*" in answer.text
    assert [link.label for link in answer.links] == ["Models"]
    assert "How do I set up LM Studio?" not in answer.suggestions
    assert len(answer.suggestions) == 3


def test_the_prompt_is_short_and_carries_the_matching_notes(make_studio):
    studio, _ = make_studio(["ok"])
    guide = GuideAssistant(router=studio._router, model="local/tiny")

    prompt = guide.system_prompt(GuideState(), "how do I set up lm studio")

    assert "## Setting up LM Studio" in prompt
    assert "- Obsidian:" in prompt, "every topic is in the index"
    assert "## Obsidian" not in prompt, "unrelated topics are not written out"
    assert len(prompt) < len(knowledge_text())


@pytest.mark.asyncio
async def test_the_guide_borrows_the_model_lm_studio_has_loaded(
    tmp_path, store, web_tools, studio_settings
):
    studio, local, _, _ = build(tmp_path, store, web_tools, studio_settings)

    answer = await studio.ask_guide("how do I set up lm studio")

    assert answer.offline is False
    assert answer.text == "Local here."
    assert local.calls == ["qwen-4b"]
    assert answer.links[0].route == "/studio#models"


@pytest.mark.asyncio
async def test_the_guide_sheet_shows_problems_and_every_topic(
    tmp_path, store, web_tools, studio_settings
):
    offline = FakeLocal()
    offline.served = ()
    studio, *_ = build(tmp_path, store, web_tools, studio_settings, local=offline)
    await studio.ensure_defaults()

    overview = await studio.guide_overview()

    assert overview["offline"] is True
    assert len(overview["topics"]) == len(GUIDE_TOPICS)
    assert overview["topics"][0]["page"] == "Command Center"
    assert overview["starters"]
    assert all(
        {"title", "fix", "route", "page"} <= set(p) for p in overview["problems"]
    )


@pytest.mark.asyncio
async def test_jarvis_looks_up_the_app_with_app_help(make_studio):
    replies = iter(
        [
            tool_reply("app_help", {"question": "how do I set up lm studio?"}),
            "Open LM Studio's Developer tab and press Start Server.",
        ]
    )
    studio, model = make_studio(lambda system, prompt: next(replies))
    await studio.ensure_defaults()

    chat = await studio.main_say("how do I set up lm studio?", background=False)

    assert "app_help" in model.calls[0]["tools"]
    transcript = await studio.transcript(chat.id)
    looked_up = next(message for message in transcript if message.role == "tool")
    assert "Developer tab" in looked_up.text
    assert "Pages: Models." in looked_up.text
    builder = await studio.agent_by_name("Builder")
    assert builder is not None and "app_help" not in builder.tools
