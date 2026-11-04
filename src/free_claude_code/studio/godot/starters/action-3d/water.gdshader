// Still dark water: slow ripples, a sky sheen at grazing angles.
shader_type spatial;
render_mode cull_back, specular_schlick_ggx;

uniform vec3 deep : source_color = vec3(0.01, 0.04, 0.05);
uniform vec3 sheen : source_color = vec3(0.45, 0.32, 0.25);

void vertex() {
	VERTEX.y += sin(VERTEX.x * 0.9 + TIME * 1.1) * 0.025 + cos(VERTEX.z * 0.7 + TIME * 0.8) * 0.025;
}

void fragment() {
	vec2 w = UV * 24.0 + vec2(TIME * 0.12, TIME * 0.07);
	vec3 ripple = normalize(vec3(sin(w.x * 2.1 + TIME) * 0.08 + sin(w.y * 1.3) * 0.05, 1.0, cos(w.y * 2.4 - TIME) * 0.08));
	NORMAL = normalize((VIEW_MATRIX * vec4(ripple, 0.0)).xyz);
	float fresnel = pow(1.0 - clamp(dot(NORMAL, VIEW), 0.0, 1.0), 4.0);
	ALBEDO = mix(deep, sheen, fresnel * 0.6);
	ROUGHNESS = 0.04;
	SPECULAR = 0.7;
	ALPHA = 0.9;
}
