extends Node3D
## The Ember Temple at dusk: a valley with a stone path between torches and
## burning trees, a ring of ruined pillars round the arena, a five-tier
## pagoda, a still pond, wind in the grass, embers in the air and mist on
## the ground. The bonfire is your checkpoint; the Ember Warden waits in the
## arena. Change the place in WORLD, the surfaces in look.gd, the fight in
## player.gd and boss.gd. F2 cycles the graphics: Low, Medium, High, Ultra.

const Look := preload("res://look.gd")
const PlayerScript := preload("res://player.gd")
const BossScript := preload("res://boss.gd")
const RigScript := preload("res://camera_rig.gd")
const HudScript := preload("res://hud.gd")

const WORLD := {
	"size": 170.0,
	"cells": 150,
	"arena": Vector3(0, 0, -14),
	"arena_radius": 17.0,
	"spawn": Vector3(0, 0, 31),
	"bonfire": Vector3(2.8, 0, 26),
	"pagoda": Vector3(0, 0, -52),
	"pond": Vector3(25, 0, 9),
	"pond_radius": 7.5,
	"sun": Color("#ffa765"),
	"sky_top": Color("#121833"),
	"horizon": Color("#d9623d"),
	"fog": Color("#8a5a4a"),
}
const GRAPHICS := ["Low", "Medium", "High", "Ultra"]

var graphics := 2
var height_noise := Look.noise(5, 0.012, 4)
var environment: Environment
var sun: DirectionalLight3D
var grass: MultiMeshInstance3D
var player: CharacterBody3D
var boss: CharacterBody3D
var rig: Node3D
var hud: CanvasLayer
var sparks: GPUParticles3D
var flames: Array[OmniLight3D] = []
var won := false
var _boss_awake := false
var _last_hp := 100.0
var _clock := 0.0
var _rng := RandomNumberGenerator.new()


func _ready() -> void:
	_rng.seed = 2024
	_add_inputs()
	_add_sky_and_light()
	_add_terrain()
	_add_pond()
	_add_arena()
	_add_pagoda()
	_add_trees()
	_add_grass()
	_add_rocks()
	_add_torches()
	_add_bonfire()
	_add_air()
	player = PlayerScript.new()
	add_child(player)
	var spawn: Vector3 = WORLD["spawn"]
	player.global_position = Vector3(spawn.x, height_at(spawn.x, spawn.z) + 0.2, spawn.z)
	boss = BossScript.new()
	add_child(boss)
	var arena: Vector3 = WORLD["arena"]
	boss.global_position = Vector3(arena.x, 0.2, arena.z - 3.0)
	boss.set("home", boss.global_position)
	boss.set("player", player)
	player.set("target", boss)
	rig = RigScript.new()
	add_child(rig)
	rig.call("follow", player)
	hud = HudScript.new()
	add_child(hud)
	sparks = Look.sparks()
	add_child(sparks)
	player.connect("changed", _on_player_changed)
	player.connect("died", _on_player_died)
	player.connect("struck", _on_struck)
	boss.connect("changed", _on_boss_changed)
	boss.connect("woke", _on_boss_woke)
	boss.connect("defeated", _on_boss_defeated)
	boss.connect("slammed", _on_slammed)
	apply_graphics()
	_on_player_changed()
	_on_boss_changed()


# ------------------------------------------------------------------ ground

func path_x(z: float) -> float:
	return sin(z * 0.075) * 3.2


## How much of the stone path is here (0..1).
func path_mask(x: float, z: float) -> float:
	if z > 46.0 or z < -62.0:
		return 0.0
	return 1.0 - smoothstep(2.2, 4.6, absf(x - path_x(z)))


func height_at(x: float, z: float) -> float:
	var h := height_noise.get_noise_2d(x, z) * 5.0
	h += maxf(0.0, Vector2(x, z).length() - 48.0) * 0.34
	var arena: Vector3 = WORLD["arena"]
	var radius: float = WORLD["arena_radius"]
	var flat := 1.0 - smoothstep(radius + 2.0, radius + 10.0, Vector2(x - arena.x, z - arena.z).length())
	h = lerpf(h, 0.0, flat)
	h = lerpf(h, h * 0.25, path_mask(x, z))
	var pagoda: Vector3 = WORLD["pagoda"]
	h = lerpf(h, 0.0, 1.0 - smoothstep(10.0, 16.0, Vector2(x - pagoda.x, z - pagoda.z).length()))
	var pond: Vector3 = WORLD["pond"]
	var pond_radius: float = WORLD["pond_radius"]
	h -= (1.0 - smoothstep(pond_radius - 2.5, pond_radius + 1.5, Vector2(x - pond.x, z - pond.z).length())) * 1.7
	return h


