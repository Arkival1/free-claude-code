"""Sandboxed website workspaces that agents build and users preview."""

import io
import os
import re
import shutil
import stat
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

import anyio.to_thread

MAX_FILE_BYTES = 512_000
MAX_SITE_FILES = 1_500
MAX_DEPTH = 12
ALLOWED_SUFFIXES = frozenset(
    {
        # web
        ".html",
        ".htm",
        ".css",
        ".scss",
        ".sass",
        ".less",
        ".js",
        ".mjs",
        ".cjs",
        ".jsx",
        ".ts",
        ".tsx",
        ".vue",
        ".svelte",
        ".astro",
        ".svg",
        ".webmanifest",
        # data and config
        ".json",
        ".jsonc",
        ".xml",
        ".csv",
        ".yml",
        ".yaml",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
        ".lock",
        ".txt",
        ".md",
        ".mdx",
        ".rst",
        ".sql",
        ".graphql",
        ".prisma",
        ".proto",
        # languages
        ".py",
        ".pyi",
        ".rb",
        ".php",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".kts",
        ".swift",
        ".c",
        ".h",
        ".cc",
        ".cpp",
        ".hpp",
        ".cs",
        ".dart",
        ".lua",
        ".r",
        ".scala",
        ".ex",
        ".exs",
        ".zig",
        # scripts
        ".sh",
        ".bash",
        ".zsh",
        ".ps1",
        ".bat",
        ".cmd",
    }
)
ALLOWED_NAMES = frozenset(
    {
        "Dockerfile",
        "Makefile",
        "Procfile",
        "LICENSE",
        "README",
        "Gemfile",
        ".gitignore",
        ".dockerignore",
        ".editorconfig",
        ".prettierrc",
        ".eslintrc",
        ".npmrc",
        ".nvmrc",
        ".python-version",
        ".env.example",
    }
)
# Files agents may not write but the preview may serve, e.g. build output.
PREVIEW_ONLY_SUFFIXES = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".avif",
        ".ico",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".wasm",
        ".map",
        ".mp3",
        ".mp4",
        ".webm",
    }
)
# Dependency and cache folders: huge, regenerated, never listed or zipped.
SKIP_DIRS = frozenset(
    {
        "node_modules",
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".next",
        ".nuxt",
        ".cache",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".turbo",
        ".parcel-cache",
        "target",
        ".studio-history",
    }
)
HISTORY_DIR = ".studio-history"
"""Earlier versions of each file, kept so an agent or the user can undo."""
MAX_VERSIONS = 10
_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".cjs": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".webmanifest": "application/manifest+json",
    ".xml": "application/xml; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".wasm": "application/wasm",
    ".map": "application/json; charset=utf-8",
    ".mp3": "audio/mpeg",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
}
_SEGMENT_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
# Windows refuses these names in any folder, with or without an extension.
WINDOWS_RESERVED = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{index}" for index in range(1, 10)}
    | {f"lpt{index}" for index in range(1, 10)}
)


def is_windows_reserved(segment: str) -> bool:
    """Return whether Windows would refuse this file or folder name."""
    stem = segment.split(".", 1)[0].lower()
    return stem in WINDOWS_RESERVED or segment.endswith((".", " "))


STARTER_PAGE = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{title}</title>
    <link rel="stylesheet" href="styles.css" />
  </head>
  <body>
    <main>
      <h1>{title}</h1>
      <p>This site is empty. Ask an agent to build it.</p>
    </main>
    <script src="app.js"></script>
  </body>
