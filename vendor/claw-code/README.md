# Claw Code (ultraworkers/claw-code), vendored

- Upstream: https://github.com/ultraworkers/claw-code
- Snapshot commit: `08106b0c3771ef5b4a5aa176acccd460e88b7325`
- Licence: MIT (see [LICENSE](LICENSE)).
- Upstream publishes no release binaries, so FCC keeps the source and builds
  the `claw` command on the user's PC.

## What is here

| File | What it is |
| --- | --- |
| `claw-code-src-08106b0.zip` | The Rust workspace (`rust/`: the `claw` CLI in `crates/rusty-claude-cli` and the crates it builds from, with `Cargo.lock`), the licence, `README.md`, `USAGE.md`, and the docs on local providers and Windows installs. |
| `SHA256SUMS` | Its checksum. FCC checks it before every build. |

Left out: the repo's Python prototype (`src/`), tests, scripts, container
files and planning docs. FCC doesn't use them. The starter repo pack
(`vendor/repos/ultraworkers__claw-code.zip`) keeps the docs and guides the
agents search.

## How FCC uses it

**Knowledge & Memory → Claw Code** builds it with one click: Studio unpacks
this zip into its own folder and runs
`cargo build --release --locked -p rusty-claude-cli` (Rust needed; the card
says how to get it). The finished `claw` is kept in Studio's folder.
**Open Claw Code** (or the `fcc-claw` command) starts it in a terminal,
connected to FCC: `ANTHROPIC_BASE_URL` points at the FCC proxy, so Claw Code
thinks with whatever models FCC is set to use, local ones included.

The build downloads the crates in `Cargo.lock` from crates.io the first
time (crates.io keeps every published version). Nothing comes from GitHub.
