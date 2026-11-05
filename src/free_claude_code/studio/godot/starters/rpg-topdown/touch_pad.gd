extends CanvasLayer
## Touch controls for a 2D game, shown only on touch screens: a thumb stick on
## the left (it presses left, right, and up and down when `vertical` is on)
## and round buttons on the right, each pressing an input action.

const STICK_RADIUS := 80.0
## [action, label, offset from the bottom-right corner, radius]
var buttons: Array = [["jump", "JUMP", Vector2(-120, -140), 60.0]]
var vertical := false
var _stick_touch := -1
var _stick_origin := Vector2.ZERO
var _base: TextureRect
var _knob: TextureRect
var _pads: Array[TouchScreenButton] = []


func _ready() -> void:
	visible = DisplayServer.is_touchscreen_available()
	_base = _disc(STICK_RADIUS, Color(1, 1, 1, 0.14))
	_knob = _disc(STICK_RADIUS * 0.45, Color(1, 1, 1, 0.4))
	_base.visible = false
	_knob.visible = false
	add_child(_base)
	add_child(_knob)
	for spec: Array in buttons:
		var radius: float = spec[3]
		var pad := TouchScreenButton.new()
		pad.texture_normal = _dot(radius, Color(0.05, 0.05, 0.08, 0.5))
		pad.texture_pressed = _dot(radius, Color(1.0, 0.6, 0.2, 0.75))
		var shape := CircleShape2D.new()
		shape.radius = radius
		pad.shape = shape
		pad.shape_centered = true
		pad.action = spec[0]
		pad.set_meta("offset", spec[2])
		pad.set_meta("radius", radius)
		var label := Label.new()
		label.text = spec[1]
		label.size = Vector2(radius * 2.0, radius * 2.0)
		label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
		label.add_theme_font_size_override("font_size", int(radius * 0.42))
		pad.add_child(label)
		add_child(pad)
		_pads.append(pad)
	get_viewport().size_changed.connect(_place)
	_place()


func _place() -> void:
	var screen := get_viewport().get_visible_rect().size
	for pad in _pads:
		var radius: float = pad.get_meta("radius")
		pad.position = screen + (pad.get_meta("offset") as Vector2) - Vector2(radius, radius)


func _dot(radius: float, colour: Color) -> GradientTexture2D:
	var dot := GradientTexture2D.new()
	dot.width = int(radius * 2.0)
	dot.height = int(radius * 2.0)
	dot.fill = GradientTexture2D.FILL_RADIAL
	dot.fill_from = Vector2(0.5, 0.5)
	dot.fill_to = Vector2(0.5, 0.0)
	var gradient := Gradient.new()
	gradient.offsets = PackedFloat32Array([0.0, 0.92, 1.0])
	gradient.colors = PackedColorArray([colour, colour, Color(colour, 0.0)])
	dot.gradient = gradient
	return dot


func _disc(radius: float, colour: Color) -> TextureRect:
	var holder := TextureRect.new()
	holder.texture = _dot(radius, colour)
	holder.size = Vector2(radius * 2.0, radius * 2.0)
	holder.mouse_filter = Control.MOUSE_FILTER_IGNORE
	return holder


func _input(event: InputEvent) -> void:
	if not visible:
		return
	var screen := get_viewport().get_visible_rect().size
	if event is InputEventScreenTouch:
		var touch := event as InputEventScreenTouch
		if touch.pressed and touch.position.x < screen.x * 0.45 and _stick_touch == -1:
			_stick_touch = touch.index
			_stick_origin = touch.position
			_base.position = touch.position - _base.size * 0.5
			_knob.position = touch.position - _knob.size * 0.5
			_base.visible = true
			_knob.visible = true
		elif not touch.pressed and touch.index == _stick_touch:
			_stick_touch = -1
			_base.visible = false
			_knob.visible = false
			for action: String in ["left", "right", "up", "down"]:
				if InputMap.has_action(action):
					Input.action_release(action)
	elif event is InputEventScreenDrag:
		var drag := event as InputEventScreenDrag
		if drag.index != _stick_touch:
			return
		var offset := (drag.position - _stick_origin).limit_length(STICK_RADIUS)
		_knob.position = _stick_origin + offset - _knob.size * 0.5
		var stick := offset / STICK_RADIUS
		_press("right", stick.x)
		_press("left", -stick.x)
		if vertical:
			_press("down", stick.y)
			_press("up", -stick.y)


func _press(action: String, strength: float) -> void:
	if not InputMap.has_action(action):
		return
	if strength > 0.2:
		Input.action_press(action, clampf(strength, 0.0, 1.0))
	else:
		Input.action_release(action)
