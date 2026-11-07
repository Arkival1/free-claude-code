extends Node3D
## The third-person camera: it follows the player smoothly on a spring arm
## that pulls in when a wall is in the way, turns with the mouse or the right
## stick, frames the target when locked on, and shakes on big hits.

const MOUSE := 0.0025
const STICK := 2.6
const FOLLOW := 10.0

var player: Node3D
var target: Node3D
var locked := false
var yaw := 0.0
var pitch := -0.32
var arm: SpringArm3D
var camera: Camera3D
var _shake := 0.0
var _rng := RandomNumberGenerator.new()


func _ready() -> void:
	arm = SpringArm3D.new()
	arm.spring_length = 4.6
	arm.margin = 0.25
	add_child(arm)
	camera = Camera3D.new()
	camera.fov = 60.0
	camera.near = 0.08
	camera.far = 600.0
	arm.add_child(camera)
	camera.make_current()


func follow(who: Node3D) -> void:
	player = who
	global_position = who.global_position + Vector3(0, 1.55, 0)
	if who is CollisionObject3D:
		arm.add_excluded_object((who as CollisionObject3D).get_rid())


func shake(strength: float) -> void:
	_shake = maxf(_shake, strength)


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED and not locked:
		var motion := event as InputEventMouseMotion
		yaw -= motion.relative.x * MOUSE
		pitch = clampf(pitch - motion.relative.y * MOUSE, -1.1, 0.35)


func _process(delta: float) -> void:
	if not player:
		return
	var look := Input.get_vector("look_left", "look_right", "look_up", "look_down")
	if not locked:
		yaw -= look.x * STICK * delta
		pitch = clampf(pitch - look.y * STICK * delta, -1.1, 0.35)
	elif target:
		var to := target.global_position - player.global_position
		var wanted := atan2(-to.x, -to.z)
		yaw = lerp_angle(yaw, wanted, minf(1.0, delta * 6.0))
		pitch = lerpf(pitch, -0.28, minf(1.0, delta * 4.0))
	var anchor := player.global_position + Vector3(0, 1.55, 0)
	global_position = global_position.lerp(anchor, minf(1.0, delta * FOLLOW))
	rotation = Vector3(pitch, yaw, 0)
	_shake = maxf(0.0, _shake - delta * 2.5)
	camera.h_offset = _rng.randf_range(-1.0, 1.0) * _shake * 0.15
	camera.v_offset = _rng.randf_range(-1.0, 1.0) * _shake * 0.15
