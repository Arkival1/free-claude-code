"""The Builder checks its project before it may finish."""

import ast
from pathlib import Path

import pytest

from free_claude_code.studio import presets
from free_claude_code.studio.models import Agent
from free_claude_code.studio.presets import BUILDER_PROMPT, PROMPT_UPGRADES
from free_claude_code.studio.project_check import check_project

from .conftest import tool_reply

GOOD_PAGE = (
    "<!doctype html><html><head><title>Hi</title>"
    '<meta name="viewport" content="width=device-width">'
    '<link rel="stylesheet" href="style.css"></head>'
    '<body><a href="#top" id="top">Top</a><img src="logo.png" alt="Logo">'
    '<script src="app.js"></script></body></html>'
)


def test_a_clean_project_has_no_problems():
    files = {
        "index.html": GOOD_PAGE,
        "style.css": "body { color: red; } @media (max-width: 600px) { a { b: c; } }",
        "app.js": "const re = /[(]+/g;\nif (re.test('(')) { console.log(`x ${1 + 2}`); }",
        "logo.png": "",
        "data.json": '{"ok": true}',
        "tool.py": "def f():\n    return 1\n",
    }
    assert check_project(files) == []


def test_the_usual_mistakes_are_found():
    problems = check_project(
        {
            "pages/about.html": (
                '<html><body><a href="../missing.html">x</a><a href="#nope">y</a>'
                '<img src="../img/a.png"><script src="https://cdn.example/x.js"></script>'
                "</body></html>"
            ),
            "js/app.js": "import { x } from './util.js';\nfunction f() {\n  return (1;\n}",
            "css/site.css": "a { color: red;",
            "bad.py": "def f(:\n",
            "bad.json": "{nope}",
        }
    )
    text = "\n".join(problems)
    assert problems[0] == "There is no index.html, so the preview has no start page."
    assert "pages/about.html: links to missing.html, which is missing." in text
    assert "pages/about.html: links to img/a.png, which is missing." in text
    assert "#nope, but no element has that id" in text
    assert "cdn.example" not in text
    assert "no <title>" in text and "viewport" in text and "alt text" in text
    assert "js/app.js: imports js/util.js, which is missing." in text
    assert "js/app.js: unexpected '}' on line 4." in text
    assert "css/site.css: '{' opened on line 1 is never closed." in text
    assert "bad.py: syntax error on line 1" in text
    assert "bad.json: invalid JSON" in text


@pytest.mark.asyncio
async def test_the_builder_fixes_problems_before_it_finishes(make_studio):
    studio, model = make_studio(
        [
            tool_reply(
                "write_file",
                {
                    "path": "index.html",
                    "content": "<html><body><p>hi</p></body></html>",
                },
            ),
            tool_reply("finish", {"summary": "Done."}, call_id="call_2"),
            tool_reply(
                "write_file",
                {
                    "path": "index.html",
                    "content": GOOD_PAGE.replace(
                        '<link rel="stylesheet" href="style.css">', ""
                    )
                    .replace('<img src="logo.png" alt="Logo">', "")
                    .replace('<script src="app.js"></script>', ""),
                },
                call_id="call_3",
            ),
            tool_reply("finish", {"summary": "Fixed and done."}, call_id="call_4"),
        ]
    )
    await studio.ensure_defaults()
    builder = await studio.agent_by_name("Builder")
    assert builder is not None and "check_project" in builder.tools
    site = await studio.create_site(name="Hello")
    chat = await studio.create_chat(agent_id=builder.id, site_id=site.id)

    result = await studio.send(chat.id, "make a page")

    assert result.text == "Fixed and done."
    transcript = await studio.transcript(chat.id)
    check = next(m for m in transcript if m.author == "check_project")
    assert check.data["before_finish"] is True
    assert "no <title>" in check.text
    assert len(model.calls) == 4
    assert "check_project found problems" in model.calls[2]["prompt"]