func _add_terrain() -> void:
	var size: float = WORLD["size"]
	var cells: int = WORLD["cells"]
	var arena: Vector3 = WORLD["arena"]
	var radius: float = WORLD["arena_radius"]
	var step := size / cells
	var tool := SurfaceTool.new()
	tool.begin(Mesh.PRIMITIVE_TRIANGLES)
	for iz in cells + 1:
		for ix in cells + 1:
			var x := -size / 2.0 + ix * step
			var z := -size / 2.0 + iz * step
			var worn := 1.0 - smoothstep(radius - 1.0, radius + 4.0, Vector2(x - arena.x, z - arena.z).length())
			tool.set_color(Color(maxf(path_mask(x, z), worn), 0, 0))
			tool.set_uv(Vector2(ix, iz) / cells)
			tool.add_vertex(Vector3(x, height_at(x, z), z))
	for iz in cells:
		for ix in cells:
			var a := iz * (cells + 1) + ix
			var c := a + cells + 1
			for index: int in [a, a + 1, c, a + 1, c + 1, c]:
				tool.add_index(index)
	tool.generate_normals()
	tool.generate_tangents()
	var mesh := tool.commit()
	var ground := ShaderMaterial.new()
	ground.shader = preload("res://terrain.gdshader")
	ground.set_shader_parameter("grass_tex", Look.texture("grass", 31, "color"))
	ground.set_shader_parameter("dirt_tex", Look.texture("dirt", 32, "color"))
	ground.set_shader_parameter("rock_tex", Look.texture("rock", 33, "color"))
	ground.set_shader_parameter("bumps", Look.texture("rock", 34, "normal"))
	var land := MeshInstance3D.new()
	land.mesh = mesh
	land.material_override = ground
	add_child(land)
	var body := StaticBody3D.new()
	var shape := CollisionShape3D.new()
	shape.shape = mesh.create_trimesh_shape()
	body.add_child(shape)
	add_child(body)


func _add_pond() -> void:
	var pond: Vector3 = WORLD["pond"]
	var water := MeshInstance3D.new()
	var plane := PlaneMesh.new()
	var radius: float = WORLD["pond_radius"]
	plane.size = Vector2(radius * 2.4, radius * 2.4)
	plane.subdivide_width = 24
	plane.subdivide_depth = 24
	var material := ShaderMaterial.new()
	material.shader = preload("res://water.gdshader")
	plane.material = material
	water.mesh = plane
	water.position = Vector3(pond.x, -0.75, pond.z)
	water.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	add_child(water)


# ------------------------------------------------------------------ places

func _solid(mesh: Mesh, material: Material, at: Vector3, shape: Shape3D = null, turn := Vector3.ZERO) -> MeshInstance3D:
	var item := MeshInstance3D.new()
	item.mesh = mesh
	item.material_override = material
	if shape:
		var body := StaticBody3D.new()
		body.position = at
		body.rotation = turn
		var collider := CollisionShape3D.new()
		collider.shape = shape
		body.add_child(collider)
		body.add_child(item)
		add_child(body)
	else:
		item.position = at
		item.rotation = turn
		add_child(item)
	return item


func _box(size: Vector3) -> BoxMesh:
	var mesh := BoxMesh.new()
	mesh.size = size
	return mesh


func _box_shape(size: Vector3) -> BoxShape3D:
	var shape := BoxShape3D.new()
	shape.size = size
	return shape


func _cylinder(top: float, bottom: float, height: float, sides := 20) -> CylinderMesh:
	var mesh := CylinderMesh.new()
	mesh.top_radius = top
	mesh.bottom_radius = bottom
	mesh.height = height
	mesh.radial_segments = sides
	return mesh


func _cylinder_shape(radius: float, height: float) -> CylinderShape3D:
	var shape := CylinderShape3D.new()
	shape.radius = radius
	shape.height = height
	return shape


