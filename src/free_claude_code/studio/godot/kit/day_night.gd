extends Node
## Day and night (FCC kit): the sun crosses the sky and the light, sky and
## ambient colour are tinted warm at dawn and dusk and blue at night, over
## seconds_per_day. In 3D give it the sun and the WorldEnvironment; in 2D it
## adds a CanvasModulate that tints the whole scene. The scene's own colours
## are kept at noon. time_of_day: 0 midnight, 0.25 sunrise, 0.5 noon, 0.75
## sunset.

var seconds_per_day := 240.0
var sun: DirectionalLight3D
var world: WorldEnvironment
var time_of_day := 0.4
var _tint: CanvasModulate
var _sun_energy := 1.0
var _sky_top := Color.WHITE
var _sky_horizon := Color.WHITE
var _ground_horizon := Color.WHITE
var _background := Color.WHITE
var _ambient := Color.WHITE

## The light's tint through the day (white at noon keeps the scene's colours).
const TINT := [
	[0.0, Color(0.22, 0.26, 0.48)],
	[0.2, Color(0.3, 0.32, 0.55)],
	[0.27, Color(1.0, 0.72, 0.55)],
	[0.36, Color(1.0, 0.95, 0.88)],
	[0.5, Color(1, 1, 1)],
	[0.64, Color(1.0, 0.94, 0.85)],
	[0.73, Color(1.0, 0.62, 0.42)],
	[0.8, Color(0.3, 0.32, 0.55)],
	[1.0, Color(0.22, 0.26, 0.48)],
]


func _ready() -> void:
	if sun == null:
		_tint = CanvasModulate.new()
		get_parent().call_deferred("add_child", _tint)
		return
	_sun_energy = sun.light_energy
	if world and world.environment:
		var env := world.environment
		_background = env.background_color
		_ambient = env.ambient_light_color
		if env.sky and env.sky.sky_material is ProceduralSkyMaterial:
			var sky := env.sky.sky_material as ProceduralSkyMaterial
			_sky_top = sky.sky_top_color
			_sky_horizon = sky.sky_horizon_color
			_ground_horizon = sky.ground_horizon_color


static func _at(table: Array, t: float) -> Color:
	for i in range(1, table.size()):
		if t <= table[i][0]:
			var a: Array = table[i - 1]
			var b: Array = table[i]
			return (a[1] as Color).lerp(b[1], (t - a[0]) / max(b[0] - a[0], 0.0001))
	return table[-1][1]


func _process(delta: float) -> void:
	time_of_day = fmod(time_of_day + delta / max(seconds_per_day, 1.0), 1.0)
	var tint := _at(TINT, time_of_day)
	if _tint:
		_tint.color = tint
		return
	if sun:
		# Up from the east at sunrise, overhead at noon, down at sunset.
		sun.rotation.x = -(time_of_day - 0.25) * TAU
		var height := sin((time_of_day - 0.25) * TAU)
		sun.light_energy = _sun_energy * clampf(height * 2.5, 0.0, 1.0)
		sun.light_color = tint
	if world and world.environment:
		var env := world.environment
		if env.background_mode == Environment.BG_COLOR:
			env.background_color = _background * tint
		elif env.sky and env.sky.sky_material is ProceduralSkyMaterial:
			var sky := env.sky.sky_material as ProceduralSkyMaterial
			sky.sky_top_color = _sky_top * tint
			sky.sky_horizon_color = _sky_horizon * tint
			sky.ground_horizon_color = _ground_horizon * tint
		env.ambient_light_color = _ambient * tint
