extends CharacterBody2D
## The hero: walks in eight directions, faces the way it moves, and bobs
## while walking.

const SPEED := 70.0
var sprite: Sprite2D
var walk_time := 0.0


func _ready() -> void:
	sprite = Sprite2D.new()
	sprite.texture = preload("res://assets/characters.png")
	sprite.region_enabled = true
	sprite.region_rect = Rect2(4 * 16, 7 * 16, 16, 16)
	add_child(sprite)
	var shape := CollisionShape2D.new()
	var circle := CircleShape2D.new()
	circle.radius = 5
	shape.shape = circle
	shape.position = Vector2(0, 3)
	add_child(shape)


func _physics_process(delta: float) -> void:
	var direction := Input.get_vector("left", "right", "up", "down")
	velocity = direction * SPEED
	move_and_slide()
	if direction.x != 0.0:
		sprite.flip_h = direction.x < 0.0
	if direction != Vector2.ZERO:
		walk_time += delta
		sprite.position.y = -absf(sin(walk_time * 12.0)) * 1.5
	else:
		sprite.position.y = 0.0
