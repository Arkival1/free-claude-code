"""Add skills, agents, commands, and MCP servers from a GitHub repo.

One link pulls in whatever a repo holds, the Claude Code way:
- skills: every SKILL.md (name and description up top, instructions below),
- agents: agents/*.md (an agent's name, description, tools, and prompt),
- commands: commands/*.md (a prompt the team can follow by name),
- MCP servers: .mcp.json, or mcpServers in a plugin's plugin.json,
- and a plain repo with none of those becomes one skill from its README.

Everything is kept on this PC under Studio's extensions folder, and the
downloaded repo is also kept in the repo vault: if the repo is later deleted
from GitHub, adding it again (or restoring it) uses that copy. MCP servers
from a repo start switched off: running one runs that repo's code, so the
user turns each on after seeing its command.
"""

import io
import json
import re
import secrets
import shutil
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath

import anyio.to_thread
import httpx

from .vault import RepoVault, VaultError

MAX_ZIP_BYTES = 80 * 1024 * 1024
MAX_UNPACKED_BYTES = 300 * 1024 * 1024
MAX_SKILL_CHARS = 16_000
README_SKILL_CHARS = 8_000
MAX_FOUND = 300
MAX_AGENTS = 400
"""Agent collections list a few hundred (one per specialty)."""
MAX_SKILLS = 2_000
"""Skill repos can hold hundreds of skills (one per technique or tool)."""
TEXT_SUFFIXES = frozenset({".md", ".mdx", ".txt", ".rst"})
MAX_SEARCH_BYTES = 60 * 1024 * 1024
"""Text read from one repo per search: lists like public-apis are large."""
MAX_SEARCH_FILE = 4 * 1024 * 1024
MANIFEST = "extension.json"
UPLOAD_OWNER = "uploaded"
"""The vault's owner name for repo zips the user uploads."""
PLUGIN_ROOT = "${CLAUDE_PLUGIN_ROOT}"
_GITHUB = re.compile(
    r"^(?:https?://)?(?:www\.)?github\.com/(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+?)"
    r"(?:\.git)?(?:/(?:tree|blob)/(?P<ref>[^/]+)(?:/(?P<sub>.*?))?)?/?$",
    re.I,
)
_SHORT = re.compile(r"^(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)$")
_NAME = re.compile(r"[^a-z0-9]+")


class ExtensionError(ValueError):
    """A repo couldn't be fetched or read."""


@dataclass(slots=True)
class Skill:
    name: str
    description: str
    path: str
    """Where its text lives, relative to the extension folder."""
    kind: str = "skill"
    """skill, command, or readme."""


@dataclass(slots=True)
class AgentDef:
    name: str
    description: str
    prompt: str
    tools: list[str] = field(default_factory=list)


@dataclass(slots=True)
class McpServer:
    name: str
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    enabled: bool = False

    @property
    def transport(self) -> str:
        return "http" if self.url else "stdio"

    def shown(self) -> str:
        """The command line or address, as the user approves it."""
        if self.url:
            return self.url
        return " ".join([self.command, *self.args]).strip()


@dataclass(slots=True)
class Extension:
    id: str
    name: str
    source: str
    description: str = ""
    skills: list[Skill] = field(default_factory=list)
    agents: list[AgentDef] = field(default_factory=list)
    servers: list[McpServer] = field(default_factory=list)
    plugins: list[str] = field(default_factory=list)
    vaulted: str = ""
    """Where the copy came from when GitHub no longer had it: the vault entry."""
    origin: str = ""
    """'' (GitHub), 'bundled' (came with FCC), or 'upload' (a zip from the user)."""

    def to_json(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, object]) -> Extension:
        return cls(
            id=_text(data, "id"),
            name=_text(data, "name"),
            source=_text(data, "source"),
            description=_text(data, "description"),
            skills=[
                Skill(
                    name=_text(item, "name"),
                    description=_text(item, "description"),
                    path=_text(item, "path"),
                    kind=_text(item, "kind") or "skill",
                )
                for item in _dicts(data, "skills")
            ],
            agents=[
                AgentDef(
                    name=_text(item, "name"),
                    description=_text(item, "description"),
                    prompt=_text(item, "prompt"),
                    tools=_texts(item, "tools"),
                )
                for item in _dicts(data, "agents")
            ],
            servers=[
                McpServer(
                    name=_text(item, "name"),
                    command=_text(item, "command"),
                    args=_texts(item, "args"),
                    env=_pairs(item, "env"),
                    url=_text(item, "url"),
                    headers=_pairs(item, "headers"),
                    enabled=item.get("enabled") is True,
                )
                for item in _dicts(data, "servers")
            ],
            plugins=_texts(data, "plugins"),
            vaulted=_text(data, "vaulted"),
            origin=_text(data, "origin"),
        )


