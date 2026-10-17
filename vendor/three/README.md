# three.js (mrdoob/three.js), vendored

- Upstream: https://github.com/mrdoob/three.js
- Release: npm package `three@0.186.1` (r186), published 2026-09-24
- Commit: `9b4a2ac29c63ccb43fd51c5661f2f873ac2c39b8` (the package's `gitHead`)
- npm integrity: `sha512-blFeqb49wRCSGUGj7gtpfnSGHy2lwDk94RhUmS1c/hTby70kvChbWpkJ4Pm1390LqzzvTmzgXKHPEafJwCb8jA==`
- Licence: MIT (see [LICENSE](LICENSE)).

Studio draws its 3D views with three.js: the Trading Bank's debate arena
(the five seats around the Portfolio Manager), the Ops page's system pulse,
and the 3D site templates the Builder can start from.

The files Studio serves are kept, byte for byte, in
`src/free_claude_code/api/studio_static/`, where the app loads them from
(the r186 release has no minified builds, so these are the readable
sources too):

| Served as | From the package | Job |
| --- | --- | --- |
| `three.module.js` | `build/three.module.js` | The WebGL renderer and the public module (imports `three.core.js`) |
| `three.core.js` | `build/three.core.js` | Scenes, cameras, geometry, materials, maths |
| `three-orbit.js` | `examples/jsm/controls/OrbitControls.js` | Drag to turn and zoom the 3D views |

`SHA256SUMS` lists the checksums of those files and of the npm tarball
(`three-0.186.1.tgz`) they came from; a test checks the served copies
still match. Studio loads them only when a 3D view opens, through the
import map in `index.html` (`three` → `three.module.js`), and sends them
gzip-compressed (about 2.1 MB becomes about 450 KB).

Left out: the rest of the package (the WebGPU and TSL builds, the other
examples, `src/`), which Studio doesn't use. The full tarball can be
fetched again from npm and checked against `SHA256SUMS`.
