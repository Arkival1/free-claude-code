"""Sandboxed website workspaces that agents build and users preview."""

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

import anyio.to_thread

MAX_FILE_BYTES = 512_000
MAX_SITE_FILES = 400
ALLOWED_SUFFIXES = frozenset(
    {
        ".html",
        ".htm",
        ".css",
        ".js",
        ".mjs",
        ".json",
        ".svg",
        ".txt",
        ".md",
        ".webmanifest",
        ".xml",
        ".csv",
    }
)
_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".webmanifest": "application/manifest+json",
    ".xml": "application/xml; charset=utf-8",
    ".csv": "text/csv; charset=utf-8",
}
_SEGMENT_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")

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
STARTER_STYLES = """:root { color-scheme: light dark; }
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
    return _CONTENT_TYPES.get(Path(path).suffix.lower(), "application/octet-stream")


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

    def resolve(self, site_id: str, relative_path: str) -> Path:
        """Return an absolute path inside the site, or raise ``SiteError``."""
        candidate = (relative_path or "").strip().replace("\\", "/").lstrip("/")
        if not candidate:
            raise SiteError("A file path is required.")
        segments = [part for part in candidate.split("/") if part not in {"", "."}]
        if not segments or len(segments) > 6:
            raise SiteError("That file path is not allowed.")
        for segment in segments:
            if segment == ".." or not _SEGMENT_PATTERN.match(segment):
                raise SiteError(f"Unsafe path segment: {segment!r}")
        suffix = Path(segments[-1]).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            allowed = ", ".join(sorted(ALLOWED_SUFFIXES))
            raise SiteError(f"Only these file types are allowed: {allowed}")
        target = self.directory(site_id).joinpath(*segments)
        base = self.directory(site_id).resolve()
        if not str(target.resolve()).startswith(str(base)):
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
        target = self.resolve(site_id, relative_path)

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
            target.unlink()
            return True

        return await anyio.to_thread.run_sync(work)

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
                if path.is_file()
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
                    if path.is_file():
                        bundle.write(path, self._relative(site_id, path))
            return buffer.getvalue()

        return await anyio.to_thread.run_sync(work)

    async def remove(self, site_id: str) -> None:
        """Delete the whole site directory."""
        directory = self.directory(site_id)

        def work() -> None:
            if not directory.is_dir():
                return
            for path in sorted(directory.rglob("*"), reverse=True):
                path.unlink() if path.is_file() else path.rmdir()
            directory.rmdir()

        await anyio.to_thread.run_sync(work)

    def _relative(self, site_id: str, path: Path) -> str:
        return path.relative_to(self.directory(site_id)).as_posix()

    def _count(self, directory: Path) -> int:
        if not directory.is_dir():
            return 0
        return sum(1 for path in directory.rglob("*") if path.is_file())
