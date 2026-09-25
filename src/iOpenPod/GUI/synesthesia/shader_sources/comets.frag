#version 450

layout(location = 0) in vec2 vComet;
layout(location = 1) in vec3 vColor;
layout(location = 2) in float vIntensity;
layout(location = 0) out vec4 fragColor;

void main()
{
    if (vIntensity < 0.0005) {
        discard;
    }
    float taper = 1.0 - vComet.x;
    float crossSection = exp(-abs(vComet.y) * mix(8.0, 22.0, vComet.x));
    float tail = exp(-vComet.x * 3.9) * taper;
    float head = exp(-dot(vec2(vComet.x * 5.5, vComet.y * 2.5),
        vec2(vComet.x * 5.5, vComet.y * 2.5)));
    float intensity = (crossSection * tail + head * 1.8) * vIntensity;
    vec3 color = mix(vColor, vec3(0.92, 0.98, 1.0), head * 0.72);
    fragColor = vec4(color * intensity, intensity);
}
