extends Node3D
## A fighter's body, built from shapes on jointed pivots (hips, spine, head,
## shoulders, elbows, legs, knees) and dressed in armour, cloth and a cape,
## with its poses: idle, move, roll, light, heavy, heal, hit, dead, and the
## boss's sweep, slam, charge, burst and roar. The model faces -Z.
## pose(state, time, progress, speed) is called every frame.

const Look := preload("res://look.gd")

var hips: Node3D
var spine: Node3D
var head: Node3D
var arm_l: Node3D
var arm_r: Node3D
var elbow_l: Node3D
var elbow_r: Node3D
var leg_l: Node3D
var leg_r: Node3D
var knee_l: Node3D
var knee_r: Node3D
var cape: Node3D
var weapon: Node3D
var weapon_glow: StandardMaterial3D
var eye_glow: StandardMaterial3D
var height := 1.0


func build(options: Dictionary) -> void:
	height = options.get("size", 1.0)
	var armour := Look.surface(options.get("armour", "steel"), 4, 1.5)
	var cloth := Look.surface(options.get("cloth", "cloth"), 7, 2.5)
	var skin := Look.surface(options.get("skin", "leather"), 9, 2.5)
	var trim := Look.surface("gold", 5, 2.0)
	hips = _joint(self, Vector3(0, 0.95, 0))
	_part(hips, _box(Vector3(0.38, 0.2, 0.24)), Vector3(0, 0.0, 0), skin)
	_part(hips, _box(Vector3(0.42, 0.34, 0.03)), Vector3(0, -0.2, -0.13), cloth)
	_part(hips, _box(Vector3(0.42, 0.34, 0.03)), Vector3(0, -0.2, 0.13), cloth)
	spine = _joint(hips, Vector3(0, 0.1, 0))
	_part(spine, _capsule(0.19, 0.6), Vector3(0, 0.32, 0), cloth)
	_part(spine, _box(Vector3(0.44, 0.36, 0.3)), Vector3(0, 0.44, 0), armour)
	_part(spine, _box(Vector3(0.46, 0.05, 0.31)), Vector3(0, 0.27, 0), trim)
	for side: float in [-1.0, 1.0]:
		var pauldron := _part(spine, _sphere(0.15), Vector3(side * 0.29, 0.6, 0), armour)
		pauldron.scale = Vector3(1.25, 0.75, 1.1)
	head = _joint(spine, Vector3(0, 0.72, 0))
	_part(head, _capsule(0.07, 0.12), Vector3(0, 0.03, 0), skin)
	_part(head, _sphere(0.14), Vector3(0, 0.17, 0), armour)
	_part(head, _box(Vector3(0.2, 0.025, 0.04)), Vector3(0, 0.16, -0.125), Look.glow(Color(0.02, 0.02, 0.02), 0.0))
	arm_l = _joint(spine, Vector3(-0.3, 0.6, 0))
	arm_r = _joint(spine, Vector3(0.3, 0.6, 0))
	for arm: Node3D in [arm_l, arm_r]:
		_part(arm, _capsule(0.07, 0.34), Vector3(0, -0.17, 0), cloth)
	elbow_l = _joint(arm_l, Vector3(0, -0.34, 0))
	elbow_r = _joint(arm_r, Vector3(0, -0.34, 0))
	for elbow: Node3D in [elbow_l, elbow_r]:
		_part(elbow, _capsule(0.07, 0.3), Vector3(0, -0.15, 0), armour)
		_part(elbow, _sphere(0.06), Vector3(0, -0.33, 0), skin)
	leg_l = _joint(hips, Vector3(-0.12, -0.04, 0))
	leg_r = _joint(hips, Vector3(0.12, -0.04, 0))
	for leg: Node3D in [leg_l, leg_r]:
		_part(leg, _capsule(0.085, 0.44), Vector3(0, -0.22, 0), cloth)
	knee_l = _joint(leg_l, Vector3(0, -0.44, 0))
	knee_r = _joint(leg_r, Vector3(0, -0.44, 0))
	for knee: Node3D in [knee_l, knee_r]:
		_part(knee, _capsule(0.08, 0.42), Vector3(0, -0.2, 0), armour)
		_part(knee, _box(Vector3(0.13, 0.08, 0.26)), Vector3(0, -0.44, -0.04), skin)
	cape = _joint(spine, Vector3(0, 0.66, 0.17))
	_part(cape, _box(Vector3(0.5, 1.0, 0.025)), Vector3(0, -0.5, 0), Look.surface(options.get("cape", "cloth"), 12, 2.0))
	weapon = _joint(elbow_r, Vector3(0, -0.34, 0))
	weapon_glow = Look.glow(options.get("glow", Color(1.0, 0.45, 0.12)), 0.0)
	if options.get("weapon", "sword") == "maul":
		_part(weapon, _cylinder(0.035, 1.5), Vector3(0, 0, -0.55), Look.surface("bark", 2, 3.0)).rotation.x = PI / 2
		_part(weapon, _box(Vector3(0.5, 0.36, 0.36)), Vector3(0, 0, -1.3), Look.surface("ember", 6, 2.0))
		_part(weapon, _box(Vector3(0.52, 0.06, 0.38)), Vector3(0, 0, -1.3), weapon_glow)
	else:
		_part(weapon, _cylinder(0.025, 0.24), Vector3(0, 0, 0), Look.surface("leather", 3, 4.0)).rotation.x = PI / 2
		_part(weapon, _box(Vector3(0.28, 0.04, 0.06)), Vector3(0, 0, -0.13), trim)
		_part(weapon, _box(Vector3(0.07, 0.016, 1.05)), Vector3(0, 0, -0.67), armour)
		_part(weapon, _box(Vector3(0.012, 0.018, 1.0)), Vector3(0, 0, -0.66), weapon_glow)
	if options.get("horns", false):
		eye_glow = Look.glow(Color(1.0, 0.35, 0.05), 6.0)
		for side: float in [-1.0, 1.0]:
			var horn := _part(head, _cone(0.07, 0.5), Vector3(side * 0.14, 0.32, 0.02), Look.surface("bark", 8, 4.0))
			horn.rotation = Vector3(-0.35, 0, -side * 0.6)
			_part(head, _sphere(0.025), Vector3(side * 0.05, 0.17, -0.13), eye_glow)
	scale = Vector3.ONE * height


