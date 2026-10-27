---
name: code-review
description: How to review someone else's change - read the diff and the code around it, check it against what was asked, confirm each problem with evidence (a test run or a page try), and report only confirmed problems with where and how to fix them.
---

# Code review

1. **Know the goal.** Read what the owner asked and what this step was
   meant to do. A change that works but doesn't do what was asked fails.
2. **Read the diff, then around it.** Read every changed line, then the
   callers and the code next to it: the bug is often in what the change
   didn't update.
3. **Check, in this order:**
   - Correct: right results, edge cases (empty, zero, one, many, very
     long, wrong type, missing), off-by-one, async calls awaited.
   - State and steps: the order things happen, what happens after a
     retry, a restart, a pause or a half-finished run.
   - Front end, back end and stored data agree: names, fields, routes.
   - Errors: shown plainly, never swallowed; nothing hides a failure.
   - Safety: no keys in files or logs, input checked, paths stay inside
     their folder, no `eval`/`innerHTML` with outside text, safety checks
     never weakened (the Trading Bank only gets stricter).
   - Tests: they call the real code and would fail if it broke.
   - Tidy: matches the code around it, no dead code or copies.
4. **Confirm before you fail it.** For each problem find evidence: run the
   test (`fcc_changer tests`), use the page (`fcc_changer try`), or quote
   the exact lines and the input that breaks them. Unconfirmed worries go
   in notes, not findings.
5. **Report.** Verdict pass or fail. Each finding: the problem, where (file
   and line), the evidence, and the fix. Short and concrete; no style
   opinions as failures.

More skills when needed (skill tool, read by name): security-and-hardening, performance-optimization.
