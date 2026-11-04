extends RefCounted
## The game's look, made in code so nothing needs a licence: surfaces drawn
## from seamless noise (colour, bumps and roughness), glowing materials, and
## fire, embers, smoke and sparks. Change a surface's colours here and every
## model that uses it follows.

const SURFACES := {
	"stone": {"colors": [Color("#2e2c2b"), Color("#5d5954"), Color("#8f897f")], "frequency": 0.018, "bump": 9.0, "rough": 0.92, "metal": 0.0},
	"moss": {"colors": [Color("#223014"), Color("#3f5a22"), Color("#6f8a3c")], "frequency": 0.03, "bump": 5.0, "rough": 0.96, "metal": 0.0},
	"bark": {"colors": [Color("#1a120c"), Color("#35261b"), Color("#56402d")], "frequency": 0.045, "bump": 14.0, "rough": 0.95, "metal": 0.0},
	"steel": {"colors": [Color("#22252a"), Color("#4d535b"), Color("#8e959e")], "frequency": 0.07, "bump": 2.0, "rough": 0.34, "metal": 0.92},
	"gold": {"colors": [Color("#5a3d12"), Color("#a07a2c"), Color("#e2c06b")], "frequency": 0.06, "bump": 1.5, "rough": 0.3, "metal": 1.0},
	"cloth": {"colors": [Color("#2a0907"), Color("#5c1712"), Color("#86281d")], "frequency": 0.11, "bump": 3.0, "rough": 0.9, "metal": 0.0},
	"leather": {"colors": [Color("#1b120b"), Color("#3b2717"), Color("#5f4027")], "frequency": 0.09, "bump": 4.0, "rough": 0.75, "metal": 0.0},
	"wood": {"colors": [Color("#2a1208"), Color("#5a2414"), Color("#7e3a1f")], "frequency": 0.04, "bump": 6.0, "rough": 0.85, "metal": 0.0},
	"roof": {"colors": [Color("#101318"), Color("#23282f"), Color("#3a414b")], "frequency": 0.05, "bump": 8.0, "rough": 0.7, "metal": 0.2},
	"grass": {"colors": [Color("#1d2a10"), Color("#3a4d1d"), Color("#66702e")], "frequency": 0.03, "bump": 4.0, "rough": 0.95, "metal": 0.0},
	"dirt": {"colors": [Color("#2a1d14"), Color("#4c3626"), Color("#7a5c42")], "frequency": 0.05, "bump": 7.0, "rough": 0.9, "metal": 0.0},
	"rock": {"colors": [Color("#25221f"), Color("#4b4641"), Color("#7b746b")], "frequency": 0.025, "bump": 12.0, "rough": 0.9, "metal": 0.0},
	"ember": {"colors": [Color("#120a08"), Color("#2b1610"), Color("#3d1d12")], "frequency": 0.06, "bump": 10.0, "rough": 0.8, "metal": 0.1},
	"autumn": {"colors": [Color("#4a1407"), Color("#9a3b14"), Color("#e07a2c")], "frequency": 0.09, "bump": 6.0, "rough": 0.85, "metal": 0.0},
	"pine": {"colors": [Color("#0c1810"), Color("#1b2f1d"), Color("#33502d")], "frequency": 0.1, "bump": 6.0, "rough": 0.9, "metal": 0.0},
}

static var _cache := {}


static func noise(seed_value: int, frequency: float, octaves := 5) -> FastNoiseLite:
	var made := FastNoiseLite.new()
	made.seed = seed_value
	made.noise_type = FastNoiseLite.TYPE_SIMPLEX_SMOOTH
	made.frequency = frequency
	made.fractal_octaves = octaves
	return made


static func ramp(colors: Array) -> Gradient:
	var gradient := Gradient.new()
	var offsets := PackedFloat32Array()
	var list := PackedColorArray()
	for i in colors.size():
		offsets.append(float(i) / float(colors.size() - 1))
		list.append(colors[i])
	gradient.offsets = offsets
	gradient.colors = list
	return gradient