func _add_arena() -> void:
	var arena: Vector3 = WORLD["arena"]
	var radius: float = WORLD["arena_radius"]
	var stone := Look.surface("stone", 3, 0.35)
	var moss := Look.surface("moss", 4, 0.4)
	_solid(_cylinder(radius - 1.5, radius - 1.2, 0.5, 64), stone, arena + Vector3(0, -0.2, 0), _cylinder_shape(radius - 1.2, 0.5))
	for i in 14:
		var angle := TAU * i / 14.0 + 0.11
		if absf(wrapf(angle - PI / 2.0, -PI, PI)) < 0.25:
			continue
		var at := arena + Vector3(cos(angle) * (radius + 1.8), 0, sin(angle) * (radius + 1.8))
		var broken := i % 3 == 1
		var tall := 2.6 if broken else _rng.randf_range(6.0, 7.5)
		_solid(_box(Vector3(2.0, 0.7, 2.0)), moss, at + Vector3(0, 0.35, 0), _box_shape(Vector3(2.0, 0.7, 2.0)))
		_solid(_cylinder(0.6, 0.72, tall, 16), stone, at + Vector3(0, 0.7 + tall / 2.0, 0), _cylinder_shape(0.72, tall))
		if broken:
			_solid(_cylinder(0.6, 0.6, 3.6, 16), stone, at + Vector3(_rng.randf_range(-2.5, 2.5), 0.6, _rng.randf_range(1.0, 2.5)), _cylinder_shape(0.6, 3.6), Vector3(0, _rng.randf() * TAU, PI / 2.0))
		else:
			_solid(_box(Vector3(1.8, 0.6, 1.8)), stone, at + Vector3(0, 0.7 + tall + 0.3, 0))
	# The gate on the path into the arena, with a torn banner.
	var gate := arena + Vector3(0, 0, radius + 4.0)
	for side: float in [-1.0, 1.0]:
		_solid(_box(Vector3(1.6, 8.0, 1.6)), stone, gate + Vector3(side * 4.2, 4.0, 0), _box_shape(Vector3(1.6, 8.0, 1.6)))
	_solid(_box(Vector3(11.0, 1.2, 2.0)), stone, gate + Vector3(0, 8.4, 0))
	_solid(_box(Vector3(9.4, 0.25, 2.2)), Look.surface("roof", 5, 0.6), gate + Vector3(0, 9.1, 0))
	_solid(_box(Vector3(2.4, 4.2, 0.05)), Look.surface("cloth", 6, 0.8), gate + Vector3(0, 5.6, 0.2))


func _add_pagoda() -> void:
	var at: Vector3 = WORLD["pagoda"]
	var stone := Look.surface("stone", 7, 0.35)
	var wood := Look.surface("wood", 8, 0.5)
	var roof := Look.surface("roof", 9, 0.5)
	var gold := Look.surface("gold", 10, 1.0)
	_solid(_box(Vector3(18, 1.6, 18)), stone, at + Vector3(0, 0.8, 0), _box_shape(Vector3(18, 1.6, 18)))
	for step in 5:
		_solid(_box(Vector3(8, 0.32, 1.2)), stone, at + Vector3(0, 0.16 + step * 0.32, 9.0 + (4 - step) * 1.1), _box_shape(Vector3(8, 0.32, 1.2)))
	var y := 1.6
	for tier in 5:
		var width := 10.0 - tier * 1.45
		var wall := 2.6 - tier * 0.22
		_solid(_box(Vector3(width, wall, width)), wood, at + Vector3(0, y + wall / 2.0, 0), _box_shape(Vector3(width, wall, width)) if tier == 0 else null)
		_solid(_box(Vector3(width + 0.3, 0.18, width + 0.3)), gold, at + Vector3(0, y + wall, 0))
		var eaves := _solid(_cylinder(width * 0.38, width * 0.98, 1.4, 4), roof, at + Vector3(0, y + wall + 0.7, 0))
		eaves.rotation.y = PI / 4.0
		if tier < 2:
			for corner: Vector2 in [Vector2(1, 1), Vector2(-1, 1), Vector2(1, -1), Vector2(-1, -1)]:
				var lamp := at + Vector3(corner.x * width * 0.62, y + wall + 0.1, corner.y * width * 0.62)
				_solid(_box(Vector3(0.35, 0.5, 0.35)), Look.glow(Color("#ffb04a"), 4.0), lamp)
			var light := OmniLight3D.new()
			light.light_color = Color("#ff9a45")
			light.light_energy = 2.4
			light.omni_range = 14.0
			light.position = at + Vector3(0, y + wall, width * 0.62)
			add_child(light)
			flames.append(light)
		y += wall + 1.1
	_solid(_cylinder(0.08, 0.2, 3.2, 10), gold, at + Vector3(0, y + 1.6, 0))
	var orb := SphereMesh.new()
	orb.radius = 0.3
	orb.height = 0.6
	_solid(orb, Look.glow(Color("#ffcf7a"), 5.0), at + Vector3(0, y + 3.3, 0))


