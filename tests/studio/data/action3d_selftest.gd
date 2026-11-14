extends Node
## Plays the fight by itself: every combat path, then prints the result.

func _ready() -> void:
	await get_tree().create_timer(0.5).timeout
	var main := get_tree().current_scene
	var player: CharacterBody3D = main.get("player")
	var boss: CharacterBody3D = main.get("boss")
	print("SELFTEST start")
	# Graphics presets, all four, then back to High.
	for level in 4:
		main.set("graphics", level)
		main.call("apply_graphics")
	main.set("graphics", 2)
	main.call("apply_graphics")
	main.get("hud").call("flash")
	# Walk the player into the arena: the boss wakes.
	var arena: Vector3 = main.WORLD["arena"]
	player.global_position = arena + Vector3(0, 0.5, 6)
	await get_tree().create_timer(0.6).timeout
	print("SELFTEST boss state after approach: ", boss.get("state"))
	await get_tree().create_timer(2.4).timeout
	# Force each attack and let it play out.
	for attack in ["sweep", "slam", "charge", "burst"]:
		player.global_position = boss.global_position + Vector3(0, 0.3, 2.5)
		boss.call("_start", attack)
		await get_tree().create_timer(2.6).timeout
		print("SELFTEST after ", attack, ": boss ", boss.get("state"), " player hp ", player.get("hp"), " player ", player.get("state"))
		if player.call("dead"):
			await get_tree().create_timer(4.5).timeout
			print("SELFTEST revived: hp ", player.get("hp"), " state ", player.get("state"), " boss ", boss.get("state"))
			player.global_position = arena + Vector3(0, 0.5, 6)
			await get_tree().create_timer(3.0).timeout
	# Player attacks land through _swing.
	player.global_position = boss.global_position + Vector3(0, 0.3, 2.2)
	player.set("facing", 0.0)
	var before: float = boss.get("hp")
	var to: Vector3 = boss.global_position - player.global_position
	player.set("facing", atan2(-to.x, -to.z))
	player.call("_start", "light")
	await get_tree().create_timer(0.7).timeout
	print("SELFTEST light hit: ", before, " -> ", boss.get("hp"))
	# A slam cut short by a rest at the bonfire leaves no ring or glow.
	boss.call("_start", "slam")
	await get_tree().create_timer(0.6).timeout
	var ring: MeshInstance3D = boss.get("ring")
	var glow: StandardMaterial3D = boss.get("body").get("weapon_glow")
	print("SELFTEST mid-slam ring ", ring.visible, " glow ", glow.emission_energy_multiplier > 0.0)
	main.set("_boss_awake", false)
	boss.call("reset")
	main.call("_on_boss_changed")
	await get_tree().physics_frame
	print("SELFTEST after reset ring ", ring.visible, " glow ", glow.emission_energy_multiplier, " boss bar ", main.get("hud").get("boss_box").visible)
	# Keyboard alone can fight and look.
	var keys := 0
	for action in ["attack", "heavy", "look_left", "look_right"]:
		for event in InputMap.action_get_events(action):
			if event is InputEventKey:
				keys += 1
	print("SELFTEST keyboard fight keys ", keys)
	main.set("_boss_awake", true)
	boss.call("_start", "move")
	# Damage the boss into phase 2, a stagger, then death.
	boss.call("take_hit", 400.0, player.global_position)
	await get_tree().physics_frame
	print("SELFTEST phase ", boss.get("phase"), " state ", boss.get("state"))
	await get_tree().create_timer(2.2).timeout
	boss.call("take_hit", 60.0, player.global_position)
	boss.call("take_hit", 60.0, player.global_position)
	print("SELFTEST stagger? ", boss.get("state"))
	boss.call("take_hit", 9999.0, player.global_position)
	await get_tree().create_timer(2.5).timeout
	print("SELFTEST boss after death: ", boss.get("state"), " won ", main.get("won"))
	# Flask and roll.
	player.set("hp", 40.0)
	player.call("_start", "heal")
	await get_tree().create_timer(1.3).timeout
	print("SELFTEST healed to ", player.get("hp"), " flasks ", player.get("flasks"))
	player.call("_start", "roll")
	await get_tree().physics_frame
	await get_tree().create_timer(0.2).timeout
	print("SELFTEST untouchable mid-roll: ", player.call("untouchable"))
	print("SELFTEST done")
	get_tree().quit()
