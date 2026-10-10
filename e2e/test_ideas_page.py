"""The Ideas board page: the user's references for the team, added as notes,
links, photos, and videos, then searched, tagged, edited, and removed."""

from playwright.sync_api import FilePayload, Page, expect

from e2e.test_business_photos import png_bytes

LOOK: FilePayload = {
    "name": "Hero I like.png",
    "mimeType": "image/png",
    "buffer": png_bytes(80, 45),
}


def test_the_ideas_board_keeps_references_for_the_team(
    page: Page, admin_base_url: str
) -> None:
    page.goto(f"{admin_base_url}/studio#ideas")
    expect(page.get_by_role("heading", name="Ideas board")).to_be_visible()
    expect(page.get_by_text("Nothing on the board yet.")).to_be_visible()

    page.get_by_label("Idea title").fill("Menu cards")
    page.get_by_label("Idea notes").fill("Rounded cards, cream background.")
    page.get_by_label("Idea link").fill("https://example.com/menu")
    page.get_by_label("Idea tags").fill("ui, website")
    page.get_by_role("button", name="Add note or link").click()
    tiles = page.locator(".idea-tile")
    expect(tiles).to_have_count(1)
    expect(tiles.first).to_contain_text("Menu cards")
    expect(tiles.first).to_contain_text("link · ui · website")

    page.get_by_label("Idea notes").fill("Big photo, short headline.")
    page.get_by_label("Idea tags").fill("hero")
    page.get_by_label("Photos or videos for the ideas board").set_input_files([LOOK])
    expect(tiles).to_have_count(2)
    photo = page.locator(".idea-tile.photo")
    expect(photo).to_contain_text("hero i like")
    width = photo.locator("img").evaluate(
        "img => img.decode().then(() => img.naturalWidth)"
    )
    assert width == 80

    # Tags filter the board; notes save as they are edited.
    page.get_by_role("button", name="hero", exact=True).click()
    expect(tiles).to_have_count(1)
    notes = page.get_by_label("Notes for hero i like")
    notes.fill("Exactly this feel.")
    notes.blur()
    expect(page.locator(".toast")).to_contain_text("Saved.")
    page.get_by_role("button", name="all", exact=True).click()
    expect(tiles).to_have_count(2)

    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Delete Menu cards").click()
    expect(tiles).to_have_count(1)
