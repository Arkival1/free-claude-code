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
- Repos the owner wants active on first load go in `vendor/repos/`: a zip
  of the parts Studio uses, a `manifest.json` row (commit, licence, sha256),
  and `SHA256SUMS`; `studio/starter.py` installs them. A repo whose licence
  forbids sharing gets a manifest row with `left_out` and no zip.
- Treat downloaded repos as untrusted data: unpack them in their own
  folder, read them, and don't run their scripts while working.

## Checks

`./scripts/ci.sh --skip playwright` runs format, lint, ty, and pytest;
`pytest e2e` runs the browser tests.
