extends RefCounted
## FCC's Godot kit (res://fcc/), in every FCC game on the phone and the PC:
## fonts with symbols and emoji, textures and materials made from Godot's own
## noise (nothing to download), and life: particles, day and night, and
## creatures that wander. Use it with preload, e.g.
##   const Kit := preload("res://fcc/kit.gd")
##   Kit.use_fonts()                       # first thing in _ready
##   add_child(Kit.particles_3d("fireflies"))
##   floor.material_override = Kit.material("stone")

const FONTS := "res://fcc/fonts/"
## Fonts to fall back on, in order: symbols (arrows, stars, swords, chess...),
## more symbols, then emoji (black and white).
const FALLBACKS := ["symbols2.ttf", "symbols.ttf", "emoji.ttf"]
## Styles for headings and signs: font("pixel"), font("fantasy").
const STYLES := {"pixel": "pixel.ttf", "fantasy": "fantasy.ttf"}

static var _fallbacks: Array[Font] = []


static func _load(file: String) -> FontFile:
	var font := FontFile.new()
	if font.load_dynamic_font(FONTS + file) != OK:
		return null
	return font


static func _fallback_fonts() -> Array[Font]:
	if _fallbacks.is_empty():
		for file: String in FALLBACKS:
			var font := _load(file)
			if font:
				_fallbacks.append(font)
	return _fallbacks


## Give every text in the game symbols and emoji: the default font falls back
## to FCC's fonts. Call it first, before making labels.
static func use_fonts() -> void:
	# The default theme and the fallback share one font: give it fallbacks in
	# place, so labels, buttons and draw_string all find the symbols.
	for base: Font in [ThemeDB.fallback_font, ThemeDB.get_default_theme().default_font]:
		if base and base.fallbacks.is_empty():
			base.fallbacks = _fallback_fonts()


## A font in a style ("pixel" or "fantasy"), with symbols and emoji too.
static func font(style: String) -> Font:
	var file: String = STYLES.get(style, "")
	var main := _load(file) if file else null
	if main == null:
		return ThemeDB.fallback_font
	main.fallbacks = _fallback_fonts()
	return main


# --------------------------------------------------------------- screen

## Keep text and buttons the same size on the glass however the phone is
## held. Needs window/stretch/mode="canvas_items" and aspect="expand": the
## project's base size (say 1280x720) is turned round (720x1280) when the
## screen is upright, and on a touch screen its short side becomes
## touch_short (smaller = everything drawn bigger; 0 keeps the project's).
static func fit_screen(window: Window, touch_short := 0) -> void:
	var base := window.content_scale_size
	if base == Vector2i.ZERO:
		return
	var short := mini(base.x, base.y)
	var long := maxi(base.x, base.y)
	if touch_short > 0 and DisplayServer.is_touchscreen_available():
		long = int(float(long) * touch_short / short)
		short = touch_short
	var turn := func() -> void:
		var upright := window.size.y > window.size.x
		var want := Vector2i(short, long) if upright else Vector2i(long, short)
		if window.content_scale_size != want:
			window.content_scale_size = want
	window.size_changed.connect(turn)
	turn.call()


# --------------------------------------------------------------- textures

## Colours for each kind of surface: [dark, light, roughness, metallic].
const SURFACES := {
	"stone": [Color(0.32, 0.31, 0.3), Color(0.62, 0.6, 0.57), 0.9, 0.0],
	"rock": [Color(0.25, 0.22, 0.2), Color(0.5, 0.45, 0.4), 0.95, 0.0],
	"grass": [Color(0.2, 0.33, 0.14), Color(0.36, 0.52, 0.2), 0.95, 0.0],
	"dirt": [Color(0.3, 0.2, 0.12), Color(0.52, 0.38, 0.24), 1.0, 0.0],
	"sand": [Color(0.72, 0.62, 0.42), Color(0.92, 0.84, 0.62), 0.95, 0.0],
	"wood": [Color(0.36, 0.22, 0.11), Color(0.62, 0.42, 0.24), 0.75, 0.0],
	"metal": [Color(0.58, 0.6, 0.64), Color(0.78, 0.8, 0.84), 0.35, 0.9],
	"gold": [Color(0.8, 0.6, 0.18), Color(1.0, 0.84, 0.4), 0.3, 1.0],
	"snow": [Color(0.82, 0.86, 0.92), Color(1.0, 1.0, 1.0), 0.8, 0.0],
	"lava": [Color(0.35, 0.03, 0.0), Color(1.0, 0.55, 0.1), 0.6, 0.0],
	"water": [Color(0.05, 0.2, 0.35), Color(0.2, 0.55, 0.75), 0.05, 0.0],
	"brick": [Color(0.4, 0.15, 0.1), Color(0.7, 0.32, 0.22), 0.9, 0.0],
}


