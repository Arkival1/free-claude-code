# Plan: FCC mobile on the PC, with a local AI that can run the whole PC

Status: **plan only, nothing built**. Waiting for the owner's go-ahead and
the decisions at the end.

## The goal

Open the mobile version of FCC on the PC (FCC Studio already serves it at
`/phone/`) or on the iPhone through the PC link. Jarvis thinks with the
**local model** (LM Studio on the PC), and can **control the PC**:

- run commands and programs (PowerShell)
- read and write files and folders
- use other apps (click, type, read what's on screen)
- browse websites in a real browser (search, read, fill forms)
- use FCC's own tools, skills, plugins and MCP servers

You watch it work live, approve anything risky, and can stop it at any moment.

## What FCC already has to build on

| Part | Where | Use |
| --- | --- | --- |
| Mobile FCC served by the PC | `api/phone_static`, `/phone/` | the screen you drive it from, on the PC or the phone |
| Phone ↔ PC link | `studio/phone_link.py`, `/studio/api/phone/*` | control and approve from the iPhone |
| Local model | LM Studio (Qwen 3.5 4B on the 6 GB card), `studio/llm.py` | the brain; prompts stay on the PC |
| Agent tool loop, tools, skills, plugins, MCP | `studio/agents.py`, `tools.py`, `builtin_skills/`, `mcp.py` | files, web search, fetch, memory, skills |
| Cua Driver (MIT, vendored, not switched on) | `vendor/cua/` | controls Windows apps in the background: reads the window's controls (UI Automation), clicks and types without stealing your mouse, takes window screenshots |
| Playwright | already used for page checks (`page_try.py`) | a real browser the AI drives |

## How it would work

1. **The brain.** By default it's the local model in LM Studio, using its
   tool calls. Reading the screen uses the window's text (UI Automation),
   so no vision model is needed for most apps. For pictures-only screens, a
   small vision model (for example Qwen2.5-VL 3B) looks at a screenshot.
2. **The hands** (new `studio/pc_hands.py`, a set of tools for agents):
   - `pc_run`: run a PowerShell command, return its output; time limit, no
     interactive prompts.
   - `pc_files`: list, read, write, move and delete in the folders you
     approve.
   - `pc_apps`: list windows, open an app, read a window (its controls as
     text), click, type, press keys, take a window screenshot (Cua Driver).
   - `pc_browser`: open a page, read it, click, fill, download, in FCC's own
     browser profile (separate from yours; you log in yourself when needed).
   - Everything FCC agents already have: web search, fetch, memory, skills,
     plugins, MCP.
3. **The control panel** (new screen in mobile FCC, "PC control"):
   - an On/Off switch and the level (below)
   - a live feed of every step, with what it saw (screenshot or text)
   - Approve / No for waiting steps
   - a big **Stop** button
4. **The job loop.** You give a job ("tidy my Downloads by type", "find the
   cheapest RTX 4060 and put links in a note"). Jarvis plans the steps, does
   them one at a time and checks each result. It retries a failed step up to
   3 times, then stops and tells you.

## Safety (it controls your PC, so this part is not optional)

**Levels, set by you:**
- **Off** (the default after every restart).
- **Look**: read only. Screenshots, read files in approved folders, read
  windows, browse.
- **Ask**: it can do anything allowed, but every step that changes
  something waits for your Approve, showing exactly what it will do (the
  command, the click, the file).
- **Trusted**: safe steps you've allow-listed run on their own (open apps,
  browse, write inside project folders). Risky steps still ask.

**Always asks, at every level:**
- deleting files
- installing or uninstalling
- running a downloaded script
- sending messages or emails
- posting online
- logging in
- anything to do with money

**Never allowed:**
- FCC's keys and vaults (`%USERPROFILE%\.fcc` secrets, `trading-keys.vault`)
- password managers and browser password stores
- banking and real-money trading. The Trading Bank keeps its own PC-only
  approvals (the no-downgrade rule).
- Windows security settings, UAC prompts, antivirus
- formatting or partitioning drives
- changing FCC's own safety code

**Stop and logs:**
- **Stop anywhere**: the Stop button, a global hotkey (Ctrl+Alt+Pause), or
  the phone. It pauses as soon as you move the mouse or type.
- **Everything is logged**: each step, what it saw, what it did and who
  approved it, kept on the PC so you can replay it.

**Text from websites, files and apps is data, never orders.** It's fenced
off in the prompt, so a web page can't tell Jarvis to do something.

**Limits:** a step budget and a time limit per job. Only one job runs at a
time.

## Phases (each: build → tests → two previewer passes → push → you try it)

1. **Look + Ask, with commands and files.**
   - `pc_run` and `pc_files` in approved folders
   - the PC control panel, Stop button and hotkey
   - levels Off, Look and Ask
   - the audit log
2. **Apps.** Cua Driver switched on: read windows, click, type, window
   screenshots. Approvals show the target control.
3. **Websites.** FCC's own browser profile; read, click, fill and download,
   with logins done by you.
4. **Trusted level.** Allow-lists, saved routines, and FCC's skills, plugins
   and MCP inside PC jobs.
5. **From the iPhone.** Start jobs, watch the feed and approve or stop
   through the PC link.

## What can't be promised

- A 4B local model will make mistakes on long, many-app jobs. Simple and
  medium jobs are realistic; big ones are where Ask mode matters. A bigger
  model, or the NVIDIA server model as an adviser, helps.
- Some apps don't expose their controls (games, some custom apps). For
  those it falls back to screenshots, which is slower and less accurate.
- Windows security prompts (UAC) can't be clicked by any app. You do those.

## Decisions for you

1. **Brain:** local model only (private), or may the NVIDIA server model
   step in when LM Studio is off?
2. **Approved folders** to start with, e.g. `Documents\FCC`, `Downloads`, or
   others.
3. **Start with Phase 1** (commands and files), or go straight to Phase 2
   (apps)?
4. **The Stop hotkey:** is Ctrl+Alt+Pause fine?
