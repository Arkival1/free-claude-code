# PocketPal + FCC Phone: iPhone test (pending, needs the real phone)

Status: **pending**. Browser tests cover the page, the reply checks, the
tools, approvals and the reload (`e2e/test_fcc_phone_pocketpal.py`); only a
real iPhone can show PocketPal answering and Shortcuts handing the reply
back. Do this after the PR is merged (or on a preview of this branch).

## A. Share Sheet route (no copy and paste)

1. Shortcuts app → + → name it **FCC PocketPal**. In its settings (ⓘ) turn on
   **Show in Share Sheet**; receive **Safari web pages** only.
2. Add **Run JavaScript on Webpage**; input **Shortcut Input**; script (also
   on FCC Phone → More → PocketPal → Set up):
   `var p = window.fccPocketPal ? window.fccPocketPal.prompt() : (document.getElementById('prompt') || {}).value; completion(p || '');`
3. Add **Ask Pal**: your Pal (Jrives); Message = **JavaScript Result**.
4. Add **Base64 Encode** on the Ask Pal result; Line Breaks: **None**.
5. Add a second **Run JavaScript on Webpage**; input **Shortcut Input**
   (the same Safari page); paste the second script and replace
   `[Base64 Encoded]` with the **Base64 Encoded** variable chip.
6. Safari → https://arkival1.github.io/free-claude-code/phone/#pocketpal →
   **Website prompt** → **Start task**.
7. Share → **FCC PocketPal**. Wait for PocketPal.
8. Expected: FCC shows **What Jarvis did → Done** and "Saved … to Projects",
   with the preview; **Open in Projects** opens it. If PocketPal asked for a
   tool instead, the state reads **Waiting** (or **Approve?**): approve if
   asked, then Share → FCC PocketPal again for the next step.

## B. Clipboard route (fallback)

1. Shortcut **FCC PocketPal**: Get Clipboard → Ask Pal (Message: Clipboard)
   → Copy to Clipboard.
2. FCC → More → PocketPal → start a task → **Copy prompt** → **Run shortcut**.
3. Back in Safari → **Paste** (allow) → **Run FCC step**.
4. Expected as in A.8.

## Record

- iPhone model / iOS / browser:
- Route A result (screenshot of What Jarvis did):
- Route B result:
- A short website and a small game: saved, preview works?
- Any error text shown:
