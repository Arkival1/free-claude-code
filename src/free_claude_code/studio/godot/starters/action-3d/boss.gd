extends CharacterBody3D
## The Ember Warden: a horned giant with a burning maul. Every blow is
## telegraphed (a wind-up, the maul glowing, a ring on the ground where it
## will land), then the blow, then a recovery you can punish. Enough damage
## in a short time staggers it. Below half health it roars into a second
## phase: faster, with a burst of fire around it.

signal changed
signal woke
signal defeated
signal slammed(where: Vector3, strength: float)

const Fighter := preload("res://fighter.gd")
const Look := preload("res://look.gd")
const NAME := "The Ember Warden"
const GRAVITY := 24.0
const ATTACKS := {
	"sweep": {"time": 1.6, "windup": 0.72, "window": [0.72, 0.95], "damage": 26.0, "reach": 4.4, "arc": 120.0},
	"slam": {"time": 2.0, "windup": 1.0, "window": [1.0, 1.15], "damage": 40.0, "radius": 3.1, "ahead": 2.8},
	"charge": {"time": 1.9, "windup": 0.7, "window": [0.7, 1.35], "damage": 30.0, "speed": 13.0},
	"burst": {"time": 2.3, "windup": 1.2, "window": [1.2, 1.4], "damage": 34.0, "radius": 5.6},
}

var max_hp := 900.0
var hp := 900.0
var radius := 1.1
var phase := 1
var state := "dormant"
var state_time := 0.0
var player: Node3D
var home := Vector3.ZERO
var facing := 0.0
var body: Node3D
var ring: MeshInstance3D
var ring_glow: StandardMaterial3D
var fire: GPUParticles3D
var _did_hit := false
var _poise := 0.0
var _poise_clock := 0.0
var _pause := 1.0
var _clock := 0.0
var _rng := RandomNumberGenerator.new()


func _ready() -> void:
	_rng.seed = 17
	var shape := CollisionShape3D.new()
	var capsule := CapsuleShape3D.new()
	capsule.radius = radius * 0.8
	capsule.height = 3.6
	shape.shape = capsule
	shape.position.y = 1.8
	add_child(shape)
	body = Fighter.new()
	add_child(body)
	body.call("build", {"size": 1.95, "armour": "ember", "cloth": "leather", "skin": "ember", "cape": "leather", "weapon": "maul", "horns": true, "glow": Color(1.0, 0.4, 0.08)})
	ring = MeshInstance3D.new()
	var disc := CylinderMesh.new()
	disc.top_radius = 1.0
	disc.bottom_radius = 1.0
	disc.height = 0.03
	disc.radial_segments = 48
	ring.mesh = disc
	ring_glow = Look.glow(Color(1.0, 0.3, 0.05, 0.0), 4.0, true)
	ring.material_override = ring_glow
	ring.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	ring.top_level = true
	add_child(ring)
	ring.visible = false
	fire = Look.fire(1.6)
	fire.emitting = false
	add_child(fire)
	fire.position.y = 1.4
	home = global_position


func is_dead() -> bool:
	return state == "dead"


func reset() -> void:
	hp = max_hp
	phase = 1
	global_position = home
	velocity = Vector3.ZERO
	facing = 0.0
	_start("dormant")
	fire.emitting = false
	changed.emit()


func take_hit(damage: float, _from: Vector3) -> void:
	if state == "dead" or state == "dormant":
		return
	hp = maxf(0.0, hp - damage)
	_poise += damage
	_poise_clock = 0.0
	changed.emit()
	if hp <= 0.0:
		_start("dead")
		ring.visible = false
		fire.emitting = false
		defeated.emit()
	elif phase == 1 and hp < max_hp * 0.5:
		phase = 2
		_poise = 0.0
		fire.emitting = true
		_start("roar")
	elif _poise > 110.0 and state not in ["roar", "stagger"]:
		_poise = 0.0
		_start("stagger")


func _start(next: String) -> void:
	state = next
	state_time = 0.0
	_did_hit = false


func _speed_up() -> float:
	return 0.75 if phase == 2 else 1.0


