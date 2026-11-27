import json
from pathlib import Path

from free_claude_code.cli import orb


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_orb_url_and_status_probe(monkeypatch):
    assert orb.orb_url("http://127.0.0.1:8082/") == "http://127.0.0.1:8082/orb"
    monkeypatch.setattr(
        orb,
        "open_local_request",
        lambda req, timeout: FakeResponse({"status": "running"}),
    )
    assert orb.server_is_up("http://127.0.0.1:8082")

    def refused(req, timeout):
        raise OSError("refused")

    monkeypatch.setattr(orb, "open_local_request", refused)
    assert not orb.server_is_up("http://127.0.0.1:8082")


def test_background_server_never_opens_admin_browser():
    calls = []
    orb.start_background_server(popen=lambda cmd, **kw: calls.append((cmd, kw)))
    cmd, kw = calls[0]
    assert kw["env"]["FCC_OPEN_BROWSER"] == "false"
    assert kw["stdout"] is not None and cmd


def test_orb_opens_as_app_window_or_falls_back(tmp_path, monkeypatch):
    edge = tmp_path / "msedge.exe"
    edge.write_text("")
    calls = []
    used = orb.open_orb_window(
        "http://127.0.0.1:8082/orb",
        popen=lambda cmd: calls.append(cmd),
        browsers=[tmp_path / "missing.exe", edge],
    )
    assert used == str(edge)
    assert calls == [
        [str(edge), "--app=http://127.0.0.1:8082/orb", "--window-size=520,640"]
    ]
    opened = []
    monkeypatch.setattr(orb.webbrowser, "open", opened.append)
    assert (
        orb.open_orb_window("u", popen=calls.append, browsers=[Path("nope")])
        == "default browser"
    )
    assert opened == ["u"]


def test_launch_starts_fcc_when_needed_then_opens_orb(monkeypatch):
    states = iter([False, False, True])
    events = []
    monkeypatch.setattr(orb, "server_is_up", lambda root: next(states))
    monkeypatch.setattr(orb, "start_background_server", lambda: events.append("start"))
    monkeypatch.setattr(orb.time, "sleep", lambda s: None)
    monkeypatch.setattr(orb, "open_orb_window", lambda url: events.append(url))
    orb.launch([])
    assert events[0] == "start" and events[1].endswith("/orb")
