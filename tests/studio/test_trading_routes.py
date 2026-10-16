"""The Trading Bank's API: status, settings, keys (PC only, never shown back),
the feed, and the tax export."""

from typing import Any

import httpx
import pytest

from free_claude_code.studio.trading.brokers import registry
from free_claude_code.studio.trading.brokers.registry import BrokerSpec, KeyField
from tests.api.support import create_test_app

from .test_trading_desk import FakeLive


def data(value: object) -> Any:
    return value


@pytest.fixture
def fake_platform(monkeypatch):
    broker = FakeLive()
    monkeypatch.setitem(
        registry.BROKERS,
        "fake",
        BrokerSpec(
            id="fake",
            name="Fake Broker",
            markets=("us", "asx", "crypto"),
            what="test",
            get_keys="test",
            australia="test",
            fields=(
                KeyField("token", "Token"),
                KeyField("region", "Region", secret=False),
            ),
            factory=lambda values, data, transport: broker,
        ),
    )
    return broker


def client_for(app, host: str = "127.0.0.1") -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=(host, 50_000)),
        base_url="http://127.0.0.1",
    )


@pytest.mark.asyncio
async def test_the_trading_api(make_studio, fake_platform):
    studio, _ = make_studio([])
    app = create_test_app(studio=studio)
    async with client_for(app) as client:
        status = data((await client.get("/studio/api/trading")).json())
        assert status["mode"] == "paper" and status["running"] is False
        assert status["account"]["equity_base"] == 10_000
        assert [seat["name"] for seat in status["seats"]][-1] == "Portfolio Manager"

        changed = await client.put(
            "/studio/api/trading/config",
            json={"values": {"candidates": 3, "watchlist": "bhp.ax, btc"}},
        )
        assert changed.status_code == 200, changed.text
        assert data(changed.json())["watchlist"] == ["BHP.AX", "BTC"]

        refused = await client.put(
            "/studio/api/trading/config",
            json={"values": {"mode": "live_approve", "broker": "fake"}},
        )
        assert refused.status_code == 400 and "keys" in refused.json()["detail"]

        saved = await client.put(
            "/studio/api/trading/brokers/fake",
            json={"values": {"token": "super-secret", "region": "au"}},
        )
        assert saved.status_code == 200, saved.text
        assert "super-secret" not in saved.text
        brokers = data((await client.get("/studio/api/trading/brokers")).json())[
            "brokers"
        ]
        fake = next(item for item in brokers if item["id"] == "fake")
        token, region = fake["fields"]
        assert token["set"] and token["value"] == ""
        assert region["value"] == "au"
        assert "super-secret" not in str(brokers)

        tested = data(
            (await client.post("/studio/api/trading/brokers/fake/test")).json()
        )
        assert tested["account"]["number"] == "••••4567"
        confirmed = await client.post(
            "/studio/api/trading/brokers/fake/confirm",
            json={"fingerprint": tested["account"]["fingerprint"]},
        )
        assert confirmed.status_code == 200, confirmed.text
        live = await client.put(
            "/studio/api/trading/config",
            json={"values": {"mode": "live_approve", "broker": "fake"}},
        )
        assert live.status_code == 200, live.text

        feed = data((await client.get("/studio/api/trading/feed")).json())
        assert feed["last"] >= 1 and feed["events"]
        assert "pulse" in feed
        newer = data(
            (await client.get(f"/studio/api/trading/feed?after={feed['last']}")).json()
        )
        assert newer["events"] == []

        bad = await client.post("/studio/api/trading/debate", json={"symbol": "?!"})
        assert bad.status_code == 400

        export = await client.get("/studio/api/trading/export.csv")
        assert export.headers["content-type"].startswith("text/csv")
        assert export.text.startswith("Asset,Quantity")
        assert (await client.get("/studio/api/trading/summary")).json()[
            "closed_trades"
        ] == 0
        assert (await client.get("/studio/api/trading/rounds/nope")).status_code == 404
    await studio.shutdown()


@pytest.mark.asyncio
async def test_keys_and_going_live_are_for_the_pc_only(make_studio, fake_platform):
    studio, _ = make_studio([])
    app = create_test_app(studio=studio)
    async with client_for(app, host="192.168.1.20") as phone:
        saved = await phone.put(
            "/studio/api/trading/brokers/fake", json={"values": {"token": "x"}}
        )
        assert saved.status_code == 403
        live = await phone.put(
            "/studio/api/trading/config",
            json={"values": {"mode": "live_approve", "broker": "fake"}},
        )
        assert live.status_code == 400
        assert "from the PC" in live.json()["detail"]
    await studio.shutdown()
