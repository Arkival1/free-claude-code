# Handover: FCC Phone local models (for ChatGPT or the next AI)

Repo: `Arkival1/free-claude-code`, branch `claude/multi-agent-local-models-app-s6uxxh`
(never push to `main`; PR #1 is the owner's merge PR, PR #2 is review-only).
Read `CLAUDE.md` first: it holds the owner's rules (Content Farm hands off,
Trading Bank no-downgrade rule, vendoring rules for outside code, no keys
in files, short plain answers).

FCC Phone is a plain-JavaScript web app (no build step):
source `src/free_claude_code/api/phone_static/`, published copy `docs/phone/`
(rebuild with `uv run python scripts/phone/build_pages.py` after every change;
GitHub Pages serves https://arkival1.github.io/free-claude-code/phone/).

## The owner's goal

Run 2B–4B AI models **on their iPhone** inside FCC Phone, at about 5–10
words a second, with Jarvis (the main agent) able to chat and use his tools,
and nothing private leaving the phone. The owner's phone: iOS 18.5 (model
not given yet), uses Chrome on iOS, which is WebKit underneath.

## What happened (7 Nov 2026)

1. **The first engine (wllama, llama.cpp in WebAssembly, `js/engine.js`)
   copies the whole model file into the web page's memory.** On the owner's
   iPhone the page gets about 1 GB, so a 1.2 GB Qwen3.5-2B file closed the
   app ("Can't open this page" = iOS killed the tab).
2. **Crash safety (done, pushed):** when iOS closes the app mid-load, FCC
   notes it and makes the model lighter next time (context 2,048, then no
   graphics chip); at its lightest it's marked *too big*, agents stop using
   it (they switch to another phone model or the cloud key), Models shows
   "Try again", and suggestions only name models clearly smaller
   (`tooBig`, `usable`, `suggestions`, `likelyFits` in `js/engine.js`).
3. **Second engine (done, pushed): WebLLM 0.2.87 (`js/webgpu.js`, vendored in
   `vendor/web-llm/` with SHA-256 sums).** It puts the weights in the
   graphics chip's memory through WebGPU, which is how 3B–4B can fit.
   Models offers: Qwen3 4B, Qwen2.5 3B, Qwen3.5 2B, Qwen3 1.7B (all "graphics
   chip"), pinned to Hugging Face commits; f16 or f32 picked by the chip.
   Jarvis's tools go in the prompt in Qwen's `<tool_call>` format
   (`toMessages` / `fromReply`).
4. **Qwen3.5 2B small file (done):** a 3-bit GGUF (0.93 GB) for the first
   engine, for phones without WebGPU.
5. **Temperature (done):** Models → Settings → Temperature slider (0–1.5),
   used by both engines.
6. **Context (done):** Jarvis's tool list was ~6,000 tokens, so 4K–8K ran
   out. Now phone models get compact tool descriptions, oldest turns are
   dropped, the biggest optional tools (lab, linux, godot…) sit a turn out
   if needed, and only then does it ask for a bigger context
   (`fitToContext`, `compactTools`, `CORE_TOOLS`). Contexts up to 32,768.
7. Also fixed today: website-vs-game pick from the words typed, Linux file
   sync edge cases, Playground "unfinished" status, CodeRabbit turned off.

Tests: `e2e/test_fcc_phone.py` (20 tests incl. graphics-chip ones),
`e2e/test_fcc_phone_playground.py`, `tests/studio/test_phone_pages.py`.
Run browser tests with `uv run pytest e2e/<file> -n 0`; don't mix e2e and
`tests/` in one run (event-loop clash).

## Not done / needs sorting

1. **WebLLM has never run for real.** Tests use a stand-in
   (`window.fccWebLLM` in `FAKE_WEBLLM`). The cloud session's safety check
   blocked running WebLLM's downloaded code. Next step: on a machine with a
   browser and WebGPU, open the phone app, download "Qwen2.5 3B (graphics
   chip)", say hi, and fix whatever the real library complains about.
   Likely spots: `webgpu.js` `appConfig` (model URL with `/resolve/<sha>/`,
   `model_lib` absolute URL), WebLLM rejecting message order (we merge
   same-role turns and end on a user turn), Qwen3.5's stop tokens.
2. **Real speed on the iPhone is unknown.** Models → Test speed shows it.
   Expect ~5–10 tokens/s for 3B–4B on iPhone 15 Pro/16 class; older or 6 GB
   phones may not fit the 4B at all (crash safety then marks it too big).
3. **iOS 18.5 needs WebGPU switched on:** Settings → Apps → Safari →
   Advanced → Feature Flags → WebGPU, and the app must be opened in
   **Safari** (Chrome's WebView doesn't get the flag). iOS 26 has it on.
   The Models page says this when WebGPU is missing.
4. **Tool compaction is only ~30% smaller.** Bigger win: shorter tool
   schemas written for phone models (fewer parameters for `lab`, `web_kit`,
   `linux`), or a per-job tool list.
5. **Owner decisions still open (security, FCC Linux):** follow redirects
   only for package/GitHub hosts (1a, recommended) or none (1b); ask before
   the GitHub token reads an unapproved repo (recommended yes).
6. The bottom tab bar lets page text show through faintly in screenshots
   (`phone.css` `.tabs` background is 0.97 alpha); maybe make it opaque.
7. PR #1 waits for the owner to merge; no release zip/version bump was made
   for today's changes (version is 6.114.0 in `pyproject.toml`/`uv.lock`).