func _add_trees() -> void:
	var arena: Vector3 = WORLD["arena"]
	var radius: float = WORLD["arena_radius"]
	var pond: Vector3 = WORLD["pond"]
	var pagoda: Vector3 = WORLD["pagoda"]
	var placed := 0
	var tries := 0
	while placed < 95 and tries < 1500:
		tries += 1
		var angle := _rng.randf() * TAU
		var distance := _rng.randf_range(24.0, 80.0)
		var x := cos(angle) * distance
		var z := sin(angle) * distance
		if path_mask(x, z) > 0.02 or absf(x - path_x(z)) < 6.0 and z > -60.0 and z < 46.0:
			continue
		if Vector2(x - arena.x, z - arena.z).length() < radius + 6.0 or Vector2(x - pond.x, z - pond.z).length() < 11.0 or Vector2(x - pagoda.x, z - pagoda.z).length() < 16.0:
			continue
		_tree(Vector3(x, height_at(x, z), z), _rng.randf() < 0.55, false)
		placed += 1
	for i in 8:
		var angle := TAU * (i + 0.5) / 8.0
		if absf(wrapf(angle - PI / 2.0, -PI, PI)) < 0.5:
			continue
		var x := arena.x + cos(angle) * (radius + 8.0)
		var z := arena.z + sin(angle) * (radius + 8.0)
		_tree(Vector3(x, height_at(x, z), z), false, true)


func _tree(at: Vector3, pine: bool, burning: bool) -> void:
	var tall := _rng.randf_range(5.5, 9.0)
	var trunk := _cylinder(0.16, 0.38, tall, 10)
	_solid(trunk, Look.surface("bark", 11, 0.6), at + Vector3(0, tall / 2.0, 0), _cylinder_shape(0.38, tall))
	if pine:
		var needles := Look.surface("pine", 12, 0.6)
		for layer in 4:
			var width := 2.8 - layer * 0.55
			_solid(_cylinder(0.0, width, 2.8, 12), needles, at + Vector3(0, tall * 0.42 + layer * 1.35, 0))
		return
	var leaves := Look.surface("autumn", 13, 0.6)
	if burning:
		leaves = leaves.duplicate() as StandardMaterial3D
		leaves.emission_enabled = true
		leaves.emission = Color("#ff5a14")
		leaves.emission_energy_multiplier = 0.6
	for i in 6:
		var ball := SphereMesh.new()
		var size := _rng.randf_range(1.4, 2.3)
		ball.radius = size
		ball.height = size * 1.7
		ball.radial_segments = 12
		ball.rings = 8
		_solid(ball, leaves, at + Vector3(_rng.randf_range(-1.4, 1.4), tall * 0.85 + _rng.randf_range(-0.6, 1.4), _rng.randf_range(-1.4, 1.4)))
	if burning:
		var fire := Look.fire(2.4)
		fire.position = at + Vector3(0, tall * 0.9, 0)
		add_child(fire)
		var smoke := Look.smoke(2.0)
		smoke.position = at + Vector3(0, tall + 1.5, 0)
		add_child(smoke)
		var light := OmniLight3D.new()
		light.light_color = Color("#ff6a1f")
		light.light_energy = 2.2
		light.omni_range = 11.0
		light.position = at + Vector3(0, tall * 0.8, 0)
		add_child(light)
		flames.append(light)


func _blade() -> ArrayMesh:
	var tool := SurfaceTool.new()
	tool.begin(Mesh.PRIMITIVE_TRIANGLES)
	tool.set_normal(Vector3(0, 1, 0.35).normalized())
	var rows := [[0.0, 0.035], [0.4, 0.027], [0.75, 0.014]]
	for row: Array in rows:
		for side: float in [-1.0, 1.0]:
			tool.set_uv(Vector2(0.5 + side * 0.5, row[0]))
			tool.add_vertex(Vector3(side * float(row[1]), float(row[0]) * 0.55, 0))
	tool.set_uv(Vector2(0.5, 1.0))
	tool.add_vertex(Vector3(0, 0.55, 0.03))
	for index: int in [0, 1, 2, 1, 3, 2, 2, 3, 4, 3, 5, 4, 4, 5, 6]:
		tool.add_index(index)
	return tool.commit()


