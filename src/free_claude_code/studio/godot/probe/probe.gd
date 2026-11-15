extends Node3D
## FCC's Godot probe. It tries the engine's parts one at a time on the device
## it runs on (FCC Phone's Godot box, or a PC) and sorts them into works,
## limited, missing and blocked (switched off on purpose by FCC's box). It
## shows the list on screen and prints it once as one line:
## FCC_PROBE {"version": ..., "items": [{"group", "name", "status", "detail"}]}
## Every test is short and can't hang: nothing waits longer than a few seconds.

const CLASSES := {
	"3D": ["CSGBox3D", "GridMap", "GPUParticles3D", "CPUParticles3D", "MultiMeshInstance3D", "Skeleton3D", "SoftBody3D", "VehicleBody3D", "NavigationAgent3D", "Path3D", "Decal", "ReflectionProbe", "LightmapGI", "VoxelGI", "FogVolume", "OccluderInstance3D"],
	"2D": ["TileMapLayer", "GPUParticles2D", "Line2D", "Polygon2D", "Skeleton2D", "NavigationAgent2D", "Parallax2D", "PointLight2D"],
	"Sound": ["AudioStreamOggVorbis", "AudioStreamMP3", "AudioStreamWAV", "AudioStreamGenerator", "AudioStreamMicrophone", "AudioEffectReverb"],
	"Video": ["VideoStreamTheora"],
	"Code": ["GDScript", "Expression", "RegEx", "JSON", "Crypto", "ZIPReader", "ZIPPacker", "AStar3D", "FastNoiseLite"],
	"Network": ["HTTPRequest", "WebSocketPeer", "WebRTCPeerConnection", "ENetConnection", "UPNP", "MultiplayerSynchronizer"],
	"XR": ["WebXRInterface", "OpenXRInterface"],
}
const FORWARD_ONLY := "SDFGI, VoxelGI, volumetric fog, screen-space reflections, SSAO and SSIL"

var items: Array[Dictionary] = []
var _list: Label
var _ball: RigidBody3D


func _ready() -> void:
	_build_scene()
	_build_screen()
	_say("Testing Godot on this device...")
	await get_tree().process_frame
	_engine()
	_classes()
	_threads()
	_memory()
	_files()
	_data()
	_images()
	_text()
	_controls()
	await _physics()
	await _drawing()
	_sound()
	await _network()
	_bridge()
	_report()


func _add(group: String, title: String, status: String, detail: String) -> void:
	items.append({"group": group, "name": title, "status": status, "detail": detail})


func _say(text: String) -> void:
	if _list:
		_list.text = text


func _web() -> bool:
	return OS.has_feature("web")