static func _noise(kind: String) -> FastNoiseLite:
	var noise := FastNoiseLite.new()
	noise.seed = hash(kind) % 10000
	match kind:
		"wood":
			# Stretched along the grain by material() (and by uv scale in 2D).
			noise.noise_type = FastNoiseLite.TYPE_PERLIN
			noise.frequency = 0.05
			noise.fractal_octaves = 3
			noise.fractal_type = FastNoiseLite.FRACTAL_RIDGED
		"metal", "gold":
			noise.noise_type = FastNoiseLite.TYPE_SIMPLEX_SMOOTH
			noise.frequency = 0.008
			noise.fractal_octaves = 1
		"water", "lava":
			noise.noise_type = FastNoiseLite.TYPE_SIMPLEX_SMOOTH
			noise.frequency = 0.012
		"brick", "stone", "rock":
			noise.noise_type = FastNoiseLite.TYPE_CELLULAR
			noise.frequency = 0.035
			noise.cellular_return_type = FastNoiseLite.RETURN_DISTANCE2_DIV
		_:
			noise.noise_type = FastNoiseLite.TYPE_SIMPLEX
			noise.frequency = 0.04
			noise.fractal_octaves = 4
	return noise


## A seamless texture of a surface (stone, rock, grass, dirt, sand, wood,
## metal, gold, snow, lava, water, brick), for 2D sprites or 3D materials.
static func texture(kind: String, size := 256) -> Texture2D:
	var colours: Array = SURFACES.get(kind, SURFACES["stone"])
	if kind == "brick":
		return _bricks(size, colours)
	var texture := NoiseTexture2D.new()
	texture.width = size
	texture.height = size
	texture.seamless = true
	texture.noise = _noise(kind)
	var ramp := Gradient.new()
	ramp.set_color(0, colours[0])
	ramp.set_color(1, colours[1])
	texture.color_ramp = ramp
	return texture


## Bricks in rows, each a slightly different shade, with mortar between
## (drawn with whole rectangles, so it's quick on a phone too).
static func _bricks(size: int, colours: Array) -> ImageTexture:
	var image := Image.create(size, size, false, Image.FORMAT_RGBA8)
	image.fill(Color(0.72, 0.68, 0.62))
	var high: int = maxi(size >> 3, 4)  # 8 rows
	var wide: int = high * 2
	var gap: int = maxi(1, size >> 7)
	var dice := RandomNumberGenerator.new()
	dice.seed = 7
	for row in 8:
		var shift: int = high * (row % 2)
		for column in range(-1, ceili(float(size) / wide) + 1):
			var shade: Color = (colours[0] as Color).lerp(colours[1], dice.randf())
			var left := column * wide + shift
			var rect := Rect2i(left + gap, row * high + gap, wide - gap * 2, high - gap * 2)
			image.fill_rect(rect.intersection(Rect2i(0, 0, size, size)), shade)
			# Wrap round, so the texture tiles without a seam.
			if left + wide > size:
				image.fill_rect(Rect2i(rect.position.x - size, rect.position.y, rect.size.x, rect.size.y).intersection(Rect2i(0, 0, size, size)), shade)
	return ImageTexture.create_from_image(image)


## A 3D material for a surface: its colour texture, bumps from the same
## noise, and how shiny or metal it is. tile: how many times it repeats.
static func material(kind: String, tile := 4.0) -> StandardMaterial3D:
	var colours: Array = SURFACES.get(kind, SURFACES["stone"])
	var made := StandardMaterial3D.new()
	made.albedo_texture = texture(kind)
	var bumps := NoiseTexture2D.new()
	bumps.width = 256
	bumps.height = 256
	bumps.seamless = true
	bumps.as_normal_map = true
	# Smooth surfaces get gentle bumps; rough ones deep bumps.
	bumps.bump_strength = 1.5 if kind in ["metal", "gold", "water", "lava", "snow"] else 6.0
	bumps.noise = _noise(kind)
	made.normal_enabled = true
	made.normal_texture = bumps
	made.roughness = colours[2]
	made.metallic = colours[3]
	made.uv1_scale = Vector3(tile, tile, tile)
	if kind == "wood":
		# Grain: the noise drawn out along the boards.
		made.uv1_scale = Vector3(tile * 0.25, tile * 2.0, tile)
	if kind == "lava":
		made.emission_enabled = true
		made.emission = Color(1.0, 0.35, 0.05)
		made.emission_energy_multiplier = 1.5
	if kind == "water":
		made.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
		made.albedo_color = Color(1, 1, 1, 0.8)
	return made


# --------------------------------------------------------------- particles

