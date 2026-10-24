# Vendored repos

FCC Studio keeps its own copy of every outside repo it builds on, so the app
keeps working if the original repo, its releases, or its website disappear.
Each folder here holds:

- the upstream licence,
- the exact release files FCC installs, with their SHA-256 checksums,
- a source snapshot (the MIT-licensed parts FCC uses) to rebuild from,
- a README naming the upstream repo, the commit, and how FCC uses it.

The running app does the same for anything it downloads later: every repo
added from a GitHub link and every release it installs is kept in the
**Repo vault** on the PC (Settings, Repo vault), with checksums, and is
installed from there when GitHub no longer has it.

| Folder | Upstream | Licence | Used for |
| --- | --- | --- | --- |
| [`agent-skills/`](agent-skills/README.md) | https://github.com/addyosmani/agent-skills, https://github.com/anthropics/skills, https://github.com/vercel-labs/agent-skills, https://github.com/vercel-labs/skills | MIT / Apache 2.0 | Claude Code skills in `.claude/skills/` for the implementer + previewer setup in `CLAUDE.md` |
| [`claw-code/`](claw-code/README.md) | https://github.com/ultraworkers/claw-code | MIT | Claw Code built on this PC and run through FCC (Knowledge & Memory → Claw Code, `fcc-claw`) |
| [`cua/`](cua/README.md) | https://github.com/trycua/cua | MIT | Kept for a planned PC-control feature (not used yet) |
| [`stable-diffusion-cpp/`](stable-diffusion-cpp/README.md) | https://github.com/leejet/stable-diffusion.cpp | MIT | The Image engine: painted cartoon places and characters (Settings → Image engine) |
| [`uiverse/`](uiverse/README.md) | https://github.com/uiverse-io/galaxy | MIT | The UI library: 3,802 ready-made web design pieces the Builder, Coder and Designer search and copy (`ui_library` tool) |
| [`startbootstrap/`](startbootstrap/README.md) | https://github.com/StartBootstrap | MIT (libraries MIT, CC BY 4.0, LGPL-3.0) | 26 whole-website layouts the Builder starts sites from (`site_layouts` tool) |
| [`kenney/`](kenney/README.md) | https://kenney.nl/assets | CC0 (public domain) | Game art and sound: 49 packs ship, all 217 catalogued and downloaded once into the game vault (`game_assets` tool) |
| [`pocketpal-ai/`](pocketpal-ai/README.md) | https://github.com/a-ghorbani/pocketpal-ai | MIT | The classroom page's look (colours, layout); design only, no code copied |
| [`phaser/`](phaser/README.md) | https://github.com/phaserjs/phaser, https://github.com/phaserjs/examples | MIT (example assets left out) | The `phaser-game` starter's engine and 2,298 example programs (`game_assets` tool) |
| [`three/`](three/README.md) | https://github.com/mrdoob/three.js | MIT | The 3D views: the Trading Bank's debate arena, the Ops page, and the 3D site templates |
| [`repos/`](repos/README.md) | 46 repos, 44 shipped as zips (OpenHands, MetaGPT, crewAI, superpowers, impeccable, awesome-design-md, wshobson/agents, public-apis, …) | Each repo's own (MIT, Apache-2.0, CC0, AGPL-3.0) | Starter repos: skills, guides and lists every agent can search, switched off until the owner turns them on |
| [`ruflo-core/`](ruflo-core/README.md) | https://github.com/ruvnet/ruflo | MIT | Ruflo's agents, skills and MCP server for Claude Code sessions on this repo (`.claude/`, `.mcp.json`) |
| [`hyperliquid-python-sdk/`](hyperliquid-python-sdk/README.md) | https://github.com/hyperliquid-dex/hyperliquid-python-sdk | MIT | The reference signing code and test values FCC's own Hyperliquid (Invo) signing is checked against |

Not vendored: **Aider** (https://github.com/Aider-AI/aider, Apache 2.0). FCC
neither bundles nor downloads it; the owner installs it (`uv tool install
aider-chat`) and FCC only runs the installed `aider` program for the **aider**
tool. Nothing in FCC depends on Aider's repo or releases staying online.

Not vendored: **FreeLLMAPI** (https://github.com/tashfeenahmed/freellmapi,
MIT). It is a separate Node.js app the owner may run on their PC; FCC only
talks to its OpenAI-style address as the **freellmapi** provider. FCC ships
none of its code and works without it.
