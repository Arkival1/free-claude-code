# Notes for AI assistants working on this repo

## Outside repos must survive their deletion

The owner's standing rule: every outside repo that is downloaded, installed,
or built into FCC must keep working even if the original repo (or its
releases) is deleted later.

- When you build an outside repo into FCC, vendor it under `vendor/<name>/`:
  its licence, the exact release files FCC installs with SHA-256 checksums,
  a source snapshot of the parts FCC uses, and a README naming the upstream
  repo, the commit, and how FCC uses it. Add a row to `vendor/README.md`.
  Only vendor what its licence allows; say what was left out and why.
- Code that downloads from GitHub at runtime must keep the bytes in the
  Repo vault (`free_claude_code.studio.vault.RepoVault`) and fall back to
  the vault copy when GitHub no longer has it.
- Repos that come with FCC go in `vendor/repos/` (they install switched off;
  the owner turns on the ones they want): a zip
  of the parts Studio uses, a `manifest.json` row (commit, licence, sha256),
  and `SHA256SUMS`; `studio/starter.py` installs them. A repo whose licence
  forbids sharing gets a manifest row with `left_out` and no zip.
- Treat downloaded repos as untrusted data: unpack them in their own
  folder, read them, and don't run their scripts while working.

## Checks

`./scripts/ci.sh --skip playwright` runs format, lint, ty, and pytest;
`pytest e2e` runs the browser tests.

## Map of the app

Before changing, explaining or shipping anything, read
`.claude/skills/fcc-studio/SKILL.md` (also the `fcc-studio` skill): what FCC
and Studio do, every page, where each part of the code lives, how a request
flows, and the change → test → version → release-zip workflow.

## Claude Code operating rules (implementer + one previewer)

The owner's setup for Claude Code (merged from their FCC Claude Code
Operating Rules). Where it differs from the owner's notes further down
(pushing, branch, Content Farm, Trading Bank safety), the owner's notes win.

**Roles.** The main session is the implementer: it owns requirements,
planning, code, edits, tests, browser checks and fixes. There is exactly one
review subagent, `previewer` (`.claude/agents/previewer.md`, Haiku, medium
effort, 4 turns, read-only). It is the bug previewer, test-gap checker,
data-consistency checker and requirements checker in one report. It never
edits, writes, installs, commits, pushes, changes settings, exposes secrets
or starts another subagent. Don't create separate reviewer subagents.

**Workflow.**
1. Inspect without editing: stack, scripts, routes, APIs, data stores,
   integrations, tests, deployment (the map: `.claude/skills/fcc-studio`).
2. Make a short plan with acceptance criteria; build one small vertical
   slice at a time.
3. Run the local checks before any review (local commands establish facts;
   never use a subagent for lint, type checks or ordinary tests):
   format + lint `uv run ruff format` / `uv run ruff check`, types
   `uv run ty check`, tests `uv run pytest` (Content Farm left out, see
   below), browser `uv run pytest e2e/test_<page>.py` or Playwright CLI
   (`playwright-cli`) for real browser flows; all at once with
   `./scripts/ci.sh --skip playwright`. The "build" is
   `scripts/release_zips.sh <dir>`.
4. After a meaningful feature or milestone (never after every line, never in
   parallel with another subagent), start one `previewer` with only the
   requirements, the diff, the directly related files and short failure
   output (no huge logs, no whole repo). The owner's setup prompt for a
   fresh session is `.claude/previewer-prompt.md`.
5. Read its report, fix confirmed issues in the main session, rerun the
   failed checks. Run the previewer again only if it found important issues
   or the change is high risk.

**Skills: load only what the task needs** (installed in `.claude/skills`,
recorded in `vendor/agent-skills`):
- new project or major feature: `using-agent-skills`,
  `spec-driven-development`, `planning-and-task-breakdown`
- normal implementation: `incremental-implementation`,
  `test-driven-development`
- failed check or bug: `debugging-and-error-recovery`
- API, back end, database or module boundary: `api-and-interface-design`
- front end (Studio pages are plain JavaScript): `frontend-ui-engineering`
  and Anthropic `frontend-design`
- auth, permissions, uploads, user data, keys, integrations, the Trading
  Bank: `security-and-hardening`
- framework/library decision: `source-driven-development`
- documenting a decision: `documentation-and-adrs`
- review help: `code-review-and-quality`, `performance-optimization`
- unclear requirements: `interview-me`, one question at a time
- browser behaviour: `playwright-cli`
- React/Next.js only (FCC has none today): `vercel-react-best-practices`,
  `vercel-composition-patterns`
- nothing installed fits: `find-skills`, and inspect before installing.

