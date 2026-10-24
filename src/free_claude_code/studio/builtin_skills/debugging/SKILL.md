---
name: debugging
description: How to find and fix the real cause of a bug - reproduce it, read the whole error, narrow down where, test one guess at a time, fix the cause not the symptom, add a test that would have caught it, and check nothing else broke.
---

# Debugging

1. **Reproduce first.** Make the bug happen on purpose: run the failing
   test (`fcc_changer tests`, `test_code`, `run_command`) or do the steps on
   the page (`try_page`, `fcc_changer try`). No reproduction, no fix: say
   what you tried.
2. **Read the whole error.** The exception type, the message, and the
   deepest line of the trace that is in this project's code. Note what was
   expected and what happened instead.
3. **Look up a twin.** With `bug_library` (find, then get), read a real bug
   like this one from another project: its cause, its fix and the test that
   proved it. Use the pattern, not the code.
4. **Narrow down where.** `search_files` for the function, the message
   text or the element id; read those lines and their callers. Follow the
   data: where it comes in, where it changes, where it goes wrong.
5. **One guess at a time.** Write the guess in one line ("the total skips
   the last row because the slice ends at -1"), then check it with the
   smallest test or a print of the value. Wrong? Cross it off and pick the
   next. After three misses, list your assumptions, check each one, and
   ask the Researcher with the exact error.
6. **Fix the cause.** Change the code that makes the wrong value, not the
   place that shows it. No try/except that hides the error, no special case
   for the one input that failed, no turning a check off.
7. **Prove it.** Add a test that fails without the fix and passes with it.
   Run it, then the tests around it, so nothing else broke.
8. **Look for twins.** `search_files` for the same pattern elsewhere and
   fix those too, or list them.
9. **Report.** The cause in one sentence, the fix, the test, and the runs
   that show it works.