func _build_scene() -> void:
	var sun := DirectionalLight3D.new()
	sun.rotation_degrees = Vector3(-50, 30, 0)
	sun.shadow_enabled = true
	add_child(sun)
	var world := WorldEnvironment.new()
	var environment := Environment.new()
	environment.background_mode = Environment.BG_COLOR
	environment.background_color = Color(0.09, 0.11, 0.16)
	environment.glow_enabled = true
	environment.tonemap_mode = Environment.TONE_MAPPER_FILMIC
	world.environment = environment
	add_child(world)
	var camera := Camera3D.new()
	camera.position = Vector3(0, 3.5, 8)
	camera.rotation_degrees = Vector3(-18, 0, 0)
	add_child(camera)
	var floor_body := StaticBody3D.new()
	var floor_shape := CollisionShape3D.new()
	var box := BoxShape3D.new()
	box.size = Vector3(20, 1, 20)
	floor_shape.shape = box
	floor_body.add_child(floor_shape)
	var floor_mesh := MeshInstance3D.new()
	var plane := BoxMesh.new()
	plane.size = Vector3(20, 1, 20)
	floor_mesh.mesh = plane
	var ground := StandardMaterial3D.new()
	ground.albedo_color = Color(0.25, 0.35, 0.3)
	floor_mesh.material_override = ground
	floor_body.add_child(floor_mesh)
	floor_body.position.y = -0.5
	add_child(floor_body)
	_ball = RigidBody3D.new()
	var ball_shape := CollisionShape3D.new()
	var sphere := SphereShape3D.new()
	sphere.radius = 0.5
	ball_shape.shape = sphere
	_ball.add_child(ball_shape)
	var ball_mesh := MeshInstance3D.new()
	var round_mesh := SphereMesh.new()
	round_mesh.radius = 0.5
	round_mesh.height = 1.0
	ball_mesh.mesh = round_mesh
	var shiny := ShaderMaterial.new()
	var shader := Shader.new()
	shader.code = "shader_type spatial;\nvoid fragment() {\n\tALBEDO = vec3(0.9, 0.5 + 0.4 * sin(TIME * 3.0), 0.2);\n\tROUGHNESS = 0.3;\n}\n"
	shiny.shader = shader
	ball_mesh.material_override = shiny
	_ball.add_child(ball_mesh)
	_ball.position = Vector3(0, 4, 0)
	add_child(_ball)
	var sparks := GPUParticles3D.new()
	sparks.amount = 64
	var process := ParticleProcessMaterial.new()
	process.direction = Vector3(0, 1, 0)
	process.initial_velocity_min = 1.0
	process.initial_velocity_max = 2.0
	sparks.process_material = process
	var dot := SphereMesh.new()
	dot.radius = 0.05
	dot.height = 0.1
	sparks.draw_pass_1 = dot
	sparks.position = Vector3(2, 0.5, 0)
	add_child(sparks)


func _build_screen() -> void:
	var layer := CanvasLayer.new()
	add_child(layer)
	var scroll := ScrollContainer.new()
	scroll.set_anchors_preset(Control.PRESET_FULL_RECT)
	scroll.offset_left = 24
	scroll.offset_top = 24
	scroll.offset_right = -24
	scroll.offset_bottom = -24
	layer.add_child(scroll)
	_list = Label.new()
	_list.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_list.custom_minimum_size = Vector2(600, 0)
	_list.add_theme_font_size_override("font_size", 22)
	_list.add_theme_color_override("font_outline_color", Color.BLACK)
	_list.add_theme_constant_override("outline_size", 6)
	scroll.add_child(_list)


func _engine() -> void:
	var info := Engine.get_version_info()
	_add("Engine", "Godot", "works", "%s on %s" % [info["string"], OS.get_name()])
	var method := RenderingServer.get_current_rendering_method()
	var adapter := RenderingServer.get_video_adapter_name()
	_add("Drawing", "Renderer", "works" if method != "dummy" else "missing", "%s on %s" % [method, adapter if adapter else "no graphics card (headless)"])
	if method == "gl_compatibility":
		_add("Drawing", "Forward+ effects", "missing", "The web player draws with the Compatibility renderer (WebGL 2), which leaves out %s. Glow, fog, shadows, shaders and particles still work." % FORWARD_ONLY)
	if RenderingServer.get_rendering_device() == null:
		_add("Drawing", "Compute shaders", "missing", "No RenderingDevice here, so no compute shaders; do the work in GDScript or fragment shaders.")
	var compression: Array[String] = []
	for format: String in ["etc2", "astc", "s3tc", "bptc"]:
		if OS.has_feature(format):
			compression.append(format.to_upper())
	_add("Drawing", "Texture compression", "works" if compression else "limited", ", ".join(compression) if compression else "None reported; pictures stay uncompressed (more memory).")


func _classes() -> void:
	for group: String in CLASSES:
		var missing: Array[String] = []
		var present: Array[String] = []
		for kind: String in CLASSES[group]:
			if ClassDB.class_exists(kind):
				present.append(kind)
			else:
				missing.append(kind)
		if present:
			_add(group, "%s parts" % group, "works", ", ".join(present))
		if missing:
			_add(group, "%s parts left out" % group, "missing", "Not in this build: %s" % ", ".join(missing))


