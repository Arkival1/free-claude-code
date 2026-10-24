"""Godot 4.7.2 on this PC: download once, keep in the Repo vault, run headless.

The editor build for this PC comes from Godot's GitHub release and is
checked against Godot's own SHA-512 list (recorded in `vendor/godot/`) before
it is used or kept. When GitHub no longer has it, the vault's copy is used.
Jobs run one at a time (a game check, frames, an export), in the background,
each with a time limit.
"""

import asyncio
import contextlib
import hashlib
import math
import os
import re
import shutil
import stat
import sys
import zipfile
from collections.abc import AsyncIterator, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import anyio
import httpx
from loguru import logger

from ..vault import RepoVault, VaultError

VERSION = "4.7.2"
TAG = f"{VERSION}-stable"
OWNER, REPO = "godotengine", "godot"
DOWNLOAD = "https://github.com/godotengine/godot/releases/download/{tag}/{name}"
BUILDS = {
    "windows": (
        "Godot_v4.7.2-stable_win64.exe.zip",
        "83decd58fdf67b9d657958a1ae6bf1929c20785315a81effe245874cdc57acb7"
        "09bf868e00778a96984338c1b29dafdb453c6847747694621c6ecf5da2259993",
    ),
    "linux": (
        "Godot_v4.7.2-stable_linux.x86_64.zip",
        "9aa00f7a605200940bce3027a567b782f49bd8e940dd06ae9e987bd65aee1b14"
        "67edd56ed84fcdcbdd44354bf613bdbb4e5d2913e925850368e150c59ed54c65",
    ),
    "mac": (
        "Godot_v4.7.2-stable_macos.universal.zip",
        "38aa16e5bba2083941fc5b3e54be0089bd4cc35e32415f5b9fd9a8a6a7b98182"
        "55d44532ea8ef94b5aef56c4b407c2d634fa4f657e4ebe681ebbf59b7bac69ca",
    ),
}
"""Godot's own SHA-512 for each editor build (its SHA512-SUMS.txt)."""
TEMPLATES = (
    "Godot_v4.7.2-stable_export_templates.tpz",
    "ca4d71c4d7b81dfc15d1a98baa07534aa95b03fdda78a0075b06672e1648d2e5"
    "f40980c9adc28d23e1b92e732ee7bf3461997aa804af74ec2fcd7a93ccb84079",
)
"""The export templates (about 1 GB), downloaded only for an export."""
TIMED_OUT = -10_000
"""_run's code for a job stopped at its time limit (not a real exit code)."""
MAX_FRAME_SECONDS = 20.0
CHECK_SECONDS = 120
SHOT_SECONDS = 180
EXPORT_SECONDS = 600
PROBLEM = re.compile(r"(SCRIPT ERROR|ERROR:|Parse Error|USER ERROR)")
WARNING = re.compile(r"(WARNING:|USER WARNING)")
NOISE = (
    "Couldn't find the given section",
    "Failed loading resource: res://.godot",
    "resources still in use at exit",
)
"""Lines Godot prints that aren't the game's problem."""
LOAD_ALL = """extends SceneTree
# FCC's check: load every script, scene and resource in the project, so a
# file no scene uses yet is checked too. Godot prints each error it finds.

func _init() -> void:
	_walk("res://")
	quit()


func _walk(folder: String) -> void:
	for name in DirAccess.get_files_at(folder):
		if name.get_extension() in ["gd", "tscn", "tres", "gdshader"]:
			var path := folder.path_join(name)
			if load(path) == null:
				printerr("ERROR: Couldn't load %s" % path)
	for name in DirAccess.get_directories_at(folder):
		if not name.begins_with("."):
			_walk(folder.path_join(name))
"""


class GodotError(RuntimeError):
    """Godot couldn't do the job; the message says why and what to do."""


@dataclass(slots=True)
class Report:
    passed: bool
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    output: str = ""


def this_platform() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "mac"
    return "linux"


def read_lines(output: str) -> tuple[list[str], list[str]]:
    """Godot's error and warning lines, each with the line after it (where)."""
    lines = output.splitlines()
    problems: list[str] = []
    warnings: list[str] = []
    for index, line in enumerate(lines):
        if any(noise in line for noise in NOISE):
            continue
        where = lines[index + 1].strip() if index + 1 < len(lines) else ""
        text = line.strip() + (f" ({where})" if where.startswith("at:") else "")
        if PROBLEM.search(line):
            problems.append(text)
        elif WARNING.search(line):
            warnings.append(text)
    return list(dict.fromkeys(problems))[:40], list(dict.fromkeys(warnings))[:40]