## [amount, lifetime, colour, size, gravity, spread, speed]
const PARTICLES := {
	"dust": [40, 6.0, Color(1, 0.95, 0.85, 0.35), 0.04, -0.02, 180.0, 0.2],
	"leaves": [24, 7.0, Color(0.55, 0.65, 0.2, 0.9), 0.08, 0.35, 60.0, 0.6],
	"fireflies": [30, 5.0, Color(1.0, 0.95, 0.4, 1.0), 0.06, 0.0, 180.0, 0.3],
	"rain": [300, 1.2, Color(0.7, 0.8, 1.0, 0.6), 0.03, 9.8, 4.0, 8.0],
	"snow": [160, 8.0, Color(1, 1, 1, 0.9), 0.06, 0.4, 25.0, 0.4],
	"embers": [50, 3.0, Color(1.0, 0.5, 0.15, 1.0), 0.05, -0.8, 30.0, 0.8],
}


## Particles all around (3D): dust, leaves, fireflies, rain, snow, embers.
## area: the size of the box they fill, centred on the node.
static func particles_3d(kind: String, area := Vector3(30, 10, 30)) -> CPUParticles3D:
	var spec: Array = PARTICLES.get(kind, PARTICLES["dust"])
	var made := CPUParticles3D.new()
	made.name = "%s_particles" % kind
	made.amount = spec[0]
	made.lifetime = spec[1]
	made.preprocess = spec[1]
	made.emission_shape = CPUParticles3D.EMISSION_SHAPE_BOX
	made.emission_box_extents = area * 0.5
	made.gravity = Vector3(0, -spec[4], 0)
	made.spread = spec[5]
	made.initial_velocity_min = spec[6] * 0.5
	made.initial_velocity_max = spec[6]
	made.direction = Vector3(0.2, -1, 0) if kind == "rain" else Vector3(0, 1, 0)
	var mesh := QuadMesh.new()
	mesh.size = Vector2(spec[3], spec[3] * (6.0 if kind == "rain" else 1.0))
	var look := StandardMaterial3D.new()
	look.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	look.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	look.billboard_mode = BaseMaterial3D.BILLBOARD_PARTICLES
	look.vertex_color_use_as_albedo = true
	if kind in ["fireflies", "embers"]:
		look.emission_enabled = true
		look.emission = spec[2]
		look.emission_energy_multiplier = 3.0
	mesh.material = look
	made.mesh = mesh
	made.color = spec[2]
	if kind == "fireflies":
		made.color_ramp = _twinkle(spec[2])
	return made


## The same, for 2D games: area is the size in pixels (the screen, usually).
static func particles_2d(kind: String, area := Vector2(480, 270)) -> CPUParticles2D:
	var spec: Array = PARTICLES.get(kind, PARTICLES["dust"])
	var made := CPUParticles2D.new()
	made.name = "%s_particles" % kind
	made.amount = spec[0]
	made.lifetime = spec[1]
	made.preprocess = spec[1]
	made.emission_shape = CPUParticles2D.EMISSION_SHAPE_RECTANGLE
	made.emission_rect_extents = area * 0.5
	made.gravity = Vector2(0, spec[4] * 20.0)
	made.spread = spec[5]
	made.initial_velocity_min = spec[6] * 10.0
	made.initial_velocity_max = spec[6] * 20.0
	made.direction = Vector2(0.2, 1) if kind == "rain" else Vector2(0, -1)
	made.scale_amount_min = spec[3] * 20.0
	made.scale_amount_max = spec[3] * 40.0
	made.color = spec[2]
	if kind == "fireflies":
		made.color_ramp = _twinkle(spec[2])
	return made


static func _twinkle(colour: Color) -> Gradient:
	var ramp := Gradient.new()
	ramp.offsets = PackedFloat32Array([0.0, 0.3, 0.5, 0.7, 1.0])
	ramp.colors = PackedColorArray([Color(colour, 0.0), colour, Color(colour, 0.2), colour, Color(colour, 0.0)])
	return ramp


# --------------------------------------------------------------- life

## Day and night: a node that turns the sun and tints the sky and light over
## seconds_per_day (3D: give it the DirectionalLight3D and WorldEnvironment;
## 2D: give it nothing, and it adds a CanvasModulate that tints the scene).
static func day_night(seconds_per_day := 240.0, sun: DirectionalLight3D = null, world: WorldEnvironment = null) -> Node:
	var cycle: Node = preload("res://fcc/day_night.gd").new()
	cycle.set("seconds_per_day", seconds_per_day)
	cycle.set("sun", sun)
	cycle.set("world", world)
	return cycle


## Make a node wander (an NPC, an animal): it walks to random spots within
## radius of where it started, pauses, and walks on. Works in 2D and 3D.
static func wander(body: Node, radius := 6.0, speed := 1.5) -> Node:
	var walker: Node = preload("res://fcc/wander.gd").new()
	walker.set("radius", radius)
	walker.set("speed", speed)
	body.add_child(walker)
	return walker
