from fastapi.testclient import TestClient

from free_claude_code.application.orb import OrbBrain, OrbReply
from free_claude_code.core.version import package_version
from tests.api.support import create_test_app


class NoTools:
    def tools(self):
        return []

    def has(self, suffix):
        return None

    def call(self, name, arguments):
        return "ERROR: none"


class FakeBrain(OrbBrain):
    def __init__(self):
        super().__init__(
            base_url="http://127.0.0.1:1234/v1", toolbox=NoTools(), skills=""
        )
        self.asked = []

    def ask(self, text: str) -> OrbReply:
        self.asked.append(text)
        self.history.append({"role": "user", "content": text})
        return OrbReply(
            text=f"You said {text}", tools_used=["memory_recall"], model="m"
        )

    def list_models(self) -> list[dict[str, object]]:
        return [{"id": "qwen3.5-4b", "loaded": True}]

    def new_conversation(self) -> str:
        return "Saved note 'Orb conversation'"

    def resume(self, topic: str = "") -> str:
        self.memory_note = "remembered " + topic
        return self.memory_note


def local_client(app, origin=None):
    headers = {"origin": origin} if origin else {}
    return TestClient(
        app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000), headers=headers
    )


def app_with_fake_brain():
    from free_claude_code.application.orb import OrbStudio

    app = create_test_app()
    brain = FakeBrain()
    app.state.orb_studio = OrbStudio(
        lambda: "http://127.0.0.1:1234/v1",
        toolbox_factory=lambda: None,
        brain_factory=lambda **kw: brain,
    )
    return app, brain


def test_orb_page_and_assets_are_served_locally():
    client = local_client(create_test_app())
    page = client.get("/orb")
    assert page.status_code == 200
    assert f"/orb/assets/{package_version()}/orb.js" in page.text
    assert page.headers["cache-control"] == "no-store"
    for name in ("orb.js", "orb.css", "app-icon.svg"):
        assert client.get(f"/orb/assets/{package_version()}/{name}").status_code == 200
    assert (
        client.get(f"/orb/assets/{package_version()}/../admin_routes.py").status_code
        == 404
    )
    assert client.get("/orb/assets/0.0.0/orb.js").status_code == 404


def test_orb_refuses_remote_clients_and_foreign_websites():
    app = create_test_app()
    remote = TestClient(app, base_url="http://127.0.0.1", client=("10.0.0.9", 5000))
    assert remote.get("/orb").status_code == 403
    evil = local_client(app, origin="https://evil.example")
    assert (
        evil.post("/orb/api/chat", json={"text": "delete my files"}).status_code == 403
    )
    assert evil.post("/orb/api/say", json={"text": "hi"}).status_code == 403


def test_orb_chat_models_and_memory_endpoints():
    app, brain = app_with_fake_brain()
    client = local_client(app)
    answer = client.post("/orb/api/chat", json={"text": "  hello  "}).json()
    assert answer == {
        "reply": "You said hello",
        "tools_used": ["memory_recall"],
        "compacted": False,
        "model": "m",
    }
    assert client.get("/orb/api/models").json()["models"][0]["id"] == "qwen3.5-4b"
    assert (
        client.post("/orb/api/model", json={"model": "qwen3.5-4b"}).status_code == 200
    )
    assert brain.model == "qwen3.5-4b"
    assert client.post("/orb/api/new").json()["saved"].startswith("Saved note")
    resumed = client.post("/orb/api/resume", json={"topic": "tea"}).json()
    assert resumed == {"memory": "remembered tea", "loaded": True}
    status = client.get("/orb/api/status").json()
    assert status["turns"] == 1 and status["version"] == package_version()
    assert client.post("/orb/api/chat", json={"text": ""}).status_code == 422


def test_orb_chat_errors_are_reported_plainly():
    app, brain = app_with_fake_brain()

    def broken(_text):
        raise RuntimeError("Could not reach LM Studio. Open LM Studio.")

    brain.ask = broken
    response = local_client(app).post("/orb/api/chat", json={"text": "hi"})
    assert response.status_code == 503
    assert "Open LM Studio" in response.json()["detail"]
    assert (
        "Open LM Studio"
        in local_client(app).get("/orb/api/status").json()["last_error"]
    )


def test_jarvis_can_speak_through_the_orb_inbox():
    app, _ = app_with_fake_brain()
    client = local_client(app)
    first = client.post(
        "/orb/api/say", json={"text": "Download finished, sir."}
    ).json()["id"]
    client.post("/orb/api/say", json={"text": "Notes saved.", "source": "lmstudio"})
    items = client.get(f"/orb/api/inbox?after={first}").json()["items"]
    assert [(i["text"], i["source"]) for i in items] == [("Notes saved.", "lmstudio")]
