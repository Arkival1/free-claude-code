# xterm.js (FCC Linux's terminal on the phone)

- Upstream: https://github.com/xtermjs/xterm.js, npm `@xterm/xterm` 5.5.0,
  MIT (`LICENSE`).
- FCC ships `lib/xterm.js` and `css/xterm.css` as `linux/xterm.js` and
  `linux/xterm.css` in the phone app (checksums in `SHA256SUMS`). v86 draws
  FCC Linux's serial console in it, inside FCC Linux's sealed box. Left out:
  the add-ons, the ES-module build and the type files.
