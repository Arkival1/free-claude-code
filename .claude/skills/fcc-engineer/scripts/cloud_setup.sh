#!/bin/sh
# Get a fresh Claude Code cloud session ready for FCC's checks:
# Python packages, and a headless Chromium Playwright can find even when the
# installed Playwright wants a newer build number than /opt/pw-browsers has.
set -eu
cd "$(dirname "$0")/../../../.."

uv sync --quiet 2>/dev/null || true

browsers="${PLAYWRIGHT_BROWSERS_PATH:-/opt/pw-browsers}"
have=$(ls -d "$browsers"/chromium_headless_shell-* 2>/dev/null | sort -V | tail -1 || true)
want=$(.venv/bin/python - <<'EOF' 2>/dev/null || true
import json, pathlib, playwright
root = pathlib.Path(playwright.__file__).parent / "driver" / "package" / "browsers.json"
for item in json.loads(root.read_text())["browsers"]:
    if item["name"] == "chromium-headless-shell":
        print(item["revision"])
EOF
)
if [ -n "$have" ] && [ -n "$want" ] && [ ! -e "$browsers/chromium_headless_shell-$want" ]; then
    shell="$have/chrome-linux/headless_shell"
    [ -x "$shell" ] || shell=$(find "$have" -name 'headless_shell' -type f | head -1)
    mkdir -p "$browsers/chromium_headless_shell-$want/chrome-headless-shell-linux64"
    ln -sf "$shell" "$browsers/chromium_headless_shell-$want/chrome-headless-shell-linux64/chrome-headless-shell"
    echo "Linked headless shell $(basename "$have") as build $want."
else
    echo "Browser ready (or nothing to link)."
fi
