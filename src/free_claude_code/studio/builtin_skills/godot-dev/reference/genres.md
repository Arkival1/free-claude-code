# The genre book (Godot 4)

Each genre: the core loop, the Godot pieces, the feel, and what makes it
good. Start from the starter named in brackets.

## Platformer [platformer-2d]
Loop: run, jump, collect, avoid, reach the end. CharacterBody2D, TileMapLayer
with one-way platforms, Area2D pickups and hazards, Camera2D with limits.
Feel: coyote time 0.1 s, jump buffer 0.12 s, short hop on release, landing
squash. Good: levels teach one idea at a time, checkpoints, secrets.

## Metroidvania [platformer-2d]
Big connected map split into rooms (one scene each); abilities (dash,
double jump, wall jump, grapple with a RayCast2D + rope) unlock new paths;
an autoload remembers abilities, opened doors and bosses beaten; a map
screen that fills in. Good: backtracking that feels new, save rooms.

## Top-down RPG [rpg-topdown]
Explore, talk, quests, fights, items, levels. TileMapLayer layers (ground,
things, roofs above the player), NPCs with dialogue (an Area2D "talk"
range), quest flags in an autoload, stats in Resources, turn-based battles
(a battle scene with a turn queue) or real-time (hitboxes), inventory as an
Array of Item Resources, save to user://. Good: a clear goal, rewards.

## Action RPG / third person 3D [third-person-3d]
Combat combos (attack chain with timing windows), dodge roll with
invulnerable frames, lock-on (nearest enemy in a cone), stamina, loot
drops, skill tree. CharacterBody3D, AnimationTree blend spaces, hitboxes as
Area3D on weapon bones, SpringArm3D camera. Good: readable enemy wind-ups.

## Shooter (FPS, twin-stick, bullet hell)
FPS: CharacterBody3D, camera at the head, RayCast3D hitscan or projectiles,
recoil and spread, ammo and reload. Twin-stick: move with one stick, aim
with the other, bullets from an object pool. Bullet hell: patterns from
code (rings, spirals, aimed bursts), small hitbox, grazing score. Good:
enemy variety, waves that build, strong hit feedback.

## Racing and driving [third-person-3d]
VehicleBody3D with VehicleWheel3D (suspension, friction slip for drift), or
an arcade CharacterBody3D car; track as Path3D; checkpoints as Area3D in
order; laps and a timer; AI cars follow the Path3D with look-ahead and
rubber-banding. Good: boost pads, a sense of speed (FOV widens, particles).

## Puzzle
A grid in code (Array of Arrays) is the truth; nodes only draw it. Undo
(push each state), level files, hints, star ratings by moves. Tween every
move. Good: each level adds one twist; instant restart.

## Roguelike / roguelite
Seeded RandomNumberGenerator; dungeon from rooms + corridors (BSP) or cave
noise (FastNoiseLite); turn-based on a grid or real-time; items with
synergies (Resources with tags); permadeath with meta-upgrades kept in a
save. Good: readable danger, runs of 10-30 minutes.

## Tower defence
Path2D for the enemies' road (PathFollow2D), waves from data, towers placed
on a grid with range Area2D and target priority (first, strongest),
projectiles or beams, upgrades and selling, money per kill. Good: towers
that combine, a clear next-wave preview.

## Real-time strategy
Box-select units (a drag rectangle on a CanvasLayer), right-click to move
(NavigationAgent2D/3D with avoidance), gather and build (a resource
count), fog of war (a texture that clears around units), minimap
(SubViewport). Good: control groups, readable unit roles.

## City builder / sim
Grid placement with a ghost preview, roads that connect, zones that grow
over time, citizens with needs (a simulation tick on a Timer), budget and
taxes, save and load. Good: numbers you can see change, slow growth.

## Survival and crafting [third-person-3d or rpg-topdown]
Gather (hit trees and rocks), craft from recipes (Resources with inputs and
outputs), hunger, thirst, health, day and night (rotate the sun, change the
sky), build with snap points, enemies at night, chunks of world. Good: a
first night that teaches everything.

## Sandbox / voxel world
Chunks of blocks (16x16x16) built into an ArrayMesh with only visible faces,
FastNoiseLite heights and caves, place and break with a RayCast3D, save
changed chunks only, build meshes on a thread (WorkerThreadPool). See demo
`3d/voxel`. Good: biomes, a far view.

## Evolving world / god game
A world that changes on its own: a simulation tick advances seasons,
weather, plant growth, animals that eat and breed, towns that grow, a
history log of events. Keep the world as data (Arrays/Dictionaries), draw
from it, save it. The player nudges it (place, bless, destroy). Good:
surprises the player didn't cause, and a timeline to read.

## Story game / visual novel
Dialogue as data (a JSON or Resource list of lines with speaker, text,
choices and the flags they set), RichTextLabel with typing effect,
portraits, backgrounds, save slots, a lore codex the player unlocks, and
endings chosen by flags. Good: choices that come back later.

## Rhythm and music
Notes from a chart (time, lane); song position from
`AudioStreamPlayer.get_playback_position()` plus latency
(`AudioServer.get_time_since_last_mix()`); timing windows (perfect, good,
miss); combos. See demo `audio/rhythm_game`. Good: tight timing, juicy hits.

## Fighting
Two players (keyboard split or two pads), frame-based state machine
(startup, active, recovery frames at a fixed 60 fps), hitboxes and
hurtboxes as Area2D, hit stun and block stun, combos, a round timer, special
moves from input buffers (down, forward, punch). Good: every move has a
counter.

## Card and board games
Cards as Resources, a rules engine in plain code (whose turn, legal moves),
Control nodes for the hand with drag and drop, an AI that scores moves.
Good: clear feedback for every rule.

## Party, sports, idle, horror, stealth and more
Mix the pieces above: sports use rigid bodies and simple AI; idle games are
numbers that grow with upgrades and offline progress; horror is light,
sound and pacing (OmniLight3D flicker, fog); stealth is vision cones
(RayCast checks) and alert states.