func _joint(parent: Node3D, at: Vector3) -> Node3D:
	var joint := Node3D.new()
	joint.position = at
	parent.add_child(joint)
	return joint


func _part(parent: Node3D, mesh: Mesh, at: Vector3, material: Material) -> MeshInstance3D:
	var part := MeshInstance3D.new()
	part.mesh = mesh
	part.material_override = material
	part.position = at
	parent.add_child(part)
	return part


func _capsule(radius: float, length: float) -> CapsuleMesh:
	var mesh := CapsuleMesh.new()
	mesh.radius = radius
	mesh.height = length + radius * 2.0
	mesh.radial_segments = 16
	mesh.rings = 6
	return mesh


func _box(size: Vector3) -> BoxMesh:
	var mesh := BoxMesh.new()
	mesh.size = size
	return mesh


func _sphere(radius: float) -> SphereMesh:
	var mesh := SphereMesh.new()
	mesh.radius = radius
	mesh.height = radius * 2.0
	mesh.radial_segments = 18
	mesh.rings = 10
	return mesh


func _cylinder(radius: float, length: float) -> CylinderMesh:
	var mesh := CylinderMesh.new()
	mesh.top_radius = radius
	mesh.bottom_radius = radius
	mesh.height = length
	mesh.radial_segments = 10
	return mesh


func _cone(radius: float, length: float) -> CylinderMesh:
	var mesh := CylinderMesh.new()
	mesh.top_radius = 0.0
	mesh.bottom_radius = radius
	mesh.height = length
	mesh.radial_segments = 10
	return mesh


static func _ease(x: float) -> float:
	var v := clampf(x, 0.0, 1.0)
	return v * v * (3.0 - 2.0 * v)


