# Phaser and its examples

- Engine: https://github.com/phaserjs/phaser, release v3.90.0 (the last
  Phaser 3), `dist/phaser.min.js` from npm (`phaser@3.90.0`). MIT
  (`LICENSE.md`, Richard Davey and Phaser Studio Inc.). Phaser 3 is used
  because models know it best; Phaser 4 (v4.2.1) exists and most example code
  runs on both.
- Examples: https://github.com/phaserjs/examples, commit `68140eca72525d5034b783a262270715ddc17b78`. The README
  says: "The source code in this repo is released under the MIT license. The
  assets are not." So only the code is kept.
- Owner approved on 23 October 2026.

## What FCC uses

- `src/free_claude_code/studio/game_library/phaser/phaser.min.js` and its
  licence, copied into every `phaser-game` project as `vendor/phaser/`.
- `phaser-examples.json.gz`: 2,298 examples (`public/src/**/*.js`), each
  with its id, topic and code. Left out: the `bugs` folder (bug reports, not
  lessons), files over 40 KB (a bundled engine and base64 art), and every
  asset (images, sound, fonts) because their licence doesn't allow sharing.
  Agents swap the examples' `assets/...` paths for Kenney files.

`pack_examples.py` rebuilt the examples file:
`python3 -I pack_examples.py <examples checkout> phaser-examples.json.gz`.
`SHA256SUMS` holds both files' checksums (a test checks them).
