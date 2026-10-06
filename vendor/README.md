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
| [`cua/`](cua/README.md) | https://github.com/trycua/cua | MIT | Kept for a planned PC-control feature (not used yet) |