</html>
"""
STARTER_STYLES = """/* Starter styles: plain HTML looks finished before any classes. */
:root {
  --bg: #fffaf3;
  --surface: #ffffff;
  --text: #2b2118;
  --muted: #6f6257;
  --accent: #c2571a;
  --line: #eadfce;
  --radius: 16px;
  --page: 1040px;
  color-scheme: light;
  font: 17px/1.65 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #17120e;
    --surface: #211a14;
    --text: #f4ece3;
    --muted: #b3a597;
    --accent: #f08a4b;
    --line: #3a2f25;
    color-scheme: dark;
  }
}
*, *::before, *::after { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); }
body > nav, body > main, body > section, body > footer {
  width: min(var(--page), 100% - 40px);
  margin-inline: auto;
}
body > header {
  padding: clamp(56px, 10vw, 110px) max(20px, (100% - var(--page)) / 2) 36px;
  background-color: color-mix(in srgb, var(--accent) 16%, var(--bg));
  border-bottom: 1px solid var(--line);
}
header h1 { font-size: clamp(2.2rem, 7vw, 3.8rem); line-height: 1.05; margin: 0 0 10px; }
header p { font-size: 1.15rem; color: var(--muted); max-width: 40rem; }
h1, h2, h3 { line-height: 1.2; }
h2 { font-size: clamp(1.4rem, 3.5vw, 2rem); margin: 0 0 18px; }
h2::after {
  content: "";
  display: block;
  width: 48px;
  height: 4px;
  margin-top: 10px;
  border-radius: 2px;
  background: var(--accent);
}
p { margin: 0 0 14px; }
a { color: var(--accent); transition: opacity 0.2s; }
a:hover { opacity: 0.8; }
nav ul { list-style: none; display: flex; flex-wrap: wrap; gap: 8px 22px; padding: 0; margin: 18px 0 0; }
nav a { font-weight: 600; text-decoration: none; }
main { padding: 12px 0 40px; }
main > section, body > section, main > article {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: clamp(20px, 4vw, 36px);
  margin: 24px 0;
  box-shadow: 0 1px 2px rgb(0 0 0 / 0.04), 0 10px 30px rgb(0 0 0 / 0.05);
}
section > ul, section > ol {
  list-style: none;
  padding: 0;
  margin: 0 0 14px;
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
}
section > ul > li, section > ol > li {
  margin: 0;
  padding: 14px 16px;
  background: var(--bg);
  border: 1px solid var(--line);
  border-radius: 12px;
  transition: transform 0.15s, border-color 0.2s;
}
section > ul > li:hover, section > ol > li:hover {
  transform: translateY(-2px);
  border-color: var(--accent);
}
li { margin: 6px 0; }
img, svg, video { max-width: 100%; height: auto; border-radius: 12px; }
article, .card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 20px;
  margin: 0 0 16px;
}
table { width: 100%; border-collapse: collapse; margin: 0 0 16px; }
th, td { padding: 10px; border-bottom: 1px solid var(--line); text-align: left; }
button, input, select, textarea { font: inherit; }
button, .button {
  display: inline-block;
  background: var(--accent);
  color: #fff;
  border: 0;
  border-radius: 999px;
  padding: 12px 22px;
  min-height: 44px;
  font-weight: 700;
  text-decoration: none;
  cursor: pointer;
  transition: filter 0.2s, transform 0.15s;
}
button:hover, .button:hover { filter: brightness(1.08); transform: translateY(-1px); }
input, select, textarea {
  width: 100%;
  padding: 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface);
  color: var(--text);
}
form { display: grid; gap: 12px; max-width: 520px; }
footer { padding: 28px 0 44px; color: var(--muted); text-align: center; }
:focus-visible { outline: 3px solid var(--accent); outline-offset: 3px; }
"""
_OLD_STARTER_STYLES = """:root { color-scheme: light dark; }
body {
  margin: 0;
  font: 16px/1.5 system-ui, -apple-system, "SF Pro Text", sans-serif;
  display: grid;
  place-items: center;
  min-height: 100dvh;
}
main { padding: 24px; max-width: 42rem; }
"""
STARTER_SCRIPT = "// Agent-written behavior goes here.\n"


def tidy_html(content: str) -> tuple[str, list[str]]:
    """Add what every page needs when a model left it out, and say what."""
    added: list[str] = []
    lowered = content.lower()
    if "<html" not in lowered and "<body" not in lowered:
        return content, added
    head = re.search(r"<head[^>]*>", content, re.I)
    extra = []
    if "charset" not in lowered:
        extra.append('<meta charset="utf-8">')
        added.append("charset")
    if 'name="viewport"' not in lowered and "name='viewport'" not in lowered:
        extra.append(
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
        )
        added.append("mobile viewport")
    if extra:
        joined = "\n  ".join(extra)
        if head is not None:
            content = f"{content[: head.end()]}\n  {joined}{content[head.end() :]}"
        else:
            opened = re.search(r"<html[^>]*>", content, re.I)
            at = opened.end() if opened else 0
            content = f"{content[:at]}\n<head>\n  {joined}\n</head>{content[at:]}"
    if not content.lstrip().lower().startswith("<!doctype"):
        content = "<!doctype html>\n" + content.lstrip()
        added.append("doctype")
    return content, added


def is_starter(path: str, content: str) -> bool:
    """True for the placeholder files every new project starts with."""
    if path == "styles.css":
        return content in {STARTER_STYLES, _OLD_STARTER_STYLES}
    if path == "app.js":
        return content == STARTER_SCRIPT
    if path == "index.html":
        head, _, rest = STARTER_PAGE.partition("{title}")
        return (
            content.startswith(head)
            and "This site is empty. Ask an agent" in rest
            and ("This site is empty. Ask an agent to build it." in content)
        )
    return False


class SiteError(ValueError):
    """Raised when a site path or payload is rejected."""


@dataclass(frozen=True, slots=True)
class SiteFile:
    """One file inside a site workspace."""

    path: str
    size: int
    content_type: str


def slugify(name: str) -> str:
    """Return a filesystem- and URL-safe slug for a site name."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug[:48] or "site"


