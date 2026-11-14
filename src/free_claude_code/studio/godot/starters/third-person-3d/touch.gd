extends CanvasLayer
## Touch controls, shown only on touch screens (a phone or a tablet): a
## joystick under the left thumb (push it far to run), camera turning with
## the right thumb, and buttons to jump and to play again.

const STICK_RADIUS := 90.0
const LOOK_SPEED := 0.006
# Plain words: the web build has no system fonts for symbols.
const BUTTONS := [
	["jump", "JUMP", Vector2(-130, -150), 64.0],
	["restart", "AGAIN", Vector2(-110, -320), 38.0],
]

var player: Node3D
var _stick_touch := -1
var _stick_origin := Vector2.ZERO
var _look_touch := -1
var _look_last := Vector2.ZERO
var _base: Control
var _knob: Control
var _buttons: Array[TouchScreenButton] = []


func _ready() -> void:
	visible = DisplayServer.is_touchscreen_available()
	_base = _circle(STICK_RADIUS, Color(1, 1, 1, 0.12))
	_knob = _circle(STICK_RADIUS * 0.45, Color(1, 1, 1, 0.35))
	_base.visible = false
	_knob.visible = false
	add_child(_base)
	add_child(_knob)
	for spec: Array in BUTTONS:
		var button := TouchScreenButton.new()
		var radius: float = spec[3]
		button.texture_normal = _dot(radius, Color(0.08, 0.06, 0.06, 0.55))
		button.texture_pressed = _dot(radius, Color(0.9, 0.45, 0.15, 0.75))
		var shape := CircleShape2D.new()
		shape.radius = radius
		button.shape = shape
		button.shape_centered = true
		button.action = spec[0]
		button.set_meta("offset", spec[2])
		button.set_meta("radius", radius)
		var label := Label.new()
		label.text = spec[1]
		label.add_theme_font_size_override("font_size", int(radius * 0.42))
		label.add_theme_color_override("font_color", Color(1, 0.93, 0.82))
		label.size = Vector2(radius * 2.0, radius * 2.0)
		label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
		button.add_child(label)
		add_child(button)
		_buttons.append(button)
	get_viewport().size_changed.connect(_place)
	_place()


func _place() -> void:
	var screen := get_viewport().get_visible_rect().size
	for button in _buttons:
		var offset: Vector2 = button.get_meta("offset")
		var radius: float = button.get_meta("radius")
		button.position = screen + offset - Vector2(radius, radius)


func _circle(radius: float, color: Color) -> Control:
	var holder := TextureRect.new()
	holder.texture = _dot(radius, color)
	holder.size = Vector2(radius * 2.0, radius * 2.0)
	holder.mouse_filter = Control.MOUSE_FILTER_IGNORE
	return holder


func _dot(radius: float, color: Color) -> GradientTexture2D:
	var dot := GradientTexture2D.new()
	dot.width = int(radius * 2.0)
	dot.height = int(radius * 2.0)
	dot.fill = GradientTexture2D.FILL_RADIAL
	dot.fill_from = Vector2(0.5, 0.5)
	dot.fill_to = Vector2(0.5, 0.0)
	var gradient := Gradient.new()
	gradient.offsets = PackedFloat32Array([0.0, 0.92, 1.0])
	gradient.colors = PackedColorArray([color, color, Color(color.r, color.g, color.b, 0.0)])
	dot.gradient = gradient
	return dot


func _on_button(at: Vector2) -> bool:
	for button in _buttons:
		var radius: float = button.get_meta("radius")
		if at.distance_to(button.position + Vector2(radius, radius)) < radius * 1.15:
			return true
	return false


func _input(event: InputEvent) -> void:
	if not visible:
		return
	var screen := get_viewport().get_visible_rect().size
	if event is InputEventScreenTouch:
		var touch := event as InputEventScreenTouch
		if touch.pressed:
			if touch.position.x < screen.x * 0.4 and _stick_touch == -1 and not _on_button(touch.position):
				_stick_touch = touch.index
				_stick_origin = touch.position
				_base.position = touch.position - Vector2(STICK_RADIUS, STICK_RADIUS)
				_knob.position = touch.position - _knob.size * 0.5
				_base.visible = true
				_knob.visible = true
			elif touch.position.x >= screen.x * 0.4 and _look_touch == -1 and not _on_button(touch.position):
				_look_touch = touch.index
				_look_last = touch.position
		else:
			if touch.index == _stick_touch:
				_stick_touch = -1
				_base.visible = false
				_knob.visible = false
				for action: String in ["left", "right", "forward", "back"]:
					Input.action_release(action)
			elif touch.index == _look_touch:
				_look_touch = -1
	elif event is InputEventScreenDrag:
		var drag := event as InputEventScreenDrag
		if drag.index == _stick_touch:
			var offset := (drag.position - _stick_origin).limit_length(STICK_RADIUS)
			_knob.position = _stick_origin + offset - _knob.size * 0.5
			var stick := offset / STICK_RADIUS
			_press("right", stick.x)
			_press("left", -stick.x)
			_press("back", stick.y)
			_press("forward", -stick.y)
			if stick.length() > 0.92:
				Input.action_press("run")
			else:
				Input.action_release("run")
		elif drag.index == _look_touch and player:
			var moved := drag.position - _look_last
			_look_last = drag.position
			player.call("look", moved * LOOK_SPEED)


func _press(action: String, strength: float) -> void:
	if strength > 0.15:
		Input.action_press(action, clampf(strength, 0.0, 1.0))
	else:
		Input.action_release(action)
