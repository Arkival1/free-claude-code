"""The HQ: the whole team as a pixel office."""

from playwright.sync_api import Page, expect


def test_the_hq_shows_the_team_and_lets_you_pick_an_agent(
    page: Page, admin_base_url: str
) -> None:
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.goto(f"{admin_base_url}/studio#hq")
    expect(page.locator(".hq-head h2")).to_have_text("HQ")
    canvas = page.locator(".hq-canvas")
    expect(canvas).to_be_visible()
    # The office is drawn: the canvas is not blank.
    page.wait_for_function(
        "() => { const c = document.querySelector('.hq-canvas');"
        " const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;"
        " let n = 0; for (let i = 0; i < d.length; i += 4) if (d[i] || d[i+1] || d[i+2]) n++;"
        " return n > 10000; }"
    )
    team = page.locator(".hq-team .hq-person")
    expect(team.first).to_be_visible()
    team.filter(has_text="Builder").first.click()
    expect(page.locator(".hq-panel h3")).to_have_text("Builder")
    expect(page.get_by_label("Message for Builder")).to_be_visible()
    page.locator(".hq-panel > .ghost-button.small").first.click()
    expect(page.locator(".hq-panel h3")).to_have_text("The team")
    # Clicking the office's approval desk shows what's waiting there.
    box = canvas.bounding_box()
    assert box is not None
    page.mouse.click(
        box["x"] + 320 / 480 * box["width"], box["y"] + 150 / 300 * box["height"]
    )
    expect(page.locator(".hq-panel h3")).to_have_text("Approval desk")
    expect(page.locator(".hq-panel")).to_contain_text("Nothing waiting")


def test_the_hq_is_in_the_tab_bar(page: Page, admin_base_url: str) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{admin_base_url}/studio#agents")
    page.locator(".tab[data-route='hq']").click()
    expect(page.locator(".hq-canvas")).to_be_visible()
    expect(page.locator(".tab-bar .tab")).to_have_count(8)
