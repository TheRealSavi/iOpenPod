#version 450

layout(location = 0) in vec2 vLine;
layout(location = 1) in float vCharge;
layout(location = 2) in float vHue;
layout(location = 0) out vec4 fragColor;

vec3 palette(float hue)
{
    return 0.55 + 0.45 * cos(6.2831853 * (vec3(0.04, 0.37, 0.70) + hue));
}

void main()
{
    float edge = 1.0 - abs(vLine.y);
    float core = smoothstep(0.0, 0.82, edge);
    float glow = smoothstep(0.0, 1.0, edge) * 0.11;
    float intensity = (pow(core, 5.0) + glow) * vCharge;
    vec3 color = mix(palette(vHue), vec3(0.62, 0.86, 1.0), core * 0.62);
    fragColor = vec4(color * intensity, intensity);
}
