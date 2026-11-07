extends CharacterBody3D
## The warrior. Moves where the camera looks; run, dodge roll (untouchable in
## the middle of the roll), light and heavy attacks, a healing flask and
## lock-on. Every action costs stamina, which only comes back when you stop.

signal changed
signal died
signal struck(where: Vector3, heavy: bool)

const Fighter := preload("res://fighter.gd")
const WALK := 3.4
const RUN := 6.6
const ROLL := 7.8
const GRAVITY := 24.0
const TURN := 12.0
const ACTIONS := {
	"roll": {"time": 0.62, "stamina": 22.0, "safe": [0.06, 0.42]},
	"light": {"time": 0.62, "stamina": 16.0, "window": [0.3, 0.46], "damage": 26.0, "reach": 2.7},
	"heavy": {"time": 1.08, "stamina": 32.0, "window": [0.52, 0.68], "damage": 58.0, "reach": 3.1},
	"heal": {"time": 1.15},
	"hit": {"time": 0.5},
}

var max_hp := 100.0
var hp := 100.0
var max_stamina := 100.0
var stamina := 100.0
var max_flasks := 3
var flasks := 3
var state := "move"
var state_time := 0.0
var rest := 0.0
var facing := 0.0
var camera_yaw := 0.0
var target: Node3D
var locked := false
var body: Node3D
var _did_hit := false
var _healed := false
var _roll_dir := Vector3.FORWARD
var _speed := 0.0
var _clock := 0.0


func _ready() -> void:
	var shape := CollisionShape3D.new()
	var capsule := CapsuleShape3D.new()
	capsule.radius = 0.36
	capsule.height = 1.8
	shape.shape = capsule
	shape.position.y = 0.9
	add_child(shape)
	body = Fighter.new()
	add_child(body)
	body.call("build", {"size": 1.0, "armour": "steel", "cloth": "cloth", "skin": "leather", "weapon": "sword", "glow": Color(1.0, 0.55, 0.2)})
	floor_snap_length = 0.4


func dead() -> bool:
	return state == "dead"


func untouchable() -> bool:
	if state == "dead":
		return true
	if state != "roll":
		return false
	var safe: Array = ACTIONS["roll"]["safe"]
	return state_time > safe[0] and state_time < safe[1]


## Take a hit; false when the roll's i-frames dodged it.
func take_hit(damage: float, from: Vector3) -> bool:
	if untouchable():
		return false
	hp = maxf(0.0, hp - damage)
	var away := global_position - from
	away.y = 0
	velocity += away.normalized() * 6.0
	_start("dead" if hp <= 0.0 else "hit")
	changed.emit()
	if hp <= 0.0:
		died.emit()
	return true


func revive(at: Vector3) -> void:
	hp = max_hp
	stamina = max_stamina
	flasks = max_flasks
	global_position = at
	velocity = Vector3.ZERO
	_start("move")
	changed.emit()


func refill() -> void:
	hp = max_hp
	flasks = max_flasks
	changed.emit()


func _start(next: String) -> void:
	state = next
	state_time = 0.0
	_did_hit = false
	_healed = false


func _spend(action: String) -> bool:
	if stamina <= 0.0:
		return false
	stamina = maxf(0.0, stamina - float(ACTIONS[action]["stamina"]))
	rest = 0.0
	changed.emit()
	return true


func forward() -> Vector3:
	return Vector3(-sin(facing), 0, -cos(facing))


func _physics_process(delta: float) -> void:
	_clock += delta
	state_time += delta
	rest += delta
	if not is_on_floor():
		velocity.y -= GRAVITY * delta
	var input := Input.get_vector("left", "right", "forward", "back")
	var wish := Vector3(input.x, 0, input.y).rotated(Vector3.UP, camera_yaw)
	var length := ACTIONS.get(state, {}).get("time", 0.0) as float
	var progress := clampf(state_time / length, 0.0, 1.0) if length > 0.0 else 0.0
	var running := false
	match state:
		"move":
			running = Input.is_action_pressed("run") and stamina > 1.0 and wish.length() > 0.2
			var speed := RUN if running else WALK
			if running:
				stamina = maxf(0.0, stamina - 14.0 * delta)
				rest = 0.0
			velocity.x = move_toward(velocity.x, wish.x * speed, 40.0 * delta)
			velocity.z = move_toward(velocity.z, wish.z * speed, 40.0 * delta)
			_speed = clampf(Vector2(velocity.x, velocity.z).length() / RUN, 0.0, 1.0)
			if locked and target:
				var to := target.global_position - global_position
				facing = lerp_angle(facing, atan2(-to.x, -to.z), minf(1.0, TURN * delta))
			elif wish.length() > 0.1:
				facing = lerp_angle(facing, atan2(-wish.x, -wish.z), minf(1.0, TURN * delta))
			if Input.is_action_just_pressed("roll") and _spend("roll"):
				_roll_dir = wish.normalized() if wish.length() > 0.1 else forward()
				facing = atan2(-_roll_dir.x, -_roll_dir.z)
				_start("roll")
			elif Input.is_action_just_pressed("attack") and _spend("light"):
				_start("light")
			elif Input.is_action_just_pressed("heavy") and _spend("heavy"):
				_start("heavy")
			elif Input.is_action_just_pressed("heal") and flasks > 0:
				_start("heal")
		"roll":
			var push := ROLL * (1.0 - progress * 0.55)
			velocity.x = _roll_dir.x * push
			velocity.z = _roll_dir.z * push
		"light", "heavy":
			var step := forward() * (2.2 if state_time < 0.25 else 0.0)
			velocity.x = move_toward(velocity.x, step.x, 30.0 * delta)
			velocity.z = move_toward(velocity.z, step.z, 30.0 * delta)
			_swing(state)
		"heal":
			velocity.x = move_toward(velocity.x, wish.x * 1.2, 20.0 * delta)
			velocity.z = move_toward(velocity.z, wish.z * 1.2, 20.0 * delta)
			if progress > 0.55 and not _healed:
				_healed = true
				flasks -= 1
				hp = minf(max_hp, hp + 45.0)
				changed.emit()
		"hit", "dead":
			velocity.x = move_toward(velocity.x, 0.0, 18.0 * delta)
			velocity.z = move_toward(velocity.z, 0.0, 18.0 * delta)
	if state != "move" and state != "dead" and length > 0.0 and state_time >= length:
		_start("move")
	if rest > 0.75 and state == "move" and not running and stamina < max_stamina:
		stamina = minf(max_stamina, stamina + 42.0 * delta)
		changed.emit()
	move_and_slide()
	body.rotation.y = facing
	var shown := "move" if state == "move" and _speed > 0.05 else ("idle" if state == "move" else state)
	var dying := clampf(state_time / 1.4, 0.0, 1.0)
	body.call("pose", shown, _clock, dying if state == "dead" else progress, _speed)


func _swing(kind: String) -> void:
	var spec: Dictionary = ACTIONS[kind]
	var window: Array = spec["window"]
	if _did_hit or state_time < window[0] or state_time > window[1] or not target:
		return
	if target.has_method("is_dead") and target.call("is_dead"):
		return
	var to := target.global_position - global_position
	to.y = 0.0
	var radius: float = target.get("radius") if target.get("radius") != null else 0.8
	if to.length() > float(spec["reach"]) + radius:
		return
	if to.length() > 0.5 and forward().angle_to(to.normalized()) > deg_to_rad(75.0):
		return
	_did_hit = true
	target.call("take_hit", float(spec["damage"]), global_position)
	struck.emit(global_position + forward() * 1.4 + Vector3(0, 1.2, 0), kind == "heavy")
