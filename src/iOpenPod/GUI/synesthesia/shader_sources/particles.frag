#version 450

layout(location = 0) in vec2 vLocal;
layout(location = 1) in vec4 vColorAndSmoke;
layout(location = 2) in float vIntensity;
layout(location = 3) in float vDepth;
layout(location = 0) out vec4 fragColor;

void main()
{
    float radiusSquared = dot(vLocal, vLocal);
    if (radiusSquared > 1.0) {
        discard;
    }
    float smoke = vColorAndSmoke.a;
    float sharpCore = exp(-radiusSquared * mix(8.8, 2.5, smoke));
    float halo = exp(-radiusSquared * 1.85) * (0.055 + smoke * 0.11);
    float depthAttenuation = mix(1.0, 0.42, vDepth);
    float alpha = (sharpCore + halo) * vIntensity *
        mix(0.38, 0.072, smoke) * depthAttenuation;
    vec3 color = vColorAndSmoke.rgb * alpha;
    color += vec3(0.46, 0.70, 1.0) * pow(sharpCore, 5.0) *
        vIntensity * (1.0 - smoke) * depthAttenuation * 0.15;
    fragColor = vec4(color, alpha);
}
