"""The Content Farm on the PC: channels, the idea board, and the Farm chat."""

import re

from playwright.sync_api import Page, expect


def open_farm(page: Page, admin_base_url: str) -> None:
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.goto(f"{admin_base_url}/studio#farm")
    expect(page.locator(".farm-hero h1")).to_have_text("Content Farm")


def test_a_channel_is_made_and_ideas_go_on_its_line(
    page: Page, admin_base_url: str
) -> None:
    open_farm(page, admin_base_url)
    expect(page.locator(".farm-chat")).to_contain_text("Farm chat")
    page.locator(".farm-channel.add").click()
    page.get_by_label("Channel name").fill("spacefacts.daily")
    page.get_by_label("Niche").fill("space facts")
    page.locator(".farm-style", has_text="Story time").click()
    page.locator(".farm-look", has_text="Neon").click()
    page.locator(".farm-style", has_text="Art cards").click()
    page.get_by_label("Posting times").fill("9:00, 18:00")
    page.get_by_role("button", name="Make channel").click()

    expect(page.get_by_text("Channel made. Fill its idea board next.")).to_be_visible()
    channel = page.locator(".farm-channel.active")
    expect(channel).to_contain_text("@spacefacts.daily")
    expect(channel).to_contain_text("Story time")
    line = page.locator(".farm-line")
    expect(line).to_contain_text("posts at 09:00, 18:00")

    page.get_by_label("New idea").fill("Why Venus spins backwards")
    page.get_by_role("button", name="Add idea").click()
    ideas = page.locator(".farm-column.col-idea")
    expect(ideas.locator(".farm-card")).to_contain_text("Why Venus spins backwards")
    expect(ideas.locator(".farm-count")).to_have_text("1")

    page.get_by_role("button", name="Delete Why Venus spins backwards").click()
    expect(ideas.locator(".farm-card")).to_have_count(0)

    page.locator(".farm-modes .lab-mode[data-mode='setup']").click()
    expect(page.locator(".farm-look.on")).to_have_class(re.compile("look-neon"))
    expect(page.get_by_label("Posting times")).to_have_value("09:00, 18:00")
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name="Delete channel").click()
    expect(page.get_by_text("Channel deleted.")).to_be_visible()


def test_the_farm_is_in_the_tab_bar(page: Page, admin_base_url: str) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{admin_base_url}/studio#agents")
    page.locator(".tab[data-route='farm']").click()
    expect(page.locator(".farm-hero h1")).to_have_text("Content Farm")
    expect(page.locator(".farm-modes .lab-mode")).to_have_count(6)


def test_pictures_go_in_the_media_library_and_long_styles_are_offered(
    page: Page, admin_base_url: str, tmp_path
) -> None:
    open_farm(page, admin_base_url)
    page.locator(".farm-modes .lab-mode[data-mode='library']").click()
    expect(page.get_by_role("heading", name="Media library")).to_be_visible()
    picture = tmp_path / "walt teaching chemistry.png"
    picture.write_bytes(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
            "890000000d49444154789c6360f8cfc0f01f0005000201e2bd1d5c0000000049"
            "454e44ae426082"
        )
    )
    page.get_by_label("Show for new files").fill("Breaking Bad")
    page.get_by_label("Add clips, pictures, and songs").set_input_files(str(picture))
    asset = page.locator(".farm-asset", has_text="walt teaching chemistry")
    expect(asset).to_be_visible()
    expect(asset).to_contain_text("Breaking Bad")
    page.once("dialog", lambda dialog: dialog.accept())
    asset.get_by_role("button", name="Remove walt teaching chemistry").click()
    expect(asset).to_have_count(0)

    page.locator(".farm-channel.add").click()
    expect(
        page.get_by_role("heading", name="Long videos to fall asleep to (16:9, hours)")
    ).to_be_visible()
    page.locator(".farm-style", has_text="Entire lore to sleep to").click()
    expect(page.get_by_label("Length in minutes")).to_be_visible()
    expect(page.get_by_label("Length in seconds")).to_be_hidden()
    expect(page.get_by_label("Allow AI-made pictures")).to_be_checked()


def test_characters_are_added_and_cast_in_a_cartoon_channel(
    page: Page, admin_base_url: str
) -> None:
    open_farm(page, admin_base_url)
    page.locator(".farm-modes .lab-mode[data-mode='cast']").click()
    expect(page.get_by_role("heading", name="Characters")).to_be_visible()
    page.get_by_role("button", name="+ Add character").click()
    dialog = page.get_by_role("dialog", name="New character")
    dialog.get_by_label("Name").fill("Sundiata")
    dialog.get_by_label("Who they are").fill("a prince who couldn't walk")
    dialog.get_by_label("Age").select_option("kid")
    dialog.locator("select[data-key='wear']").select_option("crown")
    dialog.get_by_role("button", name="Add character").click()
    expect(page.get_by_text("Character added.")).to_be_visible()
    card = page.locator(".farm-cast-card", has_text="Sundiata")
    expect(card).to_be_visible()
    expect(card.locator("img")).to_have_js_property("complete", True)
    assert card.locator("img").evaluate("img => img.naturalWidth") > 0

    page.locator(".farm-channel.add").click()
    page.get_by_label("Channel name").fill("epiccomebacks")
    page.locator(".farm-style", has_text="Animated cartoon story").click()
    expect(page.get_by_label("Series title")).to_be_visible()
    expect(page.get_by_role("heading", name="Pictures and clips")).to_be_hidden()
    page.get_by_label("Series title").fill("Most Epic Comebacks in History")
    page.locator(".farm-cast-pick", has_text="Sundiata").locator("input").check()
    page.get_by_role("button", name="Make channel").click()
    expect(page.get_by_text("Channel made. Fill its idea board next.")).to_be_visible()
    page.locator(".farm-modes .lab-mode[data-mode='setup']").click()
    expect(page.get_by_label("Series title")).to_have_value(
        "Most Epic Comebacks in History"
    )
    expect(
        page.locator(".farm-cast-pick", has_text="Sundiata").locator("input")
    ).to_be_checked()

    page.locator(".farm-style", has_text="Music edit").click()
    expect(page.get_by_label("Big words colour")).to_be_visible()
    expect(page.get_by_label("Series title")).to_be_hidden()

    page.locator(".farm-modes .lab-mode[data-mode='cast']").click()
    page.locator(".farm-cast-card", has_text="Sundiata").click()
    page.once("dialog", lambda dialog: dialog.accept())
    page.get_by_role("dialog", name="Edit Sundiata").get_by_role(
        "button", name="Delete"
    ).click()
    expect(page.get_by_text("Character deleted.")).to_be_visible()
    expect(page.locator(".farm-cast-card")).to_have_count(0)
