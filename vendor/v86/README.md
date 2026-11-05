# v86 (x86 emulator for FCC Linux on the phone)

- Upstream: https://github.com/copy/v86, npm package `v86` 0.5.473
  (commit 315b2b0), BSD-2-Clause (`LICENSE`).
- BIOS: SeaBIOS and the Bochs VGA BIOS from the same commit's `bios/`
  folder (`seabios.bin`, `vgabios.bin`), LGPL (`COPYING.LESSER-bios`); their
  sources are SeaBIOS (https://www.seabios.org) and the Bochs VGA BIOS.

## What FCC uses

From the npm package, `build/libv86.js` and `build/v86.wasm`; with the two
BIOS files, they are in `src/free_claude_code/api/phone_static/linux/`
(checksums in `SHA256SUMS`, also checked by `js/linux.js` before anything
runs). Left out: the debug and fallback builds, the ES-module copy, the
type file and v86's demo images (FCC boots its own FCC Linux).

`js/linux.js` runs v86 in a sealed box (an iframe with
`sandbox="allow-scripts"`, a content policy with no network) and hands it
the files by message. The emulated PC gets no network card.
