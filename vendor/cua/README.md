# Cua (trycua/cua), vendored

- Upstream: https://github.com/trycua/cua
- Snapshot commit: `0b90b6f4af6885ecbe696a6b33a3ad63773183d4`
- Driver release: `cua-driver-rs-v0.34.0`
- Licence: MIT (see [LICENSE.md](LICENSE.md)). Only MIT-licensed parts are
  kept here. The optional `cua-perception` extension (it uses an
  AGPL-3.0 OmniParser model) and the FSL-licensed Cua Spaces apps are left out.

## What is here

| File | What it is |
| --- | --- |
| `cua-driver-rs-0.34.0-windows-x86_64.zip` | The official Windows release of Cua Driver: `cua-driver.exe` (background desktop control: UI Automation, PostMessage delivery that never steals focus, window screenshots), its UIA helper, licence, and notices. Kept so it never needs GitHub. |
| `SHA256SUMS` | Checksums. The zip's matches the upstream release's `SHA256SUMS`. |
| `source/cua-driver-src-0b90b6f.tar.xz` | Source of `libs/cua-driver` (Rust workspace, Python SDK, docs, tests), to rebuild the driver if ever needed (`cargo build --release -p cua-driver` in `rust/`). |
| `source/cua-python-agent-src-0b90b6f.tar.xz` | Source of the `cua-agent` and `cua-core` Python packages: the agent loop (screenshot, model, action, repeat; only the newest screenshots sent; a step budget; trajectories kept). |
| `skills/*.md` | Cua Driver's own operating guide for agents. |

## Status in FCC Studio

This copy is kept so Cua stays available to FCC even if the upstream repo
or its releases are deleted. FCC Studio doesn't run any of it yet: building
it into the app as a PC-control agent is waiting on the owner's go-ahead.
