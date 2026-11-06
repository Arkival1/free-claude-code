extends Node3D
## A low-poly 3D world built in code: sun and sky, ground, crates, ramps,
## floating orbs to collect, and the player. Change the look in LOOK
## (surfaces are FCC kit textures: grass, stone, wood, metal, sand, ...).

const Kit := preload("res://fcc/kit.gd")
const LOOK := {
	"ground_surface": "grass",
	"crate_surface": "wood",
	"sky_top": Color("#3f7fd6"),
	"sky_horizon": Color("#bfe3ff"),
	"ground": Color("#6dbb5a"),
	"crate": Color("#c98b4f"),
	"orb": Color("#ffd447"),
}
const ORBS := 12

var player: CharacterBody3D
var hud: Label
var help: Label
var collected := 0


func _ready() -> void:
	# FCC's kit: symbols and emoji in every text; on a phone the screen's
	# short side counts as 560 pixels, so texts and buttons are a good size
	# however it's held.
	Kit.use_fonts()
	Kit.fit_screen(get_window(), 560)
	_add_inputs()
	_add_world()
	player = preload("res://player.gd").new()
	player.position = Vector3(0, 1, 0)
	add_child(player)
	var rng := RandomNumberGenerator.new()
	rng.seed = 7
	for i in 18:
		var size := rng.randf_range(1.0, 3.0)
		_add_block(Vector3(rng.randf_range(-24, 24), size / 2.0, rng.randf_range(-24, 24)), Vector3.ONE * size, LOOK["crate"], 0.0, LOOK["crate_surface"])
	_add_block(Vector3(8, 0.5, -6), Vector3(6, 1, 4), LOOK["crate"], deg_to_rad(-15), LOOK["crate_surface"])
	for i in ORBS:
		var angle := TAU * i / ORBS
		_add_orb(Vector3(cos(angle) * 14.0, 1.2 + (i % 3) * 1.5, sin(angle) * 14.0))
	var layer := CanvasLayer.new()
	hud = _label(26)
	layer.add_child(hud)
	# How to play: under the count, wrapped to the screen, fading after a while.
	help = _label(18)
	help.position = Vector2(16, 50)
	help.text = "Left thumb: move (push far to run) · Right thumb: look · JUMP" if DisplayServer.is_touchscreen_available() else "WASD move · mouse look · Space jump · Shift run"
	layer.add_child(help)
	help.create_tween().tween_property(help, "modulate:a", 0.0, 2.0).set_delay(10.0)
	add_child(layer)
	get_viewport().size_changed.connect(_fit_text)
	_fit_text()
	var touch: CanvasLayer = preload("res://touch.gd").new()
	touch.set("player", player)
	add_child(touch)
	_update_hud()


func collect() -> void:
	collected += 1
	_update_hud()


func _label(size: int) -> Label:
	var label := Label.new()
	label.position = Vector2(16, 12)
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.add_theme_font_size_override("font_size", size)
	label.add_theme_color_override("font_outline_color", Color.BLACK)
	label.add_theme_constant_override("outline_size", 6)
	return label


## Texts wrap to the screen (and stay clear of the buttons on the right).
func _fit_text() -> void:
	var width := get_viewport().get_visible_rect().size.x
	hud.size.x = width - 32
	help.size.x = width * 0.6


func _update_hud() -> void:
	var touch := DisplayServer.is_touchscreen_available()
	hud.text = "● Orbs: %d / %d" % [collected, ORBS]
	if collected == ORBS:
		hud.text = "★ All orbs found! %s to play again." % ("Tap AGAIN" if touch else "Press R")


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("restart"):
		get_tree().reload_current_scene()


