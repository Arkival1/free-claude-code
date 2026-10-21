---
name: fcc-engineer
description: How to build, fix, test and ship FCC well on a small token budget - the owner's goals for FCC as a project, the cheapest working loop, which tests to run for a change (scripts/related_tests.py), FCC's traps (ty, Python 3.14, the store, Content Farm, Trading Bank rules), the report the owner wants, and how to score the Changer with a real model (references/changer-scorecard.md). Use for any coding, bug fixing, feature or release work in this repo, after the fcc-studio map.
---

# Working on FCC: lean and right

`fcc-studio` is the map (what lives where). This page is how to work.
Read `CLAUDE.md` for the owner's rules; this page doesn't repeat them.

## What the owner wants from FCC

- One app on their Windows PC (6 GB GPU) and phone that does real work:
  agents that build sites and code, a Lab, a tutor, a Trading Bank, and the
  Changer that updates FCC itself. Free or cheap models first (local LM
  Studio, NVIDIA NIM, free cloud tiers); never a paid model without asking.
- Things that actually work, shown with evidence: real files, real checks,
  screenshots, zips they can unzip over their fcc folder. No fake progress.
- Safety that only gets stricter: Trading Bank no-downgrade, keys never in
  files/logs/zips, Content Farm untouched, outside repos vendored.
- Short, plain answers. They read on an iPhone and count tokens.

## The loop (cheapest path that's still proven)

1. **Find, don't read.** `grep -n` for the symbol, then `sed -n A,Bp` the
   range. Never read whole big files (`service.py` is 10k+ lines). One
   `grep -n "def \|class "` outline beats three reads.
2. **Plan in 3-6 lines** with acceptance checks. Ask only if the intent is
   truly unclear (one question).
3. **Write the test first when it's a bug**: reproduce, see it fail, fix.
   Many cases? Parametrize: one test function, many rows.
4. **Edit with a script for multi-spot changes**: a small `python3 - <<EOF`
   with `assert old in s` for each replacement fails loudly instead of
   half-applying.
5. **Check only what the change touches:**
   `python3 .claude/skills/fcc-engineer/scripts/related_tests.py` prints
   the pytest command for the files you changed (it skips Content Farm).
   Then `uv run ruff format <files>`, `uv run ruff check <files>`,
   `uv run ty check <files>`. Format only the files you changed (a folder
   could reformat Content Farm), then confirm with `git status --short`.
   Full suite (`./scripts/ci.sh --skip playwright`, Content Farm ignored)
   only before a release or when the owner asks.
6. **Browser** only when a page changed: `uv run pytest e2e/test_<page>.py`.
   Never run Playwright and asyncio tests in one pytest call.
7. **Previewer twice** (CLAUDE.md): pass 1 on the diff, fix confirmed
   items, pass 2. Tell it "at most 6 tool calls, then report" or it can run
   out of turns with no report.
8. **Commit, push** to the owner's branch; a release also bumps
   `pyproject.toml` + `uv.lock` + the version in CLAUDE.md, then
   `scripts/release_zips.sh <scratchpad>/release-<ver>` and send every part.

## Token rules

- Background long runs; never poll with sleep.
- Pipe test output through `tail -3` or `grep -E "^FAILED|^E  |passed|failed"`.
- Don't paste diffs back to the owner; name files and what changed.
- One subagent at a time; give it the diff command, not the files' text.
- Skip skills and tools the task doesn't need.

## FCC traps (each one cost a run before)

- **No suppressions**: `# type: ignore` / `noqa` are banned. Narrow types
  with `isinstance`, small helpers like `_items()`, or explicit annotations
  (`JsonObject`, `JsonValue`, `list[dict[str, JsonValue]]`).
- **Python 3.14**: `except A, B:` (no brackets) is valid and used here.
- **Imports**: inside the package never `import free_claude_code` for paths;
  use `Path(__file__).parents[n]` (an import-boundary test checks).
- **Store**: new record → `models.py` Record + `TABLES` in `store.py`; any
  dict/list field must be in `_JSON_FIELDS`. Columns are added on their own.
- **Saves race**: reload before saving (`_save_project` pattern); never
  write a stale copy over the owner's pause/cancel.
- **Async tests**: wait on the real thing (the driver task, the run's job),
  never on `sleep`. A fake driver: set `studio._changer_driver` to a
  pending future so `changer_view` doesn't treat the work as interrupted.
- **Tool calls** in tests: `tool_reply(name, args)` from
  `tests/studio/conftest.py`; scripted teams switch on the system prompt.
- **Cloud browser**: if Playwright wants a newer headless shell than
  `/opt/pw-browsers` has, run `sh .claude/skills/fcc-engineer/scripts/cloud_setup.sh`.
- **Keys**: a key the owner gives goes in an environment variable for one
  command only, never in a file, commit, log, test or zip. Tell them to
  rotate a key pasted into chat.

## Quality bar for a change

- Does what was asked, end to end (back end, page, phone if it has it).
- A test that would have caught the bug or proves the feature.
- State changes survive restart/retry/pause (the Review focus in CLAUDE.md).
- README `## Studio` and `studio/guide.py` still true.

## Report to the owner (short)

What changed (plain words), checks run with counts, browser flows, previewer
findings and fixes, what is NOT proven (e.g. "pretend AI replies only").
Then the zips if it's a release.

## Scoring the Changer with a real model

Read `references/changer-scorecard.md` only when asked to test how well the
Changer finds bugs, fixes them or builds features.