def _text(data: dict[str, object], key: str) -> str:
    value = data.get(key)
    return str(value) if value is not None else ""


def _texts(data: dict[str, object], key: str) -> list[str]:
    value = data.get(key)
    return [str(item) for item in value] if isinstance(value, list) else []


def _dicts(data: dict[str, object], key: str) -> list[dict[str, object]]:
    value = data.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _pairs(data: dict[str, object], key: str) -> dict[str, str]:
    value = data.get(key)
    if not isinstance(value, dict):
        return {}
    return {str(k): str(v) for k, v in value.items()}


@dataclass(frozen=True, slots=True)
class RepoLink:
    owner: str
    repo: str
    ref: str
    sub: str

    @property
    def name(self) -> str:
        return f"{self.owner}/{self.repo}" + (f"/{self.sub}" if self.sub else "")

    @property
    def zip_url(self) -> str:
        return f"https://codeload.github.com/{self.owner}/{self.repo}/zip/{self.ref or 'HEAD'}"


def parse_link(text: str) -> RepoLink:
    """github.com/owner/repo, a /tree/branch/folder link, or owner/repo."""
    said = text.strip()
    found = _GITHUB.match(said) or _SHORT.match(said)
    if found is None:
        raise ExtensionError(
            "Paste a GitHub link like https://github.com/owner/repo (or owner/repo)."
        )
    parts = found.groupdict()
    return RepoLink(
        owner=parts["owner"],
        repo=parts["repo"],
        ref=parts.get("ref") or "",
        sub=(parts.get("sub") or "").strip("/"),
    )


def front_matter(text: str) -> tuple[dict[str, str], str]:
    """Flat key: value pairs between --- lines, and the body after them."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    values: dict[str, str] = {}
    key = ""
    for line in text[3:end].splitlines():
        if not line.strip():
            continue
        if line[:1] in {" ", "\t"} and key:
            values[key] = f"{values[key]} {line.strip()}".strip()
            continue
        name, separator, value = line.partition(":")
        if separator:
            key = name.strip()
            values[key] = value.strip().strip("\"'").lstrip(">|").strip()
    return values, text[end + 4 :].lstrip("\n")


def _slug(text: str) -> str:
    return _NAME.sub("-", text.lower()).strip("-")[:60] or "extension"


def _unpack(data: bytes, into: Path, sub: str) -> Path:
    """Unzip a GitHub archive (one top folder) into a folder, safely."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as error:
        raise ExtensionError("That isn't a zip file.") from error
    total = 0
    into.mkdir(parents=True, exist_ok=True)
    names = [info.filename for info in archive.infolist() if not info.is_dir()]
    tops = {PurePosixPath(name).parts[0] for name in names if PurePosixPath(name).parts}
    # GitHub zips hold one top folder; a folder zipped by hand may not.
    strip = 1 if len(tops) == 1 and all("/" in name for name in names) else 0
    for info in archive.infolist():
        parts = PurePosixPath(info.filename).parts[strip:]
        if not parts or info.is_dir():
            continue
        if any(part in {"..", ""} or part.startswith("/") for part in parts):
            continue
        total += info.file_size
        if total > MAX_UNPACKED_BYTES:
            raise ExtensionError("That repo is too big to add (over 300 MB unpacked).")
        target = into.joinpath(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(info) as source, target.open("wb") as out:
            shutil.copyfileobj(source, out)
    root = into / sub if sub else into
    if not root.is_dir():
        raise ExtensionError(f"The repo has no folder '{sub}'.")
    return root


def _relative(path: Path, base: Path) -> str:
    return path.relative_to(base).as_posix()


def _servers_from(data: object, plugin_dir: Path) -> list[McpServer]:
    if not isinstance(data, dict):
        return []
    entries = data.get("mcpServers", data)
    if not isinstance(entries, dict):
        return []
    found: list[McpServer] = []
    root = str(plugin_dir)
    for name, spec in entries.items():
        if not isinstance(spec, dict):
            continue
        args = spec.get("args")
        env = spec.get("env")
        headers = spec.get("headers")
        found.append(
            McpServer(
                name=str(name),
                command=str(spec.get("command") or "").replace(PLUGIN_ROOT, root),
                args=[str(arg).replace(PLUGIN_ROOT, root) for arg in args]
                if isinstance(args, list)
                else [],
                env={str(k): str(v).replace(PLUGIN_ROOT, root) for k, v in env.items()}
                if isinstance(env, dict)
                else {},
                url=str(spec.get("url") or ""),
                headers={str(k): str(v) for k, v in headers.items()}
                if isinstance(headers, dict)
                else {},
            )
        )
    return found


def listed_agents(listed: object, plugin_dir: Path, root: Path) -> list[Path]:
    """The agent files a plugin.json lists ("agents": a file, a folder, or a
    list of them), kept inside the repo."""
    entries = [listed] if isinstance(listed, str) else listed
    found: list[Path] = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, str):
            continue
        path = plugin_dir / entry
        if not path.resolve().is_relative_to(root.resolve()):
            continue
        if path.is_dir():
            found += sorted(path.glob("*.md"))
        elif path.suffix == ".md" and path.is_file():
            found.append(path)
    return found[:MAX_AGENTS]


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except OSError, json.JSONDecodeError:
        return None


