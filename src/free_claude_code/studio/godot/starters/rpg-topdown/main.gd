extends Node2D
## A small top-down RPG: walk the village, talk to the wizard, find the key,
## bring it back. The map is MAP below: '.' grass, ':' path, 'T' tree,
## '*' flowers, 'P' player, 'W' wizard, 'V' villager, 'K' key, 'C' chest.
## Art: Kenney's Tiny Town and Tiny Dungeon (CC0).

const TILE := 16
const MAP := [
	"TTTTTTTTTTTTTTTTTTTTTTTTT",
	"T....*......:.........*.T",
	"T..TT.......:...TT......T",
	"T..T....W...:...T...K...T",
	"T...........:...........T",
	"T:::::::::::::::::::::::T",
	"T.....*.....:.......TT..T",
	"T..V........:...C...T...T",
	"T.......TT..:...........T",
	"T..P....T...:.....*.....T",
	"T...........:...........T",
	"TTTTTTTTTTTTTTTTTTTTTTTTT",
]
const GRASS := Vector2i(0, 0)
const PATH := Vector2i(1, 1)
const TREE := Vector2i(4, 1)
const FLOWERS := Vector2i(2, 0)

var player: CharacterBody2D
var dialogue: Label
var box: PanelContainer
var has_key := false
var quest := "talk"  # talk -> find -> return -> done
var nearby: Node2D = null
var key_item: Area2D
var chest: Sprite2D


func _ready() -> void:
	_add_inputs()
	var tile_set := _make_tile_set()
	var ground := TileMapLayer.new()
	ground.tile_set = tile_set
	add_child(ground)
	# Trees and flowers sit on their own layer, over the grass.
	var things := TileMapLayer.new()
	things.tile_set = tile_set
	add_child(things)
	for row in MAP.size():
		var line: String = MAP[row]
		for col in line.length():
			var cell := Vector2i(col, row)
			var at := Vector2(col * TILE + TILE / 2.0, row * TILE + TILE / 2.0)
			var mark := line[col]
			ground.set_cell(cell, 0, PATH if mark == ":" else GRASS)
			match mark:
				"T":
					things.set_cell(cell, 0, TREE)
				"*":
					things.set_cell(cell, 0, FLOWERS)
				"P":
					player = preload("res://player.gd").new()
					player.position = at
				"W":
					_add_person(at, Vector2i(0, 7), "wizard")
				"V":
					_add_person(at, Vector2i(3, 8), "villager")
				"K":
					key_item = _add_key(at)
				"C":
					chest = _sprite(Vector2i(5, 7), preload("res://assets/characters.png"))
					chest.position = at
					add_child(chest)
	add_child(player)
	var camera := Camera2D.new()
	camera.limit_left = 0
	camera.limit_top = 0
	camera.limit_right = MAP[0].length() * TILE
	camera.limit_bottom = MAP.size() * TILE
	camera.position_smoothing_enabled = true
	player.add_child(camera)
	_make_dialogue()
	say("Use the arrows or WASD to walk. Press E to talk.")


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("talk") and nearby != null:
		talk(String(nearby.get_meta("who")))


func talk(who: String) -> void:
	if who == "villager":
		say("Villager: The wizard has been looking for something all week.")
		return
	match quest:
		"talk":
			quest = "find"
			say("Wizard: I lost my golden key somewhere east of the path. Could you find it?")
		"find":
			say("Wizard: Still no key? Try the grass past the trees.")
		"return":
			quest = "done"
			chest.region_rect = Rect2(6 * TILE, 7 * TILE, TILE, TILE)
			say("Wizard: My key! The chest is yours. Thank you, hero.")
		"done":
			say("Wizard: Safe travels.")


func pick_up_key() -> void:
	has_key = true
	quest = "return"
	say("You found a golden key. Take it to the wizard.")


func say(text: String) -> void:
	dialogue.text = text
	box.visible = true


