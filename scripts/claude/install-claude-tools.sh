#!/usr/bin/env bash
# Tools for the FCC Claude Code setup that live on the PC, not in the repo.
#
# The skills and the previewer agent are already in the repo
# (.claude/skills, .claude/agents/previewer.md; see vendor/agent-skills).
# This installs the two command-line tools they use:
#   - Playwright CLI (real browser checks)
#   - Graphify (a code map Claude Code asks before reading lots of files)
# Run from the fcc folder in Git Bash (Windows) or a terminal:
#   bash scripts/claude/install-claude-tools.sh
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

command -v npm >/dev/null 2>&1 || { echo "Node.js (npm) is needed: https://nodejs.org" >&2; exit 1; }
npm install -g @playwright/cli@latest

if command -v uv >/dev/null 2>&1; then
  uv tool install graphifyy || uv tool upgrade graphifyy
  # Registers Graphify's hooks in .claude/settings.json with this PC's path.
  # Its CLAUDE.md section is already in FCC's CLAUDE.md, so keep ours as is.
  cp CLAUDE.md CLAUDE.md.keep
  graphify claude install
  mv CLAUDE.md.keep CLAUDE.md
  echo "Building the Graphify code map (graphify-out/)..."
  graphify . || echo "Graphify couldn't build the map yet; run: graphify ."
else
  echo "uv not found, so Graphify was skipped. Install uv, then run this again."
fi

echo
echo "Done. Start Claude Code in this folder (claude) and ask:"
echo "  Read CLAUDE.md. Inspect the project only; do not edit yet."