## A seamless noise texture: colour (a ramp), bumps (a normal map) or roughness.
static func texture(kind: String, seed_value: int, use: String, size := 512) -> NoiseTexture2D:
	var recipe: Dictionary = SURFACES[kind]
	var made := NoiseTexture2D.new()
	made.width = size
	made.height = size
	made.seamless = true
	made.noise = noise(seed_value, recipe["frequency"])
	if use == "normal":
		made.as_normal_map = true
		made.bump_strength = recipe["bump"]
	elif use == "rough":
		var base: float = recipe["rough"]
		made.color_ramp = ramp([Color(base - 0.15, base - 0.15, base - 0.15), Color(base, base, base), Color(min(base + 0.08, 1.0), min(base + 0.08, 1.0), min(base + 0.08, 1.0))])
	else:
		made.color_ramp = ramp(recipe["colors"])
	return made


## A full material for a surface, mapped by world position so it never
## stretches (scale: how many times it repeats per metre).
static func surface(kind: String, seed_value := 3, scale := 0.5) -> StandardMaterial3D:
	var key := "%s/%d/%s" % [kind, seed_value, scale]
	if _cache.has(key):
		return _cache[key]
	var recipe: Dictionary = SURFACES[kind]
	var material := StandardMaterial3D.new()
	material.albedo_texture = texture(kind, seed_value, "color")
	material.normal_enabled = true
	material.normal_texture = texture(kind, seed_value + 11, "normal")
	material.normal_scale = 1.0
	material.roughness_texture = texture(kind, seed_value + 23, "rough", 256)
	material.roughness = 1.0
	material.metallic = recipe["metal"]
	material.metallic_specular = 0.5
	material.uv1_triplanar = true
	material.uv1_world_triplanar = true
	material.uv1_scale = Vector3.ONE * scale
	material.texture_filter = BaseMaterial3D.TEXTURE_FILTER_LINEAR_WITH_MIPMAPS_ANISOTROPIC
	_cache[key] = material
	return material


## A material that glows (lanterns, eyes, embers, telegraph rings).
static func glow(color: Color, energy := 3.0, see_through := false) -> StandardMaterial3D:
	var material := StandardMaterial3D.new()
	material.albedo_color = color
	material.emission_enabled = true
	material.emission = color
	material.emission_energy_multiplier = energy
	material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	if see_through:
		material.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
		material.blend_mode = BaseMaterial3D.BLEND_MODE_ADD
		material.cull_mode = BaseMaterial3D.CULL_DISABLED
	return material


static func soft_dot() -> GradientTexture2D:
	if _cache.has("dot"):
		return _cache["dot"]
	var dot := GradientTexture2D.new()
	dot.fill = GradientTexture2D.FILL_RADIAL
	dot.fill_from = Vector2(0.5, 0.5)
	dot.fill_to = Vector2(0.5, 0.0)
	dot.width = 64
	dot.height = 64
	var gradient := Gradient.new()
	gradient.set_color(0, Color(1, 1, 1, 1))
	gradient.set_color(1, Color(1, 1, 1, 0))
	dot.gradient = gradient
	_cache["dot"] = dot
	return dot


static func _sprite(size: float, add := true) -> QuadMesh:
	var quad := QuadMesh.new()
	quad.size = Vector2(size, size)
	var material := StandardMaterial3D.new()
	material.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	material.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	if add:
		material.blend_mode = BaseMaterial3D.BLEND_MODE_ADD
	material.billboard_mode = BaseMaterial3D.BILLBOARD_PARTICLES
	material.vertex_color_use_as_albedo = true
	material.albedo_texture = soft_dot()
	quad.material = material
	return quad


static func _shrink() -> CurveTexture:
	var curve := Curve.new()
	curve.add_point(Vector2(0, 0.6))
	curve.add_point(Vector2(0.25, 1.0))
	curve.add_point(Vector2(1, 0.1))
	var made := CurveTexture.new()
	made.curve = curve
	return made


static func _colors(stops: Array) -> GradientTexture1D:
	var made := GradientTexture1D.new()
	var gradient := Gradient.new()
	var offsets := PackedFloat32Array()
	var list := PackedColorArray()
	for stop: Array in stops:
		offsets.append(stop[0])
		list.append(stop[1])
	gradient.offsets = offsets
	gradient.colors = list
	made.gradient = gradient
	return made