func _add_person(at: Vector2, frame: Vector2i, who: String) -> void:
	var body := StaticBody2D.new()
	body.position = at
	body.set_meta("who", who)
	body.add_child(_sprite(frame, preload("res://assets/characters.png")))
	var shape := CollisionShape2D.new()
	var box_shape := RectangleShape2D.new()
	box_shape.size = Vector2(12, 12)
	shape.shape = box_shape
	body.add_child(shape)
	var reach := Area2D.new()
	var reach_shape := CollisionShape2D.new()
	var circle := CircleShape2D.new()
	circle.radius = 20
	reach_shape.shape = circle
	reach.add_child(reach_shape)
	reach.body_entered.connect(func(other: Node) -> void:
		if other == player:
			nearby = body)
	reach.body_exited.connect(func(other: Node) -> void:
		if other == player and nearby == body:
			nearby = null)
	body.add_child(reach)
	add_child(body)


func _add_key(at: Vector2) -> Area2D:
	var item := Area2D.new()
	item.position = at
	item.add_child(_sprite(Vector2i(9, 9), preload("res://assets/tiles.png")))
	var shape := CollisionShape2D.new()
	var circle := CircleShape2D.new()
	circle.radius = 6
	shape.shape = circle
	item.add_child(shape)
	item.body_entered.connect(func(other: Node) -> void:
		if other == player:
			pick_up_key()
			item.queue_free())
	add_child(item)
	var glow := item.create_tween().set_loops()
	glow.tween_property(item, "modulate", Color(1.4, 1.4, 1.0), 0.5)
	glow.tween_property(item, "modulate", Color.WHITE, 0.5)
	return item


func _sprite(coords: Vector2i, sheet: Texture2D) -> Sprite2D:
	var sprite := Sprite2D.new()
	sprite.texture = sheet
	sprite.region_enabled = true
	sprite.region_rect = Rect2(coords.x * TILE, coords.y * TILE, TILE, TILE)
	return sprite


func _make_dialogue() -> void:
	var layer := CanvasLayer.new()
	box = PanelContainer.new()
	box.anchor_left = 0.0
	box.anchor_right = 1.0
	box.anchor_top = 1.0
	box.anchor_bottom = 1.0
	box.offset_left = 8
	box.offset_right = -8
	box.offset_top = -38
	box.offset_bottom = -8
	dialogue = Label.new()
	dialogue.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	dialogue.add_theme_font_size_override("font_size", 9)
	box.add_child(dialogue)
	layer.add_child(box)
	add_child(layer)


func _make_tile_set() -> TileSet:
	var tile_set := TileSet.new()
	tile_set.tile_size = Vector2i(TILE, TILE)
	tile_set.add_physics_layer()
	var source := TileSetAtlasSource.new()
	source.texture = preload("res://assets/tiles.png")
	source.texture_region_size = Vector2i(TILE, TILE)
	tile_set.add_source(source, 0)
	var half := TILE / 2.0
	for coords: Vector2i in [GRASS, PATH, TREE, FLOWERS]:
		source.create_tile(coords)
	var data := source.get_tile_data(TREE, 0)
	data.add_collision_polygon(0)
	data.set_collision_polygon_points(0, 0, PackedVector2Array([
		Vector2(-half, -half), Vector2(half, -half), Vector2(half, half), Vector2(-half, half),
	]))
	return tile_set


func _add_inputs() -> void:
	var keys := {
		"left": [KEY_A, KEY_LEFT],
		"right": [KEY_D, KEY_RIGHT],
		"up": [KEY_W, KEY_UP],
		"down": [KEY_S, KEY_DOWN],
		"talk": [KEY_E, KEY_SPACE, KEY_ENTER],
	}
	for action: String in keys:
		if InputMap.has_action(action):
			continue
		InputMap.add_action(action)
		for code: Key in keys[action]:
			var key := InputEventKey.new()
			key.physical_keycode = code
			InputMap.action_add_event(action, key)