class GodotEngine:
    def __init__(
        self,
        root: Path,
        *,
        vault: RepoVault | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        platform: str = "",
    ) -> None:
        self.root = root
        self._vault = vault
        self._transport = transport
        self.platform = platform or this_platform()
        self._lock = asyncio.Lock()
        """One Godot job at a time (a check, frames, an export)."""
        self._install_lock = asyncio.Lock()
        """One download or unpack at a time (two agents can ask at once)."""
        self.state = "idle"
        self.message = ""

    # ---------------------------------------------------------- the engine

    @property
    def folder(self) -> Path:
        return self.root / VERSION

    def binary(self) -> Path | None:
        """The Godot program, once installed."""
        if not self.folder.is_dir():
            return None
        if self.platform == "windows":
            console = sorted(self.folder.glob("Godot_v*_console.exe"))
            programs = console or sorted(self.folder.glob("Godot_v*.exe"))
        elif self.platform == "mac":
            programs = sorted(self.folder.glob("*.app/Contents/MacOS/Godot"))
        else:
            programs = sorted(self.folder.glob("Godot_v*.x86_64"))
        return programs[0] if programs else None

    def status(self) -> dict[str, object]:
        program = self.binary()
        return {
            "version": VERSION,
            "installed": program is not None,
            "state": self.state,
            "message": self.message,
            "busy": self._lock.locked() or self._install_lock.locked(),
        }

    async def install(self) -> Path:
        """Get Godot ready: from the vault if it has it, else from GitHub."""
        async with self._install_lock:
            program = self.binary()
            if program is not None:
                return program
            name, digest = BUILDS[self.platform]
            try:
                archive = await self._verified(
                    name, digest, f"Getting Godot {VERSION}…"
                )
                await anyio.to_thread.run_sync(_unpack, archive, self.folder)
                archive.unlink(missing_ok=True)
            except GodotError as error:
                self.state, self.message = "failed", str(error)
                (self.root / name).unlink(missing_ok=True)
                raise
            except (OSError, httpx.HTTPError, zipfile.BadZipFile) as error:
                self.state, self.message = "failed", str(error)
                (self.root / name).unlink(missing_ok=True)
                raise GodotError(f"Couldn't get Godot {VERSION}: {error}") from error
            program = self.binary()
            if program is None:
                raise GodotError("Godot was unpacked but its program wasn't found.")
            if self.platform != "windows":
                program.chmod(program.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
            self.state, self.message = "ready", f"Godot {VERSION} is ready."
            return program

    async def _verified(self, name: str, digest: str, message: str) -> Path:
        """The release file, checked against Godot's SHA-512 and kept in the
        vault: the vault's copy first, GitHub's when that one is missing or
        doesn't match. Nothing is used or kept before the check."""
        self.root.mkdir(parents=True, exist_ok=True)
        archive = self.root / name
        self.state, self.message = "downloading", message
        if await self._from_vault(name, archive):
            if await anyio.to_thread.run_sync(_sha512, archive) == digest:
                return archive
            archive.unlink(missing_ok=True)
        await self._download(DOWNLOAD.format(tag=TAG, name=name), archive)
        if await anyio.to_thread.run_sync(_sha512, archive) != digest:
            archive.unlink(missing_ok=True)
            raise GodotError(
                f"The download of {name} doesn't match Godot's published checksum, "
                "so it wasn't used. Try again later."
            )
        await self._keep(archive, name)
        return archive

    async def _from_vault(self, name: str, target: Path) -> bool:
        if self._vault is None:
            return False
        for item in await self._vault.items():
            if (
                item.full_name.lower() == f"{OWNER}/{REPO}"
                and item.name == name
                and await self._vault.intact(item)
            ):
                with contextlib.suppress(VaultError, OSError):
                    await self._vault.restore_file(item, target)
                    return True
        return False

    async def _keep(self, archive: Path, name: str) -> None:
        if self._vault is None:
            return
        try:
            await self._vault.keep_file(
                owner=OWNER,
                repo=REPO,
                kind="release",
                path=archive,
                url=DOWNLOAD.format(tag=TAG, name=name),
                ref=TAG,
            )
        except (OSError, VaultError) as error:
            logger.info("Studio: could not keep Godot in the vault: {}", error)

    async def _download(self, url: str, target: Path) -> None:
        partial = target.with_name(target.name + ".part")
        try:
            async with (
                httpx.AsyncClient(
                    timeout=httpx.Timeout(30.0, read=120.0),
                    follow_redirects=True,
                    transport=self._transport,
                ) as client,
                client.stream("GET", url) as answer,
            ):
                if answer.status_code != 200:
                    raise GodotError(f"GitHub answered {answer.status_code} for {url}.")
                with partial.open("wb") as handle:
                    async for chunk in answer.aiter_bytes(1 << 20):
                        handle.write(chunk)
        except BaseException:
            partial.unlink(missing_ok=True)  # never leave a big half file
            raise
        partial.replace(target)

    # ------------------------------------------------------------- jobs

    async def _run(
        self, args: Sequence[str], *, cwd: Path, timeout: float
    ) -> tuple[int, str]:
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except OSError as error:
            raise GodotError(f"Godot couldn't start: {error}") from error
        try:
            out, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except TimeoutError:
            return TIMED_OUT, f"Godot was stopped after {int(timeout)} seconds."
        finally:
            # A job that timed out or was cancelled never leaves Godot running.
            if process.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
                await process.wait()
        return process.returncode or 0, out.decode("utf-8", "replace")

    @contextlib.asynccontextmanager
    async def _job_async(self, state: str, message: str) -> AsyncIterator[None]:
        with self._job(state, message):
            yield

    @contextlib.contextmanager
    def _job(self, state: str, message: str) -> Iterator[None]:
        """The status while a job runs, put right however it ends."""
        self.state, self.message = state, message
        try:
            yield
        except BaseException as error:
            self.state, self.message = "failed", str(error)[:300]
            raise
        self.state, self.message = "ready", ""

    async def check(self, project: Path, *, frames: int = 300) -> Report:
        """Import the project, load every script and scene, then run it
        headless for a few seconds: every error and warning Godot prints,
        and any step that didn't finish."""
        if not (project / "project.godot").is_file():
            raise GodotError("This project has no project.godot: start one first.")
        program = await self.install()
        async with self._lock, self._job_async("checking", f"Checking {project.name}…"):
            self.root.mkdir(parents=True, exist_ok=True)
            checker = self.root / "fcc_load_all.gd"
            checker.write_text(LOAD_ALL, encoding="utf-8")
            steps = (
                ("Importing the project", ["--import"]),
                ("Loading every script and scene", ["--script", str(checker)]),
                ("Running the game", ["--quit-after", str(frames)]),
            )
            results: list[tuple[str, int, str]] = []
            for step, extra in steps:
                code, text = await self._run(
                    [str(program), "--headless", "--path", ".", *extra],
                    cwd=project,
                    timeout=CHECK_SECONDS,
                )
                results.append((step, code, text))
        output = "\n".join(text for _, _, text in results)
        problems, warnings = read_lines(output)
        for step, code, text in results:
            if code == TIMED_OUT:
                problems.append(f"{step} didn't finish: {text.strip()}")
            elif code != 0:
                problems.append(f"{step}: Godot stopped with code {code}.")
        tail = "\n".join(output.strip().splitlines()[-40:])
        return Report(
            passed=not problems, problems=problems, warnings=warnings, output=tail
        )

    async def frames(
        self, project: Path, target: Path, *, seconds: float = 3.0
    ) -> Path:
        """Run the game for a few seconds and save its last frame as a picture."""
        program = await self.install()
        length = seconds if math.isfinite(seconds) else 3.0
        length = min(max(length, 0.3), MAX_FRAME_SECONDS)
        count = int(length * 30)
        work = self.root / "frames" / project.name
        args = [
            str(program),
            "--path",
            ".",
            "--write-movie",
            str(work / "frame.png"),
            "--fixed-fps",
            "30",
            "--quit-after",
            str(count),
        ]
        if self.platform == "linux" and not os.environ.get("DISPLAY"):
            runner = shutil.which("xvfb-run")
            if runner is None:
                raise GodotError(
                    "Recording frames needs a screen: run FCC on the desktop, "
                    "or install xvfb."
                )
            args = [
                runner,
                "-a",
                "-s",
                "-screen 0 1280x720x24",
                *args,
                "--rendering-driver",
                "opengl3",
            ]
        async with (
            self._lock,
            self._job_async("recording", f"Recording {project.name}…"),
        ):
            shutil.rmtree(work, ignore_errors=True)
            work.mkdir(parents=True)
            _, output = await self._run(args, cwd=project, timeout=SHOT_SECONDS)
            shots = sorted(work.glob("frame*.png"))
            if shots:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(shots[-1], target)
        if not shots:
            problems, _ = read_lines(output)
            raise GodotError(
                "Godot didn't record any frames"
                + (f": {problems[0]}" if problems else ". Run action check first.")
            )
        return target

    def templates_folder(self) -> Path:
        home = Path.home()
        if self.platform == "windows":
            base = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
            return base / "Godot" / "export_templates" / f"{VERSION}.stable"
        if self.platform == "mac":
            return (
                home
                / "Library/Application Support/Godot/export_templates"
                / f"{VERSION}.stable"
            )
        return home / ".local/share/godot/export_templates" / f"{VERSION}.stable"

    async def install_templates(self) -> Path:
        """Godot's export templates, unpacked whole or not at all."""
        async with self._install_lock:
            folder = self.templates_folder()
            if (folder / "version.txt").is_file():
                return folder
            name, digest = TEMPLATES
            with self._job(
                "downloading", "Getting Godot's export templates (about 1 GB)…"
            ):
                archive = await self._verified(
                    name, digest, "Getting Godot's export templates (about 1 GB)…"
                )
                try:
                    await anyio.to_thread.run_sync(_unpack_templates, archive, folder)
                finally:
                    archive.unlink(missing_ok=True)
            return folder

    async def export(self, project: Path, target: Path, *, preset: str = "") -> Path:
        """Export a game you can play (Windows Desktop by default). The preset
        is checked first, so a project without one downloads nothing."""
        chosen = preset or {"windows": "Windows Desktop", "mac": "macOS"}.get(
            self.platform, "Linux"
        )
        presets = project / "export_presets.cfg"
        if not presets.is_file() or f'name="{chosen}"' not in presets.read_text(
            encoding="utf-8"
        ):
            raise GodotError(
                f'The project has no "{chosen}" export preset in export_presets.cfg.'
            )
        program = await self.install()
        await self.install_templates()
        target.parent.mkdir(parents=True, exist_ok=True)
        async with (
            self._lock,
            self._job_async("exporting", f"Exporting {project.name}…"),
        ):
            code, output = await self._run(
                [
                    str(program),
                    "--headless",
                    "--path",
                    ".",
                    "--export-release",
                    chosen,
                    str(target),
                ],
                cwd=project,
                timeout=EXPORT_SECONDS,
            )
        if code == TIMED_OUT or not target.is_file():
            problems, _ = read_lines(output)
            reason = problems[0] if problems else output.strip()[-300:]
            raise GodotError(f"The export didn't make a game: {reason}")
        return target


def _sha512(path: Path) -> str:
    digest = hashlib.sha512()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _unpack(archive: Path, folder: Path) -> None:
    partial = folder.with_name(folder.name + ".part")
    shutil.rmtree(partial, ignore_errors=True)
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            target = (partial / member.filename).resolve()
            if not target.is_relative_to(partial.resolve()):
                raise GodotError("The Godot download has a file outside its folder.")
        bundle.extractall(partial)
    shutil.rmtree(folder, ignore_errors=True)
    partial.replace(folder)


def _unpack_templates(archive: Path, folder: Path) -> None:
    partial = folder.with_name(folder.name + ".part")
    shutil.rmtree(partial, ignore_errors=True)
    partial.mkdir(parents=True)
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            name = member.filename.removeprefix("templates/")
            if not name or member.is_dir():
                continue
            target = (partial / name).resolve()
            if not target.is_relative_to(partial.resolve()):
                raise GodotError(
                    "The export templates have a file outside their folder."
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(member) as source, target.open("wb") as handle:
                shutil.copyfileobj(source, handle)
    # Moved into place only when whole, so a broken unpack is never "ready".
    shutil.rmtree(folder, ignore_errors=True)
    partial.replace(folder)
