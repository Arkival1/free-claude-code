extends Node
## Wander (FCC kit): moves its parent (an NPC, an animal) to random spots
## within radius of where it started, pausing between walks. 2D (Node2D, in
## pixels: radius x 16) or 3D (Node3D, in metres). A CharacterBody moves with
## its physics; anything else is moved directly.

var radius := 6.0
var speed := 1.5
var _home := Vector3.ZERO
var _target := Vector3.ZERO
var _pause := 1.0
var _walk := 0.0
var _flat := false


func _ready() -> void:
	var body := get_parent()
	_flat = body is Node2D
	_home = _where()
	_target = _home
	_pause = randf_range(0.5, 2.5)


func _where() -> Vector3:
	var body := get_parent()
	if _flat:
		var at: Vector2 = (body as Node2D).position
		return Vector3(at.x, at.y, 0)
	return (body as Node3D).position


func _physics_process(delta: float) -> void:
	var body := get_parent()
	if _pause > 0.0:
		_pause -= delta
		if body is CharacterBody3D and not (body as CharacterBody3D).is_on_floor():
			var faller := body as CharacterBody3D
			faller.velocity.y -= 9.8 * delta
			faller.move_and_slide()
		if _pause <= 0.0:
			var angle := randf() * TAU
			var reach := randf_range(0.3, 1.0) * radius * (16.0 if _flat else 1.0)
			_target = _home + (Vector3(cos(angle), sin(angle), 0) if _flat else Vector3(cos(angle), 0, sin(angle))) * reach
			_walk = 0.0
		return
	var now := _where()
	var away := _target - now
	if not _flat:
		away.y = 0.0  # walk on the ground: a body that settled lower still arrives
	var step := speed * (16.0 if _flat else 1.0)
	_walk += delta
	# Arrived, or stuck against something for too long: rest, then go on.
	if away.length() < step * delta * 2.0 or _walk > radius * 2.5 / maxf(speed, 0.1) + 1.0:
		_pause = randf_range(1.0, 3.5)
		if body is CharacterBody2D or body is CharacterBody3D:
			body.set("velocity", Vector2.ZERO if _flat else Vector3.ZERO)
		return
	var heading := away.normalized() * step
	if body is CharacterBody2D:
		(body as CharacterBody2D).velocity = Vector2(heading.x, heading.y)
		(body as CharacterBody2D).move_and_slide()
	elif body is CharacterBody3D:
		var mover := body as CharacterBody3D
		mover.velocity = Vector3(heading.x, mover.velocity.y - 9.8 * delta, heading.z)
		mover.move_and_slide()
		_face(mover, heading)
	elif _flat:
		(body as Node2D).position += Vector2(heading.x, heading.y) * delta
	else:
		var node := body as Node3D
		node.position += heading * delta
		_face(node, heading)


## Turn to face the way it walks (never straight up or down).
func _face(node: Node3D, heading: Vector3) -> void:
	var flat := Vector3(heading.x, 0, heading.z)
	if flat.length() > 0.001:
		node.look_at(node.global_position + flat, Vector3.UP)
