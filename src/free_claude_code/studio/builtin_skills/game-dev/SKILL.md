---
name: game-dev
description: How to make a real browser game in FCC - start from the phaser-game template (Phaser 3, keyboard and touch), pick Kenney's free art and sound with game_assets, copy mechanics from Phaser's example code, and add the animation, juice and engineering that make a game feel good. Use for any game, arcade, platformer, shooter, puzzle, card or dungeon job.
---

# Game development

## 1. Start right
- `start_project` with `phaser-game`: Phaser 3.90 in `vendor/phaser` (never
  edit it), a working platformer in `game.js`, Kenney art in `assets/`, touch
  buttons and keyboard, pause when the tab is hidden. Reshape it into the
  game asked for; keep what works.
- One scene per screen (title, level, game over) once the game grows:
  `class Title extends Phaser.Scene`, `this.scene.start("level")`.
- Open it with `try_page` and play it: press keys, tap the buttons, check
  the score changes and nothing throws.

## 2. Art and sound (game_assets)
- `game_assets` action `find` with plain words: "coin", "spaceship",
  "explosion", "laser sound", "tile grass", kind `sprite`, `sheet`, `sound`.
  Shipped packs are ready; others say to `download` once (kept on the PC).
- `use` copies files into `assets/<pack>/`. Load single images with
  `this.load.image(key, path)`; tile and character sheets with
  `this.load.spritesheet(key, path, { frameWidth, frameHeight })` (the pack's
  Tilesheet.txt gives the size; `_packed` sheets have no spacing).
- Sounds: `this.load.audio(key, "assets/.../x.mp3")`, then
  `this.sound.play(key, { volume: 0.5 })`. Phaser starts sound after the
  first tap. Kenney is CC0: no credit needed, but a "Art: Kenney.nl" line is
  kind.
- One art style per game: don't mix pixel art with vector packs.

## 3. Mechanics (game_assets examples)
- `game_assets` action `examples` with words ("tilemap collision",
  "particles explode", "drag input", "tween yoyo"), then `example` for the
  code. Phaser examples load Phaser's own art from `assets/...`: swap those
  for Kenney files you `use`d.
- Movement that feels good: accelerate toward a target speed
  (`Phaser.Math.Linear`), coyote time (jump ~100 ms after leaving a ledge),
  a jump buffer (a press ~120 ms early still jumps), cut the jump short when
  the button is let go.
- Grid and turn-based games: keep the board as data (an array of rows);
  move on the data, then tween the sprite to the new cell.
- Enemies: patrol and bounce (`setBounceX(1)`), chase on a grid (step
  toward the player on the longer axis), spawn waves with a timer whose
  delay shrinks as the score grows.

## 4. Animation and juice
- Sprite-sheet animations: `this.anims.create({ key, frames:
  this.anims.generateFrameNumbers(sheet, { frames: [0, 1] }), frameRate,
  repeat: -1 })`; play idle, walk, jump, hit.
- Tweens for squash, bob, flash and fades; `yoyo: true` for a bounce.
- Particles: `this.add.particles(0, 0, key, { speed, scale: { start, end },
  lifespan, emitting: false })` then `.explode(n, x, y)` on hits.
- Screen shake on big hits (`this.cameras.main.shake(100, 0.005)`), a short
  hit flash (`setTint` then `clearTint`), and a sound for every action.
- Respect reduced motion: skip shake and spin when
  `matchMedia("(prefers-reduced-motion: reduce)")` matches.

## 5. Engineering
- Arcade physics for most games: `physics.add.collider` and `overlap`;
  static groups for the level; `setSize`/`setOffset` for fair hitboxes.
- Pool bullets and effects (`this.physics.add.group({ maxSize })`, `get()`,
  disable instead of destroy).
- A small state per object (`idle`, `run`, `hurt`) instead of tangled flags.
- Keep the best score with `localStorage` inside try/catch.
- Phones: on-screen buttons that fill a `held` set on pointerdown and clear
  it on pointerup/leave/cancel, `touch-action: none`, buttons at least
  48 px, `Phaser.Scale.FIT`. Test at 390 px wide.
- Pause on `visibilitychange` (`game.loop.sleep()` / `wake()`).

## 6. Before finishing
- Play it in `try_page` on phone and computer sizes; no console errors.
- A title or start screen, a clear goal, a score or lives, a win and a lose
  screen, and a way to play again.
- Say what the game is, how to play, and which packs it uses.
