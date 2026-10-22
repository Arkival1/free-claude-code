---
name: app-developer-engineer
description: How to build an app or tool that works and keeps working - a short spec, clear structure, one source of truth for state, every error handled, safe input and output, a usable interface, real tests, and a README, checked before finishing.
---

# App developer engineer

Work in this order. Each step has a rule you can check.

1. **Spec first.** In a few lines: who uses it, the main things they do
   (the flows), the data it keeps, and the edge cases (empty, too long,
   offline, wrong input). Plan the steps with `update_plan`, one working
   slice at a time (each slice runs end to end).
2. **Structure.** Keep the interface, the logic and the data/IO apart
   (separate files or modules). Small functions named for what they do.
   Settings in one place; secrets from environment variables, never in
   code. No dead code, no copies of the same logic.
3. **State and data.** One source of truth for each piece of state. Check
   every input where it comes in (forms, files, APIs). The interface shows
   loading, empty and error states, not a blank screen. Saved data has a
   version so it can be upgraded later; saving twice does no harm.
4. **Errors.** Never swallow an error. Show the person a plain message and
   what to do; keep the details in the log. Network calls get a timeout and
   a retry with a short wait.
5. **Safety.** Put text on the page with `textContent`, not `innerHTML`.
   Database queries use parameters. Uploads are checked for type and size.
   File paths stay inside the app's folder. No `eval`. Ask before deleting,
   or offer undo.
6. **Interface.** Use the website design engineer's design system (palette,
   type, spacing in `:root`). Everything works with the keyboard, labels on
   every field, it fits a phone screen, buttons are at least 44px tall.
7. **Tests that run the real code.** Unit tests for the logic and one test
   of the main flow, importing or calling the real functions (never a test
   that re-does the sums itself). Run them with `test_code` or
   `run_command` and fix until they pass. Every bug fixed gets a test.
8. **Speed.** No repeated queries in a loop, debounce typing, page long
   lists, load heavy parts only when needed.
9. **Delivery.** A README: what it does, how to install, run and test it,
   and its settings. Pinned dependencies (`package.json`, `pyproject.toml`
   or `requirements.txt`). No errors in the console when it runs.
10. **Before finishing.** Run `check_project`, run the tests and the app
    itself (`try_page` and `look_page` for its pages), fix everything they
    show, then say what you built, how you checked it, and anything left to
    do. A focused edit can go to `aider` (task + files) as a draft; check
    its work like your own.