func _physics_process(delta: float) -> void:
	_clock += delta
	state_time += delta
	_poise_clock += delta
	if _poise_clock > 4.0:
		_poise = 0.0
	if not is_on_floor():
		velocity.y -= GRAVITY * delta
	var to := Vector3.ZERO
	if player:
		to = player.global_position - global_position
		to.y = 0.0
	var distance := to.length()
	var player_down: bool = player != null and player.has_method("dead") and player.call("dead")
	var shown := state
	var progress := 0.0
	match state:
		"dormant":
			velocity.x = 0.0
			velocity.z = 0.0
			if player and distance < 17.0 and not player_down:
				_start("roar")
				woke.emit()
		"roar":
			_stop(delta)
			progress = state_time / 2.0
			if state_time > 2.0:
				_start("move")
		"stagger":
			_stop(delta)
			progress = state_time / 1.4
			if state_time > 1.4:
				_start("move")
		"dead":
			_stop(delta)
			shown = "dead"
			progress = state_time / 2.2
		"move":
			if player_down:
				_stop(delta)
				shown = "idle"
			else:
				facing = lerp_angle(facing, atan2(-to.x, -to.z), minf(1.0, delta * 4.0))
				var walk := 2.4 if phase == 1 else 3.4
				var wanted := to.normalized() * (walk if distance > 3.2 else 0.0)
				velocity.x = move_toward(velocity.x, wanted.x, 12.0 * delta)
				velocity.z = move_toward(velocity.z, wanted.z, 12.0 * delta)
				shown = "move" if distance > 3.2 else "idle"
				_pause -= delta
				if _pause <= 0.0:
					_choose(distance)
		_:
			_attack(delta, to, distance)
			shown = state
			progress = state_time / (float(ATTACKS[state]["time"]) * _speed_up())
	move_and_slide()
	body.rotation.y = facing
	var speed := clampf(Vector2(velocity.x, velocity.z).length() / 3.4, 0.0, 1.0)
	body.call("pose", shown, _clock, clampf(progress, 0.0, 1.0), speed)


func _stop(delta: float) -> void:
	velocity.x = move_toward(velocity.x, 0.0, 20.0 * delta)
	velocity.z = move_toward(velocity.z, 0.0, 20.0 * delta)


func _choose(distance: float) -> void:
	var options: Array[String] = []
	if distance > 7.5:
		options = ["charge", "charge", "slam"]
	elif distance < 4.6:
		options = ["sweep", "sweep", "slam"]
	else:
		options = ["slam", "charge", "sweep"]
	if phase == 2:
		options.append("burst")
	_start(options[_rng.randi_range(0, options.size() - 1)])
	_pause = _rng.randf_range(0.5, 1.1) * _speed_up()


func _attack(delta: float, to: Vector3, distance: float) -> void:
	var spec: Dictionary = ATTACKS[state]
	var pace := _speed_up()
	var windup := float(spec["windup"]) * pace
	var window: Array = spec["window"]
	var opens := float(window[0]) * pace
	var closes := float(window[1]) * pace
	var glow: StandardMaterial3D = body.get("weapon_glow")
	glow.emission_energy_multiplier = lerpf(0.0, 9.0, clampf(state_time / windup, 0.0, 1.0)) if state_time < closes else maxf(0.0, glow.emission_energy_multiplier - delta * 12.0)
	if state_time < windup * 0.8:
		facing = lerp_angle(facing, atan2(-to.x, -to.z), minf(1.0, delta * 5.0))
	var ahead := Vector3(-sin(facing), 0, -cos(facing))
	match state:
		"charge":
			if state_time >= opens and state_time <= closes:
				velocity.x = ahead.x * float(spec["speed"])
				velocity.z = ahead.z * float(spec["speed"])
			else:
				_stop(delta)
		_:
			_stop(delta)
	if spec.has("radius"):
		var centre := global_position + (ahead * float(spec.get("ahead", 0.0)))
		ring.visible = state_time < closes
		ring.global_position = Vector3(centre.x, global_position.y + 0.05, centre.z)
		var grow := clampf(state_time / windup, 0.0, 1.0)
		ring.scale = Vector3(float(spec["radius"]) * grow, 1.0, float(spec["radius"]) * grow)
		ring_glow.albedo_color.a = 0.25 + 0.5 * grow
	if state_time >= opens and state_time <= closes and not _did_hit and player:
		_try_hit(spec, to, distance, ahead)
	if state == "slam" or state == "burst":
		if state_time >= opens and state_time - (1.0 / 60.0) < opens:
			slammed.emit(ring.global_position, 1.0 if state == "slam" else 1.4)
	if state_time >= float(spec["time"]) * pace:
		ring.visible = false
		_start("move")


func _try_hit(spec: Dictionary, to: Vector3, distance: float, ahead: Vector3) -> void:
	var hit := false
	match state:
		"sweep":
			hit = distance < float(spec["reach"]) and (distance < 1.0 or rad_to_deg(ahead.angle_to(to.normalized())) < float(spec["arc"]) * 0.5)
		"slam", "burst":
			var flat := player.global_position - ring.global_position
			flat.y = 0.0
			hit = flat.length() < float(spec["radius"])
		"charge":
			hit = distance < radius + 1.0
	if hit and player.call("take_hit", float(spec["damage"]), global_position):
		_did_hit = true
