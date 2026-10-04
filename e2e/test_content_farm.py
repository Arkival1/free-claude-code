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
    expect(page.locator(".farm-modes .lab-mode")).to_have_count(4)
