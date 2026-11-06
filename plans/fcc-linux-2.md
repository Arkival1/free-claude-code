# FCC Linux 2 and Jarvis self-teaching: the owner's plan (agreed 2026-11-06)

Owner's answers (short): all languages in ONE download; GitHub with the owner's
token (kept in FCC, never inside Linux), Jarvis asks before pushing; an area
inside FCC Linux to switch plugins/internet on (off by default); any site while
switched on, sites that block phone apps are skipped; shared Projects folders;
a desktop (file manager, editor, browser); Jarvis teaches himself (phone model
first; during jobs, practice sessions, when told; time cap the owner sets or no
limit; tests his code for bugs first; researches in the browser; new skills
wait for the owner's OK; notes by chat message, phone notification and a
learning page); websites tested privately in browsers; libraries as big as
possible but fast (Web kit, Lab tutorials, Jarvis's lessons, games, inventions:
builds, parts catalogue, guides, saved inventions); 3 GB of phone storage.

## Facts found (2026-11-06)
- Alpine x86 has gcc/g++ 14.2, nodejs 22, rust 1.83 + cargo, go 1.23,
  openjdk8 (no 11/17/21), ruby 3.3, php 8.3, perl, git, lua; no NetSurf
  (use dillo), no clang/zig/dotnet/kotlin.
- CORS (can the phone fetch it?): yes for api.github.com, raw.githubusercontent.com,
  pypi.org, files.pythonhosted.org, registry.npmjs.org, index.crates.io,
  proxy.golang.org; NO for dl-cdn.alpinelinux.org, github.com git/archives,
  docs.python.org, wikipedia pages. So: FCC Linux's files ship with FCC
  (GitHub Pages: 1 GB site, 100 MB per file), GitHub works through its REST API.
- v86 0.5.473 has: filesystem {basefs, baseurl} (lazy 9p, files named by
  sha256, .zst decompressed in wasm, loaded with XMLHttpRequest) and
  net_device relay "fetch" (guest HTTP on port 80 -> fetch()).

## Stages (each: tests, previewer x2 at milestones, push)
A. FCC Linux 2.0 core: lazy content-addressed root over 9p (small initramfs
   mounts it; kernel + modules from linux-lts), all languages, 512 MB RAM,
   box XHR stand-in -> page fetches files (sha-checked, Cache API, big files in
   parts under 50 MB), "Get everything now" for offline. Boot/restore timing.
B. Internet switch + plugins area (inside Linux: fcc-net / fcc-plugin; page
   screen too) via the fetch network; pip/npm/cargo/go through it; GitHub
   (fcc-github clone/pull/push on the REST API; token in FCC; push asks).
C. Shared /projects folders (sync both ways over the serial bridge).
D. Desktop: Xorg fbdev + jwm + pcmanfm + mousepad + dillo on v86's screen.
E. Jarvis self-teaching: courses per language, practice runner (tests first),
   skills waiting for approval, notes (chat, notification, learning page),
   time cap / no limit, phone model first.
F. Websites: private browser testing of built sites; Web kit growth.
G. Libraries: Web kit, Lab tutorials, lessons, games, inventions library
   (builds, parts catalogue, guides, saved inventions), loaded on demand.
H. Release + report; then "see what's missing or needs work".

## Progress (2026-11-06)
- A done (0ed97227, f8b1da83): FCC Linux 2.0, 21 packs (433 MB), boot ~12 s,
  restore ~2 s, every language checked in a browser (C, C++, Rust, Go, Java,
  Node, Python, Ruby, PHP, Perl, Lua, git). Review: 2 passes, fixes in.
- B core done (d6d2ea28): internet switch (js/linuxnet.js), fcc-github /
  fcc-plugin / fcc-net, GitHub token outside Linux (not in backups), push
  asks once per repo for 10 min. Boot sets eth0 192.168.86.100, gw/DNS .1
  (no DHCP: no AF_PACKET). Real pip/npm/cargo/go check in progress.
- C done (edafc7b1): /projects/<slug> both ways (js/linuxprojects.js); user
  commands detected by counting owed prompt markers.
- Next: B/C review fixes, then E (self-teaching), F+G, D (desktop: needs
  Xorg fbdev + bochs drm modules in the 9p root), release.
