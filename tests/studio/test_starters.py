"""6.61: the outside repos that come with FCC (active on first load, kept
with checksums so they work after the original is deleted), repo zips the
user uploads, and searching every repo's skills and text."""

import hashlib
import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest

from free_claude_code.core.json_types import JsonValue
from free_claude_code.studio.agents import SEALED_PROMPT, SEALED_TOOLS
from free_claude_code.studio.extensions import AgentDef, ExtensionLibrary
from free_claude_code.studio.llm import LLMReply, ToolCall
from free_claude_code.studio.memory import SHARED_MEMORY_ID
from free_claude_code.studio.models import Agent
from free_claude_code.studio.starter import BUNDLE, bundled_bytes, load_starters
from free_claude_code.studio.tools import ToolContext
from tests.api.support import create_test_app
from tests.studio.test_extensions import repo_zip

ASKED_FOR = {
    "OpenHands/openhands",
    "florinpop17/app-ideas",
    "nilbuild/developer-roadmap",
    "ossu/computer-science",
    "vectorize-io/hindsight",
    "google/ax",
    "paperclipai/paperclip",
    "stablyai/orca",
    "agent-substrate/substrate",
    "calesthio/OpenMontage",
    "leonxlnx/taste-skill",
    "aishwaryanr/awesome-generative-ai-guide",
    "volcengine/OpenViking",
    "ai-boost/awesome-harness-engineering",
    "mukul975/anthropic-cybersecurity-skills",
    "cathrynlavery/diagram-design",
    "k-dense-ai/scientific-agent-skills",
    "rohitg00/agentmemory",
    "steven2358/awesome-generative-ai",
    "usestrix/strix",
    "public-apis/public-apis",
    "ripienaar/free-for-dev",
    "langflow-ai/langflow",
    "supermemoryai/supermemory",
    "letta-ai/letta",
    "ultraworkers/claw-code",
}

SECURITY_SKILLS = {
    "skills/k8s-rbac/SKILL.md": (
        "---\nname: auditing-kubernetes-rbac\ndescription: Find risky Kubernetes "
        "RBAC bindings.\n---\nList the cluster role bindings first."
    ),
    # The same skill copied for another agent tool is listed once.
    ".claude/skills/k8s-rbac/SKILL.md": (
        "---\nname: auditing-kubernetes-rbac\ndescription: copy\n---\ncopy"
    ),
    ".mcp.json": json.dumps({"mcpServers": {"scanner": {"command": "scan"}}}),
    "agents/auditor.md": "---\nname: auditor\ndescription: Audits.\n---\nAudit.",
    "LICENSE": "Apache License 2.0",
}
API_LIST = {
    "README.md": "# Public APIs\n\n## Weather\n| Open-Meteo | Free weather API | No |\n"
    + "\n".join(f"| Filler {n} | Something else | No |" for n in range(200)),
    "LICENSE": "MIT License",
}


def bundle(folder: Path, repos: dict[str, dict[str, str]], *, github_only=()):
    """A starter bundle like vendor/repos, with zips, checksums, and a manifest."""
    folder.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    for full, files in repos.items():
        owner, repo = full.split("/")
        data = repo_zip(files, top=f"{repo}-abc1234")
        name = f"{owner}__{repo}.zip"
        (folder / name).write_bytes(data)
        rows.append(
            {
                "owner": owner,
                "repo": repo,
                "commit": "abc1234def",
                "licence": "MIT",
                "about": f"About {repo}.",
                "file": name,
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
            }
        )
    for full in github_only:
        owner, repo = full.split("/")
        rows.append(
            {
                "owner": owner,
                "repo": repo,
                "commit": "fff",
                "licence": "personal use only",
                "about": "A roadmap.",
                "left_out": "Its licence doesn't allow FCC to share it.",
            }
        )
    (folder / "manifest.json").write_text(json.dumps({"repos": rows}))
    return folder


def github_with(files: dict[str, str], state: dict[str, bool]) -> httpx.MockTransport:
    def answer(request: httpx.Request) -> httpx.Response:
        if state.get("down"):
            return httpx.Response(503)
        return httpx.Response(200, content=repo_zip(files))

    return httpx.MockTransport(answer)


# ------------------------------------------------------------ the bundle


