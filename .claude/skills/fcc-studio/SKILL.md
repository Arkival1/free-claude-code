---
name: fcc-studio
description: Map of FCC and FCC Studio (LCC) - what the app does for the owner, where every part of the code lives, how a request flows through it, and the workflow for changing, testing and releasing it (version bump, phone rebuild, release zips). Use before changing, explaining, testing or shipping anything in this repo.
---

# FCC and FCC Studio (LCC): the map

Read `CLAUDE.md` first (owner's rules and preferences). This page is the map;
the user-facing description of every feature is the `## Studio` section of
`README.md` (about line 357 to 2209). Read the part you are changing.

## What the app is

- **FCC (Free Claude Code)** is a local proxy: Claude Code, Codex, Cline,
  OpenCode, Aider, Claw Code and other coding tools talk to it as if it were
  their usual API, and it forwards to free or cheap providers (NVIDIA NIM,
  Gemini, Groq, OpenRouter, local LM Studio/Ollama/llama.cpp...). It has an
  Admin page for providers, models and settings. Start it with `fcc-server`;
  the launchers (`fcc-claude`, `fcc-codex`, ...) are in `cli/launchers/`.
- **FCC Studio (LCC)** is a multi-agent app served by the same server at
  `/studio`. Jarvis (the main AI) runs a team of agents on local models (on
  the owner's PC) and server models (API providers). It is the owner's main
  project.
- **FCC Phone** is a phone web app (PWA) hosted on GitHub Pages from
  `docs/phone/`. It has its own small team and engine and can pair with the
  PC (PC link) to use the PC's brain and memory.
- **Windows desktop app**: `scripts/windows/` installs a shortcut that starts
  the hidden server and opens Studio in an app window.

## What the owner can do (Studio pages, `#hash` routes)

| Page | What it does |
| --- | --- |
| Home (`#home`, HUD) | Jarvis command center: gold orb, talk/voice (offline Kokoro speech + Whisper), team status, agents at work, agent chat room |
| Chats (`#chats`, `#chat/<id>`, `#room/<id>`) | Chats with one agent, and rooms where several agents talk, hand off and finish tasks |
| Agents (`#agents`, `#agent/<id>`, `#task/<id>`) | Run a task for an agent, add agents (presets, + button, repo agents), Team brains (a model per agent: Test, then Save) |
| Projects / sites (`#site/<id>`) | Websites and apps agents build, with preview, files, history/undo, download zip |
| Ideas board (`#ideas`) | Owner's notes, links, photos, videos for the agents; categories website/app/lab/general |
| Models (`#models`) | Local models: downloads, pick a .gguf from the PC, give each agent its own model |
| Model Control (`#engine`) | Built-in llama.cpp engine (instead of LM Studio): GPU detection, Tune for my PC, speed test |
| Tuning (`#tune`, `#job`, `#lora`) | Light tuning, and LoRA training on a rented GPU that installs the new model |
| Classroom / Learn (`#learn`, `#class/<id>`) | A teacher model teaches a student model; Learn mode where Jarvis studies a topic |
| The Changer (`#changer`, menu) | An agent (server model) that changes a copy of FCC's own files (project "FCC (Changer copy)"), checks it, screenshots it on a spare port, uses helper Changers, and packs update + backup zips (`changer.py`, the `fcc_changer` tool) |
| Maths tutor (`#tutor`, from Learn) | Electrician maths for the owner (NSW licence path): questions made and marked in code (`tutor/topics.py`), progress and tests (`tutor/coach.py`), the AI only explains |
| Lab (`#lab`) | Chemistry, materials, tech and design sandbox with a lab chat; designs drawn in real materials with a physics check (`lab/design.py`), saved parts to reuse |
| Content Farm (`#farm`) | Video channels, scripts, cartoons, beat edits, rendering. Don't touch unless asked |
| HQ (`#hq`) | Pixel office showing the whole agent workflow live |
| Trading Bank (`#trade`) | Five model seats debate trades (Desk with 3D arena and engine health, Debate, Risk, Orders with decision records and audit, Debriefs with learning and backtest, Setup); practice / alert-only / live-approve / live-auto; platforms (Alpaca, IBKR, Kraken, Coinbase, AU exchanges, Hyperliquid/Invo, webhook) |
| Ops (`#ops`, menu) | The PC's load, background worker lanes, busy agents, model queue, desk pulse, with a 3D system pulse |
| Connectors (`#connectors`) | Gmail, GitHub, Zapier and other outside services (tokens owner-only, never sent to the UI) |
| More (`#more`) | Add from GitHub (skills, Claude Code plugins, MCP servers, agents), repo on/off switches, Repo vault, Learning |
| Settings (`#settings`) | Every FCC setting, searchable (keys, models, step limits, Studio, image engine...) |

Other features: memory (each agent's own, a local team memory, and a
server team memory `server:team`), Obsidian mirror of memory, deep research
(web + Reddit + YouTube), desktop browser agents drive, video watching,
image engine (sd.cpp locally or a cloud images API), team plans (one job
split into ordered steps), relays (a local agent, then each fitting repo's
agents in turn), approved shell commands in projects, the OpenAI-compatible
`/v1/chat/completions` endpoint and LCC as an MCP server for other tools.

## Where the code is

```
src/free_claude_code/
  api/            FastAPI app: app.py, routes.py (proxy), admin_*.py (Admin page),
                  studio_routes.py (every /studio/api route), openai_chat.py,
                  team_mcp.py (LCC as MCP server), phone_cors.py
  api/studio_static/  Studio UI: index.html, studio.js (the whole single-page app:
                  router, pages, HUD), studio.css, hq.js/css, lab.js/css,
                  farm.js/css, trade.js/css (Trading Bank), tutor.js/css (maths tutor), changer.js/css (the Changer),
                  ops.js/css (Ops),
                  fcc3d.js (shared 3D engine), trade3d.js and ops3d.js (3D
                  views, loaded only when shown), three.*.js and three-orbit.js
                  (vendored three.js, see vendor/three), sw.js, icons
  api/phone_static/   FCC Phone source (js/agents.js, tools.js, projects.js,
                  polish.js, ...); built into docs/phone
  api/admin_static/   Admin page UI
  studio/         Studio back end (below)
  providers/, core/, application/, runtime/, harnesses/, messaging/, config/,
  cli/            the FCC proxy, provider adapters, settings, launchers
tests/            pytest (tests/studio/ is Studio's, about 80 files)
e2e/              Playwright browser tests (admin_base_url fixture serves an
                  isolated app; studio pages open at f"{admin_base_url}/studio#page")
vendor/           kept copies of outside repos (see CLAUDE.md)
scripts/          ci.sh, phone/build_pages.py, release_zips.sh, windows/, install*
docs/             GitHub Pages: index.html and docs/phone (built phone app)
```

### `studio/` modules

| File | Job |
| --- | --- |
| `service.py` | `StudioService`: the hub every route calls. Chats, agents, tasks, rooms, projects, extensions, starters, ideas, relays, settings |
| `agents.py` | `AgentRunner`: the agent loop (think, call tools, finish), prompts (`AGENT_BASE_PROMPT`, ...), step budget (`step_budget`, Builder 40), last-steps cornering, finish review, stop on repeated failures |
| `tools.py` | `AgentToolbox`: every tool agents call (files, edit, project, search, memory remember/recall, delegate, ideas, mcp, skill, commands...) |
| `llm.py` | `StudioModelRouter`, `ProxyLLM` (server models via FCC), `LocalOpenAILLM` (LM Studio/Ollama/engine), stand-ins, `error_detail` |
| `models.py`, `store.py` | Pydantic records (Agent, Chat, Task, Idea, Extension...) and the SQLite store (`studio.db` in Studio's data folder under `~/.fcc`) |
| `memory.py` | `MemoryService`: per-agent, team and `server:team` memory |
| `crew.py`, `orders.py`, `teamplan.py`, `relay.py`, `rooms.py` | Jarvis hands work out; direct orders from what the user says; team plans; repo relays; chat rooms |
| `extensions.py`, `mcp.py`, `starter.py`, `vault.py`, `connectors.py` | Add from GitHub (skills, plugin agents, MCP servers), MCP client, starter repo pack (installs switched off), Repo vault, connectors |
| `sites.py`, `templates*.py`, `project_check.py`, `polish.py`, `page_try.py`, `commands.py`, `code_loop.py` | Project workspaces, starter templates (`templates_3d.py`: 3d-landing, 3d-dashboard, the FCC web kit; three.js copied in with `copy_library`), checks, design once-over, page tryout, approved commands, Coder/Tester loop |
| `ideas.py`, `photos.py`, `images.py`, `image_engine.py`, `image_cloud.py` | Ideas board, business photos, free photos (Openverse), AI images |
| `research.py`, `search.py`, `platforms.py`, `videos.py`, `video_ears.py`, `desk.py`, `connectivity.py` | Web research, search, Reddit/YouTube, video notes, desktop browser, online check |
| `engine*.py`, `downloads.py`, `model_*.py`, `gguf_info.py`, `team_models.py` | Built-in engine, model downloads, model files, Team brains |
| `tuning.py`, `lora.py`, `lora_worker.py`, `school.py`, `learning.py` | Tuning, LoRA, classroom, Learn mode |
| `guide.py` | The in-app Guide's knowledge of every page and setting. Keep it in step with features |
| `playbook.py`, `call_guard.py`, `presets.py` | Jarvis's tool notes, small-model call guard, agent presets |
| `voice.py`, `local_voice.py`, `obsidian.py`, `phone_link.py`, `hq.py`, `lab/`, `farm/` | Voice, Obsidian mirror, phone pairing, HQ, Lab, Content Farm |
| `changer.py` | The Changer: `Changer` (copy of the app, baseline hashes, changes/diffs, checks, screenshots of the copy run with an empty HOME and no key env vars, update and backup zips); glue in `service.py` (`changer_*`, `_changer_tool`, `_changer_helper`) |
| `tutor/` | The maths tutor: `topics.py` (28 topics, each question made from a seed and solved step by step in code), `coach.py` (`Tutor`: marking, `TutorAttempt` progress, practice tests, AI explanations), `pathway.py` (NSW licence path and sources) |
| `trading/` | The Trading Bank: `desk.py` (`TradingDesk`: the loop, debates, risk period, routing, approvals, protection, views), `debate.py` (four rounds; `breaks.py` research/brainstorm, `simulate.py`), `contract.py` (checked seat answers), `seats.py`, `briefing.py`, `information.py`/`quality.py`/`news.py` (data checks), `evidence.py` (numbered evidence pack), `infotest.py` (information stress test), `assessment.py` (risk period), `stress.py` (investment stress test), `engine.py`/`scorecard.py`/`conflicts.py`/`regime.py` (decision layer), `decisions.py` (decision records, audit trail), `protection.py` (circuit breaker, kill latch), `fills.py` (practice fills), `positions.py` (position manager), `worker.py` (lease, step health, job retries, metrics), `learning.py` (versioned vote weights), `backtest.py`, `keyvault.py` (encrypted keys), `hlsign.py` (Hyperliquid signing), `risk.py` (hard limits), `precheck.py` (account check), `forecasts.py`, `debrief.py`, `ledger.py` (FIFO, AU tax CSV), `scanner.py`, `patterns.py`, `indicators.py`, `sessions.py` (ASX/NY hours), `data.py` and `providers/` (Yahoo, CoinGecko, DexScreener, Coinbase/Kraken books, news, Hyperliquid), `brokers/` (paper, Alpaca, IBKR, Kraken, Coinbase, BTC Markets, Independent Reserve, CoinSpot, Swyftx, Hyperliquid/Invo, webhook; `registry.py`, `catalog.py`, `common.py` with the no-money-moves guard), `config.py`, `log.py` |
| `workers.py`, `resilience.py`, `jsonish.py`, `system_monitor.py` | Background lanes (`WorkerPool`), retries/rate limits/circuit breakers/`submit_once`, forgiving JSON reading, CPU/RAM/GPU readings |

## How a request flows

UI (`studio.js`) calls `/studio/api/...` in `api/studio_routes.py`, which
calls `StudioService`. Agent work runs in `AgentRunner` (`agents.py`): each
step asks `StudioModelRouter` (`llm.py`) for a reply with the agent's tools
(`tools.py`), runs the tool calls, and repeats until the agent finishes or
runs out of steps. Results land in the store and stream back to the page.
Settings and keys live in `~/.fcc/.env` (`%USERPROFILE%\.fcc` on Windows);
`config/` reads them.

## How to change something (the workflow used so far)

1. Read the code and the README part first. Ask only if the owner's intent
   is unclear.
2. Change the back end and the UI together; if the phone app has the same
   feature, change `api/phone_static/` too and rebuild `docs/phone` with
   `python scripts/phone/build_pages.py`.
3. Add or update tests: `tests/studio/test_*.py`, and an `e2e/test_*.py`
   for UI behaviour.
4. Keep the docs true: README `## Studio` section and `studio/guide.py`.
5. Run `./scripts/ci.sh --skip playwright` (format, lint, ty, pytest) and
   the e2e tests you touched (`pytest e2e/test_x.py`). If the container's
   `uv` is too old, use `.venv/bin/python -m pytest`. Don't mix Playwright
   and asyncio tests in one pytest run. A test that fails only under load
   can be re-run once; a second failure is real.
6. For a release, bump `version` in `pyproject.toml` and the
   `free-claude-code` entry in `uv.lock` (same number).
7. Commit with a clear message, push to the owner's branch.
8. To hand the owner a build: `scripts/release_zips.sh <scratchpad dir>`
   makes `FCC-Studio-<version>.zip` plus `-partN` zips (each under 25 MB);
   send them all. The owner unzips every one into the same folder.

Rules that bite: no `# type: ignore` (CI bans suppressions); outside repos
follow CLAUDE.md's vendoring rules; connector tokens stay owner-only and
are never returned to the UI.
