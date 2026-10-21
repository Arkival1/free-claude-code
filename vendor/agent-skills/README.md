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
| find-skills | https://github.com/vercel-labs/skills | a80e4c9d12d607631249d4d7d059f835d4b2f13a | MIT (`LICENSE-vercel-labs-skills`) |
| playwright-cli (written by `playwright-cli install --skills`, @playwright/cli 0.1.22) | https://github.com/microsoft/playwright-cli | b1a5903c5b633b8c9f843ad7b629c2a78437040c | Apache 2.0 (`LICENSE-microsoft-playwright-cli`) |

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
