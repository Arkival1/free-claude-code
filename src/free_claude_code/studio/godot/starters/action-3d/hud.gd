extends CanvasLayer
## What's on the screen: health, stamina and flasks top left, the boss's name
## and health at the bottom, big messages (FALLEN, VICTORY, Bonfire lit), a
## prompt for things you can use, the controls (they fade), a vignette that
## flashes red when you're hit, and the graphics line (F3).

var health: ProgressBar
var stamina: ProgressBar
var flasks: Label
var boss_box: VBoxContainer
var boss_bar: ProgressBar
var boss_name: Label
var message: Label
var prompt: Label
var help: Label
var info: Label
var vignette: ColorRect
var _fade: Tween


func _ready() -> void:
	vignette = ColorRect.new()
	vignette.set_anchors_preset(Control.PRESET_FULL_RECT)
	vignette.mouse_filter = Control.MOUSE_FILTER_IGNORE
	var shade := ShaderMaterial.new()
	shade.shader = preload("res://vignette.gdshader")
	vignette.material = shade
	add_child(vignette)
	var top := VBoxContainer.new()
	top.position = Vector2(36, 30)
	top.add_theme_constant_override("separation", 7)
	add_child(top)
	health = _bar(Color("#b3261e"), 420, 16)
	stamina = _bar(Color("#5a8f3a"), 320, 10)
	top.add_child(health)
	top.add_child(stamina)
	flasks = _label(20, Color("#f0c27a"))
	top.add_child(flasks)
	boss_box = VBoxContainer.new()
	boss_box.set_anchors_preset(Control.PRESET_CENTER_BOTTOM)
	boss_box.position = Vector2(-380, -96)
	boss_box.size = Vector2(760, 60)
	boss_box.visible = false
	add_child(boss_box)
	boss_name = _label(22, Color("#e8dcc8"))
	boss_box.add_child(boss_name)
	boss_bar = _bar(Color("#8f1d12"), 760, 14)
	boss_box.add_child(boss_bar)
	message = _label(84, Color("#c9392b"))
	message.set_anchors_preset(Control.PRESET_CENTER)
	message.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	message.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	message.position = Vector2(-600, -70)
	message.size = Vector2(1200, 140)
	message.modulate.a = 0.0
	add_child(message)
	prompt = _label(24, Color("#f2e8d5"))
	prompt.set_anchors_preset(Control.PRESET_CENTER_BOTTOM)
	prompt.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	prompt.position = Vector2(-300, -200)
	prompt.size = Vector2(600, 40)
	add_child(prompt)
	help = _label(17, Color("#e9e2d6"))
	help.set_anchors_preset(Control.PRESET_TOP_RIGHT)
	help.position = Vector2(-470, 30)
	help.size = Vector2(440, 200)
	help.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	if DisplayServer.is_touchscreen_available():
		help.text = "Left thumb: move (push far to run)\nRight thumb: turn the camera\nHIT, HEAVY, ROLL, HEAL, LOCK, REST"
	else:
		help.text = "WASD move - Shift run - Space roll\nLeft click or J light - Right click or K heavy\nArrows or mouse look - Q lock on - F flask\nE rest at the bonfire - Click grabs the mouse, Esc frees it\nF2 graphics - F3 info - a gamepad works too"
	add_child(help)
	var fade := create_tween()
	fade.tween_interval(9.0)
	fade.tween_property(help, "modulate:a", 0.0, 2.0)
	info = _label(15, Color("#9fb3c8"))
	info.set_anchors_preset(Control.PRESET_BOTTOM_LEFT)
	info.position = Vector2(36, -40)
	info.visible = false
	add_child(info)


func _bar(color: Color, width: float, height: float) -> ProgressBar:
	var bar := ProgressBar.new()
	bar.custom_minimum_size = Vector2(width, height)
	bar.show_percentage = false
	var back := StyleBoxFlat.new()
	back.bg_color = Color(0.03, 0.03, 0.03, 0.75)
	back.border_color = Color(0.75, 0.62, 0.42, 0.55)
	back.set_border_width_all(1)
	var fill := StyleBoxFlat.new()
	fill.bg_color = color
	bar.add_theme_stylebox_override("background", back)
	bar.add_theme_stylebox_override("fill", fill)
	return bar


func _label(size: int, color: Color) -> Label:
	var label := Label.new()
	label.add_theme_font_size_override("font_size", size)
	label.add_theme_color_override("font_color", color)
	label.add_theme_color_override("font_outline_color", Color(0, 0, 0, 0.85))
	label.add_theme_constant_override("outline_size", 8)
	return label


func show_player(hp: float, max_hp: float, stamina_now: float, max_stamina: float, flasks_left: int, flasks_max := 3) -> void:
	health.max_value = max_hp
	health.value = hp
	stamina.max_value = max_stamina
	stamina.value = stamina_now
	flasks.text = "Flask  %d / %d" % [flasks_left, flasks_max]


func show_boss(title: String, hp: float, max_hp: float, visible_now: bool) -> void:
	boss_box.visible = visible_now
	boss_name.text = title
	boss_bar.max_value = max_hp
	boss_bar.value = hp


func say(text: String, color: Color, seconds := 3.0) -> void:
	message.text = text
	message.add_theme_color_override("font_color", color)
	if _fade and _fade.is_valid():
		_fade.kill()
	_fade = create_tween()
	_fade.tween_property(message, "modulate:a", 1.0, 0.6)
	_fade.tween_interval(seconds)
	_fade.tween_property(message, "modulate:a", 0.0, 1.0)


func flash() -> void:
	var shade := vignette.material as ShaderMaterial
	shade.set_shader_parameter("flash", 1.0)
	var fade := create_tween()
	fade.tween_method(func(value: float) -> void: shade.set_shader_parameter("flash", value), 1.0, 0.0, 0.45)
