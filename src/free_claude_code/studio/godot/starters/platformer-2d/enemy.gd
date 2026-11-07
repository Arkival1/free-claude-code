extends CharacterBody2D
## An enemy that walks back and forth and turns at walls and ledges.
## Jump on it to defeat it; touch it from the side and you start again.

const SPEED := 30.0
const GRAVITY := 900.0

var direction := -1.0
var sprite: Sprite2D
var floor_check: RayCast2D


func _ready() -> void:
	sprite = Sprite2D.new()
	sprite.texture = preload("res://assets/characters.png")
	sprite.region_enabled = true
	sprite.region_rect = Rect2(8 * 24, 0, 24, 24)
	sprite.position = Vector2(0, -3)
	add_child(sprite)
	var shape := CollisionShape2D.new()
	var circle := CircleShape2D.new()
	circle.radius = 7
	shape.shape = circle
	add_child(shape)
	floor_check = RayCast2D.new()
	floor_check.target_position = Vector2(8, 14)
	add_child(floor_check)
	var hurt := Area2D.new()
	var hurt_shape := CollisionShape2D.new()
	var hurt_circle := CircleShape2D.new()
	hurt_circle.radius = 9
	hurt_shape.shape = hurt_circle
	hurt.add_child(hurt_shape)
	hurt.body_entered.connect(_on_touch)
	add_child(hurt)


func _physics_process(delta: float) -> void:
	velocity.y += GRAVITY * delta
	floor_check.target_position.x = 8.0 * direction
	if is_on_wall() or (is_on_floor() and not floor_check.is_colliding()):
		direction = -direction
	velocity.x = SPEED * direction
	move_and_slide()
	sprite.rotation += delta * 4.0 * direction


func _on_touch(body: Node) -> void:
	if not body is CharacterBody2D or body == self:
		return
	var main := get_parent()
	if body.velocity.y > 0.0 and body.global_position.y < global_position.y - 4.0:
		body.velocity.y = -220.0  # bounce off the enemy
		queue_free()
	elif main.has_method("respawn"):
		main.respawn()
