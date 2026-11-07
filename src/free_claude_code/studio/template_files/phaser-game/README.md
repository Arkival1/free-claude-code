# $title

A browser game on Phaser 3 (MIT, FCC's own copy in `vendor/phaser`), with art
and sound from Kenney (CC0, public domain) in `assets/`. It starts as a
platformer: run, jump, stomp crawlers, collect coins, reach the flag. It works
on a computer (keyboard) and a phone (the touch buttons).

- `game.js`: `LEVEL` draws the level (one character per tile), `FRAMES` names
  the sprite-sheet frames, and the `Level` scene holds the mechanics
  (coyote time, jump buffer, short hops, stomping, camera follow, particles).
- `index.html` and `styles.css`: the page around the game, the score and the
  touch buttons.
- `assets/`: Kenney's Pixel Platformer sheets and a few sounds. The
  `game_assets` tool finds thousands more sprites and sounds, and Phaser's
  example code for any mechanic; the `game-dev` skill has the recipes.

Open it through Studio's preview (Phaser loads its files from a web server).
