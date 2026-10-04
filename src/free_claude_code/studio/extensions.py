"""Add skills, agents, commands, and MCP servers from a GitHub repo.

One link pulls in whatever a repo holds, the Claude Code way:
- skills: every SKILL.md (name and description up top, instructions below),
- agents: agents/*.md (an agent's name, description, tools, and prompt),
- commands: commands/*.md (a prompt the team can follow by name),
- MCP servers: .mcp.json, or mcpServers in a plugin's plugin.json,
- and a plain repo with none of those becomes one skill from its README.

Everything is kept on this PC under Studio's extensions folder. MCP servers
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

MAX_ZIP_BYTES = 80 * 1024 * 1024
MAX_UNPACKED_BYTES = 300 * 1024 * 1024
MAX_SKILL_CHARS = 16_000
README_SKILL_CHARS = 8_000
MAX_FOUND = 300
MANIFEST = "extension.json"
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
        raise ExtensionError("GitHub sent something that isn't a zip.") from error
    total = 0
    into.mkdir(parents=True, exist_ok=True)
    for info in archive.infolist():
        parts = PurePosixPath(info.filename).parts[1:]
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
    for listing in walk(".mcp.json"):
        extension.servers += _servers_from(_read_json(listing), listing.parent)
    for path in walk("SKILL.md"):
        values, _ = front_matter(path.read_text(encoding="utf-8", errors="replace"))
        extension.skills.append(
            Skill(
                name=values.get("name") or path.parent.name,
                description=values.get("description", "")[:400],
                path=_relative(path, base),
            )
        )
    for path in walk("*.md"):
        folder = path.parent.name
        if folder not in {"agents", "commands"} or path.name.lower() == "readme.md":
            continue
        values, body = front_matter(path.read_text(encoding="utf-8", errors="replace"))
        if folder == "agents":
            tools = values.get("tools", "")
            extension.agents.append(
                AgentDef(
                    name=values.get("name") or path.stem,
                    description=values.get("description", "")[:400],
                    prompt=body.strip()[:MAX_SKILL_CHARS],
                    tools=[t.strip() for t in tools.split(",") if t.strip()],
                )
            )
        else:
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
        self, folder: Path, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._folder = folder
        self._transport = transport

    @property
    def folder(self) -> Path:
        return self._folder

    async def add_github(self, link: str) -> Extension:
        repo = parse_link(link)
        data = await self._download(repo)
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
            extension.source = f"https://github.com/{repo.owner}/{repo.repo}" + (
                f"/tree/{repo.ref or 'HEAD'}/{repo.sub}" if repo.sub else ""
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
