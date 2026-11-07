"""FCC Phone's Trading card and Plugins list, through the PC link: the phone
reads the desk and can stop it, deny, use the kill switch and work in
practice; real money stays on the PC."""

import dataclasses
from typing import Any

import pytest

from free_claude_code.studio.extensions import BUILTIN_ID
from free_claude_code.studio.models import now_ms
from free_claude_code.studio.trading.records import TradeOrder
from tests.api.support import create_test_app

from .test_phone_link import ORIGIN, paired
from .test_trading_routes import client_for, fake_platform

__all__ = ["fake_platform"]

PHONE_PATHS = (
    ("GET", "/studio/api/phone/trading"),
    ("POST", "/studio/api/phone/trading/start"),
    ("POST", "/studio/api/phone/trading/stop"),
    ("POST", "/studio/api/phone/trading/kill"),
    ("POST", "/studio/api/phone/trading/orders/x/approve"),
    ("POST", "/studio/api/phone/trading/orders/x/deny"),
    ("GET", "/studio/api/phone/plugins"),
    ("POST", "/studio/api/phone/skill"),
)


def data(value: object) -> Any:
    return value


async def waiting_order(studio, mode: str, broker: str = "") -> TradeOrder:
    order = TradeOrder(
        client_id=f"fcc-test-{mode}-{broker}",
        broker=broker or ("paper" if mode == "paper" else "fake"),
        mode=mode,
        symbol="BHP.AX",
        qty=5,
        status="awaiting_approval",
        due_at=now_ms() + 600_000,
    )
    await studio._store.put(order)
    return order


@pytest.mark.asyncio
async def test_the_phones_trading_and_plugin_paths_need_the_phone_secret(make_studio):
    studio, _ = make_studio([])
    app = create_test_app(studio=studio)
    async with client_for(app) as client:
        for method, path in PHONE_PATHS:
            refused = await client.request(
                method, path, json={}, headers={"Origin": ORIGIN}
            )
            assert refused.status_code == 401, path
            assert refused.headers["access-control-allow-origin"] == "*"
            wrong = await client.request(
                method, path, json={}, headers={"Authorization": "Bearer nope"}
            )
            assert wrong.status_code == 401, path
    await studio.shutdown()


@pytest.mark.asyncio
async def test_the_phone_watches_and_runs_the_practice_desk(make_studio):
    studio, _ = make_studio([])
    app = create_test_app(studio=studio)
    async with client_for(app) as client:
        _, phone = await paired(client)
        card = data(
            (await client.get("/studio/api/phone/trading", headers=phone)).json()
        )
        assert card["mode"] == "paper" and card["running"] is False
        assert card["live"] is False and card["kill"] is None
        assert card["account"]["equity_base"] == 10_000
        # Totals only: nothing that names or unlocks the account.
        for private in ("number", "fingerprint", "permissions"):
            assert private not in card["account"]
        assert card["summary"]["closed_trades"] == 0

        started = await client.post("/studio/api/phone/trading/start", headers=phone)
        assert started.status_code == 200, started.text
        assert studio.trading.config().running
        stopped = await client.post("/studio/api/phone/trading/stop", headers=phone)
        assert stopped.status_code == 200
        assert not studio.trading.config().running

        order = await waiting_order(studio, "paper")
        denied = await client.post(
            f"/studio/api/phone/trading/orders/{order.id}/deny", headers=phone
        )
        assert denied.status_code == 200, denied.text
        assert (await studio._store.get(TradeOrder, order.id)).status == "denied"

        # Closing everything needs the typed phrase, as on the PC.
        careless = await client.post(
            "/studio/api/phone/trading/kill",
            json={"flatten": True, "confirm": "yes"},
            headers=phone,
        )
        assert careless.status_code == 400 and "CLOSE EVERYTHING" in careless.text
        killed = await client.post(
            "/studio/api/phone/trading/kill",
            json={"flatten": True, "confirm": "CLOSE EVERYTHING"},
            headers=phone,
        )
        assert killed.status_code == 200, killed.text
        card = data(
            (await client.get("/studio/api/phone/trading", headers=phone)).json()
        )
        assert card["kill"] is not None
        again = await client.post("/studio/api/phone/trading/start", headers=phone)
        assert again.status_code == 400 and "kill switch" in again.text.lower()
        assert card["events"] and card["last"] >= card["events"][-1]["seq"]
        newer = data(
            (
                await client.get(
                    f"/studio/api/phone/trading?after={card['last']}", headers=phone
                )
            ).json()
        )
        assert newer["events"] == []
    await studio.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "broker", "allowed"),
    [
        ("paper", "paper", True),
        # A sell of a real holding made while the desk is in practice keeps
        # its real account: it routes there, so it is real money.
        ("paper", "fake", False),
        ("live_approve", "paper", False),
        ("live_approve", "fake", False),
        ("alert_only", "paper", False),
    ],
)
async def test_the_phone_approves_practice_orders_only(
    make_studio, monkeypatch, mode, broker, allowed
):
    studio, _ = make_studio([])
    app = create_test_app(studio=studio)
    approved: list[str] = []

    async def approve(order_id: str):
        approved.append(order_id)
        return {"id": order_id, "status": "submitted"}

    monkeypatch.setattr(studio.trading, "approve", approve)
    async with client_for(app) as client:
        _, phone = await paired(client)
        order = await waiting_order(studio, mode, broker)
        answer = await client.post(
            f"/studio/api/phone/trading/orders/{order.id}/approve", headers=phone
        )
        if allowed:
            assert answer.status_code == 200, answer.text
            assert approved == [order.id]
        else:
            assert answer.status_code == 400 and "on the PC" in answer.text
            assert approved == []
            assert (await studio._store.get(TradeOrder, order.id)).status == (
                "awaiting_approval"
            )
            # Saying no is always allowed from the phone.
            denied = await client.post(
                f"/studio/api/phone/trading/orders/{order.id}/deny", headers=phone
            )
            assert denied.status_code == 200, denied.text
        gone = await client.post(
            "/studio/api/phone/trading/orders/nope/approve", headers=phone
        )
        assert gone.status_code == 400
    await studio.shutdown()