func _threads() -> void:
	_add("Code", "Thread support", "works" if OS.has_feature("threads") else "missing", "This build runs on several threads." if OS.has_feature("threads") else "This build is single-threaded: Thread objects don't run on their own, so long work freezes the game. Spread it over frames (await get_tree().process_frame).")
	var counter := [0]
	var task := WorkerThreadPool.add_task(func() -> void: counter[0] += 1)
	WorkerThreadPool.wait_for_task_completion(task)
	_add("Code", "WorkerThreadPool", "works" if counter[0] == 1 else "limited", "Tasks run%s." % ("" if OS.has_feature("threads") else ", but on the one main thread"))


func _memory() -> void:
	var before := OS.get_static_memory_usage()
	var big := PackedByteArray()
	var wanted := 128 * 1024 * 1024
	var error := big.resize(wanted)
	var ok := error == OK and big.size() == wanted
	big = PackedByteArray()
	_add("Engine", "Big memory (128 MB at once)", "works" if ok else "limited", "Took and gave back 128 MB." if ok else "Couldn't take 128 MB at once (error %d)." % error)
	_add("Engine", "Memory in use", "works", "%d MB at the start" % int(before / 1048576.0))


func _files() -> void:
	var path := "user://fcc_probe.txt"
	var file := FileAccess.open(path, FileAccess.WRITE)
	if file == null:
		_add("Files", "Saving (user://)", "missing", "Couldn't write: error %d" % FileAccess.get_open_error())
		return
	file.store_string("probe")
	file.close()
	var back := FileAccess.get_file_as_string(path)
	DirAccess.remove_absolute(path)
	if back != "probe":
		_add("Files", "Saving (user://)", "limited", "Wrote but read back '%s'" % back)
	elif _web() and not OS.is_userfs_persistent():
		_add("Files", "Saving (user://)", "limited", "Works while the game is open; it starts fresh each time (FCC's box keeps no game files).")
	else:
		_add("Files", "Saving (user://)", "works", "Kept between plays (on a phone, FCC keeps each game's saves)." if OS.is_userfs_persistent() else "Works.")
	_add("Files", "Game files (res://)", "works" if FileAccess.file_exists("res://probe.gd") else "limited", "Scripts, scenes and data read from the game's pack.")


func _data() -> void:
	var parsed: Variant = JSON.parse_string('{"a": [1, 2, 3]}')
	_add("Code", "JSON", "works" if parsed is Dictionary and (parsed as Dictionary)["a"].size() == 3 else "limited", "Read and write JSON.")
	var regex := RegEx.new()
	var regex_ok := regex.compile("(\\d+)-(\\d+)") == OK and regex.search("x 12-34").get_string(2) == "34"
	_add("Code", "RegEx", "works" if regex_ok else "missing", "Patterns in text.")
	var expression := Expression.new()
	var sum: Variant = null
	if expression.parse("2 + 3 * 4") == OK:
		sum = expression.execute()
	_add("Code", "Expression", "works" if sum == 14 else "limited", "Maths typed in at run time.")
	var hashing := HashingContext.new()
	hashing.start(HashingContext.HASH_SHA256)
	hashing.update("abc".to_utf8_buffer())
	var digest := hashing.finish().hex_encode()
	_add("Code", "Hashing (SHA-256)", "works" if digest.begins_with("ba7816bf") else "limited", "Checksums for saves and data.")
	var bytes := Crypto.new().generate_random_bytes(16)
	_add("Code", "Random bytes (Crypto)", "works" if bytes.size() == 16 else "limited", "Secure random numbers.")


func _images() -> void:
	var image := Image.create_empty(32, 32, false, Image.FORMAT_RGBA8)
	image.fill(Color(0.2, 0.6, 1.0))
	var formats := {"PNG": image.save_png_to_buffer(), "WebP": image.save_webp_to_buffer(true), "JPEG": image.save_jpg_to_buffer()}
	for kind: String in formats:
		var data: PackedByteArray = formats[kind]
		var back := Image.new()
		var error := ERR_UNAVAILABLE
		match kind:
			"PNG":
				error = back.load_png_from_buffer(data)
			"WebP":
				error = back.load_webp_from_buffer(data)
			"JPEG":
				error = back.load_jpg_from_buffer(data)
		var ok := data.size() > 0 and error == OK and back.get_width() == 32
		_add("Pictures", "%s pictures" % kind, "works" if ok else "missing", "Made and read back at run time." if ok else "Couldn't make or read one here.")
	var texture := ImageTexture.create_from_image(image)
	_add("Pictures", "Textures from pictures", "works" if texture.get_width() == 32 else "limited", "Image -> ImageTexture, for pictures loaded at run time.")


