"""The Builder keeps going when a small local model stumbles, and finishes real pages.

These cover what went wrong with a real 1.5B and 3B model: tool calls with
unescaped HTML, replies cut off mid-file, reading the same files over and
over, the context filling up, and ending in plain words before the check.
"""

import pytest

from free_claude_code.studio.agents import (
    CUT_OFF_NOTE,
    IDLE_NOTE,
    SEEN_NOTE,
    UNREADABLE_NOTE,
    compact_history,
)
from free_claude_code.studio.llm import (
    ChatMessage,
    LLMReply,
    StudioLLMError,
    ToolCall,
    parse_tool_directives,
    unreadable_tool_call,
)
from free_claude_code.studio.sites import (
    _OLD_STARTER_STYLES,
    STARTER_STYLES,
    is_starter,
    tidy_html,
)

from .conftest import tool_reply
from .test_builder_upgrades import builder_chat, tools_used

PAGE = (
    "<!doctype html>\n<html><head><title>Sunrise Bakery</title>"
    '<meta name="viewport" content="width=device-width, initial-scale=1">'
    "</head><body><h1>Sunrise Bakery</h1></body></html>"
)


def sent(call: dict) -> str:
    messages = call["messages"]
    return "\n".join(m.content for m in messages) if isinstance(messages, list) else ""


def test_a_file_can_follow_the_json_in_a_code_block():
    (call,), _ = parse_tool_directives(
        '{"tool": "write_file", "arguments": {"path": "styles.css"}}\n'
        "```css\nbody { color: red; }\n.a { margin: 0 }\n```"
    )
    assert call.arguments == {
        "path": "styles.css",
        "content": "body { color: red; }\n.a { margin: 0 }",
    }


def test_small_model_json_mistakes_are_read():
    (lines,), _ = parse_tool_directives(
        '{"tool": "write_file", "arguments": {"path": "a.txt", "content": "one\ntwo"}}'
    )
    assert lines.arguments["content"] == "one\ntwo"
    (quotes,), _ = parse_tool_directives(
        '{"tool": "write_file", "arguments": {"path": "index.html", '
        '"content": "<p class="big">Hi</p>\\n"}}'
    )
    assert quotes.arguments == {
        "path": "index.html",
        "content": '<p class="big">Hi</p>\n',
    }
    assert parse_tool_directives('Done.\n```json\n{"final": "All good"}\n```') == (
        (),
        "All good",
    )


def test_a_cut_off_call_is_not_guessed_at():
    cut = '{"tool": "write_file", "arguments": {"path": "index.html", "content": "<p class="a'
    assert parse_tool_directives(cut) == ((), None)
    assert unreadable_tool_call(cut)
    assert not unreadable_tool_call("I built the page.")


def test_pages_get_what_every_page_needs():
    fixed, added = tidy_html(
        "<html><head><title>x</title></head><body>Hi</body></html>"
    )
    assert fixed.startswith("<!doctype html>\n")
    assert '<meta charset="utf-8">' in fixed and 'name="viewport"' in fixed
    assert added == ["charset", "mobile viewport", "doctype"]
    assert tidy_html(PAGE.replace("<head>", '<head><meta charset="utf-8">'))[1] == []
    assert tidy_html("body { color: red }") == ("body { color: red }", [])


def test_new_and_old_starter_styles_count_as_placeholders():
    assert is_starter("styles.css", STARTER_STYLES)
    assert is_starter("styles.css", _OLD_STARTER_STYLES)
    assert "section > ul" in STARTER_STYLES, "plain lists become tiles"


def test_long_histories_shrink_their_oldest_tool_output():
    history = [ChatMessage.user("Build the bakery site.")]
    for index in range(12):
        history.append(
            ChatMessage(
                role="assistant",
                tool_calls=(
                    ToolCall(
                        id=f"c{index}",
                        name="write_file",
                        arguments={"path": "index.html", "content": "x" * 5_000},
                    ),
                ),
            )
        )
        history.append(
            ChatMessage(role="tool", content="y" * 5_000, tool_call_id=f"c{index}")
        )

    kept = compact_history(history, budget=40_000)

    assert kept[0].content == "Build the bakery site."
    assert "older result shortened" in kept[2].content
    assert str(kept[1].tool_calls[0].arguments["content"]).startswith(
        "[written to the file"
    )
    assert kept[-1].content == "y" * 5_000, "the newest stay whole"
    assert compact_history(history[:3]) == history[:3]


@pytest.mark.asyncio
async def test_a_garbled_tool_call_is_sent_back_instead_of_ending_the_job(make_studio):
    studio, model = make_studio(
        [
            LLMReply(
                text='{"tool": "write_file", "arguments": {"path": "index.html", '
                '"content": "<p class="a'
            ),
            tool_reply("write_file", {"path": "index.html", "content": PAGE}),
            tool_reply("finish", {"summary": "Built it."}, call_id="c2"),
        ]
    )
    _, site, chat = await builder_chat(studio)

    await studio.send(chat.id, "make the bakery page")

    assert UNREADABLE_NOTE in sent(model.calls[1])
    assert "Sunrise Bakery" in await studio.workspace.read(site.id, "index.html")
    assert (await studio.transcript(chat.id))[-1].text == "Built it."