@pytest.mark.asyncio
async def test_a_clean_project_finishes_straight_away(make_studio):
    studio, model = make_studio(
        [
            tool_reply("write_file", {"path": "data.json", "content": "{}"}),
            tool_reply("finish", {"summary": "Done."}, call_id="call_2"),
        ]
    )
    await studio.ensure_defaults()
    builder = await studio.agent_by_name("Builder")
    assert builder is not None
    site = await studio.create_site(name="Data")
    chat = await studio.create_chat(agent_id=builder.id, site_id=site.id)

    result = await studio.send(chat.id, "save data")

    assert result.text == "Done."
    assert len(model.calls) == 2


@pytest.mark.asyncio
async def test_unedited_starter_prompts_are_upgraded(make_studio):
    studio, _ = make_studio([])
    old_builder = next(
        old for old, new in PROMPT_UPGRADES.items() if new == BUILDER_PROMPT
    )
    await studio.store.put(
        Agent.model_validate(
            {
                "name": "Builder",
                "role": "builder",
                "model": "m",
                "system_prompt": old_builder,
            }
        )
    )
    await studio.store.put(
        Agent.model_validate(
            {
                "name": "Researcher",
                "role": "researcher",
                "model": "m",
                "system_prompt": "My own words.",
            }
        )
    )

    await studio.ensure_defaults()

    builder = await studio.agent_by_name("Builder")
    researcher = await studio.agent_by_name("Researcher")
    assert builder is not None and builder.system_prompt == BUILDER_PROMPT
    assert "check_project" in builder.tools
    assert researcher is not None and researcher.system_prompt == "My own words."


def test_every_old_starter_prompt_has_its_own_name_and_upgrades():
    # Two old Builder prompts once shared a name with another, so the later
    # one hid the earlier and agents on it were never upgraded.
    tree = ast.parse(Path(presets.__file__).read_text(encoding="utf-8"))
    names = [
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    ]
    assert len(names) == len(set(names))
    old = {getattr(presets, name) for name in names if name.startswith("_OLD_")}
    assert old <= set(PROMPT_UPGRADES)


def test_a_one_page_request_gets_a_one_page_template():
    # "Bakery" alone means the five-page business site; "one-page" wins.
    assert "asks for one page" in BUILDER_PROMPT
    assert BUILDER_PROMPT.index("asks for one page") < BUILDER_PROMPT.index(
        "use business"
    )


def test_a_favicon_cut_short_by_a_double_quote_is_a_problem():
    cut = GOOD_PAGE.replace(
        "</head>",
        '<link rel="icon" href="data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg">'
        '<text>x</text></svg>"></head>',
    )
    files = {"index.html": cut, "style.css": "", "logo.png": "", "app.js": ""}
    assert any("cut short by a double quote" in p for p in check_project(files))

    whole = GOOD_PAGE.replace(
        "</head>",
        '<link rel="icon" href="data:image/svg+xml,<svg xmlns=\'http://www.w3.org/2000/svg\'>'
        '<text>x</text></svg>"></head>',
    )
    encoded = GOOD_PAGE.replace(
        "</head>",
        '<link rel="icon" href="data:image/svg+xml,%3Csvg%3E%3C/svg%3E"></head>',
    )
    for page in (whole, encoded):
        files = {"index.html": page, "style.css": "", "logo.png": "", "app.js": ""}
        assert not any("cut short" in p for p in check_project(files))


def test_a_form_with_nowhere_to_send_messages_is_a_problem():
    page = (
        '<!doctype html><html><head><title>Cuts</title><meta name="viewport" '
        'content="width=device-width"></head><body>{form}{mail}</body></html>'
    )

    def problems(form: str, mail: str = "") -> list[str]:
        files = {"index.html": page.format(form=form, mail=mail)}
        return [p for p in check_project(files) if "nowhere to send" in p]

    assert problems('<form id="contact-form" data-endpoint="" data-email="">')
    assert problems("<form>", '<a href="mailto:hello@example.com">mail</a>')
    assert not problems('<form data-email="book@fadekings.test">')
    assert not problems('<form data-endpoint="https://formspree.io/f/x">')
    assert not problems('<form action="/send">')
    assert not problems("<form>", '<a href="mailto:book@fadekings.test">mail</a>')