def test_every_repo_asked_for_comes_with_fcc_checked_and_licensed():
    starters = {starter.full_name: starter for starter in load_starters(BUNDLE)}
    assert set(starters) >= ASKED_FOR
    sums: dict[str, str] = {}
    for line in (BUNDLE / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split()
        sums[name] = digest
    for starter in starters.values():
        assert starter.commit and starter.licence and starter.about, starter.full_name
        if not starter.bundled:
            # Only repos whose licence keeps them out of FCC have no copy.
            assert starter.left_out, starter.full_name
            assert not list(BUNDLE.glob(f"{starter.owner}__{starter.repo}*"))
            continue
        assert sums[starter.file] == starter.sha256
        data = bundled_bytes(BUNDLE, starter)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()
        tops = {name.split("/", 1)[0] for name in names}
        assert len(tops) == 1, starter.full_name
        assert any(
            name.split("/", 1)[1].lower().startswith(("license", "licence"))
            for name in names
        ), f"{starter.full_name} ships without its licence"
    assert {s for s, starter in starters.items() if not starter.bundled} == {
        "nilbuild/developer-roadmap",
        "ripienaar/free-for-dev",
    }
    readme = (BUNDLE.parent / "README.md").read_text()
    assert "repos/README.md" in readme
    assert "roadmap.sh" in (BUNDLE / "README.md").read_text()


# ------------------------------------------------------------ first load


@pytest.mark.asyncio
async def test_the_starter_repos_are_active_on_first_load(make_studio, tmp_path):
    studio, _ = make_studio([])
    studio._starter_folder = bundle(
        tmp_path / "bundle",
        {
            "mukul975/security-skills": SECURITY_SKILLS,
            "public-apis/public-apis": API_LIST,
        },
        github_only=("nilbuild/roadmap",),
    )
    state = {"down": True}
    roadmap = {"README.md": "# Roadmaps\nLearn backend step by step.", "license": "x"}
    studio._extensions._transport = github_with(roadmap, state)
    team_before = len(await studio._store.find(Agent))

    added = await studio.ensure_starters()
    assert sorted(extension.name for extension in added) == [
        "mukul975/security-skills",
        "public-apis/public-apis",
    ]
    security = next(e for e in added if e.name == "mukul975/security-skills")
    assert [skill.name for skill in security.skills] == ["auditing-kubernetes-rbac"]
    assert security.origin == "bundled"
    assert security.source == "https://github.com/mukul975/security-skills"
    # Secure by default: servers stay off, agents don't join the team.
    assert [(s.name, s.enabled) for s in security.servers] == [("scanner", False)]
    assert len(await studio._store.find(Agent)) == team_before
    # Each copy is kept in the vault too.
    kept = {item.full_name for item in await studio.vault.items()}
    assert {"mukul975/security-skills", "public-apis/public-apis"} <= kept

    # GitHub was down for the GitHub-only repo: it's tried again next load.
    assert await studio.ensure_starters() == []
    studio._starters_checked = False
    state["down"] = False
    [roadmaps] = await studio.ensure_starters()
    assert roadmaps.name == "nilbuild/roadmap" and roadmaps.origin == ""
    assert "nilbuild/roadmap" in {i.full_name for i in await studio.vault.items()}

    # Removing a starter sticks; it can be added again by hand.
    await studio.remove_extension(security.id)
    studio._starters_checked = False
    assert await studio.ensure_starters() == []
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        rows = (await client.get("/studio/api/starters")).json()["starters"]
        by_name = {row["name"]: row for row in rows}
        assert by_name["mukul975/security-skills"]["extension_id"] == ""
        assert by_name["public-apis/public-apis"]["skills"] == 1
        assert by_name["nilbuild/roadmap"]["bundled"] is False
        again = await client.post(
            "/studio/api/starters/add", json={"url": "mukul975/security-skills"}
        )
        assert again.status_code == 200, again.text
        assert again.json()["origin"] == "bundled"
        unknown = await client.post("/studio/api/starters/add", json={"url": "a/b"})
        assert unknown.status_code == 400


@pytest.mark.asyncio
async def test_a_damaged_copy_is_never_installed(tmp_path, make_studio):
    studio, _ = make_studio([])
    folder = bundle(tmp_path / "bundle", {"public-apis/public-apis": API_LIST})
    zip_path = folder / "public-apis__public-apis.zip"
    zip_path.write_bytes(zip_path.read_bytes() + b"tampered")
    studio._starter_folder = folder
    assert await studio.ensure_starters() == []
    assert await studio.extensions() == []


@pytest.mark.asyncio
async def test_a_real_starter_installs_from_the_copy_that_comes_with_fcc(tmp_path):
    [starter] = [
        s for s in load_starters(BUNDLE) if s.full_name == "public-apis/public-apis"
    ]
    library = ExtensionLibrary(tmp_path / "ext")
    added = await library.add_archive(
        owner=starter.owner,
        repo=starter.repo,
        data=bundled_bytes(BUNDLE, starter),
        origin="bundled",
        ref=starter.commit,
        source=starter.source,
    )
    assert added.skills[0].kind == "readme"
    hits = await library.search("weather")
    assert hits and all(hit["repo"] == "public-apis/public-apis" for hit in hits)


# ------------------------------------------------------------ uploads


@pytest.mark.asyncio
async def test_an_uploaded_repo_zip_is_added_and_kept(make_studio):
    studio, _ = make_studio([])
    flat = io.BytesIO()
    with zipfile.ZipFile(flat, "w") as archive:
        # Zipped by hand: files at the top, no single folder.
        archive.writestr("README.md", "# My notes\nHow we ship.")
        archive.writestr(
            "skills/ship/SKILL.md",
            "---\nname: ship\ndescription: Ship it.\n---\nSteps.",
        )
        archive.writestr("../escape.txt", "nope")
    app = create_test_app(studio=studio)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        sent = await client.post(
            "/studio/api/extensions/upload?name=My Notes (v2).zip",
            content=flat.getvalue(),
        )
        assert sent.status_code == 200, sent.text
        added = sent.json()
        assert added["origin"] == "upload" and added["name"] == "uploaded/My-Notes-v2"
        assert [skill["name"] for skill in added["skills"]] == ["ship"]
        assert not (studio._extensions.folder.parent / "escape.txt").exists()
        listing = (await client.get("/studio/api/vault")).json()["items"]
        [item] = [i for i in listing if i["full_name"] == "uploaded/My-Notes-v2"]
        await client.delete(f"/studio/api/extensions/{added['id']}")
        restored = await client.post(f"/studio/api/vault/{item['id']}/restore")
        assert restored.status_code == 200, restored.text
        assert restored.json()["origin"] == "upload"
        assert restored.json()["source"] == "upload:My-Notes-v2"
        bad = await client.post(
            "/studio/api/extensions/upload?name=x.zip", content=b"not a zip"
        )
        assert bad.status_code == 400 and "isn't a zip" in bad.text


# ------------------------------------------------------------ the skill tool


@pytest.mark.asyncio
async def test_agents_search_every_repo_and_read_the_part_they_need(
    make_studio, tmp_path
):
    studio, _ = make_studio([])
    many = {
        f"skills/s{n}/SKILL.md": f"---\nname: skill-{n}\ndescription: Skill {n}.\n---\nx"
        for n in range(90)
    }
    studio._starter_folder = bundle(
        tmp_path / "bundle",
        {
            "mukul975/security-skills": SECURITY_SKILLS,
            "public-apis/public-apis": API_LIST,
            "owner/many": many,
        },
    )
    context = ToolContext(agent_id="a", chat_id="c")

    async def skill(**arguments: JsonValue) -> str:
        outcome = await studio._assistant_tool(
            ToolCall(id="1", name="skill", arguments=arguments), context
        )
        return outcome.text

    # The tool adds the starter repos itself if the app hasn't yet.
    found = await skill(action="search", query="kubernetes rbac")
    assert "- auditing-kubernetes-rbac: Find risky Kubernetes RBAC bindings." in found
    assert "skills/k8s-rbac/SKILL.md" in found

    weather = await skill(action="search", query="free weather api")
    assert "public-apis/public-apis/README.md:4: | Open-Meteo |" in weather
    part = await skill(
        action="read", repo="public-apis/public-apis", file="README.md", line=4
    )
    assert "Open-Meteo" in part and "Filler 70" in part and "Filler 150" not in part

    listed = await skill(action="list")
    assert "92 skills in 3 repos" in listed and "- owner/many: 90 skills" in listed
    one_repo = await skill(action="list", repo="security")
    assert one_repo.startswith("Skills:") and "auditing-kubernetes-rbac" in one_repo
    with pytest.raises(ValueError, match="no file"):
        await skill(action="read", repo="public-apis", file="../../etc/passwd")
    nothing = await skill(action="search", query="zebra unicorn")
    assert "Nothing in the added repos matches" in nothing


def test_the_starter_bundle_lives_beside_the_app():
    assert BUNDLE.name == "repos" and BUNDLE.parent.name == "vendor"
    assert (BUNDLE / "manifest.json").is_file()


@pytest.mark.asyncio
async def test_a_starter_added_by_hand_is_never_added_twice(make_studio, tmp_path):
    studio, _ = make_studio([])
    studio._starter_folder = bundle(
        tmp_path / "bundle", {"public-apis/public-apis": API_LIST}
    )
    studio._extensions._transport = github_with(API_LIST, {})
    by_hand = await studio.add_extension("https://github.com/public-apis/public-apis")
    assert await studio.ensure_starters() == []
    assert [e.id for e in await studio.extensions()] == [by_hand.id]


# ------------------------------------------------------------ repo agents

SECRET = "The user's bank PIN is 4321 and the dog is called Biscuit."


@pytest.mark.asyncio
async def test_repo_agents_on_the_team_never_see_memory_and_get_only_their_tools(
    make_studio,
):
    def answer(system: str, prompt: str) -> LLMReply:
        if "running notes" in system:
            return LLMReply(text="Goal:\n- Chat")
        return LLMReply(text="Done.")

    studio, model = make_studio(
        answer, STUDIO_PRIVATE_MEMORY=True, STUDIO_ALL_TOOLS=True
    )
    studio._starter_folder = BUNDLE
    await studio.ensure_defaults()
    await studio.ensure_starters()
    await studio.remember(SHARED_MEMORY_ID, SECRET)
    found = [
        (extension, agent)
        for extension in await studio.extensions()
        for agent in extension.agents
    ]
    # Only real Claude Code agents (named and described up top) are offered:
    # docs and templates that sit in an agents folder are not.
    assert sorted(agent.name for _, agent in found) == [
        "codemod-runner",
        "token-auditor",
    ]
    for extension, definition in found:
        agent = await studio.add_extension_agent(extension.id, definition.name)
        assert agent.all_tools is False
        assert await studio.is_private_from(agent)
        in_use = set(await studio.tools_in_use(agent))
        assert not in_use & SEALED_TOOLS
        assert not in_use & {"delete_file", "web_fetch", "team_task", "manage_agent"}

        chat = await studio.create_chat(agent_id=agent.id)
        await studio.send(chat.id, "what is my bank PIN and my dog's name?")
        call = model.calls[-1]
        messages = call["messages"]
        said = [m.content for m in messages] if isinstance(messages, list) else []
        sent = "\n".join([str(call["system"]), *said])
        assert SEALED_PROMPT in str(call["system"])
        assert call["memory"] == ""
        assert "4321" not in sent and "Biscuit" not in sent


@pytest.mark.asyncio
async def test_repos_added_before_are_read_again_with_the_agent_rule(
    make_studio, tmp_path
):
    studio, _ = make_studio([])
    files = {
        "docs/agents/ARCHITECTURE.md": "# Architecture\nNotes, not an agent.",
        "agents/real.md": "---\nname: real\ndescription: Does work.\n---\nWork.",
        "LICENSE": "MIT",
    }
    studio._extensions._transport = github_with(files, {})
    added = await studio.add_extension("owner/mixed")
    assert [a.name for a in added.agents] == ["real"]
    # A manifest written by 6.61.0, when every note in an agents folder counted.
    added.agents.append(AgentDef(name="ARCHITECTURE", description="", prompt="x"))
    await studio._extensions.save(added)
    studio._starter_folder = bundle(tmp_path / "bundle", {})

    await studio.ensure_starters()

    [again] = await studio.extensions()
    assert [a.name for a in again.agents] == ["real"]
