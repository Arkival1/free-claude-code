extends CanvasLayer
## Touch controls for a 2D game, shown only on touch screens: a thumb stick on
## the left (it presses left, right, and up and down when `vertical` is on)
## and round buttons on the right, each pressing an input action.
## Sizes are for a 720-pixel-high screen and scale with the screen's short
## side, so the controls are the same size on the glass whatever the game's
## resolution or the way the phone is held.
## Held upright (portrait), the bottom `controls_share` of the screen becomes
## a panel for the controls and the game is drawn above it: call
## fit(camera, world_size) once the camera exists.

const STICK_RADIUS := 80.0
## [action, label, offset of its centre from the bottom-right corner, radius]
var buttons: Array = [["jump", "JUMP", Vector2(-120, -140), 60.0]]
var vertical := false
## How much of an upright screen the controls get (0.38 = the bottom 38%).
var controls_share := 0.38
## The most the camera zooms in to fill an upright screen.
var max_zoom := 2.0
var panel_colour := Color(0.07, 0.07, 0.1)
var _stick_touch := -1
var _stick_origin := Vector2.ZERO
var _base: TextureRect
var _knob: TextureRect
var _panel: ColorRect
var _hint: Label
var _pads: Array[TouchScreenButton] = []
var _camera: Camera2D
var _world := Vector2.ZERO
var _room := 0.0
var _scale := 1.0


func _ready() -> void:
	visible = DisplayServer.is_touchscreen_available()
	_panel = ColorRect.new()
	_panel.color = panel_colour
	_panel.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(_panel)
	# Where the thumb goes, shown faintly in the panel.
	_hint = Label.new()
	# Arrows need a font with symbols (FCC's kit, Kit.use_fonts()); else plain.
	var font: Font = ThemeDB.fallback_font
	var arrows := font.has_char(0x25C0) or font.fallbacks.any(func(extra: Font) -> bool: return extra.has_char(0x25C0))
	var sides := ["◀", "▶", "▲", "▼"] if arrows else ["<", ">", "^", "v"]
	_hint.text = "%s  slide to move  %s" % [sides[0], sides[1]]
	if vertical:
		_hint.text = "%s\n%s\n%s" % [sides[2], _hint.text, sides[3]]
	_hint.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_hint.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	_hint.modulate = Color(1, 1, 1, 0.3)
	_hint.mouse_filter = Control.MOUSE_FILTER_IGNORE
	_panel.add_child(_hint)
	_base = _disc(STICK_RADIUS, Color(1, 1, 1, 0.14))
	_knob = _disc(STICK_RADIUS * 0.45, Color(1, 1, 1, 0.4))
	_base.visible = false
	_knob.visible = false
	add_child(_base)
	add_child(_knob)
	for spec: Array in buttons:
		var radius: float = spec[3]
		var pad := TouchScreenButton.new()
		pad.texture_normal = _dot(radius, Color(0.05, 0.05, 0.08, 0.5), Color(1, 1, 1, 0.55))
		pad.texture_pressed = _dot(radius, Color(1.0, 0.6, 0.2, 0.75), Color(1, 1, 1, 0.8))
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
		label.add_theme_color_override("font_outline_color", Color.BLACK)
		label.add_theme_constant_override("outline_size", int(radius * 0.08))
		pad.add_child(label)
		add_child(pad)
		_pads.append(pad)
	get_viewport().size_changed.connect(_place)
	_place()


## Draw the game above the controls on an upright screen: the camera zooms
## in (up to max_zoom) so world_size's height fills the space above the
## panel, and its bottom limit leaves room for the panel.
func fit(camera: Camera2D, world_size: Vector2) -> void:
	_camera = camera
	_world = world_size
	_place()


## The height (screen pixels) the controls panel takes at the bottom.
func controls_room() -> float:
	return _room


## How much bigger than a 720-high screen's sizes things are drawn (texts in
## the game can use it too, so they stay readable).
func size_scale() -> float:
	return _scale


func _place() -> void:
	var screen := get_viewport().get_visible_rect().size
	_scale = minf(screen.x, screen.y) / 720.0
	var upright := screen.y > screen.x * 1.1
	_room = screen.y * controls_share if upright and visible else 0.0
	_panel.visible = _room > 0.0
	_panel.position = Vector2(0, screen.y - _room)
	_panel.size = Vector2(screen.x, _room)
	_hint.position = Vector2.ZERO
	_hint.size = Vector2(screen.x * 0.45, _room)
	_hint.add_theme_font_size_override("font_size", int(30 * _scale))
	_base.scale = Vector2(_scale, _scale)
	_knob.scale = Vector2(_scale, _scale)
	for pad in _pads:
		var radius: float = pad.get_meta("radius")
		var offset: Vector2 = pad.get_meta("offset")
		pad.scale = Vector2(_scale, _scale)
		pad.position = screen + (offset - Vector2(radius, radius)) * _scale
	if _camera:
		var zoom := 1.0
		if upright and _world.y > 0.0:
			zoom = clampf((screen.y - _room) / _world.y, 1.0, max_zoom)
		_camera.zoom = Vector2(zoom, zoom)
		_camera.limit_bottom = int(_world.y + _room / zoom)


## A round button face: colour inside, with a ring (if given) at the edge so
## it shows on dark and light backgrounds alike.
func _dot(radius: float, colour: Color, ring := Color(0, 0, 0, 0)) -> GradientTexture2D:
	var dot := GradientTexture2D.new()
	dot.width = int(radius * 2.0)
	dot.height = int(radius * 2.0)
	dot.fill = GradientTexture2D.FILL_RADIAL
	dot.fill_from = Vector2(0.5, 0.5)
	dot.fill_to = Vector2(0.5, 0.0)
	var gradient := Gradient.new()
	if ring.a > 0.0:
		gradient.offsets = PackedFloat32Array([0.0, 0.84, 0.88, 0.95, 1.0])
		gradient.colors = PackedColorArray([colour, colour, ring, ring, Color(ring, 0.0)])
	else:
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
	var reach := STICK_RADIUS * _scale
	if event is InputEventScreenTouch:
		var touch := event as InputEventScreenTouch
		if touch.pressed and touch.position.x < screen.x * 0.45 and _stick_touch == -1:
			_stick_touch = touch.index
			_stick_origin = touch.position
			_base.position = touch.position - _base.size * 0.5 * _scale
			_knob.position = touch.position - _knob.size * 0.5 * _scale
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
		var offset := (drag.position - _stick_origin).limit_length(reach)
		_knob.position = _stick_origin + offset - _knob.size * 0.5 * _scale
		var stick := offset / reach
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
