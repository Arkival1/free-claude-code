"""fcc-github (FCC Linux's GitHub, through GitHub's API): clone, push and pull
against a small fake GitHub, with real git."""

import base64
import hashlib
import importlib.machinery
import importlib.util
import json
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "linux" / "files" / "fcc-github"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def load():
    loader = importlib.machinery.SourceFileLoader("fcc_github", str(SCRIPT))
    spec = importlib.util.spec_from_loader("fcc_github", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def git_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


class FakeGitHub:
    """Just enough of GitHub's API (and raw downloads) for fcc-github."""

    def __init__(self) -> None:
        self.files = {
            "README.md": b"# Hello\n",
            "src/app.py": b"print('hi')\n",
            "run.sh": b"#!/bin/sh\necho run\n",
        }
        self.modes = {"run.sh": "100755"}
        self.commit = "c" * 40
        self.tree = "t" * 40
        self.blobs: dict[str, bytes] = {}
        self.trees: dict[str, list] = {}
        self.calls: list[tuple[str, str]] = []

    def items(self) -> list[dict]:
        return [
            {
                "path": path,
                "mode": self.modes.get(path, "100644"),
                "type": "blob",
                "sha": git_sha(data),
            }
            for path, data in self.files.items()
        ]

    def handle(self, method: str, path: str, body: dict | None) -> tuple[int, bytes]:
        self.calls.append((method, path))
        if path.startswith("/raw/"):
            parts = path.split("/", 5)
            return 200, self.files[parts[5]]
        if method == "GET" and path == "/repos/o/r":
            return 200, json.dumps(
                {"default_branch": "main", "private": False}
            ).encode()
        if method == "GET" and path == "/repos/o/r/commits/main":
            return 200, json.dumps(
                {"sha": self.commit, "commit": {"tree": {"sha": self.tree}}}
            ).encode()
        if method == "GET" and path.startswith(f"/repos/o/r/git/trees/{self.tree}"):
            return 200, json.dumps({"tree": self.items(), "truncated": False}).encode()
        if method == "POST" and path == "/repos/o/r/git/blobs":
            assert body is not None
            data = base64.b64decode(body["content"])
            sha = git_sha(data)
            self.blobs[sha] = data
            return 201, json.dumps({"sha": sha}).encode()
        if method == "POST" and path == "/repos/o/r/git/trees":
            assert body is not None and body["base_tree"] == self.tree
            sha = hashlib.sha1(json.dumps(body, sort_keys=True).encode()).hexdigest()
            self.trees[sha] = body["tree"]
            return 201, json.dumps({"sha": sha}).encode()
        if method == "POST" and path == "/repos/o/r/git/commits":
            assert body is not None and body["parents"] == [self.commit]
            return 201, json.dumps(
                {
                    "sha": hashlib.sha1(body["tree"].encode()).hexdigest(),
                    "tree": body["tree"],
                }
            ).encode()
        if method == "PATCH" and path == "/repos/o/r/git/refs/heads/main":
            assert body is not None
            for entry in self.trees[list(self.trees)[-1]]:
                if entry["sha"] is None:
                    self.files.pop(entry["path"], None)
                else:
                    self.files[entry["path"]] = self.blobs[entry["sha"]]
            self.commit = body["sha"]
            self.tree = list(self.trees)[-1]
            return 200, json.dumps({"object": {"sha": body["sha"]}}).encode()
        return 404, json.dumps({"message": "Not Found"}).encode()


@pytest.fixture
def github(monkeypatch):
    fake = FakeGitHub()

    class Handler(BaseHTTPRequestHandler):
        def _answer(self) -> None:
            length = int(self.headers.get("content-length") or 0)
            body = json.loads(self.rfile.read(length)) if length else None
            status, data = fake.handle(self.command, self.path, body)
            self.send_response(status)
            self.send_header("content-length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = do_PATCH = _answer

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    module = load()
    monkeypatch.setattr(module, "API", base)
    monkeypatch.setattr(module, "RAW", f"{base}/raw")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    yield module, fake
    server.shutdown()
    server.server_close()


def git(folder: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(folder), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def test_clone_push_and_pull_through_githubs_api(github, tmp_path, capsys):
    tool, fake = github
    folder = tmp_path / "r"
    assert tool.main(["clone", "o/r", str(folder)]) == 0
    assert (folder / "README.md").read_bytes() == b"# Hello\n"
    assert (folder / "src" / "app.py").read_text() == "print('hi')\n"
    assert (folder / "run.sh").stat().st_mode & 0o111  # kept executable
    assert git(folder, "status", "--porcelain") == ""

    # Nothing to push yet; an uncommitted change is refused with a reason.
    assert tool.main(["push", str(folder)]) == 0
    (folder / "src" / "app.py").write_text("print('hello from FCC Linux')\n")
    (folder / "README.md").unlink()
    (folder / "NEW.txt").write_text("new\n")
    assert tool.main(["push", str(folder)]) == 1
    assert "Commit your changes first" in capsys.readouterr().err
    git(folder, "add", "-A")
    git(folder, "commit", "-q", "-m", "Say hello")
    assert tool.main(["push", str(folder)]) == 0
    assert fake.files["src/app.py"] == b"print('hello from FCC Linux')\n"
    assert fake.files["NEW.txt"] == b"new\n" and "README.md" not in fake.files
    assert ("PATCH", "/repos/o/r/git/refs/heads/main") in fake.calls

    # Someone else changes GitHub: pull brings it in.
    fake.files["src/app.py"] = b"print('changed on GitHub')\n"
    fake.commit, fake.tree = "d" * 40, "e" * 40
    assert tool.main(["pull", str(folder)]) == 0
    assert (folder / "src" / "app.py").read_text() == "print('changed on GitHub')\n"
    assert tool.main(["status", str(folder)]) == 0
    assert "no newer commits" in capsys.readouterr().out


def test_push_refuses_when_github_moved_and_clone_stays_in_its_folder(
    github, tmp_path, capsys
):
    tool, fake = github
    folder = tmp_path / "r"
    assert tool.main(["clone", "o/r", str(folder)]) == 0
    (folder / "x.txt").write_text("x\n")
    git(folder, "add", "-A")
    git(folder, "commit", "-q", "-m", "x")
    fake.commit = "f" * 40
    assert tool.main(["push", str(folder)]) == 1
    assert "pull first" in capsys.readouterr().err
    # A listing that points outside the folder is refused.
    fake.files = {"../escape.txt": b"no"}
    fake.commit, fake.tree = "1" * 40, "2" * 40
    assert tool.main(["clone", "o/r", str(tmp_path / "other")]) == 1
    assert "outside the folder" in capsys.readouterr().err
    assert not (tmp_path / "escape.txt").exists()
