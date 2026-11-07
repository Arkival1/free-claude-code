# Godot 4.7.2 web player (for FCC Phone)

- Upstream: https://github.com/godotengine/godot, release `4.7.2-stable`
  (commit ed1daf0bf), MIT (`LICENSE`, Godot's own).
- Release file: `Godot_v4.7.2-stable_export_templates.tpz`, entry
  `templates/web_nothreads_debug.zip` (10,232,720 bytes; the zip's CRC was
  checked when it was taken out of the release, and its SHA-256 is in
  `SHA256SUMS`). The tpz's own SHA-512 is in `../godot/README.md`.

## What FCC uses

FCC Phone runs Godot games on the phone with Godot's official web player,
the single-threaded debug build (it runs in any browser without special
server headers, and its errors name the file and line). From the zip FCC
ships, in `src/free_claude_code/api/phone_static/godot/`:

| File | What it is |
| --- | --- |
| `godot.js` | the player's loader, as released |
| `godot.wasm.gz` | the engine, `godot.wasm` gzipped (level 9, no timestamp) so the app stays 10 MB lighter; the phone unpacks it with the browser's own DecompressionStream |
| `godot.audio.worklet.js`, `godot.audio.position.worklet.js` | the sound code, as released |
| `LICENSE.txt` | this licence |

`SHA256SUMS` lists every one of them, and the unpacked `godot.wasm`.
`js/godot.js` holds the same checksums and refuses to run a file that
doesn't match (`tests/studio/test_phone_godot.py` checks they agree).

Left out: the zip's `godot.html`, `godot.offline.html` and
`godot.service.worker.js` (FCC has its own page and service worker), the
multi-threaded players (they need cross-origin isolation headers that GitHub
Pages can't send), the players with dynamic linking for GDExtension, and the
release build (39.5 MB; the debug build's error lines are what the agents fix
games from).

## How FCC uses it

`phone_static/js/godot.js` makes a game package (`.pck`, written in JS by
`godot/pack.js`) from a project's files and runs it in a sealed box: an
iframe with `sandbox="allow-scripts allow-pointer-lock"` (an origin of its own), a content
policy with no network, the engine and the game handed in by message, a
memory cap, and a watchdog. The service worker keeps the engine's files in
their own cache (`fcc-phone-godot-4.7.2`) after the first game.

To update: take the new release's `web_nothreads_debug.zip` from its
templates, copy the four files as above (gzip `godot.wasm` with
`gzip -9 -n`), refresh `SHA256SUMS`, the checksums in `js/godot.js` and
`ENGINE_BYTES`, and run the phone's Godot tests.
