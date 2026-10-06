"""A finished app is handed over in the chat, ready to download, like a file."""

import gc
import io
import zipfile
from pathlib import Path

from playwright.sync_api import Page, expect

from e2e.code_support import CodeControl
from free_claude_code.studio.service import StudioService

PAGE = "<!doctype html><title>Tides</title><h1>Tides</h1>"


def studio_of_this_test(tmp_path: Path) -> StudioService:
    """The Studio serving this test (its database lives in this test's folder)."""
    [studio] = [
        obj
        for obj in gc.get_objects()
        if isinstance(obj, StudioService) and tmp_path in obj._store.path.parents
    ]
    return studio


def test_a_finished_app_downloads_from_the_chat(
    page: Page, admin_base_url: str, code_control: CodeControl, tmp_path: Path
) -> None:
    studio = studio_of_this_test(tmp_path)

    async def build() -> tuple[str, str]:
        await studio.ensure_defaults()
        builder = await studio.agent_by_name("Builder")
        assert builder is not None
        site = await studio.create_site(name="Tide Times")
        await studio.workspace.write(site.id, "index.html", PAGE)
        chat = await studio.create_chat(agent_id=builder.id, site_id=site.id)
        await studio._offer_app_download(chat, frozenset({site.id}))
        return chat.id, site.id

    chat_id, site_id = code_control.run(build())
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{admin_base_url}/studio#chat/{chat_id}")

    card = page.locator(".download-card")
    expect(card).to_contain_text("Tide Times")
    expect(card).to_contain_text("tide-times.zip")
    expect(card.get_by_role("link", name="Open")).to_have_attribute(
        "href", f"/studio/sites/{site_id}/index.html"
    )
    box = card.bounding_box()
    assert box is not None and box["width"] <= 390, "fits a phone"

    with page.expect_download() as waiting:
        card.get_by_role("link", name="Download Tide Times").click()
    download = waiting.value
    assert download.suggested_filename == "tide-times.zip"
    with zipfile.ZipFile(io.BytesIO(download.path().read_bytes())) as archive:
        names = archive.namelist()
    assert "index.html" in names

    card.get_by_role("button", name="Files").click()
    expect(page).to_have_url(f"{admin_base_url}/studio#site/{site_id}")