func _text() -> void:
	var font := ThemeDB.fallback_font
	var symbols := font.has_char(0x2605) and font.has_char(0x2694)
	_add("Text", "Letters (Latin)", "works" if font.has_char(0x41) else "missing", "The built-in font.")
	_add("Text", "Symbols and emoji", "works" if symbols else "missing", "The built-in font has them." if symbols else "Symbols like stars and swords (and emoji) show as empty boxes in the built-in font%s. Use words, draw them, or bring a font file into the game." % (", and the web player has no system fonts to fall back on" if _web() else ""))
	# FCC's kit (res://fcc/, added by FCC to games that use it) brings fonts
	# with symbols and emoji as fallbacks of the built-in one.
	if ResourceLoader.exists("res://fcc/kit.gd"):
		var kit: Script = load("res://fcc/kit.gd")
		kit.call("use_fonts")
		var star := false
		var smile := false
		for extra: Font in font.fallbacks:
			star = star or extra.has_char(0x2605)
			smile = smile or extra.has_char(0x1F600)
		_add("Text", "Symbols and emoji with FCC's kit", "works" if star and smile else "missing", "Kit.use_fonts() (res://fcc/kit.gd) gives every text symbols and emoji, black and white." if star and smile else "The kit's fonts didn't load.")
	var system := OS.get_system_fonts()
	_add("Text", "System fonts", "works" if system.size() > 0 else "missing", "%d found" % system.size() if system.size() > 0 else "None reachable from here.")
	var server := TextServerManager.get_primary_interface()
	_add("Text", "Text shaping", "works", server.get_name() if server else "unknown")
	var speech := DisplayServer.has_feature(DisplayServer.FEATURE_TEXT_TO_SPEECH) and DisplayServer.tts_get_voices().size() > 0
	_add("Text", "Speech (text to speech)", "works" if speech else "missing", "%d voices" % DisplayServer.tts_get_voices().size() if speech else "No voices reachable.")


func _controls() -> void:
	var touch := DisplayServer.is_touchscreen_available()
	_add("Input", "Touch screen", "works" if touch else "missing", "Touches arrive as InputEventScreenTouch and Drag." if touch else "No touch screen here.")
	_add("Input", "Game controllers", "works", "%d connected now (they appear when a button is pressed)." % Input.get_connected_joypads().size())
	var keyboard := DisplayServer.has_feature(DisplayServer.FEATURE_VIRTUAL_KEYBOARD)
	_add("Input", "On-screen keyboard", "works" if keyboard else "limited", "LineEdit opens the phone's keyboard." if keyboard else "Not reported; typing in a game may need a keyboard.")
	var tilt := Input.get_accelerometer()
	_add("Input", "Tilt (accelerometer)", "works" if tilt != Vector3.ZERO else "missing", "Reading %s" % tilt if tilt != Vector3.ZERO else "Reads zero here; use touch controls.")


func _physics() -> void:
	var engine_name := str(ProjectSettings.get_setting("physics/3d/physics_engine", "DEFAULT"))
	var start := _ball.position.y
	for _tick in 90:
		await get_tree().physics_frame
	var fell := _ball.position.y < start - 1.0
	var rests := _ball.position.y > -0.2
	_add("Physics", "3D physics" if engine_name == "DEFAULT" else "3D physics (%s)" % engine_name, "works" if fell and rests else "limited", "A ball fell and landed on the floor." if fell and rests else "The ball went from %.2f to %.2f." % [start, _ball.position.y])
	var space := get_world_3d().direct_space_state
	var ray := PhysicsRayQueryParameters3D.create(Vector3(0, 10, 0), Vector3(0, -10, 0))
	var hit := space.intersect_ray(ray)
	_add("Physics", "Ray casts", "works" if not hit.is_empty() else "limited", "Hit the %s." % (hit["collider"] as Object).get_class() if not hit.is_empty() else "Hit nothing.")


