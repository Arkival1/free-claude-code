# Plan: Jarvis's PC (a local AI that runs the PC, with a Stop button)

For the owner's laptop (Lenovo Legion Y7000P: i7-9750H, 16 GB, GTX 1660 Ti
6 GB, 256 GB SSD). Jarvis lives there, making games and researching.

## The owner's rules (built into the code)

- **Only Jarvis, the main AI, on the local model, controls the PC.** The PC
  tools (`pc_run`, `pc_files`) are handed out only to the main agent while
  his turn runs on a `local/` model and is not sealed onto a server model.
  They are checked again when a tool runs (`ToolContext.pc_hands`).
- **No other AI agents.** While PC control is on, Jarvis gets no delegation
  tools (`ask_agent`, subagents, `manage_agent`), so at most 3 AIs work: Jarvis
  plus 2 advisers (`MAX_ADVISERS = 2`).
- **Advisers get the web only**: `web_search`, `web_fetch`, `research`,
  `toolshed` (to suggest tools, skills and plugins). They advise and suggest;
  they never act.
- **API models never touch the PC.** An adviser can be switched between an
  API and a local model; either way it stays web-only. If Jarvis himself is
  set to an API model (or LM Studio is off and the server model steps in),
  he has no PC tools that turn.
- **Stop always works**: from any Studio page, over the HUD and over open
  panels, from the phone (signed in), and with Ctrl+Alt+Pause (or
  Ctrl+Alt+S) on a Studio page. Stop kills what he's running and survives a
  restart. Letting him carry on works only from the PC.

## Built (Phase 1, branch `claude/jarvis-pc-control`)

- `studio/pc_control.py`: levels, never-list, risky list, folders, Stop,
  the log (`pc-control.json`, `pc-control-log.jsonl` in FCC's data folder).
- `studio/tools.py`: `pc_run` (a command, in his folders) and `pc_files`
  (list, read, write, append, mkdir, move, delete). Steps that need your OK
  use Studio's usual Approve / Deny cards.
- `studio/agents.py`: who gets which tools (`_pc_view`).
- Settings: **Jarvis Controls This PC** (`STUDIO_PC_CONTROL`, off by default).
- Studio: the red **Stop Jarvis** button and the **PC** panel (level, his
  folders, what he did). Routes under `/studio/api/pc-control`.
- Tests: `tests/studio/test_pc_control.py`, `e2e/test_pc_stop.py`.

**Levels** (kept across restarts; Off until you choose):
- **Off**: no PC tools.
- **Look**: reads files and folders only.
- **Ask**: every change waits for your OK.
- **Full**: works on his own; deleting, moving, installing, running
  programs and scripts, and other risky commands still ask.

**Never, at any level:** Windows' own folders (read only), FCC's code and
keys (`%USERPROFILE%\.fcc`, `trading-keys.vault`), saved passwords and
browser logins, `.ssh`/cloud keys, password managers, formatting or wiping
drives, Windows security and firewall, user accounts, shutting the PC down,
killing FCC itself. Banking and real money stay with the Trading Bank's own
PC-only rules.

## Next phases (each: build, tests, two previewer passes, push, you try it)

2. **Websites, YouTube and Reddit** (owner: "go on YouTube, Reddit, interact
   with the web and websites and games, and learn"). Jarvis gets his own
   browser (Playwright, FCC's own profile, separate from yours): open, read,
   click, scroll, fill, download into his folders. YouTube: watch through
   FCC's video study (transcript + frames), take notes. Reddit: read
   threads and comments. **Ask first**: logging in, posting, commenting,
   voting, messaging, buying, anything with your name on it. Page text is
   data, never orders (fenced in the prompt).
3. **Apps and games.** Cua Driver (vendored, MIT) switched on: list
   windows, open an app, read its controls, click, type, window
   screenshots; a small vision model for screens with no controls (games).
   Playing a game to test it or learn from it; Godot games he makes run
   and get checked the same way.
4. **Learning.** What he learns from the web, videos, Reddit and games goes
   into his own memory (lessons, patterns), searched per job, never all
   read at once; new skills wait for your OK (as FCC Linux's lessons do).
5. **From the iPhone.** The PC panel and Stop on FCC Phone through the PC
   link; start jobs and watch the feed.
6. **Later:** a Windows-wide Stop hotkey (outside the browser), pausing when
   you move the mouse or type, allow-lists and saved routines.

## What can't be promised

- A 4B local model makes mistakes on long, many-app jobs. Ask level is the
  safety net; the 2 advisers help with ideas and checks.
- Some apps and games don't expose their controls; screenshots are slower
  and less accurate.
- Windows security prompts (UAC) can't be clicked by any app. You do those.
