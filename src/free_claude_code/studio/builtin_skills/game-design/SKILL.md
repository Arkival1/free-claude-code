---
name: game-design
description: How to design a game before and while building it - the core loop, mechanics and balance, levels and pacing, story and dialogue, rewards and economy, art direction and effects, sound - with eight specialist guides (game, level, narrative and economy designer, technical artist, audio, Godot gameplay and shaders). Use when a game job needs design decisions, not only code, or when a game feels flat, too hard, too easy or unfinished.
---

# Game design

Design first, in a few lines, then build with `godot-dev` (or `game-dev`
for a browser game). Keep the design in the project as `DESIGN.md` and
update it when the game changes.

1. **The core loop.** What the player does every few seconds, why it feels
   good, and what changes over a minute and over a session. One sentence each.
2. **The rules.** Every mechanic with its numbers (speed, jump height, damage,
   cooldowns, costs) in one table, so balance is changed in one place.
3. **Levels and pacing.** Teach one idea at a time: introduce it safely,
   test it, then combine it with an earlier one. Rest beats between hard
   parts; the hardest part near the end.
4. **Feedback.** Every action answers with sound, motion or light within a
   tenth of a second (hit flash, screen shake, particles, a sound).
5. **Story and goal.** Who the player is, what they want, and what stands in
   the way, told through the world more than through text.
6. **Rewards.** What the player earns, how often, and what it lets them do;
   no reward that breaks the balance table.
7. **Art and sound direction.** One palette, one style, one mood; every
   asset fits it. Name the reference games or photos (look_reference).
8. **Test it like a player.** Play it (`godot` action `frames`), note where
   it is confusing, boring or unfair, and fix the biggest one first.

## The specialist guides (read only the one you need)

With the skill tool, action read, name "game-design", file as below:

- `reference/game-designer.md`: loops, systems, balance, the design document.
- `reference/level-designer.md`: layout, flow, encounters, pacing.
- `reference/narrative-designer.md`: story, dialogue, lore, branching.
- `reference/economy-designer.md`: currencies, rewards, sinks, prices.
- `reference/technical-artist.md`: shaders, effects, art pipeline, budgets.
- `reference/game-audio-engineer.md`: music, sound effects, mixing.
- `reference/godot-gameplay-scripter.md`: GDScript structure, signals, nodes.
- `reference/godot-shader-developer.md`: Godot shaders and visual effects.

They come from The Agency (msitarzewski/agency-agents, MIT; `LICENSE` here).
They were written for other tools too: where one names Unity, Unreal, FMOD or
a paid service, use the Godot or FCC equivalent, and never install anything
the owner didn't ask for. Make your own game: take a reference's feel and
mechanics, never another game's characters, names or art.
