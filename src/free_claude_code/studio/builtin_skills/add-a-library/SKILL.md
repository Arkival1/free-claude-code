---
name: add-a-library
description: How the Changer adds an outside library to FCC so agents can use it - a UI library, website layouts, game art and sound, example code or any collection - the way the owner asked for Uiverse, Start Bootstrap, Kenney and Phaser - find it, check its licence, show the owner a preview, keep a copy inside FCC, give agents a tool, test it and ship it.
---

# Add a library to FCC

The owner's rules (CLAUDE.md): every outside repo FCC uses must keep
working if the original is deleted, downloaded files are data (never run
their scripts), and nothing new is added without saying what it is, its
licence, its size and what it can reach.

## 1. Find and judge it
- Search (web_search, web_fetch, the repo's README) and pick the best one or
  two. For each: what it holds and how many, the licence, the total size,
  the format (FCC sites are plain HTML/CSS/JS; games use Phaser 3), and
  whether it is kept up.
- Licence decides what can ship: MIT, Apache-2.0, BSD, ISC, CC0 and CC BY
  (keep the credit) can; LGPL can as an unchanged file with its licence;
  anything "non-commercial", "no derivatives", "assets not included" or with
  no licence can't. Ship only the parts the licence allows and say what was
  left out (Phaser's examples: the code is MIT, the art isn't, so only code).

## 2. Ask the owner first
- Before building, tell the owner in plain words: the name and link, what
  agents will get, the licence, the size inside FCC, anything downloaded
  later, and a handful of real samples (names, a screenshot from
  fcc_changer look if it renders). Build only after a yes; build only the
  parts they approve.

## 3. Keep a copy inside FCC
- Download into its own folder outside src/ (git clone --depth 1, curl),
  read it as data with Python run as `python3 -I`, and never run its own
  install or build scripts.
- Write a packer in `vendor/<name>/pack.py` that turns the files into one
  data file in `src/free_claude_code/studio/<library>/`: gzip JSON for text
  pieces (`ui_library/uiverse.json.gz`), a zip for files and pictures
  (`site_layouts/layouts.zip`). Shrink big photos and video with ffmpeg,
  turn .ogg into .mp3 (iPhones), point CDN links at a vendor/ copy, and drop
  outside services (form backends, trackers).
- Keep it small enough for the release zips (aim under about 30 MB). For
  more, ship a core set and a catalogue of the rest with each file's
  address and SHA-256; download on request into a vault folder under
  Studio's data and check the checksum before keeping it (see
  `game_library.GameVault`).
- `vendor/<name>/`: LICENSE, README (upstream link, commit or release, what
  FCC uses, what was left out and why), SHA256SUMS of the shipped data
  files, and the packer. Add a row to `vendor/README.md`.

## 4. Give agents a tool
- Follow the closest existing one in `studio/tools.py`: `ui_library`
  (search and get one piece's code), `site_layouts` (list and copy a whole
  layout with `_copy_kit`), `game_assets` (find, use, download, examples).
  Add the ToolSpec (with an enum of actions), the `case` in the dispatch,
  and a handler that turns bad input into a failed ToolOutcome with a clear
  message, never an exception.
- Give it to the right agents: `_DEFAULT_UPGRADES` in service.py (saved
  agents get it too; presets like Designer and Developer by name and
  role), `CODER_TOOLS` and the presets in presets.py, the "Code and files"
  group, the HQ `TOOL_STATION`, and `WRITE_TOOLS` in agents.py if it writes
  files. Add its sample words to `templates.STARTER_TEXT` so check_project
  asks for them to be replaced, then run scripts/phone/build_pages.py.
- A starter template or a built-in skill (`studio/builtin_skills/<name>/
  SKILL.md`) when agents need to know how to use it well.

## 5. Test and ship
- Tests in `tests/studio/test_<library>.py`: the checksum in SHA256SUMS
  matches, the counts are right, search finds real things, the tool works
  through the toolbox (`run(studio, context, "<tool>", ...)`), bad input
  fails cleanly, and a saved agent is upgraded. A browser test in `e2e/`
  when it makes pages or games.
- README and guide.py say what it is. Then fcc_changer check and tests, and
  say exactly what was added, its licence and size, and what was left out.
