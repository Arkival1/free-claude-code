# FCC Linux (FCC Phone's own small Linux)

FCC Linux 1.1 is Alpine Linux 3.21.9 (32-bit x86, what v86 emulates) with
FCC's additions, built by `scripts/linux/build_fcc_linux.py` without running
anything downloaded. `contents.json` lists exactly what is inside: the 15
base packages of Alpine's minimal root filesystem, the 35 packages FCC adds
(python3, lua5.4, bash, nano, tmux, sqlite, jq, bc, make, htop, lynx,
figlet and what they need), and the parts left out (manuals, Python's own
tests and GUI kits).

- Inputs, pinned by SHA-256 (`SHA256SUMS`): `alpine-minirootfs-3.21.9-x86.tar.gz`
  and `alpine-netboot-3.21.9-x86.tar.gz` (for the kernel, `vmlinuz-lts`,
  Linux 6.12) from https://dl-cdn.alpinelinux.org/alpine/v3.21/releases/x86/;
  the package index's RSA signature is checked with Alpine's keys from that
  (pinned) minimal root, every package's control part with the index's
  SHA-1, and its files with the SHA-256 (`datahash`) its control part names.
  Nothing downloaded is run, and a check that can't be made stops the build.
- Python's library is compiled to bytecode at build time by the build
  machine's own Python 3.12 (`compile()` only parses the sources; nothing
  downloaded is run), as unchecked-hash `.pyc` files, so the first `python3`
  on the phone starts in about 4 s instead of 15. The build needs
  `python3.12` (`uv python install 3.12`) and gives the same bytes each run.
- Outputs, in `src/free_claude_code/api/phone_static/linux/`:
  `fcc-linux.kernel`, `fcc-linux.initrd` (zstd) and `fcc-linux.json`.
- FCC's own files inside: `/init`, `/etc/inittab`, `/etc/fcc/` (boot and
  login), `/etc/profile.d/fcc.sh` (the prompt and the `__fcc_run` bridge
  the phone and Jarvis use over the serial line: commands run in bash with
  no keyboard input, and the prompt tells the phone when the shell is idle
  or busy, so nothing is typed into an open program), `/etc/motd`,
  `/etc/os-release` and `fcc-info`.

## Licences and sources

The packages keep their own licences (Linux and BusyBox are GPL-2.0;
Python is PSF; the rest are listed per package in Alpine's index). Their
exact sources are Alpine's: the build recipes at
https://gitlab.alpinelinux.org/alpine/aports (branch 3.21-stable) and the
source tarballs on Alpine's mirrors, for the versions in `contents.json`.
FCC Linux is for the owner's own use in FCC Phone; if it is ever passed on
to others, the matching sources go with it.

## Rebuilding

    uv run python scripts/linux/build_fcc_linux.py

Then put the new kernel and initrd checksums into `js/linux.js` (`FILES`)
and `SHA256SUMS`, and run the FCC Linux tests.
