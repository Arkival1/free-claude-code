"""Hearthbox's simulation (docs/hearthbox) runs for days without a screen:
the village survives, people talk, a whispered party spreads, something new
gets built, and the save loads back."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

GAME = Path(__file__).resolve().parents[1] / "docs" / "hearthbox"


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
@pytest.mark.parametrize("seed", ["4242", "777"])
def test_the_village_lives_without_a_screen(seed: str) -> None:
    result = subprocess.run(
        ["node", str(GAME / "test" / "headless.mjs"), "8", seed],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
    assert "PASS" in result.stdout


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_edge_cases_from_review() -> None:
    """Fact cap during a party, two parties, fires across a save, stuck plans,
    a village with no buildings, and the same seed telling the same story."""
    result = subprocess.run(
        ["node", str(GAME / "test" / "edges.mjs")],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]


def test_offline_cache_lists_every_game_file() -> None:
    """iPhone home-screen play works offline only if sw.js caches every file."""
    sw = (GAME / "sw.js").read_text(encoding="utf-8")
    listed = set(re.findall(r'"([\w./-]+\.(?:html|css|js|png|webmanifest))"', sw))
    on_disk = {f"js/{p.name}" for p in (GAME / "js").glob("*.js")}
    on_disk |= {p.name for p in GAME.glob("icon-*.png")}
    on_disk |= {"index.html", "style.css", "manifest.webmanifest"}
    assert on_disk <= listed, sorted(on_disk - listed)
    assert all((GAME / name).exists() for name in listed - {"sw.js"})
    html = (GAME / "index.html").read_text(encoding="utf-8")
    assert 'rel="apple-touch-icon" href="icon-180.png"' in html