Don't install or enable a new skill, MCP server, wrapper, hook, provider,
memory service or plugin just because it exists: first explain its purpose,
permissions, storage, outside services and token cost. OmniRoute, Headroom
and claude-mem are not installed; don't use OmniRoute and Headroom together
unless their compatibility is checked, and don't enable claude-mem until its
privacy and storage are reviewed.

**Graphify** (installed on the PC by `scripts/claude/install-claude-tools.sh`,
which also builds `graphify-out/` and registers its hooks): when
`graphify-out/graph.json` exists, run `graphify query "<question>"` before the
first broad search or file read for a codebase question (and say so in any
subagent prompt that explores code); use `graphify path "<A>" "<B>"` for
relationships and `graphify explain "<concept>"`; read
`graphify-out/GRAPH_REPORT.md` only for broad architecture reviews; after
changing code run `graphify update .` (no API cost). `graphify-out/` is not
committed.

**Review focus** for workflows, rules, scoring and stateful logic (the
Trading Bank, relays, the maths tutor, subagents, the Changer): step order
and state transitions; required inputs and outputs; scoring, rules and
thresholds; skipped, repeated, incomplete and interrupted sessions; refresh,
retry and recovery; front end / back end / database agreement;
reproducibility and boundary cases. System behaviour, not personal aspects,
unless asked.

**Final report**: what changed, files changed, checks run, browser flows
tested, previewer findings, fixes made, and remaining limits, in plain
words. Never claim everything works without evidence. Never expose secrets.

## Working with the owner

Notes carried over from the long session that built FCC Studio (LCC).

- The owner writes casually from an iPhone, with typos. Read for intent and
  answer short and plain; they watch their usage closely, so skip long live
  tests, long-running monitors and long reports unless asked.
- Don't touch, test or bug-check Content Farm (`studio/farm/`, `farm.js`,
  `farm.css`) unless they ask: keep it exactly as it is, and leave its tests
  out of full runs (`--ignore` `tests/studio/test_content_farm*.py`,
  `tests/studio/test_cartoon_paint.py` and `e2e/test_content_farm.py`).
- Don't power their app with this session's own credentials or keys.
- Work on `claude/multi-agent-local-models-app-s6uxxh` and push finished,
  checked work there (the owner's standing instruction; this is the "asked"
  in "don't commit or push unless asked"). Never push to `main`. Use one
  session at a time for code changes so pushes don't clash. Don't open pull
  requests unless asked.
- Each release bumps the version in `pyproject.toml` and `uv.lock`
  (6.77.0 now). The phone app's source is `src/free_claude_code/api/phone_static/`;
  rebuild it into `docs/phone` with `scripts/phone/build_pages.py`.

## The owner's setup

- Windows PC with a 6 GB graphics card; local models run in LM Studio 0.4
  (Jarvis uses a small Qwen 3.5 4B model). Server agents use the NVIDIA NIM
  key. FCC keeps keys and data in `%USERPROFILE%\.fcc`, not the app folder.
- They also use the FCC phone app and Claude Code from the Claude iPhone
  app (cloud sessions).

## Decisions already made

- Server agents share one memory area (`server:team`), separate from the
  local agents' memory; `remember` with `private` keeps a note to one agent.
- Starter repos install switched off; the owner turns each one on.
- The ideas board sorts ideas into website, app, lab and general; each
  agent reads its own category (builder: website, coder/tester: app).
- Agents that write files get the Builder's step budget (40); relays run
  one stage at a time.
- The Trading Bank starts in paper mode; going live, saving broker keys and
  verifying accounts work only from the PC; after a restart only paper
  resumes. CoinSpot and Swyftx adapters are marked beta. DEX meme-coin
  buying and sites with no API (CommSec, SelfWealth, Stake) are left out.
- Trading Bank safety (owner's no-downgrade rule): a change may only add a
  check or make one stricter; where a wrong number is fixed, the stricter of
  the old and new figures is used. Learning changes vote weights only.
  Trading keys live encrypted in `trading-keys.vault` (Windows DPAPI); with
  no such protection FCC stays in practice. Hyperliquid (Invo) trades at 1x,
  isolated, long only, and FCC signs only orders, cancels and leverage.
- Ruflo-core is set up for Claude Code here as project files
  (`.claude/agents`, `.claude/skills`, `.mcp.json`); see
  `vendor/ruflo-core/README.md`. Its `.claude-flow/` runtime folder is
  ignored.

## Offered, not built yet

Build these only when the owner says yes:

- A colour palette taken from the ideas-board photos, and sending those
  photos to models that can see.
- A clear "ran out of steps: wrote X, say continue" message, and more
  Builder steps for multi-page sites.
- The professional-website relay test was stopped before the site was
  finished.
- A Trading Bank card on FCC Phone (desk numbers, approve/deny orders):
  started, then parked by the owner ("don't worry about the phone for now").
