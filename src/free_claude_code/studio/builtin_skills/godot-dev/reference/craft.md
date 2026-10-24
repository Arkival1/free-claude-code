# Looks, animation, physics, worlds and story (Godot 4)

## Art styles
- Pixel art: low viewport (e.g. 480x270) with `window/stretch/mode="canvas_items"`,
  nearest filtering (`default_texture_filter=0`), a small palette, whole-pixel
  movement for crisp sprites.
- Hand-drawn / painterly: big textures, linear filtering, soft
  `PointLight2D`s, a paper-grain shader on a full-screen ColorRect.
- Low-poly 3D: simple meshes (BoxMesh, CylinderMesh, or imported .glb),
  flat colours in `StandardMaterial3D`, a sun with shadows, distance fog.
- Toon / cel: a spatial shader that bands the light:
  `float l = dot(NORMAL, LIGHT); DIFFUSE_LIGHT += step(0.3, l) * ATTENUATION * LIGHT_COLOR;`
  plus an outline (a second pass with `cull_front` and the mesh grown).
- Neon: black background, bright emissive colours, `Environment.glow_enabled`
  (3D) or a WorldEnvironment with glow in 2D (Compatibility renderer: enable
  HDR 2D).
- Realistic PBR: Forward+ renderer, `StandardMaterial3D` with albedo,
  normal, roughness and metallic maps, SDFGI or VoxelGI, volumetric fog,
  ACES or AgX tonemapping.
- Isometric: TileSet with `tile_shape` isometric and Y-sort on.
- Voxel: see the sandbox genre.
Materials: wood, stone, metal, glass, water and lava come from roughness,
metallic, emission and a scrolling noise texture in a shader. Demos:
`3d/material_testers`, `3d/procedural_materials`, `2d/sprite_shaders`.

## Animation
- Sprites: `AnimatedSprite2D` with SpriteFrames (make them in code from a
  sheet: `SpriteFrames.new()`, `add_animation`, `add_frame` with
  `AtlasTexture`s), or Sprite2D region frames as in the starters.
- Keyframes: `AnimationPlayer` for doors, cutscenes, UI, attacks.
- Blending: `AnimationTree` with a BlendSpace1D/2D for walk to run, and a
  state machine for jump, fall, attack.
- Bones: `Skeleton2D` for cut-out characters; 3D models from .glb with their
  own animations; inverse kinematics for feet and aiming (demo `3d/ik`).
- Juice with Tweens: squash and stretch, pop-ins, number counters, shakes
  (`camera.offset` with random jitter that fades).
- Particles: `GPUParticles2D/3D` (or `CPUParticles` on old PCs) for dust,
  sparks, magic, fire, rain; one-shot bursts on hits and pickups.

## Physics
- Characters: CharacterBody with acceleration, friction, gravity; slopes via
  `floor_max_angle`; moving platforms carry the body automatically.
- Props: RigidBody2D/3D, joints (PinJoint, HingeJoint3D, Generic6DOF),
  ragdolls (demo `3d/ragdoll_physics`), soft bodies (cloth, jelly).
- Vehicles: VehicleBody3D + VehicleWheel3D (suspension stiffness, friction).
- Queries: RayCast2D/3D, ShapeCast, `PhysicsDirectSpaceState` for line of sight.
- Collision layers and masks for teams (player, enemies, bullets, world).
- `physics/common/physics_interpolation` for smooth motion at any frame rate.

## Worlds
- TileMapLayer per layer (ground, decoration, collision); terrain sets for
  auto-tiling; Y-sort for top-down depth.
- Procedural: FastNoiseLite (heights, caves, biomes), seeded RNG, BSP rooms,
  cellular automata caves; chunks that load around the player.
- Evolving: keep the world state as data, advance it on a Timer tick
  (growth, seasons, AI needs), draw from the data, save it to user://.
- Day and night: rotate the DirectionalLight3D, lerp the sky colours, swap
  ambient sounds.
- Navigation: NavigationRegion + NavigationAgent (avoidance on), AStarGrid2D
  for grids (demo `2d/navigation_astar`).

## Story and lore
- Dialogue data (JSON or Resources): id, speaker, text, choices with
  `next` and `set_flag`; a dialogue box with RichTextLabel and portraits.
- Flags and quests in an autoload; journal and codex screens that fill in.
- Cutscenes with AnimationPlayer (camera moves, text, sound) and `await`.
- Characters remember: store relationship values and check them in lines.
- Lore: write a short bible first (world, factions, history, three
  characters with wants), then put pieces of it in items, signs and lines.

## Sound
`AudioStreamPlayer` (UI, music), `AudioStreamPlayer2D/3D` (in the world),
buses with effects (reverb in caves), music that changes with the action.
Kenney's sound packs through `game_assets`.
