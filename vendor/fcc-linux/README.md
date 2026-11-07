# FCC Linux (FCC Phone's own Linux)

FCC Linux 2.0 is Alpine Linux 3.21.9 (32-bit x86, what v86 emulates) with
every language: C/C++ (gcc 14, g++, cmake, gdb, nasm), Rust 1.83 (cargo),
Go 1.23, Java 8 (OpenJDK, the only JDK Alpine builds for x86), Node.js 22
(npm), Python 3.12 (pip), Ruby 3.3, PHP 8.3, Perl, Lua 5.4 and git, plus FCC
Linux 1's tools (bash, nano, tmux, sqlite, jq, htop, lynx...). It is built by
`scripts/linux/build_fcc_linux2.py` (which reuses `build_fcc_linux.py`'s
download, signature and unpacking code) without running anything
downloaded. `contents.json` lists exactly what is inside: the 15 base
packages, the 136 packages added, what was left out, the kernel, the
start-up system, the file list and every pack with its SHA-256.

- Inputs, pinned or checked: `alpine-minirootfs-3.21.9-x86.tar.gz` (SHA-256 in
  `SHA256SUMS`) from https://dl-cdn.alpinelinux.org/alpine/v3.21/releases/x86/;
  the package index's RSA signature is checked with Alpine's keys from that
  (pinned) minimal root, every package's control part with the index's
  SHA-1, and its files with the SHA-256 (`datahash`) its control part names.
  The kernel and its modules come from the `linux-lts` package (6.12.115),
  checked the same way. Nothing downloaded is run, and a check that can't be
  made stops the build.
- Python's library is compiled to bytecode at build time by the build
  machine's own Python 3.12 (`compile()` only parses the sources), as
  unchecked-hash `.pyc` files. The build needs `python3.12`.
- How it reaches the phone. The whole system (1.2 GB, 19,600 files) is too big
  to live in memory, so:
  - `fcc-linux.initrd` (1 MB) is a start-up system: busybox, musl, the 9p and
    network-card modules and `/init`, which mounts the real system over 9p
    (v86's virtio file system, tag `host9p`) and switches to it;
  - `fs/fs-*.json.gz` is the file list in v86's format (version 3); each file
    is named `<pack>-<offset>-<length>.zst` (hex);
  - `fs/*.pack` are 18 packs (24 MB at most, 433 MB in all) of zstd-compressed
    files, named by their SHA-256;
  - `fcc-linux.json` is the manifest; the phone pins its SHA-256 (`js/linux.js`)
    and checks every pack against it (`js/linuxfiles.js`), fetching a pack the
    first time something in it is used and keeping it on the phone. "Get
    everything now" fetches them all for offline use.
- FCC's own files inside: `/etc/inittab`, `/etc/fcc/` (boot and login),
  `/etc/profile.d/fcc.sh` (the prompt and the `__fcc_run` bridge the phone
  and Jarvis use over the serial line: commands run in bash with no keyboard
  input, and the prompt tells the phone when the shell is idle or busy, so
  nothing is typed into an open program), `/etc/profile.d/fcc-languages.sh`
  (JAVA_HOME, Go and Cargo folders), `/etc/motd`, `/etc/os-release` and
  `fcc-info`.

## Licences and sources

The packages keep their own licences (Linux and BusyBox are GPL-2.0;
Python is PSF; GCC is GPL-3.0 with the runtime exception; Rust, Go, Node.js,
Ruby, PHP, Perl and git under theirs; the rest are listed per package in
Alpine's index). Their exact sources are Alpine's: the build recipes at
https://gitlab.alpinelinux.org/alpine/aports (branch 3.21-stable) and the
source tarballs on Alpine's mirrors, for the versions in `contents.json`.
FCC Linux is for the owner's own use in FCC Phone; if it is ever passed on
to others, the matching sources go with it.

## Rebuilding

    uv run python scripts/linux/build_fcc_linux2.py

Compressed files are cached in `.cache/fcc-linux/blobs`, so a rebuild takes
about a minute. Then put the new kernel, initrd and manifest checksums into
`js/linux.js` (`FILES`) and `SHA256SUMS`, copy `fcc-linux.json` to
`contents.json`, and run the FCC Linux tests. Packs that didn't change keep
their names, so an update only adds the packs that changed.
