# Agent skills for Claude Code (FCC setup)

Claude Code skills installed into this repo for the owner's FCC Claude Code
setup (see the "Claude Code operating rules" in `CLAUDE.md`). The skills
themselves live in `.claude/skills/<name>/` as real folders (not symlinks, so
they survive a Windows checkout); this folder keeps their licences, where they
came from, and checksums, so they keep working if the upstream repos go away.

| Skills | Upstream | Commit | Licence |
| --- | --- | --- | --- |
| using-agent-skills, interview-me, spec-driven-development, planning-and-task-breakdown, incremental-implementation, test-driven-development, debugging-and-error-recovery, source-driven-development, api-and-interface-design, security-and-hardening, documentation-and-adrs, frontend-ui-engineering, code-review-and-quality, performance-optimization | https://github.com/addyosmani/agent-skills | aeac41d4d005999432bb7312f7ff06383a91d59d | MIT (`LICENSE-addyosmani-agent-skills`) |
| frontend-design | https://github.com/anthropics/skills | dbd4588f9e1033efb41dad4bef2f7947c8993d44 | Apache 2.0 (`LICENSE-anthropics-frontend-design.txt`, also in the skill folder) |
| vercel-react-best-practices, vercel-composition-patterns | https://github.com/vercel-labs/agent-skills | 063bee94c3f4df8453406c830b0a7df0f2860278 | MIT (stated in each SKILL.md) |
| web-design-guidelines (its rules kept beside it as `guidelines.md`, from vercel-labs/web-interface-guidelines 434b7f9) | https://github.com/vercel-labs/agent-skills | 063bee94c3f4df8453406c830b0a7df0f2860278 | MIT (stated in its SKILL.md; `LICENSE-vercel-labs-web-interface-guidelines` for the rules) |
| taste-skill, gpt-tasteskill, image-to-code-skill, imagegen-frontend-web, imagegen-frontend-mobile, redesign-skill, minimalist-skill, soft-skill, brutalist-skill, stitch-skill | https://github.com/leonxlnx/taste-skill | ce26fc25c0e5e8cab638f883de62d9a86ee5e45b | MIT (`LICENSE-leonxlnx-taste-skill`) |
| impeccable (its whole `scripts/` folder, launcher and downloaded binary left out; a note in its SKILL.md says to skip every launcher step and use `reference/` directly) | https://github.com/pbakaus/impeccable | e07dc019a75e973db1c71843143bf6f9fd33d87c | Apache 2.0 (`LICENSE-pbakaus-impeccable`, `NOTICE-pbakaus-impeccable.md`) |
| systematic-debugging, verification-before-completion, receiving-code-review, writing-plans (scripts left out) | https://github.com/obra/superpowers | 2ce8aa15d05bd57213e6f746f953aafb7ded7a8b | MIT (`LICENSE-obra-superpowers`) |
| writing-guidelines | https://github.com/vercel-labs/agent-skills | 063bee94c3f4df8453406c830b0a7df0f2860278 | MIT (stated in its SKILL.md) |
| karpathy-guidelines (also an FCC built-in skill, with a note for agents that can't stop to ask) | https://github.com/multica-ai/andrej-karpathy-skills | 2c606141936f1eeef17fa3043a72095b4765b9c2 | MIT (stated in its README, plugin.json and SKILL.md; `LICENSE-multica-ai-andrej-karpathy-skills.md`) |
| find-skills | https://github.com/vercel-labs/skills | a80e4c9d12d607631249d4d7d059f835d4b2f13a | MIT (`LICENSE-vercel-labs-skills`) |
| agency-agents (an FCC-written SKILL.md and an INDEX.md of the 283 roles; the role texts stay in `vendor/repos/msitarzewski__agency-agents.zip` and are read one at a time with `unzip -p`) | https://github.com/msitarzewski/agency-agents | b37b5bb33b78f2c1d6567d98e25ca818e3259219 | MIT (`LICENSE` inside the zip) |
| fastapi (installed with `npx skills add fastapi/fastapi --skill fastapi -a claude-code`; FCC's Studio API is FastAPI) | https://github.com/fastapi/fastapi | 79cab5b | MIT (`LICENSE-fastapi`) |
| python-testing-patterns (installed with `npx skills add wshobson/agents --skill python-testing-patterns -a claude-code`; also in FCC's bundled wshobson/agents copy) | https://github.com/wshobson/agents | 0874a27b17a22e2b7c2e2bcd725768e0803cad06 | MIT (`LICENSE-wshobson-agents`) |
| playwright-cli (written by `playwright-cli install --skills`, @playwright/cli 0.1.22) | https://github.com/microsoft/playwright-cli | b1a5903c5b633b8c9f843ad7b629c2a78437040c | Apache 2.0 (`LICENSE-microsoft-playwright-cli`) |

Not installed for Claude Code (owner's call, 6.84): the rest of superpowers
(its always-on and multi-agent skills clash with the owner's lean,
one-previewer rules), strix, agent-reach, flick, rea and the Vercel deploy
skills (they need their own command-line tools or services). They are still
starter repos in FCC.

- `skills-lock.json`: the installer's record (source repo, path, hash per skill).
- `SHA256SUMS`: checksums of every installed skill file (`sha256sum -c SHA256SUMS`
  from the repo root).

FCC is plain JavaScript, not React, so the two Vercel React skills only apply
if a React project is added later.

Left out on purpose (from the owner's `install-fcc-claude.sh`): the eight
"reference repo" clones (graphify, vercel skills, playwright-cli, OmniRoute,
Headroom, claude-mem, anthropic skills, agent-skills). Cloning them without
keeping a copy would break the rule that outside repos must survive deletion,
and OmniRoute, Headroom and claude-mem change routing, wrappers or storage, so
they are not installed until the owner reviews them. Graphify and Playwright
CLI are tools installed on the PC by `scripts/claude/install-claude-tools.sh`.
