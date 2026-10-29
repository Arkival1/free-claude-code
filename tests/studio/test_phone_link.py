"""FCC Phone pairs with the PC, shares memory both ways, and borrows its brain."""

import sys

import httpx
import pytest

from free_claude_code.studio.llm import LLMReply, ToolCall
from free_claude_code.studio.memory import SHARED_MEMORY_ID
from free_claude_code.studio.models import PhoneLink
from free_claude_code.studio.phone_link import (
    MAX_WRONG_CODES,
    PHONE_TAG,
    PhoneLinkError,
    PhoneLinks,
    chat_messages,
    clean_code,
    token_hash,
)
from tests.api.support import create_test_app

ORIGIN = "https://arkival1.github.io"


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.mark.asyncio
async def test_a_code_pairs_one_phone_once(store):
    clock = Clock()
    links = PhoneLinks(store, clock=clock)
    code = links.new_code()
    assert len(code) == 9 and code[4] == "-"
    assert clean_code(code.lower().replace("-", " ")) == code.replace("-", "")

    link, token = await links.pair(code.lower(), "  Sam's   iPhone ")
    assert link.name == "Sam's iPhone"
    assert link.token_hash == token_hash(token) and token not in link.token_hash
    assert (await links.check(token)).id == link.id
    with pytest.raises(PhoneLinkError, match="didn't work"):
        await links.pair(code, "again")

    late = links.new_code()
    clock.now += 601
    with pytest.raises(PhoneLinkError):
        await links.pair(late, "late")


@pytest.mark.asyncio
async def test_guessing_codes_cancels_them_all(store):
    links = PhoneLinks(store)
    real = links.new_code()
    for _ in range(MAX_WRONG_CODES):
        with pytest.raises(PhoneLinkError):
            await links.pair("AAAA-AAAA", "guess")
    with pytest.raises(PhoneLinkError):
        await links.pair(real, "owner")


@pytest.mark.asyncio
async def test_an_unknown_or_removed_phone_is_turned_away(store):
    links = PhoneLinks(store)
    with pytest.raises(PhoneLinkError, match="isn't paired"):
        await links.check("")
    link, token = await links.pair(links.new_code(), "iPhone")
    await links.unlink(link.id)
    with pytest.raises(PhoneLinkError, match="Pair it again"):
        await links.check(token)


def test_phone_messages_become_studio_turns():
    turns = chat_messages(
        [
            {"role": "user", "content": "weather in Oslo?"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {
                            "name": "weather",
                            "arguments": '{"place":"Oslo"}',
                        },
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "5°C"},
        ]
    )
    assert [turn.role for turn in turns] == ["user", "assistant", "tool"]
    assert turns[1].tool_calls == (
        ToolCall(id="c1", name="weather", arguments={"place": "Oslo"}),
    )
    assert turns[2].tool_call_id == "c1"
    with pytest.raises(PhoneLinkError):
        chat_messages([{"role": "system", "content": "x"}])
    with pytest.raises(PhoneLinkError):
        chat_messages([])


async def paired(client: httpx.AsyncClient) -> tuple[dict, dict]:
    code = (await client.post("/studio/api/phones/code")).json()["code"]
    paired = await client.post(
        "/studio/api/phone/pair",
        json={"code": code, "name": "iPhone 12 Pro"},
        headers={"Origin": ORIGIN},
    )
    assert paired.status_code == 200
    body = paired.json()
    return body, {"Authorization": f"Bearer {body['token']}", "Origin": ORIGIN}


@pytest.mark.asyncio
async def test_the_phone_and_pc_share_memory(make_studio):
    studio, _ = make_studio(["Hi."], STUDIO_MAIN_AGENT_MODEL="local/jarvis-8b")
    await studio.ensure_defaults()
    await studio.remember(SHARED_MEMORY_ID, "The bakery colours are teal and gold.")
    main = await studio.main_agent()
    await studio.remember(main.id, "The user wakes at 6am.")
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        try:
            body, headers = await paired(client)
            assert body["private"] is True and body["main"] == main.name
            assert "token" in body and body["link"]["name"] == "iPhone 12 Pro"
            assert "token_hash" not in body["link"]

            hello = await client.get("/studio/api/phone/hello", headers=headers)
            assert hello.json()["model"] == "local/jarvis-8b"
            assert hello.headers["access-control-allow-origin"] == "*"

            synced = await client.post(
                "/studio/api/phone/sync",
                headers=headers,
                json={
                    "memories": [
                        {"id": "p1", "agent": "Jarvis", "text": "Dentist on Friday."},
                        {"id": "p2", "agent": "Coach", "text": "Runs 5 km on Sundays."},
                        {"id": "p3", "agent": "Coach", "text": "   "},
                    ]
                },
            )
            assert synced.status_code == 200
            result = synced.json()
            assert result["stored"] == 2
            texts = [row["text"] for row in result["pc_memories"]]
            assert "The bakery colours are teal and gold." in texts
            assert "The user wakes at 6am." in texts
            assert "Dentist on Friday." not in texts, "the phone has its own already"

            team = await studio.memories(SHARED_MEMORY_ID)
            from_phone = [e for e in team if PHONE_TAG in e.tags]
            assert {e.author for e in from_phone} == {"Jarvis (phone)", "Coach (phone)"}

            again = await client.post(
                "/studio/api/phone/sync",
                headers=headers,
                json={"memories": [{"agent": "Jarvis", "text": "Dentist on Friday."}]},
            )
            assert len(await studio.memories(SHARED_MEMORY_ID)) == len(team), (
                "the same memory twice is kept once"
            )
            assert again.json()["stored"] == 1

            listed = (await client.get("/studio/api/phones")).json()["phones"]
            assert listed[0]["memories_in"] == 3 and listed[0]["last_sync"] > 0
        finally:
            await studio.shutdown()
            await app.state.services.admin.close()


