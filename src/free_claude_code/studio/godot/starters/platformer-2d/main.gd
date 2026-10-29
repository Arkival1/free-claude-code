extends Node2D
## The level: built from LEVEL below, so changing the map is editing text.
## '#' ground, '=' floating platform, 'o' coin, '^' spikes, 'e' enemy,
## 'P' player start, 'F' finish flag. Art: Kenney's Pixel Platformer (CC0).

const TILE := 18
const LEVEL := [
	"                                                            ",
	"                                                            ",
	"                                  o o o                     ",
	"                    o o          =======          o         ",
	"                   =====                         ===     F  ",
	"          o o                o            o              == ",
	"         =====     e        ===   ^^^    ===       e        ",
	"  P                ===                                      ",
	"######   ######  ###########   ##############   ############",
	"######   ######  ###########   ##############   ############",
]
const GROUND := Vector2i(2, 0)
const GROUND_FILL := Vector2i(4, 0)
const PLATFORM := Vector2i(2, 1)

var coins := 0
var total_coins := 0
var hud: Label
var player: CharacterBody2D
var start := Vector2.ZERO


func _ready() -> void:
	Input.set_use_accumulated_input(false)
	_add_inputs()
	RenderingServer.set_default_clear_color(Color("#87c4ff"))
	var tiles := TileMapLayer.new()
	tiles.tile_set = _make_tile_set()
	add_child(tiles)
	for row in LEVEL.size():
		var line: String = LEVEL[row]
		for col in line.length():
			var cell := Vector2i(col, row)
			var at := Vector2(col * TILE + TILE / 2.0, row * TILE + TILE / 2.0)
			match line[col]:
				"#":
					var above: bool = row > 0 and LEVEL[row - 1][col] == "#"
					tiles.set_cell(cell, 0, GROUND_FILL if above else GROUND)
				"=":
					tiles.set_cell(cell, 0, PLATFORM)
				"o":
					_add_pickup(at)
				"^":
					_add_spikes(at)
				"e":
					_add_enemy(at)
				"F":
					_add_flag(at)
				"P":
					start = at
	player = preload("res://player.gd").new()
	player.position = start
	add_child(player)
	var camera := Camera2D.new()
	camera.position_smoothing_enabled = true
	camera.limit_left = 0
	camera.limit_bottom = LEVEL.size() * TILE
	camera.limit_right = LEVEL[0].length() * TILE
	player.add_child(camera)
	var layer := CanvasLayer.new()
	hud = Label.new()
	hud.position = Vector2(8, 6)
	hud.add_theme_font_size_override("font_size", 12)
	hud.add_theme_color_override("font_outline_color", Color.BLACK)
	hud.add_theme_constant_override("outline_size", 4)
	layer.add_child(hud)
	add_child(layer)
	_update_hud()


func _physics_process(_delta: float) -> void:
	if player.position.y > LEVEL.size() * TILE + 64:
		respawn()


func respawn() -> void:
	player.position = start
	player.velocity = Vector2.ZERO


func collect() -> void:
	coins += 1
	_update_hud()


func finish() -> void:
	hud.text = "You made it! %d / %d coins. Press R to play again." % [coins, total_coins]
	player.set_physics_process(false)


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("restart"):
		get_tree().reload_current_scene()


func _update_hud() -> void:
	hud.text = "Coins: %d / %d" % [coins, total_coins]


func _add_inputs() -> void:
	var keys := {
		"left": [KEY_A, KEY_LEFT],
		"right": [KEY_D, KEY_RIGHT],
		"jump": [KEY_SPACE, KEY_W, KEY_UP],
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
	var pad := {"left": JOY_BUTTON_DPAD_LEFT, "right": JOY_BUTTON_DPAD_RIGHT, "jump": JOY_BUTTON_A}
	for action: String in pad:
		var button := InputEventJoypadButton.new()
		button.button_index = pad[action]
		InputMap.action_add_event(action, button)


func _make_tile_set() -> TileSet:
	var tile_set := TileSet.new()
	tile_set.tile_size = Vector2i(TILE, TILE)
	tile_set.add_physics_layer()
	var source := TileSetAtlasSource.new()
	source.texture = preload("res://assets/tiles.png")
	source.texture_region_size = Vector2i(TILE, TILE)
	tile_set.add_source(source, 0)
	var half := TILE / 2.0
	var square := PackedVector2Array([
		Vector2(-half, -half), Vector2(half, -half), Vector2(half, half), Vector2(-half, half),
	])
	for coords: Vector2i in [GROUND, GROUND_FILL, PLATFORM]:
		source.create_tile(coords)
		var data := source.get_tile_data(coords, 0)
		data.add_collision_polygon(0)
		data.set_collision_polygon_points(0, 0, square)
		if coords == PLATFORM:
			data.set_collision_polygon_one_way(0, 0, true)
	return tile_set


func _sprite(coords: Vector2i, sheet: Texture2D = preload("res://assets/tiles.png"), size := TILE) -> Sprite2D:
	var sprite := Sprite2D.new()
	sprite.texture = sheet
	sprite.region_enabled = true
	sprite.region_rect = Rect2(coords.x * size, coords.y * size, size, size)
	return sprite


func _add_pickup(at: Vector2) -> void:
	var coin := Area2D.new()
	coin.position = at
	coin.add_child(_sprite(Vector2i(11, 7)))
	var shape := CollisionShape2D.new()
	var circle := CircleShape2D.new()
	circle.radius = 6
	shape.shape = circle
	coin.add_child(shape)
	coin.body_entered.connect(func(body: Node) -> void:
		if body == player:
			collect()
			var pop := create_tween()
			pop.tween_property(coin, "scale", Vector2(1.6, 1.6), 0.12)
			pop.parallel().tween_property(coin, "modulate:a", 0.0, 0.12)
			pop.tween_callback(coin.queue_free))
	add_child(coin)
	total_coins += 1
	var bob := coin.create_tween().set_loops()
	bob.tween_property(coin, "position:y", at.y - 3, 0.6).set_trans(Tween.TRANS_SINE)
	bob.tween_property(coin, "position:y", at.y, 0.6).set_trans(Tween.TRANS_SINE)


func _add_spikes(at: Vector2) -> void:
	var spikes := Area2D.new()
	spikes.position = at
	spikes.add_child(_sprite(Vector2i(8, 3)))
	var shape := CollisionShape2D.new()
	var box := RectangleShape2D.new()
	box.size = Vector2(14, 8)
	shape.shape = box
	shape.position = Vector2(0, 4)
	spikes.add_child(shape)
	spikes.body_entered.connect(func(body: Node) -> void:
		if body == player:
			respawn())
	add_child(spikes)


func _add_enemy(at: Vector2) -> void:
	var enemy := preload("res://enemy.gd").new()
	enemy.position = at
	add_child(enemy)


func _add_flag(at: Vector2) -> void:
	var flag := Area2D.new()
	flag.position = at
	flag.add_child(_sprite(Vector2i(11, 5)))
	var shape := CollisionShape2D.new()
	var box := RectangleShape2D.new()
	box.size = Vector2(12, 18)
	shape.shape = box
	flag.add_child(shape)
	flag.body_entered.connect(func(body: Node) -> void:
		if body == player:
			finish())
	add_child(flag)