func _add_grass() -> void:
	var arena: Vector3 = WORLD["arena"]
	var radius: float = WORLD["arena_radius"]
	var pond: Vector3 = WORLD["pond"]
	var pagoda: Vector3 = WORLD["pagoda"]
	var blades := MultiMesh.new()
	blades.transform_format = MultiMesh.TRANSFORM_3D
	blades.use_colors = true
	blades.mesh = _blade()
	var spots: Array[Transform3D] = []
	var tints: Array[Color] = []
	var tries := 0
	while spots.size() < 60000 and tries < 200000:
		tries += 1
		# Thick where you walk and fight, thinner out in the hills.
		var reach := 46.0 if tries % 3 else 72.0
		var x := _rng.randf_range(-reach, reach)
		var z := _rng.randf_range(-reach, minf(reach, 60.0))
		if path_mask(x, z) > 0.15 or Vector2(x - arena.x, z - arena.z).length() < radius + 0.5:
			continue
		if Vector2(x - pond.x, z - pond.z).length() < 8.0 or Vector2(x - pagoda.x, z - pagoda.z).length() < 10.0:
			continue
		var basis := Basis(Vector3.UP, _rng.randf() * TAU).scaled(Vector3(1.0, _rng.randf_range(0.55, 1.35), 1.0) * _rng.randf_range(0.8, 1.25))
		spots.append(Transform3D(basis, Vector3(x, height_at(x, z) - 0.02, z)))
		var shade := _rng.randf_range(0.82, 1.18)
		tints.append(Color(shade * _rng.randf_range(0.95, 1.1), shade, shade * 0.9))
	blades.instance_count = spots.size()
	for i in spots.size():
		blades.set_instance_transform(i, spots[i])
		blades.set_instance_color(i, tints[i])
	grass = MultiMeshInstance3D.new()
	grass.multimesh = blades
	grass.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	var material := ShaderMaterial.new()
	material.shader = preload("res://grass.gdshader")
	grass.material_override = material
	add_child(grass)


func _rock_mesh(seed_value: int) -> ArrayMesh:
	var ball := SphereMesh.new()
	ball.radius = 1.0
	ball.height = 2.0
	ball.radial_segments = 12
	ball.rings = 7
	var arrays := ball.get_mesh_arrays()
	var points: PackedVector3Array = arrays[Mesh.ARRAY_VERTEX]
	var lumps := Look.noise(seed_value, 0.9, 3)
	for i in points.size():
		var p := points[i]
		var push := 1.0 + lumps.get_noise_3d(p.x * 2.0, p.y * 2.0, p.z * 2.0) * 0.45
		points[i] = Vector3(p.x * push, maxf(p.y, -0.35) * push * 0.75, p.z * push)
	arrays[Mesh.ARRAY_VERTEX] = points
	arrays[Mesh.ARRAY_NORMAL] = null
	arrays[Mesh.ARRAY_TANGENT] = null
	var raw := ArrayMesh.new()
	raw.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arrays)
	var tool := SurfaceTool.new()
	tool.create_from(raw, 0)
	tool.deindex()
	tool.generate_normals()
	tool.generate_tangents()
	return tool.commit()


func _add_rocks() -> void:
	var shapes: Array[ArrayMesh] = []
	for i in 5:
		shapes.append(_rock_mesh(40 + i))
	var stone := Look.surface("rock", 14, 0.45)
	var moss := Look.surface("moss", 15, 0.5)
	var arena: Vector3 = WORLD["arena"]
	var radius: float = WORLD["arena_radius"]
	for i in 34:
		var x := _rng.randf_range(-62.0, 62.0)
		var z := _rng.randf_range(-62.0, 52.0)
		if path_mask(x, z) > 0.05 or Vector2(x - arena.x, z - arena.z).length() < radius + 3.0:
			continue
		var size := _rng.randf_range(0.6, 2.6)
		var rock := _solid(shapes[i % shapes.size()], moss if i % 3 == 0 else stone, Vector3(x, height_at(x, z) + size * 0.2, z), _box_shape(Vector3(size * 1.4, size, size * 1.4)), Vector3(0, _rng.randf() * TAU, 0))
		rock.scale = Vector3.ONE * size


func _add_torches() -> void:
	var z := 42.0
	var side := 1.0
	while z > 6.0:
		var x := path_x(z) + side * 3.4
		var at := Vector3(x, height_at(x, z), z)
		_solid(_cylinder(0.08, 0.12, 2.2, 8), Look.surface("wood", 16, 1.0), at + Vector3(0, 1.1, 0))
		_solid(_cylinder(0.32, 0.18, 0.3, 10), Look.surface("steel", 17, 1.0), at + Vector3(0, 2.3, 0))
		var fire := Look.fire(0.6)
		fire.position = at + Vector3(0, 2.55, 0)
		add_child(fire)
		var light := OmniLight3D.new()
		light.light_color = Color("#ff8a3d")
		light.light_energy = 1.7
		light.omni_range = 8.0
		light.position = at + Vector3(0, 2.8, 0)
		add_child(light)
		flames.append(light)
		z -= 11.0
		side = -side


