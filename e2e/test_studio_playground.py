"""Studio's Playground on the PC: a Look switch (HUD or Playground), the
Manus-like New task page, a task where the main AI does the work and its
advisers advise and check it, Files, and each AI's mind."""

from playwright.sync_api import Page, expect


def test_the_playground_look_runs_a_task_and_shows_each_mind(
    page: Page, admin_base_url: str
) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(f"{admin_base_url}/studio#settings")
    tabs = page.locator(".tab-bar .tab")
    expect(tabs.first).to_contain_text("Home")
    page.get_by_role("button", name="Playground").click()
    expect(tabs).to_have_count(5)
    expect(tabs.nth(0)).to_contain_text("New task")
    expect(tabs.nth(1)).to_contain_text("Tasks")
    expect(tabs.nth(2)).to_contain_text("Files")

    tabs.nth(0).click()
    expect(
        page.get_by_role("heading", name="What do you want to get done?")
    ).to_be_visible()
    page.get_by_role("button", name="Build a website").click()
    box = page.get_by_label("The task")
    expect(box).to_have_value("Build a website for ")
    box.fill("Build a website for a calm yoga studio")
    page.get_by_role("button", name="Start task ↗").click()
    expect(page.get_by_role("heading", name="Done", exact=True)).to_be_visible(
        timeout=30000
    )
    expect(page.get_by_text("does the work · advising:", exact=False)).to_be_visible()
    expect(
        page.get_by_text("Keep it to one calm page with big headings.").first
    ).to_be_visible()
    expect(
        page.get_by_text("Made the page: index.html and styles.css.").first
    ).to_be_visible()

    tabs.nth(1).click()
    expect(page.get_by_text("Build a website for a calm yoga studio")).to_be_visible()

    page.goto(f"{admin_base_url}/studio#pminds")
    expect(
        page.get_by_text("Sketch the sections before writing the page.").first
    ).to_be_visible()
    page.get_by_label("Something you like").fill("Soft greens and lots of space.")
    page.get_by_role("button", name="Add").click()
    expect(page.get_by_text("Soft greens and lots of space.")).to_be_visible()

    # The look stays after a reload, and More switches back to the HUD.
    page.reload()
    expect(tabs.nth(0)).to_contain_text("New task")
    page.locator(".tab-bar .tab", has_text="More").click()
    page.get_by_role("button", name="HUD").click()
    expect(tabs.first).to_contain_text("Home")
    expect(tabs).to_have_count(9)
    assert errors == []
