// Grass blades that sway in the wind, darker at the root and lit through
// at the tip (each blade's colour comes from its instance colour).
shader_type spatial;
render_mode cull_disabled, diffuse_burley;

uniform vec3 root_color : source_color = vec3(0.10, 0.17, 0.06);
uniform vec3 tip_color : source_color = vec3(0.55, 0.55, 0.22);
uniform float wind = 0.32;

varying vec3 tint;

void vertex() {
	tint = COLOR.rgb;
	vec3 world = (MODEL_MATRIX * vec4(0.0, 0.0, 0.0, 1.0)).xyz;
	float h = UV.y;
	float gust = sin(TIME * 1.6 + world.x * 0.31 + world.z * 0.23) + 0.45 * sin(TIME * 3.3 + world.z * 0.9);
	VERTEX.x += gust * wind * h * h;
	VERTEX.z += gust * wind * 0.4 * h * h;
}

void fragment() {
	vec3 color = mix(root_color, tip_color, UV.y) * tint;
	ALBEDO = color;
	ROUGHNESS = 0.85;
	SPECULAR = 0.25;
	BACKLIGHT = color * 0.6 * UV.y;
}