func _add_bonfire() -> void:
	var at: Vector3 = WORLD["bonfire"]
	at.y = height_at(at.x, at.z)
	var wood := Look.surface("bark", 18, 1.0)
	for i in 3:
		var log_turn := Vector3(0.35, TAU * i / 3.0, PI / 2.0 - 0.3)
		_solid(_cylinder(0.12, 0.14, 1.6, 8), wood, at + Vector3(0, 0.3, 0), null, log_turn)
	for i in 9:
		var angle := TAU * i / 9.0
		var pebble := _solid(_rock_mesh(60 + i % 3), Look.surface("rock", 19, 1.0), at + Vector3(cos(angle) * 1.0, 0.08, sin(angle) * 1.0))
		pebble.scale = Vector3.ONE * 0.28
	_solid(_box(Vector3(0.06, 1.5, 0.02)), Look.surface("steel", 20, 1.0), at + Vector3(0, 0.9, 0), null, Vector3(0.2, 0.4, 0.1))
	var fire := Look.fire(1.3)
	fire.position = at + Vector3(0, 0.4, 0)
	add_child(fire)
	var smoke := Look.smoke(1.2)
	smoke.position = at + Vector3(0, 1.6, 0)
	add_child(smoke)
	var light := OmniLight3D.new()
	light.light_color = Color("#ff8f3f")
	light.light_energy = 3.2
	light.omni_range = 13.0
	light.shadow_enabled = true
	light.position = at + Vector3(0, 1.2, 0)
	add_child(light)
	flames.append(light)


func _add_air() -> void:
	var arena: Vector3 = WORLD["arena"]
	var embers := Look.embers(Vector3(60, 6, 80), 420)
	embers.position = arena + Vector3(0, 2.0, 10)
	add_child(embers)
	if RenderingServer.get_current_rendering_method() == "forward_plus":
		for spot: Vector3 in [arena, arena + Vector3(0, 0, 24), Vector3(WORLD["pond"])]:
			var mist := FogVolume.new()
			mist.size = Vector3(46, 3.0, 40)
			mist.shape = RenderingServer.FOG_VOLUME_SHAPE_BOX
			var material := FogMaterial.new()
			material.density = 0.22
			material.albedo = Color("#e9c2a6")
			material.height_falloff = 1.6
			material.edge_fade = 0.6
			mist.material = material
			mist.position = spot + Vector3(0, 0.6, 0)
			add_child(mist)


# ------------------------------------------------------------------ sky, light, graphics

func _add_sky_and_light() -> void:
	var sky_material := ProceduralSkyMaterial.new()
	sky_material.sky_top_color = WORLD["sky_top"]
	sky_material.sky_horizon_color = WORLD["horizon"]
	sky_material.sky_curve = 0.12
	sky_material.ground_horizon_color = WORLD["horizon"]
	sky_material.ground_bottom_color = Color("#140d0f")
	sky_material.sun_angle_max = 22.0
	sky_material.sun_curve = 0.08
	sky_material.energy_multiplier = 1.1
	var sky := Sky.new()
	sky.sky_material = sky_material
	environment = Environment.new()
	environment.background_mode = Environment.BG_SKY
	environment.sky = sky
	environment.ambient_light_source = Environment.AMBIENT_SOURCE_SKY
	environment.ambient_light_energy = 0.4
	environment.reflected_light_source = Environment.REFLECTION_SOURCE_SKY
	environment.tonemap_mode = Environment.TONE_MAPPER_AGX
	environment.tonemap_exposure = 1.05
	environment.glow_enabled = true
	environment.glow_intensity = 0.75
	environment.glow_bloom = 0.06
	environment.glow_hdr_threshold = 0.95
	environment.glow_blend_mode = Environment.GLOW_BLEND_MODE_SOFTLIGHT
	environment.fog_enabled = true
	environment.fog_light_color = WORLD["fog"]
	environment.fog_light_energy = 0.45
	environment.fog_sun_scatter = 0.3
	environment.fog_density = 0.0042
	environment.fog_aerial_perspective = 0.3
	environment.fog_sky_affect = 0.45
	environment.fog_height = 1.5
	environment.fog_height_density = 0.12
	environment.volumetric_fog_density = 0.016
	environment.volumetric_fog_albedo = Color("#e8b49a")
	environment.volumetric_fog_emission = Color("#2a0f08")
	environment.volumetric_fog_emission_energy = 0.35
	environment.volumetric_fog_anisotropy = 0.55
	environment.volumetric_fog_length = 90.0
	environment.ssao_intensity = 1.7
	environment.ssao_radius = 1.2
	environment.adjustment_enabled = true
	environment.adjustment_contrast = 1.14
	environment.adjustment_saturation = 1.02
	var world := WorldEnvironment.new()
	world.environment = environment
	add_child(world)
	sun = DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-16.0, 148.0, 0.0)
	sun.light_color = WORLD["sun"]
	sun.light_energy = 2.0
	sun.light_angular_distance = 1.2
	sun.shadow_enabled = true
	sun.shadow_blur = 1.2
	sun.directional_shadow_max_distance = 140.0
	add_child(sun)
	var fill := DirectionalLight3D.new()
	fill.rotation_degrees = Vector3(-40.0, -25.0, 0.0)
	fill.light_color = Color("#4a6ab8")
	fill.light_energy = 0.45
	fill.sky_mode = DirectionalLight3D.SKY_MODE_LIGHT_ONLY
	add_child(fill)


