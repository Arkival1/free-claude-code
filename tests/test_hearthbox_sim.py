"""Hearthbox's simulation (docs/hearthbox) runs for days without a screen:
the village survives, people talk, a whispered party spreads, something new
gets built, and the save loads back."""

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
