"""FCC Phone's 2D game art: 4,000 sprites from the Kenney packs FCC ships
(CC0), packed into games/art2d.bin with a generated catalogue, checked by
SHA-256 and kept by the service worker (owner approved, 6 November 2026)."""

import hashlib
import importlib.util
import json
import re
from collections import Counter
from pathlib import Path

from free_claude_code.api.studio_routes import PHONE_DIR

ROOT = Path(__file__).resolve().parents[2]


def build_pages():
    spec = importlib.util.spec_from_file_location(
        "build_pages", ROOT / "scripts" / "phone" / "build_pages.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_phone_ships_the_approved_4000_sprites_checked():
    """Run scripts/phone/build_pages.py after changing the game library."""
    blob, text = build_pages().art_js()
    assert (PHONE_DIR / "js" / "art2d.js").read_text(encoding="utf-8") == text
    shipped = (PHONE_DIR / "games" / "art2d.bin").read_bytes()
    assert shipped == blob
    found = re.search(r'sha256: "([0-9a-f]{64})", bytes: (\d+)', text)
    assert found is not None
    assert hashlib.sha256(shipped).hexdigest() == found[1]
    assert int(found[2]) == len(shipped)
    rows = json.loads(re.search(r"export const ART2D = (\[.*\]);\n", text)[1])
    assert len(rows) == 4000
    packs = Counter(row[0] for row in rows)
    assert len(packs) >= 35 and max(packs.values()) <= 170
    for pack, path, offset, length, width, height in rows:
        assert shipped[offset : offset + 8] == b"\x89PNG\r\n\x1a\n", (pack, path)
        assert width > 0 and height > 0 and offset + length <= len(shipped)
    assert b"CC0" in (PHONE_DIR / "games" / "LICENSE-kenney.txt").read_bytes()


def test_the_art_is_kept_offline_and_agents_get_the_tool():
    worker = (PHONE_DIR / "sw.js").read_text(encoding="utf-8")
    assert 'const ART_FILES = ["games/art2d.bin"];' in worker
    assert '"js/art.js"' in worker and '"js/art2d.js"' in worker
    state = (PHONE_DIR / "js" / "state.js").read_text(encoding="utf-8")
    assert '11: { main: ["game_art"], builder: ["game_art"] }' in state
    assert "const TOOLS_VERSION = 11;" in state
    tools = (PHONE_DIR / "js" / "tools.js").read_text(encoding="utf-8")
    assert "game_art: {" in tools and 'case "game_art":' in tools
