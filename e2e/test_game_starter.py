"""The phaser-game starter plays in Studio's preview: Phaser loads from the
project, the art and sounds load, the hero runs and the score shows."""

from pathlib import Path

from playwright.sync_api import Page, expect

from e2e.test_3d_templates import make_project


def test_the_game_starter_plays(
    page: Page, admin_base_url: str, tmp_path: Path
) -> None:
    errors: list[str] = []
    failed: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("requestfailed", lambda request: failed.append(request.url))
    page.on(
        "response",
        lambda response: (
            failed.append(response.url) if response.status >= 400 else None
        ),
    )
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(make_project(admin_base_url, tmp_path, "phaser-game"))
    page.get_by_role("button", name="Play").click()
    expect(page.locator("#screen canvas")).to_have_count(1)
    expect(page.locator("#hud")).to_contain_text("Coins 0")
    page.keyboard.down("ArrowRight")
    page.wait_for_timeout(900)
    page.keyboard.press("Space")
    page.wait_for_timeout(600)
    page.keyboard.up("ArrowRight")
    moved = page.evaluate(
        "window.game.scene.getScene('level').player.x"
        " > window.game.scene.getScene('level').start.x + 20"
    )
    assert moved, "the hero runs right"
    page.set_viewport_size({"width": 390, "height": 844})
    # The touch buttons are there (shown on touch screens, hidden with a mouse).
    expect(page.locator("#pad button")).to_have_count(3)
    assert page.evaluate("document.documentElement.scrollWidth - innerWidth") == 0
    assert errors == [] and failed == []
