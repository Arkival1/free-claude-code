// The ground: grass, a worn dirt path (the vertex colour's red) and rock on
// the slopes, each from its own texture, mapped by world position.
shader_type spatial;

uniform sampler2D grass_tex : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D dirt_tex : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D rock_tex : source_color, filter_linear_mipmap_anisotropic, repeat_enable;
uniform sampler2D bumps : hint_normal, filter_linear_mipmap_anisotropic, repeat_enable;
uniform float scale = 0.11;

varying vec3 world_pos;
varying float slope;

void vertex() {
	world_pos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
	slope = 1.0 - clamp((MODEL_MATRIX * vec4(NORMAL, 0.0)).y, 0.0, 1.0);
}

void fragment() {
	vec2 uv = world_pos.xz * scale;
	vec3 grass = texture(grass_tex, uv).rgb;
	vec3 dirt = texture(dirt_tex, uv * 1.4).rgb;
	vec3 rock = texture(rock_tex, uv * 0.6).rgb;
	float path = smoothstep(0.15, 0.85, COLOR.r);
	vec3 color = mix(grass, dirt, path);
	color = mix(color, rock, smoothstep(0.22, 0.45, slope));
	ALBEDO = color;
	ROUGHNESS = mix(0.92, 0.8, path);
	NORMAL_MAP = texture(bumps, uv * 2.3).rgb;
	NORMAL_MAP_DEPTH = 1.2;
}
