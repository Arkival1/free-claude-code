---
name: vibe-coding
description: How to turn a loose idea into working software quickly without breaking things - one-line goal and checks, the smallest slice that runs, run after every change, read errors exactly, helpers for drafts, and proof before saying done.
---

# Vibe coding (fast, but it has to work)

1. **Goal in one line, then the checks.** Write what the person wants in
   one sentence and 2-4 checks that prove it works ("typing 50 shows
   $57.50"). Plan with `update_plan`. Ask one question only if you truly
   can't guess; otherwise pick the sensible default and say so.
2. **Smallest slice that runs.** Get one path working end to end first
   (the page loads, the button does the main thing), then add the rest one
   slice at a time. Never write everything and test at the end.
3. **Run it after every change.** Use the check that fits: `test_code` or
   `run_command` for code, `try_page` for a page, `check_project` for the
   project, `fcc_changer check`/`tests`/`try` in the Changer copy.
4. **Read the error exactly.** Copy the first real error line, find the
   file and line, read the code around it, then fix the cause. Don't guess
   twice at the same error: after two misses, use the debugging skill.
5. **Match what's there.** Read the code you change and follow its style,
   names and structure. Edit with `edit_file`; whole files only when new.
   Complete code only: no placeholders, TODOs or "rest stays the same".
6. **Helpers for drafts.** A focused edit across a few files can go to
   `aider` (task + files), a separate part to a helper. Their work is a
   draft: read it and run the checks as if you wrote it.
7. **See it.** When you made or changed a page, look at it (`look_page`
   or `fcc_changer look`), fix what looks wrong, look again (3 rounds max).
8. **Done means proven.** Finish only when every check from step 1 passes.
   Say what you built, the checks you ran and what they showed, and
   anything not done. Never say it works without a run that shows it.

For careful edits to existing code, also follow `karpathy-guidelines`
(think first, simplest change, touch only what you must, verify).

More skills when needed (skill tool, read by name): test-driven-development, incremental-implementation, verification-before-completion.
