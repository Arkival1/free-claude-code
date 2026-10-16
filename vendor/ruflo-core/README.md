# Ruflo core (ruvnet/ruflo), vendored

- Upstream: https://github.com/ruvnet/ruflo (`plugins/ruflo-core`)
- Snapshot commit: `1882006a02487590c8c66a7eec8d7504f6af33c3`
- Licence: MIT (see [LICENSE](LICENSE)).

Cloud Claude Code sessions (the Claude app, claude.ai/code) don't install
plugins, so the parts of the ruflo-core plugin that work as plain project
files are kept in the repo instead, where every session loads them:

| In the repo | From upstream | Changes |
| --- | --- | --- |
| `.claude/agents/ruflo-coder.md`, `ruflo-researcher.md`, `ruflo-reviewer.md` | `agents/coder.md`, `researcher.md`, `reviewer.md` | Renamed with a `ruflo-` prefix |
| `.claude/skills/ruflo-status/`, `ruflo-doctor/`, `ruflo-discover-plugins/` | `skills/ruflo-status/`, `ruflo-doctor/`, `discover-plugins/` | `discover-plugins` renamed |
| `.mcp.json` (`ruflo` server) | `.mcp.json` | Runs `npx -y @claude-flow/cli@3.56.10 mcp start` directly |

In every copied file `@claude-flow/cli@latest` is pinned to `3.56.10`, and
the plugin's MCP tool names (`mcp__plugin_ruflo-core_ruflo__…`) are renamed
to the project server's (`mcp__ruflo__…`). `SHA256SUMS` lists the checksums
of the upstream files as they were at the snapshot commit.

Left out:

- `hooks/hooks.json` and `scripts/ruflo-hook.cjs`: they run ruflo after
  every Bash command and file edit, and their PreToolUse hooks answer
  "allow", which would skip permission prompts.
- The `witness` command, skill, agent and scripts: they need the plugin's
  script folder and only sign fix manifests.
- The `init-project` skill: `ruflo init` rewrites `CLAUDE.md` and
  `.claude/settings.json`.
- The `ruflo-status` command: the skill of the same name does the same.
- The `@claude-flow/cli` npm package itself: `npx` downloads it from npm
  when a session starts the MCP server; it is not kept here.