def scan(root: Path, *, base: Path, name: str) -> Extension:
    """Everything a repo folder offers, the Claude Code way."""
    extension = Extension(id="", name=name, source="")
    skipped = {".git", "node_modules", ".venv", "__pycache__"}

    def walk(pattern: str) -> list[Path]:
        found = [
            path
            for path in sorted(root.rglob(pattern))
            if not skipped & set(path.relative_to(root).parts)
        ]
        return found[:MAX_FOUND]

    plugin_agents: list[Path] = []
    for manifest in walk("plugin.json"):
        if manifest.parent.name != ".claude-plugin":
            continue
        data = _read_json(manifest)
        plugin_dir = manifest.parent.parent
        if isinstance(data, dict):
            extension.plugins.append(str(data.get("name") or plugin_dir.name))
            if not extension.description and data.get("description"):
                extension.description = str(data["description"])
            servers = data.get("mcpServers")
            if isinstance(servers, str):
                servers = _read_json(plugin_dir / servers)
            extension.servers += _servers_from(servers, plugin_dir)
            plugin_agents += listed_agents(data.get("agents"), plugin_dir, root)
    for listing in walk(".mcp.json"):
        extension.servers += _servers_from(_read_json(listing), listing.parent)
    # Repos often copy one skill into .claude/, .codex/, .cursor/ and skills/:
    # the visible copy is kept and the rest are left out by name.
    skill_files = sorted(
        (
            path
            for path in root.rglob("SKILL.md")
            if not skipped & set(path.relative_to(root).parts)
        ),
        key=lambda path: (
            any(part.startswith(".") for part in path.relative_to(root).parts),
            path.relative_to(root).as_posix(),
        ),
    )
    named: set[str] = set()
    for path in skill_files:
        if len(extension.skills) >= MAX_SKILLS:
            break
        values, _ = front_matter(path.read_text(encoding="utf-8", errors="replace"))
        skill_name = values.get("name") or path.parent.name
        if skill_name.casefold() in named:
            continue
        named.add(skill_name.casefold())
        extension.skills.append(
            Skill(
                name=skill_name,
                description=values.get("description", "")[:400],
                path=_relative(path, base),
            )
        )
    agent_files = [*plugin_agents, *walk("agents/*.md")]
    for path in [*dict.fromkeys(agent_files), *walk("commands/*.md")]:
        folder = "agents" if path in agent_files else path.parent.name
        if path.name.lower() in {"readme.md", "skill.md"}:
            continue
        values, body = front_matter(path.read_text(encoding="utf-8", errors="replace"))
        if folder == "agents":
            # A Claude Code agent names and describes itself up top. Other
            # notes kept in an agents folder (docs, templates) stay searchable
            # text, not team members.
            agent_name = values.get("name", "").strip()
            if not agent_name or not values.get("description", "").strip():
                continue
            if any(agent.name == agent_name for agent in extension.agents):
                continue
            tools = values.get("tools", "")
            extension.agents.append(
                AgentDef(
                    name=agent_name,
                    description=values.get("description", "")[:400],
                    prompt=body.strip()[:MAX_SKILL_CHARS],
                    tools=[t.strip() for t in tools.split(",") if t.strip()],
                )
            )
        elif f"/{path.stem}".casefold() not in named:
            named.add(f"/{path.stem}".casefold())
            first = next((line for line in body.splitlines() if line.strip()), "")
            extension.skills.append(
                Skill(
                    name=f"/{path.stem}",
                    description=(values.get("description") or first)[:400],
                    path=_relative(path, base),
                    kind="command",
                )
            )
    if not (extension.skills or extension.agents or extension.servers):
        readme = next(
            (p for p in sorted(root.glob("*")) if p.name.lower().startswith("readme")),
            None,
        )
        if readme is not None and readme.is_file():
            text = readme.read_text(encoding="utf-8", errors="replace")
            first = next(
                (
                    line.strip("# ").strip()
                    for line in text.splitlines()
                    if line.strip()
                ),
                name,
            )
            extension.skills.append(
                Skill(
                    name=name.rsplit("/", 1)[-1],
                    description=first[:400],
                    path=_relative(readme, base),
                    kind="readme",
                )
            )
    seen: set[str] = set()
    unique: list[McpServer] = []
    for server in extension.servers:
        if server.name not in seen:
            seen.add(server.name)
            unique.append(server)
    extension.servers = unique
    return extension


