# Starter repos

The outside repos FCC Studio ships ready to use. On first load Studio adds
each one like an **Add from GitHub** link, so every agent can search and
read its skills, guides and lists with the `skill` tool. They are also kept
in the **Repo vault** on the PC.

Each zip here holds only the parts Studio uses, cut from the upstream repo
at the commit below. That means:

- every `SKILL.md` folder, with its text, scripts and references (files
  up to 400 KB),
- Markdown and text guides up to 1.5 MB,
- Claude Code plugin manifests and `.mcp.json`,
- the repo's licence.

Images, videos, binaries, `node_modules`, translations and app source code
are left out. `SHA256SUMS` lists every zip's checksum. Studio checks it
before installing and won't install a damaged copy.

It is all read-only data. Studio unpacks a repo into its own folder and
reads it, and nothing in it runs. MCP servers from these repos (hindsight,
paperclip, openviking, agentmemory) start **switched off**; the user turns
each one on after seeing its command. Agents in them (paperclip, OpenMontage,
langflow) join the team only when the user clicks **Add to team**. Removing
a starter repo sticks, and **Repos that come with FCC** on the More page
adds it back.

| Repo | Commit | Licence | Copy here | What it gives the team |
| --- | --- | --- | --- | --- |
| [OpenHands/openhands](https://github.com/OpenHands/openhands) | `b0a1a2d136` | MIT | `OpenHands__openhands.zip` (0.15 MB) | AI software engineer platform: its agent skills and guides. |
| [florinpop17/app-ideas](https://github.com/florinpop17/app-ideas) | `9e8dd00f10` | MIT | `florinpop17__app-ideas.zip` (0.11 MB) | Hundreds of app ideas by level, to practise building. |
| [nilbuild/developer-roadmap](https://github.com/nilbuild/developer-roadmap) | `2282f21b6f` | roadmap.sh licence (personal use only) | not shipped (see below) | roadmap.sh: step-by-step developer roadmaps. |
| [ossu/computer-science](https://github.com/ossu/computer-science) | `33d44a44e3` | MIT | `ossu__computer-science.zip` (0.06 MB) | A free, self-taught computer science degree path. |
| [vectorize-io/hindsight](https://github.com/vectorize-io/hindsight) | `9269b88417` | MIT | `vectorize-io__hindsight.zip` (4.06 MB) | Hindsight agent memory: docs, skills and integrations. |
| [google/ax](https://github.com/google/ax) | `ac2332829f` | Apache-2.0 | `google__ax.zip` (0.02 MB) | Google AX: agent experience guides. |
| [paperclipai/paperclip](https://github.com/paperclipai/paperclip) | `0fe47882cf` | MIT | `paperclipai__paperclip.zip` (3.51 MB) | Paperclip: running teams of AI agents; skills and docs. |
| [stablyai/orca](https://github.com/stablyai/orca) | `842c6c667a` | MIT | `stablyai__orca.zip` (1.37 MB) | Orca: AI agent workspace; skills and docs. |
| [agent-substrate/substrate](https://github.com/agent-substrate/substrate) | `601c03ba59` | Apache-2.0 | `agent-substrate__substrate.zip` (0.47 MB) | Substrate: agent runtime; skills and docs. |
| [calesthio/OpenMontage](https://github.com/calesthio/OpenMontage) | `9327439db6` | AGPL-3.0 | `calesthio__OpenMontage.zip` (4.08 MB) | OpenMontage: AI video production skills and pipelines. |
| [leonxlnx/taste-skill](https://github.com/leonxlnx/taste-skill) | `ce26fc25c0` | MIT | `leonxlnx__taste-skill.zip` (0.16 MB) | Taste skills: anti-slop design rules for premium frontends. |
| [aishwaryanr/awesome-generative-ai-guide](https://github.com/aishwaryanr/awesome-generative-ai-guide) | `45f73c38d3` | MIT | `aishwaryanr__awesome-generative-ai-guide.zip` (1.76 MB) | Generative AI guide, incl. the free agentic AI crash course. |
| [volcengine/OpenViking](https://github.com/volcengine/OpenViking) | `10f368145f` | AGPL-3.0 | `volcengine__OpenViking.zip` (2.46 MB) | OpenViking: context database for agents; skills and docs. |
| [ai-boost/awesome-harness-engineering](https://github.com/ai-boost/awesome-harness-engineering) | `7a88f06b91` | CC0-1.0 | `ai-boost__awesome-harness-engineering.zip` (0.09 MB) | Curated list on agent harness engineering. |
| [mukul975/anthropic-cybersecurity-skills](https://github.com/mukul975/anthropic-cybersecurity-skills) | `54a798831d` | Apache-2.0 | `mukul975__anthropic-cybersecurity-skills.zip` (8.78 MB) | Hundreds of defensive security skills (read-only guides). |
| [cathrynlavery/diagram-design](https://github.com/cathrynlavery/diagram-design) | `d137637196` | MIT | `cathrynlavery__diagram-design.zip` (1.38 MB) | Diagram design skill: clear, good-looking diagrams. |
| [k-dense-ai/scientific-agent-skills](https://github.com/k-dense-ai/scientific-agent-skills) | `92ace75ac2` | MIT | `k-dense-ai__scientific-agent-skills.zip` (8.14 MB) | Scientific agent skills: biology, chemistry, data, papers. |
| [rohitg00/agentmemory](https://github.com/rohitg00/agentmemory) | `007a1a7fe8` | Apache-2.0 | `rohitg00__agentmemory.zip` (1.84 MB) | agentmemory: persistent memory for coding agents. |
| [steven2358/awesome-generative-ai](https://github.com/steven2358/awesome-generative-ai) | `3e16ff8a97` | CC0-1.0 | `steven2358__awesome-generative-ai.zip` (0.04 MB) | Curated list of generative AI tools and projects. |
| [usestrix/strix](https://github.com/usestrix/strix) | `f1386cad37` | Apache-2.0 | `usestrix__strix.zip` (0.42 MB) | Strix security-testing agent: its skills as read-only guides. |
| [public-apis/public-apis](https://github.com/public-apis/public-apis) | `874e5879d2` | MIT | `public-apis__public-apis.zip` (0.10 MB) | A big list of free public APIs. |
| [ripienaar/free-for-dev](https://github.com/ripienaar/free-for-dev) | `a7fadd2734` | no licence file | not shipped (see below) | Free tiers for developers: hosting, APIs, tools. |
| [langflow-ai/langflow](https://github.com/langflow-ai/langflow) | `f9b283243d` | MIT | `langflow-ai__langflow.zip` (4.04 MB) | Langflow: visual AI workflow builder; skills and docs. |
| [supermemoryai/supermemory](https://github.com/supermemoryai/supermemory) | `58ef43ba5c` | MIT | `supermemoryai__supermemory.zip` (0.44 MB) | Supermemory: memory API for AI; skill and docs. |
| [letta-ai/letta](https://github.com/letta-ai/letta) | `5bcdd177d7` | Apache-2.0 | `letta-ai__letta.zip` (0.02 MB) | Letta (MemGPT): stateful agents with memory; overview. |
| [letta-ai/letta-code](https://github.com/letta-ai/letta-code) | `4b028fab07` | Apache-2.0 | `letta-ai__letta-code.zip` (0.45 MB) | Letta Code: where Letta's code lives now; skills and docs. |
| [ultraworkers/claw-code](https://github.com/ultraworkers/claw-code) | `08106b0c37` | MIT | `ultraworkers__claw-code.zip` (0.69 MB) | Claw Code: open agent harness; docs and plugins. |
| [Anil-matcha/AI-Youtube-Shorts-Generator](https://github.com/Anil-matcha/AI-Youtube-Shorts-Generator) | `a57bb938ba` | MIT | `Anil-matcha__AI-Youtube-Shorts-Generator.zip` (0.01 MB) | Auto-clip: turn long videos into Shorts (from the auto-clip topic). |
| [milanm/DevOps-Roadmap](https://github.com/milanm/DevOps-Roadmap) | `d7499e6dab` | Apache-2.0 | `milanm__DevOps-Roadmap.zip` (0.02 MB) | DevOps roadmap (from the developer-roadmap topic). |
| [rudra496/devroadmaps](https://github.com/rudra496/devroadmaps) | `104d7bc31f` | MIT | `rudra496__devroadmaps.zip` (0.02 MB) | Developer roadmaps in Markdown (from the developer-roadmap topic). |

## Left out, and why

- **nilbuild/developer-roadmap** (roadmap.sh): its licence allows personal
  use only and forbids sharing its content outside the repo, so FCC does
  not ship a copy. Studio adds it from GitHub on first load, for the user's
  own use, and keeps that download in the Repo vault on their PC. From then
  on it survives the repo being deleted.
- **ripienaar/free-for-dev**: the repo has no licence file, so FCC may not
  redistribute it. It is handled the same way: added from GitHub on first
  load and kept in the Repo vault.
- **letta-ai/letta** now only points to **letta-ai/letta-code**, where
  Letta's code lives, so both are included.
- The GitHub topic pages (`auto-clip`, `developer-roadmap`) are lists, not
  repos. From them FCC ships the repos picked from those pages:
  Anil-matcha/AI-Youtube-Shorts-Generator (auto-clip),
  milanm/DevOps-Roadmap and rudra496/devroadmaps (developer roadmaps).
- The awesome-generative-ai-guide link pointed at its free agentic AI crash
  course. The whole guide is shipped, and the course is in
  `free_courses/agentic_ai_crash_course/`.

## Updating

Clone the repo into its own folder (don't run anything in it), keep the
same parts, zip them under one top folder named `<repo>-<commit7>/`, and
update `manifest.json` (commit, sha256, size) and `SHA256SUMS`.
`tests/studio/test_starters.py` checks every row.
