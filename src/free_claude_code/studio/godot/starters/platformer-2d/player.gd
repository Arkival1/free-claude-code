extends CharacterBody2D
## The player: run, jump (higher while held), coyote time and a jump buffer,
## so jumps feel fair; squash and stretch on landing and take-off.

const SPEED := 120.0
const ACCEL := 900.0
const FRICTION := 1100.0
const JUMP := 300.0
const GRAVITY := 900.0
const COYOTE := 0.1
const BUFFER := 0.12

var coyote := 0.0
var buffer := 0.0
var sprite: Sprite2D
var frame_time := 0.0


func _ready() -> void:
	sprite = Sprite2D.new()
	sprite.texture = preload("res://assets/characters.png")
	sprite.region_enabled = true
	sprite.region_rect = Rect2(0, 0, 24, 24)
	sprite.position = Vector2(0, -3)
	add_child(sprite)
	var shape := CollisionShape2D.new()
	var capsule := CapsuleShape2D.new()
	capsule.radius = 6
	capsule.height = 16
	shape.shape = capsule
	add_child(shape)


func _physics_process(delta: float) -> void:
	var was_on_floor := is_on_floor()
	if not is_on_floor():
		velocity.y += GRAVITY * delta
		coyote -= delta
	else:
		coyote = COYOTE
	buffer -= delta
	if Input.is_action_just_pressed("jump"):
		buffer = BUFFER
	if buffer > 0.0 and coyote > 0.0:
		velocity.y = -JUMP
		buffer = 0.0
		coyote = 0.0
		_squash(Vector2(0.8, 1.2))
	if Input.is_action_just_released("jump") and velocity.y < 0.0:
		velocity.y *= 0.5  # let go early for a short hop
	var direction := Input.get_axis("left", "right")
	if direction:
		velocity.x = move_toward(velocity.x, direction * SPEED, ACCEL * delta)
		sprite.flip_h = direction > 0.0
	else:
		velocity.x = move_toward(velocity.x, 0.0, FRICTION * delta)
	move_and_slide()
	if is_on_floor() and not was_on_floor:
		_squash(Vector2(1.25, 0.8))
	_animate(delta)


func _animate(delta: float) -> void:
	frame_time += delta
	var walking := is_on_floor() and absf(velocity.x) > 10.0
	var frame := 1 if (walking and int(frame_time * 8.0) % 2 == 1) or not is_on_floor() else 0
	sprite.region_rect = Rect2(frame * 24, 0, 24, 24)


func _squash(amount: Vector2) -> void:
	sprite.scale = amount
	create_tween().tween_property(sprite, "scale", Vector2.ONE, 0.15)
