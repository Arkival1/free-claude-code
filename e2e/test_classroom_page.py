"""The classroom (PocketPal's look): plan with the teacher, confirm, watch the
class, ask the teacher how the student did, and open the training choices."""

import os

from playwright.sync_api import Page, expect

SHOTS = os.environ.get("FCC_LAB_SHOTS", "")


def shot(page: Page, name: str) -> None:
    if SHOTS:
        page.screenshot(path=f"{SHOTS}/{name}.png")


def test_plan_watch_ask_and_train(page: Page, admin_base_url: str) -> None:
    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(f"{admin_base_url}/studio#learn")
    page.get_by_placeholder("Tide prediction for beginners").fill("Ohm's law")
    page.get_by_role("button", name="Open class").click()

    # The teacher chat: the owner says what to learn, the teacher plans.
    expect(page.locator(".pp-title strong")).to_have_text("Teacher")
    box = page.get_by_label("Message the teacher")
    box.fill("Teach it the maths an apprentice electrician needs")
    box.press("Enter")
    plan = page.locator(".pp-card", has_text="Lesson plan")
    expect(plan).to_contain_text("Using V = I x R")
    expect(plan).to_contain_text("Looks up: ohm's law worked examples")
    shot(page, "classroom-1-plan")

    # Confirm: the class runs; the owner watches.
    page.get_by_role("button", name="Confirm plan and start").click()
    expect(page.locator(".pp-title strong")).to_have_text("Ohm's law")
    expect(page.locator(".pp-title span")).to_contain_text("Passed", timeout=20_000)
    messages = page.locator(".pp-messages")
    expect(messages).to_contain_text("left the classroom")
    expect(messages).to_contain_text("do I multiply or divide")
    # The student's test question is answered by the teacher (it waits
    # first when the teacher is still out of the room).
    expect(messages).to_contain_text("Multiply: V = I x R")
    expect(page.locator(".pp-q.good")).to_have_count(2)
    expect(page.locator(".pp-seat.teacher")).to_contain_text("In class")
    shot(page, "classroom-2-watch")

    # The teacher chat: ask how the student is doing.
    page.get_by_role("button", name="Talk to the teacher", exact=True).click()
    page.get_by_role("button", name="How is the student doing?").click()
    expect(page.locator(".pp-msg.teacher").last).to_contain_text("doing well")
    shot(page, "classroom-3-ask")

    page.get_by_role("button", name="Train the student").click()
    sheet = page.get_by_role("dialog")
    expect(sheet).to_contain_text("This PC")
    expect(sheet).to_contain_text("Kaggle")
    expect(sheet).to_contain_text("Google Colab")
    shot(page, "classroom-4-train")
    sheet.get_by_role("button", name="Close").click()

    page.get_by_role("button", name="Teacher and student settings").click()
    expect(page.get_by_role("dialog")).to_contain_text("Use the cloud notebook")
    shot(page, "classroom-5-settings")
    page.get_by_role("dialog").get_by_role("button", name="Close").click()

    # On an iPhone-sized screen.
    page.set_viewport_size({"width": 390, "height": 844})
    page.get_by_role("button", name="Back to the classroom").click()
    expect(page.locator(".pp-stage")).to_be_visible()
    shot(page, "classroom-6-phone")
    page.get_by_role("button", name="Classes").click()
    expect(page.locator(".pp-session.active")).to_contain_text("Ohm's law")
    shot(page, "classroom-7-drawer")
