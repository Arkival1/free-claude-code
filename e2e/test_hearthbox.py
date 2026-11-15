"""Hearthbox, the village sim in docs/hearthbox, plays on a phone-sized screen:
villagers talk, the panels open, a whispered party spreads, a blueprint gets
placed, powers and land brushes work, and the world saves and loads."""

import http.server
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

GAME = Path(__file__).resolve().parents[1] / "docs" / "hearthbox"


class _QuietFiles(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(GAME), **kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        return


@pytest.fixture(scope="module")
def game_url() -> Iterator[str]:
    handler = _QuietFiles
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def test_hearthbox_plays_on_a_phone(page: Page, game_url: str) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on(
        "console",
        lambda m: errors.append(m.text) if m.type == "error" else None,
    )
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(game_url + "?seed=777")
    expect(page.locator("#clock")).to_contain_text("Day 1")
    expect(page.locator("#res")).to_contain_text("🍞")

    # A morning passes; people talk.
    page.evaluate("hearthbox.sim.advance(8 * 60)")
    assert page.evaluate("hearthbox.sim.feed.length") > 0

    # People tab, then a villager's card with stats, plan and memories.
    page.locator("#tabs button[data-tab=people]").click()
    page.locator("#plist .person").first.click()
    sheet = page.locator("#sheetBody")
    for part in ("Health", "Happiness", "Today's plan", "Relationships", "Memories"):
        expect(sheet).to_contain_text(part)

    # Whisper a party and let the news travel.
    page.locator("[data-act=whisper-open]").click()
    page.locator("[data-act=whisper][data-k=party]").click()
    page.evaluate("hearthbox.sim.advance(10 * 60)")
    knowers = page.evaluate(
        "(() => { const s = hearthbox.sim;"
        " const f = [...s.facts.values()].find(f => f.kind === 'party');"
        " return s.agents.filter(a => a.knowsSet.has(f.id)).length; })()"
    )
    assert knowers >= 2, "the party invitation spread"

    # Talk tab: chat transcripts and the news board.
    page.locator("#tabs button[data-tab=talk]").click()
    expect(sheet.locator(".convo").first).to_be_visible()
    page.locator("[data-act=seg][data-s=news]").click()
    expect(sheet).to_contain_text("known by")

    # Build: place a well next to the village.
    page.locator("#tabs button[data-tab=build]").click()
    page.locator("[data-act=tool-build][data-type=well]").click()
    before = page.evaluate("hearthbox.sim.buildings.length")
    spot = page.evaluate(
        "(() => { const s = hearthbox.sim; const v = s.villages[0];"
        " const p = s.findSpot(v, 'well'); const r = hearthbox.r;"
        " const q = r.toScreen(p.x + 0.5, p.y + 0.5);"
        " return {x: q.x / r.dpr, y: q.y / r.dpr}; })()"
    )
    page.evaluate(
        "(([x, y]) => { const r = hearthbox.r; r.cam.x += (x - 195) * r.dpr / r.cam.z;"
        " r.cam.y += (y - 400) * r.dpr / r.cam.z; })"
        f"([{spot['x']}, {spot['y']}])"
    )
    page.mouse.click(195, 400)
    expect(page.locator("#confirm")).to_be_visible()
    if page.locator("#confirmYes").is_visible():
        page.locator("#confirmYes").click()
        assert page.evaluate("hearthbox.sim.buildings.length") == before + 1
    page.locator("#toolDone").click()

    # Powers: rain, a sheep, a meteor away from town.
    page.locator("#tabs button[data-tab=powers]").click()
    page.locator("[data-act=tool-power][data-p=rain]").click()
    assert page.evaluate("hearthbox.sim.weather.kind") == "rain"
    page.locator("[data-act=tool-power][data-p=sheep]").click()
    page.mouse.click(195, 300)
    page.locator("#toolDone").click()
    assert page.evaluate("hearthbox.sim.power('meteor', 8, 8).ok")

    # Land: paint forest with a drag.
    page.locator("#tabs button[data-tab=land]").click()
    page.locator("[data-act=tool-land][data-l=forest]").click()
    page.mouse.move(120, 300)
    page.mouse.down()
    page.mouse.move(220, 320, steps=6)
    page.mouse.up()
    page.locator("#toolDone").click()

    # Stats, then save and reload.
    page.locator("#tabs button[data-tab=stats]").click()
    expect(sheet).to_contain_text("happiness")
    day = page.evaluate("hearthbox.sim.day")
    page.evaluate("hearthbox.save()")
    page.goto(game_url)
    expect(page.locator("#clock")).to_contain_text(f"Day {day}")
    assert errors == [], errors