## Pose the body: state, seconds alive, progress 0..1 of a one-off move,
## and speed 0..1 (walk to run).
func pose(state: String, t: float, k: float, speed: float) -> void:
	for joint: Node3D in [hips, spine, head, arm_l, arm_r, elbow_l, elbow_r, leg_l, leg_r, knee_l, knee_r, cape]:
		joint.rotation = Vector3.ZERO
	hips.position = Vector3(0, 0.95, 0)
	var breathe := sin(t * 2.0) * 0.025
	var guard := func() -> void:
		arm_r.rotation = Vector3(-0.55, 0, 0.18)
		elbow_r.rotation.x = -0.9
		arm_l.rotation = Vector3(-0.2, 0, -0.15)
		elbow_l.rotation.x = -0.5
	match state:
		"idle", "dormant":
			guard.call()
			spine.rotation.x = breathe
			head.rotation.x = -breathe
			knee_l.rotation.x = 0.12
			knee_r.rotation.x = 0.12
			hips.position.y = 0.94 + breathe * 0.3
		"move":
			var pace := t * (7.0 + 5.0 * speed)
			var stride := sin(pace) * (0.55 + 0.35 * speed)
			leg_l.rotation.x = stride
			leg_r.rotation.x = -stride
			knee_l.rotation.x = maxf(0.0, -sin(pace)) * (0.7 + 0.5 * speed)
			knee_r.rotation.x = maxf(0.0, sin(pace)) * (0.7 + 0.5 * speed)
			arm_l.rotation.x = -stride * 0.6
			elbow_l.rotation.x = -0.4
			arm_r.rotation = Vector3(-0.5 + stride * 0.3, 0, 0.18)
			elbow_r.rotation.x = -0.8
			spine.rotation.x = 0.08 + 0.18 * speed
			hips.position.y = 0.95 + absf(cos(pace)) * 0.05
			cape.rotation.x = 0.2 + 0.35 * speed + sin(pace * 0.5) * 0.08
		"roll":
			var arc := _ease(k)
			hips.rotation.x = -arc * TAU
			hips.position.y = 0.95 - sin(k * PI) * 0.5
			for leg: Node3D in [leg_l, leg_r]:
				leg.rotation.x = -1.4
			knee_l.rotation.x = 2.0
			knee_r.rotation.x = 2.0
			arm_l.rotation.x = -1.2
			arm_r.rotation.x = -1.2
			elbow_l.rotation.x = -1.4
			elbow_r.rotation.x = -1.4
			spine.rotation.x = 0.7
		"light", "sweep":
			var wind := _ease(k / 0.35)
			var cut := _ease((k - 0.35) / 0.25)
			var back := _ease((k - 0.7) / 0.3)
			var swing := lerpf(lerpf(0.0, 1.0, wind), -1.0, cut)
			swing = lerpf(swing, 0.0, back)
			spine.rotation.y = swing * 0.7
			arm_r.rotation = Vector3(-1.5 + absf(swing) * 0.2, swing * 1.4, 0.4)
			elbow_r.rotation.x = -0.3
			arm_l.rotation = Vector3(-0.3, 0, -0.3)
			leg_l.rotation.x = -0.35 * (1.0 - back)
			knee_r.rotation.x = 0.4
			hips.position.y = 0.9
		"heavy", "slam":
			var lift := _ease(k / 0.5)
			var drop := _ease((k - 0.5) / 0.15)
			var back := _ease((k - 0.75) / 0.25)
			var raise := lerpf(lerpf(0.0, -2.9, lift), 0.4, drop)
			raise = lerpf(raise, -0.5, back)
			arm_r.rotation = Vector3(raise, 0, 0.1)
			arm_l.rotation = Vector3(raise, 0, -0.1)
			elbow_r.rotation.x = -0.3
			elbow_l.rotation.x = -0.3
			spine.rotation.x = lerpf(-0.25 * lift, 0.5, drop) * (1.0 - back)
			knee_l.rotation.x = 0.5 * drop * (1.0 - back)
			knee_r.rotation.x = 0.5 * drop * (1.0 - back)
			hips.position.y = 0.95 - 0.15 * drop * (1.0 - back)
		"charge":
			var pace := t * 16.0
			var stride := sin(pace) * 0.9
			leg_l.rotation.x = stride
			leg_r.rotation.x = -stride
			knee_l.rotation.x = maxf(0.0, -sin(pace)) * 1.2
			knee_r.rotation.x = maxf(0.0, sin(pace)) * 1.2
			spine.rotation.x = 0.5
			arm_r.rotation = Vector3(0.6, 0, 0.3)
			arm_l.rotation = Vector3(0.6, 0, -0.3)
		"burst", "roar":
			var open := _ease(k / 0.4)
			spine.rotation.x = -0.45 * open
			head.rotation.x = -0.5 * open
			arm_l.rotation = Vector3(-0.5, 0, -1.4 * open)
			arm_r.rotation = Vector3(-0.5, 0, 1.4 * open)
			knee_l.rotation.x = 0.3
			knee_r.rotation.x = 0.3
		"heal":
			guard.call()
			arm_l.rotation = Vector3(-2.2 * _ease(k / 0.4), 0.4, 0)
			elbow_l.rotation.x = -1.6
			head.rotation.x = 0.25
		"hit", "stagger":
			var jolt := 1.0 - _ease(k)
			spine.rotation.x = -0.45 * jolt
			head.rotation.x = -0.4 * jolt
			arm_l.rotation.x = 0.6 * jolt
			arm_r.rotation.x = 0.4 * jolt
			knee_l.rotation.x = 0.4
			knee_r.rotation.x = 0.4
		"dead":
			var fall := _ease(k)
			hips.position.y = 0.95 - 0.78 * fall
			hips.rotation.x = 1.45 * fall
			arm_l.rotation.z = -0.9 * fall
			arm_r.rotation.z = 0.9 * fall
			knee_l.rotation.x = 0.6 * fall
			knee_r.rotation.x = 0.2 * fall
	if state != "move":
		cape.rotation.x = maxf(cape.rotation.x, 0.08 + sin(t * 1.3) * 0.04)