@pytest.mark.asyncio
async def test_a_phone_agent_can_think_with_the_pc(make_studio):
    def reply(system: str, prompt: str) -> LLMReply:
        if "use the calculator" in prompt:
            return LLMReply(
                tool_calls=(
                    ToolCall(id="t1", name="calculate", arguments={"sum": "2+2"}),
                ),
                stop_reason="tool_use",
            )
        return LLMReply(text=f"PC says hi to: {prompt}")

    studio, model = make_studio(reply, STUDIO_MAIN_AGENT_MODEL="local/jarvis-8b")
    await studio.ensure_defaults()
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        try:
            _, headers = await paired(client)
            answered = await client.post(
                "/studio/api/phone/complete",
                headers=headers,
                json={
                    "system": "You are Jarvis on the phone.",
                    "messages": [{"role": "user", "content": "hello"}],
                },
            )
            assert answered.status_code == 200
            assert answered.json()["text"] == "PC says hi to: hello"
            assert model.calls[-1]["system"] == "You are Jarvis on the phone."
            assert str(model.calls[-1]["model"]).endswith("jarvis-8b")

            tooled = await client.post(
                "/studio/api/phone/complete",
                headers=headers,
                json={
                    "messages": [{"role": "user", "content": "use the calculator"}],
                    "tools": [
                        {
                            "type": "function",
                            "function": {
                                "name": "calculate",
                                "description": "Do sums.",
                                "parameters": {"type": "object", "properties": {}},
                            },
                        }
                    ],
                },
            )
            assert tooled.json()["tool_calls"] == [
                {"id": "t1", "name": "calculate", "arguments": {"sum": "2+2"}}
            ]
            assert model.calls[-1]["tools"] == ["calculate"]
        finally:
            await studio.shutdown()
            await app.state.services.admin.close()


@pytest.mark.asyncio
async def test_phone_paths_need_the_phone_secret(make_studio):
    studio, _ = make_studio([])
    await studio.ensure_defaults()
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        try:
            for path in ("/studio/api/phone/sync", "/studio/api/phone/complete"):
                refused = await client.post(path, json={}, headers={"Origin": ORIGIN})
                assert refused.status_code == 401
                assert refused.headers["access-control-allow-origin"] == "*"
            wrong = await client.get(
                "/studio/api/phone/hello", headers={"Authorization": "Bearer nope"}
            )
            assert (
                wrong.status_code == 401 and "Pair it again" in wrong.json()["detail"]
            )
            bad_code = await client.post(
                "/studio/api/phone/pair", json={"code": "ZZZZ-ZZZZ"}
            )
            assert bad_code.status_code == 400

            preflight = await client.options(
                "/studio/api/phone/sync",
                headers={
                    "Origin": ORIGIN,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "authorization,content-type",
                },
            )
            assert preflight.status_code == 204
            assert "authorization" in preflight.headers["access-control-allow-headers"]

            # Making codes and managing phones never answers another origin.
            made = await client.post(
                "/studio/api/phones/code", headers={"Origin": ORIGIN}
            )
            assert "access-control-allow-origin" not in made.headers
            assert (
                "access-control-allow-origin"
                not in (
                    await client.get(
                        "/studio/api/memory/shared", headers={"Origin": ORIGIN}
                    )
                ).headers
            )
            assert not await studio._store.find(PhoneLink)
        finally:
            await studio.shutdown()
            await app.state.services.admin.close()


@pytest.mark.skipif(sys.platform == "win32", reason="runs a POSIX script")
@pytest.mark.asyncio
async def test_the_pc_finds_its_tailscale_address(tmp_path, monkeypatch):
    from free_claude_code.studio import phone_link

    fake = tmp_path / "tailscale"
    fake.write_text(
        f"#!{sys.executable}\n"
        "import json\n"
        "print(json.dumps({'Self': {'DNSName': 'gaming-pc.tail1234.ts.net.'}}))\n"
    )
    fake.chmod(0o755)
    monkeypatch.setattr(phone_link, "_TAILSCALE_PROGRAMS", (str(fake),))
    assert await phone_link.tailscale_address() == "https://gaming-pc.tail1234.ts.net"
    monkeypatch.setattr(phone_link, "_TAILSCALE_PROGRAMS", (str(tmp_path / "none"),))
    assert await phone_link.tailscale_address() is None


@pytest.mark.asyncio
async def test_a_phone_agent_can_search_the_web_through_the_pc(make_studio):
    studio, _ = make_studio([])
    await studio.ensure_defaults()
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        try:
            _, headers = await paired(client)
            found = await client.post(
                "/studio/api/phone/search", headers=headers, json={"query": "tides"}
            )
            assert found.status_code == 200
            assert found.json()["results"][0] == {
                "title": "Tide tables",
                "url": "https://example.test/tides",
                "snippet": "",
            }
            anonymous = await client.post(
                "/studio/api/phone/search", json={"query": "tides"}
            )
            assert anonymous.status_code == 401
        finally:
            await studio.shutdown()
            await app.state.services.admin.close()