## Low, Medium, High (the default) or Ultra; the heavy effects need the
## Forward+ renderer (a real graphics card).
func apply_graphics() -> void:
	var forward := RenderingServer.get_current_rendering_method() == "forward_plus"
	environment.ssao_enabled = forward and graphics >= 1
	environment.ssil_enabled = forward and graphics >= 2
	environment.volumetric_fog_enabled = forward and graphics >= 1
	environment.sdfgi_enabled = forward and graphics >= 3
	environment.ssr_enabled = forward and graphics >= 3
	environment.glow_enabled = graphics >= 1
	sun.directional_shadow_mode = DirectionalLight3D.SHADOW_PARALLEL_4_SPLITS if graphics >= 2 else DirectionalLight3D.SHADOW_PARALLEL_2_SPLITS
	grass.multimesh.visible_instance_count = [12000, 30000, -1, -1][graphics]
	get_viewport().msaa_3d = [Viewport.MSAA_DISABLED, Viewport.MSAA_2X, Viewport.MSAA_2X, Viewport.MSAA_4X][graphics]
	if hud:
		hud.get("info").text = "Graphics: %s · renderer %s · F2 to change" % [GRAPHICS[graphics], RenderingServer.get_current_rendering_method()]


# ------------------------------------------------------------------ the game

func _process(delta: float) -> void:
	_clock += delta
	for i in flames.size():
		var light := flames[i]
		if not light.has_meta("base"):
			light.set_meta("base", light.light_energy)
		light.light_energy = float(light.get_meta("base")) * (0.85 + 0.15 * sin(_clock * 11.0 + i * 1.7) + 0.05 * sin(_clock * 23.0 + i))
	player.set("camera_yaw", rig.get("yaw"))
	var bonfire: Vector3 = WORLD["bonfire"]
	var near := Vector2(player.global_position.x - bonfire.x, player.global_position.z - bonfire.z).length() < 2.8
	hud.get("prompt").text = "E  Rest at the bonfire" if near and not player.call("dead") else ""
	if near and Input.is_action_just_pressed("interact") and not player.call("dead"):
		player.call("refill")
		if not won:
			_boss_awake = false
			boss.call("reset")
			_lock(false)
			_on_boss_changed()
		hud.call("say", "BONFIRE LIT", Color("#f0c27a"), 2.0)
	if Input.is_action_just_pressed("lock"):
		var close := player.global_position.distance_to(boss.global_position) < 32.0
		_lock(not bool(player.get("locked")) and _boss_awake and close and not boss.call("is_dead"))
	if bool(player.get("locked")) and boss.call("is_dead"):
		_lock(false)


func _lock(on: bool) -> void:
	player.set("locked", on)
	rig.set("locked", on)
	rig.set("target", boss if on else null)


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseButton and (event as InputEventMouseButton).pressed and Input.mouse_mode != Input.MOUSE_MODE_CAPTURED:
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED
	elif event.is_action_pressed("ui_cancel"):
		Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
	elif event.is_action_pressed("graphics"):
		graphics = (graphics + 1) % GRAPHICS.size()
		apply_graphics()
		hud.call("say", "Graphics: " + GRAPHICS[graphics], Color("#e8dcc8"), 1.0)
	elif event.is_action_pressed("info"):
		var info: Label = hud.get("info")
		info.visible = not info.visible