@pytest.mark.asyncio
async def test_a_reply_cut_off_at_the_limit_is_told_to_write_in_parts(make_studio):
    studio, model = make_studio(
        [
            LLMReply(
                text='{"tool": "write_file", "arguments": {"path": "index.html", '
                '"content": "<html><body>' + "x" * 50,
                stop_reason="length",
            ),
            tool_reply("write_file", {"path": "index.html", "content": PAGE}),
            tool_reply(
                "write_file",
                {"path": "index.html", "content": "<!-- more -->", "append": True},
                call_id="c2",
            ),
            tool_reply("finish", {"summary": "Done."}, call_id="c3"),
        ]
    )
    _, site, chat = await builder_chat(studio)

    await studio.send(chat.id, "make the bakery page")

    assert CUT_OFF_NOTE in sent(model.calls[1])
    page = await studio.workspace.read(site.id, "index.html")
    assert page.startswith("<!doctype html>") and page.endswith("<!-- more -->")
    added = [
        m for m in tools_used(await studio.transcript(chat.id)) if "Added to" in m.text
    ]
    assert added


@pytest.mark.asyncio
async def test_reading_the_same_file_again_says_to_write_instead(make_studio):
    read = tool_reply("read_file", {"path": "index.html"})
    studio, _ = make_studio(
        [
            read,
            tool_reply("read_file", {"path": "index.html"}, call_id="c2"),
            tool_reply(
                "write_file", {"path": "index.html", "content": PAGE}, call_id="c3"
            ),
            tool_reply("read_file", {"path": "index.html"}, call_id="c4"),
            tool_reply("finish", {"summary": "Done."}, call_id="c5"),
        ]
    )
    _, _, chat = await builder_chat(studio)

    await studio.send(chat.id, "make the bakery page")

    first, again, _, after_write, *_ = tools_used(await studio.transcript(chat.id))
    assert "<!doctype html>" in first.text
    assert again.text == SEEN_NOTE
    assert "Sunrise Bakery" in after_write.text, (
        "a write makes reading worthwhile again"
    )


@pytest.mark.asyncio
async def test_looking_around_too_long_gets_a_nudge_to_write(make_studio):
    looks = [
        tool_reply("list_files", {"pattern": f"*{n}"}, call_id=f"l{n}")
        for n in range(4)
    ]
    studio, model = make_studio(
        [*looks, tool_reply("finish", {"summary": "Done."}, call_id="f")]
    )
    _, _, chat = await builder_chat(studio)

    await studio.send(chat.id, "make the bakery page")

    assert IDLE_NOTE.format(steps=4) in sent(model.calls[4])
    assert IDLE_NOTE.format(steps=4) not in sent(model.calls[3])


@pytest.mark.asyncio
async def test_a_full_context_is_squeezed_and_tried_again(make_studio):
    calls = {"n": 0}

    def respond(system: str, prompt: str):
        calls["n"] += 1
        if calls["n"] == 2:
            raise StudioLLMError(
                "Model endpoint returned 400: request (16933 tokens) exceeds the "
                "available context size (16384 tokens)"
            )
        if calls["n"] == 1:
            return tool_reply("write_file", {"path": "index.html", "content": PAGE})
        return tool_reply("finish", {"summary": "Done."}, call_id="f")

    studio, _ = make_studio(respond)
    _, _, chat = await builder_chat(studio)

    await studio.send(chat.id, "make the bakery page")

    assert (await studio.transcript(chat.id))[-1].text == "Done."
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_ending_in_plain_words_still_runs_the_check(make_studio):
    studio, model = make_studio(
        [
            tool_reply(
                "write_file",
                {"path": "index.html", "content": PAGE.replace("<title>", "<x>")},
            ),
            LLMReply(text="The site is done."),
            tool_reply(
                "write_file", {"path": "index.html", "content": PAGE}, call_id="c2"
            ),
            LLMReply(text="Fixed and done."),
        ]
    )
    _, _, chat = await builder_chat(studio)

    await studio.send(chat.id, "make the bakery page")

    assert "Not finished yet. check_project found problems" in sent(model.calls[2])
    assert "no <title>" in sent(model.calls[2])
    assert (await studio.transcript(chat.id))[-1].text == "Fixed and done."


@pytest.mark.asyncio
async def test_a_thin_stylesheet_keeps_the_designed_base_underneath(make_studio):
    studio, _ = make_studio(
        [
            tool_reply(
                "write_file",
                {"path": "styles.css", "content": "header { background-color: gold; }"},
            ),
            tool_reply(
                "write_file",
                {"path": "styles.css", "content": "h1 { color: red; }"},
                call_id="c2",
            ),
            tool_reply("finish", {"summary": "Done."}, call_id="c3"),
        ]
    )
    _, site, chat = await builder_chat(studio)

    await studio.send(chat.id, "style the page")

    first, second, *_ = tools_used(await studio.transcript(chat.id))
    assert "kept its base styles underneath" in first.text
    assert "kept its base styles underneath" in second.text
    css = await studio.workspace.read(site.id, "styles.css")
    assert css.startswith("@layer studio-base {") and css.count("@layer") == 1
    assert css.endswith("/* Project styles */\nh1 { color: red; }")
    assert "gold" not in css, "the rewrite replaces the project's own rules"
