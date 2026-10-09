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
| [`claw-code/`](claw-code/README.md) | https://github.com/ultraworkers/claw-code | MIT | Claw Code built on this PC and run through FCC (Knowledge & Memory → Claw Code, `fcc-claw`) |
| [`cua/`](cua/README.md) | https://github.com/trycua/cua | MIT | Kept for a planned PC-control feature (not used yet) |
| [`repos/`](repos/README.md) | 30 repos (OpenHands, hindsight, paperclip, public-apis, …) | Each repo's own (MIT, Apache-2.0, CC0, AGPL-3.0) | Starter repos: skills, guides and lists every agent can search, active on first load |