func _drawing() -> void:
	var frames := 0
	var clock := Time.get_ticks_msec()
	while Time.get_ticks_msec() - clock < 2000:
		await get_tree().process_frame
		frames += 1
	var fps := frames * 1000.0 / maxf(1.0, Time.get_ticks_msec() - clock)
	_add("Drawing", "Frame rate (3D scene, shadows, particles, a shader)", "works" if fps >= 30 else "limited", "%d frames a second" % roundi(fps))
	if DisplayServer.get_name() == "headless":
		return
	var picture := get_viewport().get_texture().get_image()
	if picture == null or picture.is_empty():
		_add("Drawing", "Reading the screen", "missing", "Couldn't read the drawn picture back.")
		return
	var lit := 0
	var samples := 0
	for y in range(0, picture.get_height(), 24):
		for x in range(0, picture.get_width(), 24):
			samples += 1
			if picture.get_pixel(x, y).get_luminance() > 0.12:
				lit += 1
	_add("Drawing", "3D picture", "works" if lit > 0 else "limited", "Drew %dx%d; %d%% of it lit." % [picture.get_width(), picture.get_height(), roundi(100.0 * lit / maxf(1, samples))])


func _sound() -> void:
	_add("Sound", "Sound output", "works" if AudioServer.get_mix_rate() > 0 else "missing", "%d Hz, %s" % [AudioServer.get_mix_rate(), AudioServer.get_output_device()])
	var player := AudioStreamPlayer.new()
	var generator := AudioStreamGenerator.new()
	generator.buffer_length = 0.1
	player.stream = generator
	# Made-up sound needs stream playback (the web plays samples by default).
	player.playback_type = AudioServer.PLAYBACK_TYPE_STREAM
	player.volume_db = -80.0
	add_child(player)
	player.play()
	var playback := player.get_stream_playback() as AudioStreamGeneratorPlayback
	var room := playback.get_frames_available() if playback else 0
	_add("Sound", "Made-up sound (AudioStreamGenerator)", "works" if room > 0 else "limited", "Room for %d frames." % room if room > 0 else "No playback room here.")
	player.queue_free()


func _network() -> void:
	var request := HTTPRequest.new()
	request.timeout = 3.0
	add_child(request)
	var error := request.request("https://example.com/")
	var status := "blocked"
	var detail := "The game can't reach the internet (FCC's box has none, on purpose)."
	if error == OK:
		var answer: Array = await request.request_completed
		if int(answer[0]) == HTTPRequest.RESULT_SUCCESS:
			status = "works"
			detail = "Reached example.com."
	if not _web() and status == "blocked":
		status = "limited"
		detail = "No answer from example.com within 3 s."
	_add("Network", "Internet from the game", status, detail)
	request.queue_free()


func _bridge() -> void:
	if not _web() or not Engine.has_singleton("JavaScriptBridge"):
		return
	var value: Variant = JavaScriptBridge.eval("1 + 1", true)
	if value == null:
		_add("Code", "JavaScriptBridge", "blocked", "Running the browser's JavaScript from the game is off in FCC's box (on purpose).")
	else:
		_add("Code", "JavaScriptBridge", "works", "eval gave %s" % value)


func _report() -> void:
	var lines: Array[String] = ["What Godot can do here", ""]
	for status: String in ["works", "limited", "missing", "blocked"]:
		var shown: Array[String] = []
		for item in items:
			if item["status"] == status:
				shown.append("- %s: %s" % [item["name"], item["detail"]])
		if shown:
			lines.append({"works": "WORKS", "limited": "LIMITED", "missing": "MISSING", "blocked": "BLOCKED ON PURPOSE"}[status])
			lines.append_array(shown)
			lines.append("")
	_say("\n".join(lines))
	print("FCC_PROBE " + JSON.stringify({"version": Engine.get_version_info()["string"], "items": items}))
