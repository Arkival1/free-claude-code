// A soft dark edge on the screen, and a red flash when you're hit.
shader_type canvas_item;

uniform float strength = 0.6;
uniform float flash = 0.0;

void fragment() {
	vec2 p = (UV - 0.5) * vec2(1.0, 0.82);
	float edge = smoothstep(0.32, 0.86, length(p));
	COLOR = vec4(mix(vec3(0.0), vec3(0.55, 0.02, 0.0), flash), edge * strength + flash * 0.3);
}