func _on_player_changed() -> void:
	var hp: float = player.get("hp")
	hud.call("show_player", hp, player.get("max_hp"), player.get("stamina"), player.get("max_stamina"), player.get("flasks"), player.get("max_flasks"))
	if hp < _last_hp:
		hud.call("flash")
		rig.call("shake", 0.6)
	_last_hp = hp


func _on_player_died() -> void:
	_lock(false)
	hud.call("say", "FALLEN", Color("#b3261e"), 2.5)
	await get_tree().create_timer(4.0).timeout
	var bonfire: Vector3 = WORLD["bonfire"]
	player.call("revive", Vector3(bonfire.x, height_at(bonfire.x, bonfire.z) + 0.3, bonfire.z + 1.8))
	_last_hp = player.get("hp")
	if not won:
		_boss_awake = false
		boss.call("reset")
		_on_boss_changed()


func _on_struck(where: Vector3, heavy: bool) -> void:
	sparks.global_position = where
	sparks.restart()
	rig.call("shake", 0.5 if heavy else 0.25)


func _on_boss_changed() -> void:
	hud.call("show_boss", BossScript.NAME, boss.get("hp"), boss.get("max_hp"), _boss_awake and not won)


func _on_boss_woke() -> void:
	_boss_awake = true
	_on_boss_changed()
	rig.call("shake", 0.8)


func _on_boss_defeated() -> void:
	won = true
	_lock(false)
	_on_boss_changed()
	hud.call("say", "VICTORY", Color("#f0c27a"), 4.0)
	var burst := Look.embers(Vector3(8, 3, 8), 300)
	add_child(burst)
	burst.global_position = boss.global_position + Vector3(0, 1.5, 0)


func _on_slammed(where: Vector3, strength: float) -> void:
	var near := clampf(1.0 - player.global_position.distance_to(where) / 18.0, 0.0, 1.0)
	rig.call("shake", strength * near)
	sparks.global_position = where + Vector3(0, 0.3, 0)
	sparks.restart()


# ------------------------------------------------------------------ controls

func _add_inputs() -> void:
	var keys := {
		"left": [KEY_A], "right": [KEY_D], "forward": [KEY_W], "back": [KEY_S],
		"run": [KEY_SHIFT], "roll": [KEY_SPACE], "heal": [KEY_F], "lock": [KEY_Q], "interact": [KEY_E],
		"graphics": [KEY_F2], "info": [KEY_F3], "attack": [KEY_J], "heavy": [KEY_K],
		"look_left": [KEY_LEFT], "look_right": [KEY_RIGHT], "look_up": [KEY_UP], "look_down": [KEY_DOWN],
	}
	var mouse := {"attack": MOUSE_BUTTON_LEFT, "heavy": MOUSE_BUTTON_RIGHT, "lock": MOUSE_BUTTON_MIDDLE}
	var buttons := {"roll": JOY_BUTTON_B, "attack": JOY_BUTTON_RIGHT_SHOULDER, "heavy": JOY_BUTTON_Y, "heal": JOY_BUTTON_X, "lock": JOY_BUTTON_RIGHT_STICK, "interact": JOY_BUTTON_A, "run": JOY_BUTTON_LEFT_STICK}
	var axes := {
		"left": [JOY_AXIS_LEFT_X, -1.0], "right": [JOY_AXIS_LEFT_X, 1.0], "forward": [JOY_AXIS_LEFT_Y, -1.0], "back": [JOY_AXIS_LEFT_Y, 1.0],
		"look_left": [JOY_AXIS_RIGHT_X, -1.0], "look_right": [JOY_AXIS_RIGHT_X, 1.0], "look_up": [JOY_AXIS_RIGHT_Y, -1.0], "look_down": [JOY_AXIS_RIGHT_Y, 1.0],
	}
	for action: String in keys:
		if InputMap.has_action(action):
			continue
		InputMap.add_action(action, 0.2)
		for code: Key in keys[action]:
			var key := InputEventKey.new()
			key.physical_keycode = code
			InputMap.action_add_event(action, key)
		if mouse.has(action):
			var click := InputEventMouseButton.new()
			click.button_index = mouse[action]
			InputMap.action_add_event(action, click)
		if buttons.has(action):
			var button := InputEventJoypadButton.new()
			button.button_index = buttons[action]
			InputMap.action_add_event(action, button)
		if axes.has(action):
			var stick := InputEventJoypadMotion.new()
			stick.axis = axes[action][0]
			stick.axis_value = axes[action][1]
			InputMap.action_add_event(action, stick)