class ExtensionLibrary:
    """The extensions folder: one folder per added repo, plus its manifest."""

    def __init__(
        self,
        folder: Path,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        vault: RepoVault | None = None,
    ) -> None:
        self._folder = folder
        self._transport = transport
        self._vault = vault

    @property
    def folder(self) -> Path:
        return self._folder

    async def add_github(self, link: str) -> Extension:
        repo = parse_link(link)
        vaulted = ""
        try:
            data = await self._download(repo)
        except ExtensionError:
            # Gone from GitHub (or GitHub is down): use the vault's copy.
            kept = (
                await self._vault.latest(repo.owner, repo.repo)
                if self._vault is not None
                else None
            )
            if kept is None or self._vault is None:
                raise
            try:
                data = await self._vault.read(kept)
            except VaultError as error:
                raise ExtensionError(str(error)) from error
            vaulted = kept.id
        else:
            if self._vault is not None:
                await self._vault.keep(
                    owner=repo.owner,
                    repo=repo.repo,
                    kind="source",
                    name=f"{repo.repo}-{repo.ref or 'HEAD'}.zip",
                    data=data,
                    url=repo.zip_url,
                    ref=repo.ref,
                )
        return await self._install(repo, data, vaulted)

    async def restore(self, item_id: str, sub: str = "") -> Extension:
        """Add a repo again from its vault copy, with no download at all."""
        if self._vault is None:
            raise ExtensionError("There is no vault on this PC.")
        try:
            item = await self._vault.item(item_id)
            data = await self._vault.read(item)
        except VaultError as error:
            raise ExtensionError(str(error)) from error
        if item.kind != "source":
            raise ExtensionError("Only a repo's files can be added as an extension.")
        repo = RepoLink(owner=item.owner, repo=item.repo, ref=item.ref, sub=sub)
        if item.owner == UPLOAD_OWNER:
            return await self._install(
                repo, data, item.id, origin="upload", source=item.url
            )
        return await self._install(repo, data, item.id)

    async def add_archive(
        self,
        *,
        owner: str,
        repo: str,
        data: bytes,
        origin: str,
        ref: str = "",
        source: str = "",
        file_name: str = "",
    ) -> Extension:
        """Add a repo from a zip already in hand: a copy that came with FCC, or
        one the user uploaded. The zip is kept in the vault like a download."""
        if len(data) > MAX_ZIP_BYTES:
            raise ExtensionError("That zip is too big to add (over 80 MB).")
        link = RepoLink(owner=owner, repo=repo, ref=ref, sub="")
        if self._vault is not None:
            await self._vault.keep(
                owner=owner,
                repo=repo,
                kind="source",
                name=file_name or f"{repo}-{ref[:7] or 'HEAD'}.zip",
                data=data,
                url=source,
                ref=ref,
            )
        return await self._install(link, data, "", origin=origin, source=source)

    async def _install(
        self,
        repo: RepoLink,
        data: bytes,
        vaulted: str,
        *,
        origin: str = "",
        source: str = "",
    ) -> Extension:
        ext_id = f"ext_{_slug(repo.name)}_{secrets.token_hex(3)}"

        def work() -> Extension:
            home = self._folder / ext_id
            try:
                root = _unpack(data, home / "files", repo.sub)
                extension = scan(root, base=home, name=repo.name)
            except Exception:
                shutil.rmtree(home, ignore_errors=True)
                raise
            extension.id = ext_id
            extension.vaulted = vaulted
            extension.origin = origin
            extension.source = source or (
                f"https://github.com/{repo.owner}/{repo.repo}"
                + (f"/tree/{repo.ref or 'HEAD'}/{repo.sub}" if repo.sub else "")
            )
            if not (extension.skills or extension.agents or extension.servers):
                shutil.rmtree(home, ignore_errors=True)
                raise ExtensionError(
                    "That repo has no skills, agents, commands, MCP servers, or README."
                )
            self._write(extension)
            return extension

        return await anyio.to_thread.run_sync(work)

    async def _download(self, repo: RepoLink) -> bytes:
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=120, follow_redirects=True
            ) as client:
                response = await client.get(repo.zip_url)
        except httpx.HTTPError as error:
            raise ExtensionError(f"GitHub didn't answer: {error}") from error
        if response.status_code == 404:
            raise ExtensionError(
                f"GitHub has no public repo {repo.owner}/{repo.repo}"
                + (f" at '{repo.ref}'" if repo.ref else "")
                + "."
            )
        if response.status_code != 200:
            raise ExtensionError(f"GitHub answered {response.status_code}.")
        if len(response.content) > MAX_ZIP_BYTES:
            raise ExtensionError("That repo is too big to add (over 80 MB).")
        return response.content

    def _write(self, extension: Extension) -> None:
        home = self._folder / extension.id
        home.mkdir(parents=True, exist_ok=True)
        (home / MANIFEST).write_text(
            json.dumps(extension.to_json(), indent=2), encoding="utf-8"
        )

    async def save(self, extension: Extension) -> Extension:
        await anyio.to_thread.run_sync(self._write, extension)
        return extension

    async def all(self) -> list[Extension]:
        def work() -> list[Extension]:
            if not self._folder.is_dir():
                return []
            found: list[Extension] = []
            for manifest in sorted(self._folder.glob(f"*/{MANIFEST}")):
                data = _read_json(manifest)
                if isinstance(data, dict):
                    found.append(Extension.from_json(data))
            return found

        return await anyio.to_thread.run_sync(work)

    async def get(self, ext_id: str) -> Extension:
        for extension in await self.all():
            if extension.id == ext_id:
                return extension
        raise ExtensionError(f"There is no extension {ext_id}.")

    async def remove(self, ext_id: str) -> None:
        await self.get(ext_id)
        await anyio.to_thread.run_sync(
            lambda: shutil.rmtree(self._folder / ext_id, ignore_errors=True)
        )

    async def rescan_agents(self, extension: Extension) -> Extension:
        """Read an added repo's agents again with the current rules."""
        sub = ""
        if extension.source.startswith("https://github.com/"):
            try:
                sub = parse_link(extension.source).sub
            except ExtensionError:
                sub = ""
        root = self._folder / extension.id / "files"
        root = root / sub if sub else root

        def work() -> Extension:
            if not root.is_dir():
                return extension
            found = scan(root, base=self._folder / extension.id, name=extension.name)
            extension.agents = found.agents
            self._write(extension)
            return extension

        return await anyio.to_thread.run_sync(work)

    async def add_server(self, server: McpServer) -> Extension:
        """A server the user typed in: kept in a 'Added by hand' extension."""
        try:
            extension = await self.get("ext_by_hand")
        except ExtensionError:
            extension = Extension(id="ext_by_hand", name="Added by hand", source="you")
        extension.servers = [s for s in extension.servers if s.name != server.name]
        server.enabled = True
        extension.servers.append(server)
        return await self.save(extension)

    async def search(self, query: str, *, limit: int = 12) -> list[dict[str, object]]:
        """Lines in every added repo's text (guides, lists, roadmaps, skills)
        that best match the words asked for, newest repos last."""
        words = re.findall(r"[a-z0-9+#][a-z0-9+#.-]+", query.lower())[:10]
        if not words:
            return []
        extensions = await self.all()

        def work() -> list[dict[str, object]]:
            hits: list[tuple[float, str, str, int, str]] = []
            skipped = {".git", "node_modules", ".venv", "__pycache__", "dist", "build"}
            for extension in extensions:
                root = self._folder / extension.id / "files"
                if not root.is_dir():
                    continue
                budget = MAX_SEARCH_BYTES
                for path in sorted(root.rglob("*")):
                    if path.suffix.lower() not in TEXT_SUFFIXES or not path.is_file():
                        continue
                    if skipped & set(path.relative_to(root).parts):
                        continue
                    size = path.stat().st_size
                    if size > MAX_SEARCH_FILE:
                        continue
                    budget -= size
                    if budget < 0:
                        break
                    text = path.read_text(encoding="utf-8", errors="replace")
                    lowered = text.lower()
                    if not any(word in lowered for word in words):
                        continue
                    relative = path.relative_to(root).as_posix()
                    in_name = sum(0.5 for word in words if word in relative.lower())
                    for number, line in enumerate(text.splitlines(), 1):
                        low = line.lower()
                        found = sum(1 for word in words if word in low)
                        if found:
                            score = (
                                found
                                + in_name
                                + (
                                    0.5
                                    if line.lstrip().startswith(("#", "|", "-", "*"))
                                    else 0
                                )
                            )
                            hits.append(
                                (
                                    score,
                                    extension.name,
                                    relative,
                                    number,
                                    line.strip()[:300],
                                )
                            )
            hits.sort(key=lambda hit: -hit[0])
            chosen: list[dict[str, object]] = []
            per_file: dict[str, int] = {}
            for score, name, relative, number, line in hits:
                key = f"{name}/{relative}"
                if per_file.get(key, 0) >= 3:
                    continue
                per_file[key] = per_file.get(key, 0) + 1
                chosen.append(
                    {
                        "repo": name,
                        "file": relative,
                        "line": number,
                        "text": line,
                        "score": score,
                    }
                )
                if len(chosen) >= limit:
                    break
            return chosen

        return await anyio.to_thread.run_sync(work)

    async def read_file(self, repo: str, relative: str, *, around: int = 0) -> str:
        """A text file from an added repo, or the part around one line."""
        extensions = await self.all()
        wanted = repo.strip().lower()
        extension = next(
            (e for e in extensions if e.name.lower() == wanted), None
        ) or next((e for e in extensions if wanted and wanted in e.name.lower()), None)
        if extension is None:
            raise ExtensionError(f"No added repo is called '{repo}'.")

        def work() -> str:
            root = (self._folder / extension.id / "files").resolve()
            path = (root / relative.strip().lstrip("/")).resolve()
            if root not in path.parents or not path.is_file():
                raise ExtensionError(f"{extension.name} has no file {relative}.")
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            if around:
                start = max(0, around - 40)
                return "\n".join(lines[start : start + 120])
            return "\n".join(lines)[:MAX_SKILL_CHARS]

        return await anyio.to_thread.run_sync(work)

    async def skill_text(self, extension: Extension, skill: Skill) -> str:
        def work() -> str:
            path = (self._folder / extension.id / skill.path).resolve()
            home = (self._folder / extension.id).resolve()
            if home not in path.parents:
                raise ExtensionError("That skill's file is outside its extension.")
            text = path.read_text(encoding="utf-8", errors="replace")
            limit = README_SKILL_CHARS if skill.kind == "readme" else MAX_SKILL_CHARS
            _, body = front_matter(text)
            return body[:limit]

        return await anyio.to_thread.run_sync(work)