@pytest.mark.asyncio
async def test_real_money_never_starts_from_the_phone(make_studio, fake_platform):
    studio, _ = make_studio([])
    app = create_test_app(studio=studio)
    async with client_for(app) as client:
        await client.put(
            "/studio/api/trading/brokers/fake",
            json={"values": {"token": "super-secret", "region": "au"}},
        )
        tested = data(
            (await client.post("/studio/api/trading/brokers/fake/test")).json()
        )
        await client.post(
            "/studio/api/trading/brokers/fake/confirm",
            json={"fingerprint": tested["account"]["fingerprint"]},
        )
        live = await client.put(
            "/studio/api/trading/config",
            json={"values": {"mode": "live_approve", "broker": "fake"}},
        )
        assert live.status_code == 200, live.text

        _, phone = await paired(client)
        card = await client.get("/studio/api/phone/trading", headers=phone)
        assert card.status_code == 200
        assert card.json()["live"] is True
        assert "super-secret" not in card.text and "4567" not in card.text
        refused = await client.post("/studio/api/phone/trading/start", headers=phone)
        assert refused.status_code == 400 and "PC" in refused.text
        assert not studio.trading.config().running
    await studio.shutdown()


@pytest.mark.asyncio
async def test_phone_agents_read_the_pcs_switched_on_skills(make_studio):
    studio, _ = make_studio([])
    await studio._extensions.install_builtin()
    app = create_test_app(studio=studio)
    async with client_for(app) as client:
        _, phone = await paired(client)
        repos = data(
            (await client.get("/studio/api/phone/plugins", headers=phone)).json()
        )["repos"]
        fcc = next(repo for repo in repos if repo["origin"] == "builtin")
        assert fcc["enabled"] and fcc["skills"] >= 30

        read = await client.post(
            "/studio/api/phone/skill",
            json={"action": "read", "name": "game-design"},
            headers=phone,
        )
        assert read.status_code == 200, read.text
        assert "core loop" in read.json()["text"].lower()
        found = await client.post(
            "/studio/api/phone/skill",
            json={"action": "search", "query": "game design"},
            headers=phone,
        )
        assert "game-design" in found.json()["text"]
        missing = await client.post(
            "/studio/api/phone/skill",
            json={"action": "read", "name": "no-such-skill"},
            headers=phone,
        )
        assert missing.status_code == 400
        outside = await client.post(
            "/studio/api/phone/skill",
            json={
                "action": "read",
                "repo": fcc["name"],
                "file": "../../../../etc/passwd",
            },
            headers=phone,
        )
        assert outside.status_code == 400 and "root:" not in outside.text

        # A repo switched off on the PC can't be read from the phone.
        builtin = await studio._extensions.get(BUILTIN_ID)
        await studio._extensions.save(dataclasses.replace(builtin, enabled=False))
        off = await client.post(
            "/studio/api/phone/skill",
            json={
                "action": "read",
                "repo": fcc["name"],
                "file": "game-design/SKILL.md",
            },
            headers=phone,
        )
        assert off.status_code == 400 and "turned off" in off.text
        hidden = await client.post(
            "/studio/api/phone/skill",
            json={"action": "read", "name": "game-design"},
            headers=phone,
        )
        assert hidden.status_code == 400
    await studio.shutdown()