def content_type_for(path: str) -> str:
    """Return the served content type for one site file path."""
    suffix = Path(path).suffix.lower()
    if suffix in _CONTENT_TYPES:
        return _CONTENT_TYPES[suffix]
    if suffix in ALLOWED_SUFFIXES or Path(path).name in ALLOWED_NAMES:
        return "text/plain; charset=utf-8"
    return "application/octet-stream"


def _skipped(relative: Path) -> bool:
    return any(part in SKIP_DIRS for part in relative.parts)


class SiteWorkspace:
    """Own one directory per site and refuse every write that escapes it."""

    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def root(self) -> Path:
        return self._root

    def directory(self, site_id: str) -> Path:
        """Return the directory holding one site's files."""
        if not _SEGMENT_PATTERN.match(site_id):
            raise SiteError("Invalid site identifier.")
        return self._root / site_id

    def resolve(
        self, site_id: str, relative_path: str, *, for_preview: bool = False
    ) -> Path:
        """Return an absolute path inside the site, or raise ``SiteError``."""
        candidate = (relative_path or "").strip().replace("\\", "/").lstrip("/")
        if not candidate:
            raise SiteError("A file path is required.")
        segments = [part for part in candidate.split("/") if part not in {"", "."}]
        if not segments or len(segments) > MAX_DEPTH:
            raise SiteError("That file path is not allowed.")
        for segment in segments:
            if segment == ".." or not _SEGMENT_PATTERN.match(segment):
                raise SiteError(f"Unsafe path segment: {segment!r}")
            if is_windows_reserved(segment):
                raise SiteError(f"{segment!r} is a reserved name on Windows.")
        name = segments[-1]
        suffix = Path(name).suffix.lower()
        allowed = suffix in ALLOWED_SUFFIXES or name in ALLOWED_NAMES
        if for_preview:
            allowed = allowed or suffix in PREVIEW_ONLY_SUFFIXES
        if not allowed:
            raise SiteError(f"{name!r} is not a text file type agents can write here.")
        target = self.directory(site_id).joinpath(*segments)
        base = self.directory(site_id).resolve()
        if not target.resolve().is_relative_to(base):
            raise SiteError("That file path escapes the site directory.")
        return target

    async def scaffold(self, site_id: str, title: str) -> None:
        """Create a site directory with a minimal, valid starter page."""
        await self.write(site_id, "index.html", STARTER_PAGE.format(title=title))
        await self.write(site_id, "styles.css", STARTER_STYLES)
        await self.write(site_id, "app.js", STARTER_SCRIPT)

    async def write(self, site_id: str, relative_path: str, content: str) -> SiteFile:
        """Write one text file into the site, enforcing size and count caps."""
        encoded = content.encode("utf-8")
        if len(encoded) > MAX_FILE_BYTES:
            raise SiteError(
                f"File is larger than the {MAX_FILE_BYTES // 1000} KB site limit."
            )
        target = self.resolve(site_id, relative_path)

        def work() -> SiteFile:
            directory = self.directory(site_id)
            if not target.exists() and self._count(directory) >= MAX_SITE_FILES:
                raise SiteError("This site already has the maximum number of files.")
            self._keep_version(site_id, target, replacing=encoded)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(encoded)
            return SiteFile(
                path=self._relative(site_id, target),
                size=len(encoded),
                content_type=content_type_for(target.name),
            )

        return await anyio.to_thread.run_sync(work)

    async def read(self, site_id: str, relative_path: str) -> str:
        """Return one site file decoded as UTF-8 text."""
        target = self.resolve(site_id, relative_path)

        def work() -> str:
            if not target.is_file():
                raise SiteError(f"{relative_path} does not exist in this site.")
            return target.read_text(encoding="utf-8", errors="replace")

        return await anyio.to_thread.run_sync(work)

    async def read_bytes(self, site_id: str, relative_path: str) -> bytes:
        """Return one site file's raw bytes for preview responses."""
        target = self.resolve(site_id, relative_path, for_preview=True)

        def work() -> bytes:
            if not target.is_file():
                raise SiteError(f"{relative_path} does not exist in this site.")
            return target.read_bytes()

        return await anyio.to_thread.run_sync(work)

    async def delete(self, site_id: str, relative_path: str) -> bool:
        """Delete one site file."""
        target = self.resolve(site_id, relative_path)

        def work() -> bool:
            if not target.is_file():
                return False
            self._keep_version(site_id, target, replacing=b"")
            target.unlink()
            return True

        return await anyio.to_thread.run_sync(work)

    async def versions(self, site_id: str, relative_path: str) -> list[int]:
        """When each kept earlier version of a file was saved, newest first."""
        target = self.resolve(site_id, relative_path)

        def work() -> list[int]:
            folder = self._history_folder(site_id, target)
            if not folder.is_dir():
                return []
            return sorted(
                (int(item.name) for item in folder.iterdir() if item.name.isdigit()),
                reverse=True,
            )

        return await anyio.to_thread.run_sync(work)

    async def restore(
        self, site_id: str, relative_path: str, *, back: int = 1
    ) -> SiteFile:
        """Put back an earlier version of a file; the current one is kept too."""
        target = self.resolve(site_id, relative_path)
        saved = await self.versions(site_id, relative_path)
        if not saved:
            raise SiteError(f"There is no earlier version of {relative_path}.")
        if back < 1 or back > len(saved):
            raise SiteError(f"{relative_path} has {len(saved)} earlier version(s).")
        folder = self._history_folder(site_id, target)
        content = (folder / str(saved[back - 1])).read_bytes()
        return await self.write(site_id, relative_path, content.decode("utf-8"))

    def _history_folder(self, site_id: str, target: Path) -> Path:
        relative = target.relative_to(self.directory(site_id))
        return self.directory(site_id) / HISTORY_DIR / relative

    def _keep_version(self, site_id: str, target: Path, *, replacing: bytes) -> None:
        """Save a file's current content before it changes; keep the last ten."""
        if not target.is_file():
            return
        current = target.read_bytes()
        if current == replacing:
            return
        folder = self._history_folder(site_id, target)
        folder.mkdir(parents=True, exist_ok=True)
        stamp = time.time_ns() // 1_000
        while (folder / str(stamp)).exists():
            stamp += 1
        (folder / str(stamp)).write_bytes(current)
        kept = sorted(
            (item for item in folder.iterdir() if item.name.isdigit()),
            key=lambda item: int(item.name),
        )
        for old in kept[:-MAX_VERSIONS]:
            old.unlink()

    async def files(self, site_id: str) -> tuple[SiteFile, ...]:
        """Return every file in the site, ordered by path."""
        directory = self.directory(site_id)

        def work() -> tuple[SiteFile, ...]:
            if not directory.is_dir():
                return ()
            found = [
                SiteFile(
                    path=self._relative(site_id, path),
                    size=path.stat().st_size,
                    content_type=content_type_for(path.name),
                )
                for path in sorted(directory.rglob("*"))
                if path.is_file() and not _skipped(path.relative_to(directory))
            ]
            return tuple(found)

        return await anyio.to_thread.run_sync(work)

    async def archive(self, site_id: str) -> bytes:
        """Return the whole site as a downloadable zip archive."""
        directory = self.directory(site_id)

        def work() -> bytes:
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as bundle:
                for path in sorted(directory.rglob("*")):
                    if path.is_file() and not _skipped(path.relative_to(directory)):
                        bundle.write(path, self._relative(site_id, path))
            return buffer.getvalue()

        return await anyio.to_thread.run_sync(work)

    async def remove(self, site_id: str) -> None:
        """Delete the whole site directory."""
        directory = self.directory(site_id)

        def work() -> None:
            if directory.is_dir():
                shutil.rmtree(directory, onexc=_retry_writable)

        await anyio.to_thread.run_sync(work)

    def _relative(self, site_id: str, path: Path) -> str:
        return path.relative_to(self.directory(site_id)).as_posix()

    def _count(self, directory: Path) -> int:
        if not directory.is_dir():
            return 0
        return sum(
            1
            for path in directory.rglob("*")
            if path.is_file() and not _skipped(path.relative_to(directory))
        )


def _retry_writable(function, path, _error) -> None:
    """Windows marks some files (e.g. in .git) read-only; clear it and retry."""
    os.chmod(path, stat.S_IWRITE)
    function(path)