static func _particles(amount: int, life: float, quad: float, add := true) -> GPUParticles3D:
	var made := GPUParticles3D.new()
	made.amount = amount
	made.lifetime = life
	made.draw_pass_1 = _sprite(quad, add)
	made.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	made.visibility_aabb = AABB(Vector3(-20, -2, -20), Vector3(40, 30, 40))
	return made


## Flames: a hot core that rises, reddens and fades (size in metres).
static func fire(size := 1.0) -> GPUParticles3D:
	var made := _particles(int(36 * size) + 12, 0.8, 0.55 * size)
	var process := ParticleProcessMaterial.new()
	process.emission_shape = ParticleProcessMaterial.EMISSION_SHAPE_SPHERE
	process.emission_sphere_radius = 0.28 * size
	process.direction = Vector3.UP
	process.spread = 10.0
	process.initial_velocity_min = 0.6 * size
	process.initial_velocity_max = 1.6 * size
	process.gravity = Vector3(0, 2.4 * size, 0)
	process.damping_min = 0.5
	process.damping_max = 1.0
	process.scale_min = 0.7
	process.scale_max = 1.3
	process.scale_curve = _shrink()
	process.color_ramp = _colors([[0.0, Color(1.0, 0.78, 0.45, 0.55)], [0.2, Color(1.0, 0.48, 0.12, 0.5)], [0.55, Color(0.8, 0.18, 0.04, 0.32)], [1.0, Color(0.2, 0.05, 0.02, 0.0)]])
	made.process_material = process
	return made


## Embers drifting up through a box of air (area: its size).
static func embers(area: Vector3, amount := 260) -> GPUParticles3D:
	var made := _particles(amount, 6.0, 0.09)
	var process := ParticleProcessMaterial.new()
	process.emission_shape = ParticleProcessMaterial.EMISSION_SHAPE_BOX
	process.emission_box_extents = area * 0.5
	process.direction = Vector3.UP
	process.spread = 35.0
	process.initial_velocity_min = 0.3
	process.initial_velocity_max = 1.1
	process.gravity = Vector3(0.35, 0.5, 0.1)
	process.turbulence_enabled = true
	process.turbulence_noise_strength = 1.2
	process.turbulence_noise_scale = 4.0
	process.color_ramp = _colors([[0.0, Color(1.0, 0.75, 0.3, 0.0)], [0.15, Color(1.0, 0.6, 0.2, 1.0)], [0.8, Color(1.0, 0.3, 0.08, 0.8)], [1.0, Color(0.6, 0.1, 0.0, 0.0)]])
	made.process_material = process
	made.visibility_aabb = AABB(-area * 0.5 - Vector3(2, 2, 2), area + Vector3(4, 14, 4))
	return made


## Slow grey smoke over a fire.
static func smoke(size := 1.0) -> GPUParticles3D:
	var made := _particles(int(18 * size) + 6, 4.0, 1.6 * size, false)
	var process := ParticleProcessMaterial.new()
	process.emission_shape = ParticleProcessMaterial.EMISSION_SHAPE_SPHERE
	process.emission_sphere_radius = 0.3 * size
	process.direction = Vector3.UP
	process.spread = 15.0
	process.initial_velocity_min = 0.4
	process.initial_velocity_max = 0.9
	process.gravity = Vector3(0.2, 0.3, 0.0)
	process.scale_min = 0.8
	process.scale_max = 1.8
	process.color_ramp = _colors([[0.0, Color(0.2, 0.18, 0.17, 0.0)], [0.2, Color(0.25, 0.22, 0.2, 0.35)], [1.0, Color(0.3, 0.28, 0.27, 0.0)]])
	made.process_material = process
	return made


## A burst of sparks for a hit (call restart() to fire it).
static func sparks(color := Color(1.0, 0.7, 0.3)) -> GPUParticles3D:
	var made := _particles(40, 0.5, 0.12)
	made.one_shot = true
	made.explosiveness = 0.95
	made.emitting = false
	var process := ParticleProcessMaterial.new()
	process.direction = Vector3.UP
	process.spread = 80.0
	process.initial_velocity_min = 3.0
	process.initial_velocity_max = 7.0
	process.gravity = Vector3(0, -12, 0)
	process.color_ramp = _colors([[0.0, Color(1, 1, 0.9, 1)], [0.3, color], [1.0, Color(color.r, color.g * 0.4, 0.0, 0.0)]])
	made.process_material = process
	return made
