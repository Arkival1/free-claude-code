"""The HQ's Relay card: the repos in order, each set to run on every job,
when it fits, or not at all."""

from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from free_claude_code.studio.starter import BUNDLE

VOLT = "VoltAgent/awesome-claude-code-subagents"


@pytest.fixture
def studio_starter_repos() -> Path:
    return BUNDLE


def test_the_relay_lists_every_repo_and_keeps_changes(
    page: Page, admin_base_url: str
) -> None:
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.goto(f"{admin_base_url}/studio#hq")
    relay = page.locator(".hq-relay")
    # Starter repos install in the background on the first load.
    for _ in range(30):
        if relay.locator(f"[data-repo='{VOLT}']").count():
            break
        page.wait_for_timeout(1000)
        page.reload()
    stages = relay.locator(".hq-relay-stage[data-repo]")
    expect(stages.first).to_have_attribute("data-repo", VOLT)
    expect(stages.nth(4)).to_have_attribute("data-repo", "crewAIInc/crewAI")
    assert stages.count() >= 30, "every repo in LCC has a place"
    # Every repo joins only the jobs it has agents trained for.
    expect(relay.get_by_label(f"When {VOLT} runs")).to_have_value("fits")
    expect(relay.get_by_label("When leonxlnx/taste-skill runs")).to_have_value("fits")

    # Pin an agent, switch one repo off, and move it up: it all sticks.
    relay.get_by_label(f"Agent from {VOLT}").select_option("ui-designer")
    expect(page.locator(".toast")).to_contain_text("Relay saved")
    # A second agent from the same repo takes its own turn after the first.
    relay.get_by_label(f"Use another of {VOLT}'s agents").click()
    relay.get_by_label(f"Agent 2 from {VOLT}").select_option("seo-specialist")
    expect(relay.get_by_label(f"Agent 2 from {VOLT}")).to_have_value("seo-specialist")
    expect(relay.get_by_text("LCC: final check")).to_be_visible()
    relay.get_by_label(
        "Last, LCC's agent checks a finished website, app, or game and fixes what broke"
    ).uncheck()
    expect(relay.get_by_text("LCC: final check")).to_have_count(0)
    relay.get_by_label("When crewAIInc/crewAI runs").select_option("off")
    expect(relay.locator("[data-repo='crewAIInc/crewAI']")).to_have_class(
        "hq-relay-stage off"
    )
    relay.get_by_label("Move crewAIInc/crewAI up").click()
    expect(stages.nth(3)).to_have_attribute("data-repo", "crewAIInc/crewAI")
    relay.get_by_label(
        "On: new websites, apps, and games go through the relay"
    ).uncheck()

    page.reload()
    relay = page.locator(".hq-relay")
    expect(relay.get_by_label(f"Agent from {VOLT}")).to_have_value("ui-designer")
    expect(relay.get_by_label(f"Agent 2 from {VOLT}")).to_have_value("seo-specialist")
    expect(
        relay.get_by_label(
            "Last, LCC's agent checks a finished website, app, or game and fixes what broke"
        )
    ).not_to_be_checked()
    expect(relay.get_by_label("When crewAIInc/crewAI runs")).to_have_value("off")
    expect(relay.locator(".hq-relay-stage[data-repo]").nth(3)).to_have_attribute(
        "data-repo", "crewAIInc/crewAI"
    )
    expect(
        relay.get_by_label("On: new websites, apps, and games go through the relay")
    ).not_to_be_checked()
