---
name: godot-dev
description: How to make real Godot 4 games in FCC (Godot 4.7.2, GDScript) on the owner's PC - start from a godot starter, write scripts and scenes, check with Godot headless after every change, look at frames, learn from Godot's 133 demos, and export a Windows game. Holds the genre book (reference/genres.md) and the art, animation, physics and world guide (reference/craft.md). Use for any game job that isn't a browser game.
---

# Godot 4 games

## 1. The loop (always)
1. `godot` action `start` with the closest starter: `platformer-2d`,
   `rpg-topdown` or `third-person-3d`, and the game's title. Reshape it into
   the game asked for; keep what works.
2. Read the genre's page in `reference/genres.md` (skill tool, file
   `godot-dev/reference/genres.md`) and plan: core loop, controls, levels,
   win and lose, the art style.
3. Write small changes with `write_file` / `edit_file` (`.gd`, `.tscn`,
   `project.godot`). After **every** change run `godot` action `check`. It
   loads every script and scene and plays a few seconds: fix every problem
   it lists (file and line) before going on. Never leave a FAILED check.
4. `godot` action `frames` (3-5 seconds) saves the game's frame to
   `screenshots/frame.png`; look at it and fix what looks wrong.
5. When it plays well, `export` makes a Windows game for the owner.
6. Stuck on how to do something? `godot` action `demos` with plain words
   ("tilemap", "ragdoll", "dialogue", "state machine"), then `demo` to read
   the code. They're Godot's own MIT demos: copy the patterns freely. When
   a demo is close to the game asked for, `use` copies the whole demo (code,
   art, sound, models, skies) into the project to build on; keep its licence
   files and credits.
7. Need depth on one part? The skill tool has Godot 4.7 skills for each
   (gamedev-skills/awesome-gamedev-agent-skills): read the one that fits,
   e.g. `godot-physics`, `godot-tilemap`, `godot-animation`, `godot-shaders`,
   `godot-ui-control`, `godot-signals-groups`, `godot-resources`,
   `godot-2d-movement`, `godot-3d-essentials`, `godot-audio`,
   `godot-multiplayer`, `godot-export`, `godot-gdscript`,
   `godot-nodes-scenes`, `godot-gdscript-headless-testing`. Where one says
   to run a script, use `godot` action `check` instead. If the owner turned
   that repo off, the demos and this skill are enough.

## 2. GDScript 2 (Godot 4), the rules that trip models up
- Typed variables: `var speed := 120.0`. When `:=` can't infer (a value
  from an Array, Dictionary or `match`), write the type: `var row: String = MAP[i]`.
- Annotations: `@export var speed := 120.0`, `@onready var sprite := $Sprite2D`.
- Bodies: `CharacterBody2D`/`3D` with the built-in `velocity`, then
  `move_and_slide()` (no arguments). `is_on_floor()` after moving.
- Signals: `area.body_entered.connect(_on_body_entered)` or a lambda
  `func(body): ...`; emit with `my_signal.emit(value)`.
- Tweens: `create_tween().tween_property(node, "scale", Vector2.ONE, 0.2)`.
- Tiles: `TileMapLayer` (TileMap is old). Physics layer on the TileSet, a
  collision polygon per tile (see the starters' `_make_tile_set`).
- Input: actions in `InputMap` (the starters add them in code), then
  `Input.get_axis("left", "right")`, `Input.get_vector(...)`,
  `Input.is_action_just_pressed("jump")`.
- Scenes: `preload("res://enemy.tscn").instantiate()`; scripts made in code:
  `preload("res://enemy.gd").new()`. A scene file's root type must match its
  script's `extends`.
- Timers: `await get_tree().create_timer(0.5).timeout`.
- Groups: `add_to_group("enemies")`, `get_tree().get_nodes_in_group(...)`.
- Saving: `FileAccess.open("user://save.json", FileAccess.WRITE)` and
  `JSON.stringify(data)`; `JSON.parse_string(text)` to read.
- Never invent nodes or methods: check a demo or the class name first.

## 3. Structure that keeps growing games sane
- One script per thing (player, enemy, level, hud, save). Data in
  `Resource` scripts (`class_name Item extends Resource` with `@export`s).
- An autoload (Project > Autoload; or `[autoload]` in project.godot:
  `Game="*res://game.gd"`) for score, settings, save and scene changes.
- State machines for characters (idle, run, jump, attack, hurt, dead):
  `enum State {IDLE, RUN}` and a `match state:`; see demo
  `2d/finite_state_machine`.
- Levels as text maps (as the starters do) or TileMapLayer scenes; enemies
  and items placed from the map.

## 4. Feel (do these in every game)
Coyote time, jump buffering, variable jump height, acceleration and
friction, squash and stretch, screen shake on hits, hit flash, particles on
pickups and deaths, a short pause on big hits, sounds for every action,
camera smoothing, and a clear win and lose screen.

## 5. Art, designs and other games
- Kenney's packs (CC0) through `game_assets`: copy them into `assets/`.
  One art style per game. Godot imports PNGs itself; pixel art needs
  `textures/canvas_textures/default_texture_filter=0` in project.godot.
- Pictures or videos the owner sends of a game: copy what it plays like
  (mechanics, controls, camera, pacing, layout, style); game rules belong
  to nobody. Draw your own characters, art and names; don't copy another
  game's characters, art, music or logo. The owner's own art and designs
  can be used as they are.
- Looks, animation, physics, worlds and story: `reference/craft.md`.