func _add_world() -> void:
	var sky_material := ProceduralSkyMaterial.new()
	sky_material.sky_top_color = LOOK["sky_top"]
	sky_material.sky_horizon_color = LOOK["sky_horizon"]
	sky_material.ground_horizon_color = LOOK["sky_horizon"]
	var sky := Sky.new()
	sky.sky_material = sky_material
	var environment := Environment.new()
	environment.background_mode = Environment.BG_SKY
	environment.sky = sky
	environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	environment.ambient_light_color = LOOK["sky_horizon"]
	environment.ambient_light_energy = 0.35
	environment.tonemap_mode = Environment.TONE_MAPPER_FILMIC
	# Distance haze: light, so near colours stay true.
	environment.fog_enabled = true
	environment.fog_mode = Environment.FOG_MODE_DEPTH
	environment.fog_light_color = LOOK["sky_horizon"]
	environment.fog_depth_begin = 25.0
	environment.fog_depth_end = 90.0
	environment.fog_sky_affect = 0.2
	var world := WorldEnvironment.new()
	world.environment = environment
	add_child(world)
	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-50, -35, 0)
	sun.shadow_enabled = true
	sun.light_energy = 0.9
	add_child(sun)
	_add_block(Vector3(0, -0.5, 0), Vector3(60, 1, 60), LOOK["ground"], 0.0, LOOK["ground_surface"])
	# Life (FCC kit): the day turns to dusk and night (8 minutes a day),
	# leaves blow across, and fireflies glow when it gets dark.
	var day := Kit.day_night(480.0, sun, world)
	day.set("time_of_day", 0.4)
	add_child(day)
	var leaves := Kit.particles_3d("leaves", Vector3(50, 8, 50))
	leaves.position = Vector3(0, 4, 0)
	add_child(leaves)
	var fireflies := Kit.particles_3d("fireflies", Vector3(40, 3, 40))
	fireflies.position = Vector3(0, 1.5, 0)
	add_child(fireflies)


func _material(color: Color) -> StandardMaterial3D:
	var material := StandardMaterial3D.new()
	material.albedo_color = color
	material.roughness = 0.85
	return material


## A solid box; surface: an FCC kit texture (else plain colour).
func _add_block(at: Vector3, size: Vector3, color: Color, tilt := 0.0, surface := "") -> void:
	var body := StaticBody3D.new()
	body.position = at
	body.rotation.z = tilt
	var mesh := MeshInstance3D.new()
	var box := BoxMesh.new()
	box.size = size
	box.material = Kit.material(surface, maxf(1.0, maxf(size.x, size.z) / 3.0)) if surface else _material(color)
	mesh.mesh = box
	body.add_child(mesh)
	var shape := CollisionShape3D.new()
	var box_shape := BoxShape3D.new()
	box_shape.size = size
	shape.shape = box_shape
	body.add_child(shape)
	add_child(body)


func _add_orb(at: Vector3) -> void:
	var orb := Area3D.new()
	orb.position = at
	var mesh := MeshInstance3D.new()
	var sphere := SphereMesh.new()
	sphere.radius = 0.35
	sphere.height = 0.7
	var glow := _material(LOOK["orb"])
	glow.emission_enabled = true
	glow.emission = LOOK["orb"]
	glow.emission_energy_multiplier = 1.5
	sphere.material = glow
	mesh.mesh = sphere
	orb.add_child(mesh)
	var shape := CollisionShape3D.new()
	var sphere_shape := SphereShape3D.new()
	sphere_shape.radius = 0.6
	shape.shape = sphere_shape
	orb.add_child(shape)
	orb.body_entered.connect(func(body: Node) -> void:
		if body == player:
			collect()
			orb.queue_free())
	add_child(orb)
	var bob := orb.create_tween().set_loops()
	bob.tween_property(orb, "position:y", at.y + 0.4, 0.8).set_trans(Tween.TRANS_SINE)
	bob.tween_property(orb, "position:y", at.y, 0.8).set_trans(Tween.TRANS_SINE)


func _add_inputs() -> void:
	var keys := {
		"left": [KEY_A, KEY_LEFT],
		"right": [KEY_D, KEY_RIGHT],
		"forward": [KEY_W, KEY_UP],
		"back": [KEY_S, KEY_DOWN],
		"jump": [KEY_SPACE],
		"run": [KEY_SHIFT],
		"restart": [KEY_R],
	}
	for action: String in keys:
		if InputMap.has_action(action):
			continue
		InputMap.add_action(action)
		for code: Key in keys[action]:
			var key := InputEventKey.new()
			key.physical_keycode = code
			InputMap.action_add_event(action, key)
