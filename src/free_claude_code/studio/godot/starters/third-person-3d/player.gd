extends CharacterBody3D
## A third-person character: the camera orbits with the mouse on a spring
## arm (it pulls in when a wall is in the way); the body turns to face
## where it walks, leans into turns and squashes on landing.

const WALK := 5.0
const RUN := 9.0
const JUMP := 6.5
const GRAVITY := 18.0
const TURN := 10.0
const MOUSE := 0.003

var pivot: Node3D
var arm: SpringArm3D
var body: Node3D


func _ready() -> void:
	var shape := CollisionShape3D.new()
	var capsule := CapsuleShape3D.new()
	capsule.radius = 0.4
	capsule.height = 1.6
	shape.shape = capsule
	shape.position.y = 0.8
	add_child(shape)
	body = Node3D.new()
	add_child(body)
	var mesh := MeshInstance3D.new()
	var capsule_mesh := CapsuleMesh.new()
	capsule_mesh.radius = 0.4
	capsule_mesh.height = 1.6
	var material := StandardMaterial3D.new()
	material.albedo_color = Color("#e8584f")
	capsule_mesh.material = material
	mesh.mesh = capsule_mesh
	mesh.position.y = 0.8
	body.add_child(mesh)
	var nose := MeshInstance3D.new()
	var box := BoxMesh.new()
	box.size = Vector3(0.5, 0.18, 0.25)
	nose.mesh = box
	nose.position = Vector3(0, 1.2, -0.4)
	body.add_child(nose)
	pivot = Node3D.new()
	pivot.position.y = 1.4
	add_child(pivot)
	arm = SpringArm3D.new()
	arm.spring_length = 5.0
	arm.rotation.x = deg_to_rad(-20)
	arm.add_excluded_object(get_rid())
	pivot.add_child(arm)
	var camera := Camera3D.new()
	arm.add_child(camera)
	if DisplayServer.get_name() != "headless":
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventMouseMotion and Input.mouse_mode == Input.MOUSE_MODE_CAPTURED:
		pivot.rotation.y -= event.relative.x * MOUSE
		arm.rotation.x = clampf(arm.rotation.x - event.relative.y * MOUSE, deg_to_rad(-70), deg_to_rad(20))
	if event is InputEventKey and event.keycode == KEY_ESCAPE:
		Input.mouse_mode = Input.MOUSE_MODE_VISIBLE
	if event is InputEventMouseButton and event.pressed:
		Input.mouse_mode = Input.MOUSE_MODE_CAPTURED


func _physics_process(delta: float) -> void:
	var was_on_floor := is_on_floor()
	if not is_on_floor():
		velocity.y -= GRAVITY * delta
	if Input.is_action_just_pressed("jump") and is_on_floor():
		velocity.y = JUMP
	var input := Input.get_vector("left", "right", "forward", "back")
	var direction := (pivot.global_basis * Vector3(input.x, 0, input.y))
	direction.y = 0.0
	direction = direction.normalized()
	var speed := RUN if Input.is_action_pressed("run") else WALK
	velocity.x = move_toward(velocity.x, direction.x * speed, 40.0 * delta)
	velocity.z = move_toward(velocity.z, direction.z * speed, 40.0 * delta)
	if direction.length() > 0.1:
		var target := atan2(-direction.x, -direction.z)
		body.rotation.y = lerp_angle(body.rotation.y, target, TURN * delta)
	body.rotation.z = lerpf(body.rotation.z, -input.x * 0.12, 8.0 * delta)
	move_and_slide()
	if is_on_floor() and not was_on_floor:
		body.scale = Vector3(1.15, 0.85, 1.15)
	body.scale = body.scale.lerp(Vector3.ONE, 10.0 * delta)
