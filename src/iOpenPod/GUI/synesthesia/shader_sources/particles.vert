#version 450

layout(location = 0) in vec4 particlePositionLife;
layout(location = 1) in vec4 particleVelocitySeed;

layout(std140, binding = 0) uniform FieldState {
    mat4 uViewProjection;
    vec4 uTime;
    vec4 uMusic;
    vec4 uHarmony;
    vec4 uSpectrum;
    vec4 uLayers;
    vec4 uStructure;
    vec4 uSpatial;
    vec4 uCameraRight;
    vec4 uCameraUp;
    vec4 uCameraPosition;
    vec4 uCameraForward;
    vec4 uAttractor0;
    vec4 uAttractor1;
    vec4 uAttractor2;
    vec4 uAttractor3;
    vec4 uWave0;
    vec4 uWave1;
    vec4 uWave2;
    vec4 uWave3;
    vec4 uWaveAmplitude;
    vec4 uWaveCharacter;
    vec4 uScene;
    vec4 uSceneTuning;
    vec4 uSceneMotion0;
    vec4 uSceneMotion1;
    vec4 uViewport;
    vec4 uFeedback;
    vec4 uMotionPhase;
    vec4 uFlowPhase;
    vec4 uMusicPhase;
    vec4 uAccentPhase;
};

layout(location = 0) out vec2 vLocal;
layout(location = 1) out vec4 vColorAndSmoke;
layout(location = 2) out float vIntensity;
layout(location = 3) out float vDepth;

float hash11(float value)
{
    return fract(sin(value * 127.1 + 311.7) * 43758.5453123);
}

vec3 spectralColor(float hue, float saturation, float lightness)
{
    vec3 phase = vec3(0.00, 0.67, 0.33) + hue;
    vec3 pureColor = 0.5 + 0.5 * cos(6.2831853 * phase);
    return mix(vec3(lightness), pureColor * (0.54 + lightness), saturation);
}

void main()
{
    const vec2 corners[6] = vec2[6](
        vec2(-1.0, -1.0), vec2(1.0, -1.0), vec2(1.0, 1.0),
        vec2(-1.0, -1.0), vec2(1.0, 1.0), vec2(-1.0, 1.0)
    );
    vec2 corner = corners[gl_VertexIndex];
    float seed = particleVelocitySeed.w;
    float family = hash11(seed + 71.0);
    float smoke = smoothstep(0.66, 0.90, hash11(seed + 7.0));
    float spark = smoothstep(0.84, 0.99, hash11(seed + 29.0));
    spark *= max(uMusic.w, max(uSpectrum.y, uLayers.y));
    float speed = length(particleVelocitySeed.xyz);
    float rhythmicBreath = 0.5 + 0.5 * cos(6.2831853 * uSpatial.z);
    float pulse = 0.68 + 0.20 * sin(
        uTime.x * (0.8 + hash11(seed) * 2.4) + seed
    );
    pulse += rhythmicBreath * uHarmony.z * 0.20;
    float size = mix(0.007, 0.058, smoke) *
        (0.72 + 0.65 * hash11(seed + 13.0)) * uFeedback.w;
    size *= 1.0 + spark * 1.9 + min(speed, 3.0) * 0.055;
    size *= 0.84 + uSpatial.y * 0.42 + uLayers.z * 0.16;
    vec3 velocityDirection = particleVelocitySeed.xyz / max(speed, 0.001);
    vec3 right = normalize(uCameraRight.xyz + velocityDirection * corner.y *
        min(speed * 0.035, 0.16));
    vec3 worldPosition = particlePositionLife.xyz +
        right * corner.x * size + uCameraUp.xyz * corner.y * size;
    gl_Position = uViewProjection * vec4(worldPosition, 1.0);

    float familyOffset = mix(-0.12, 0.18, family) * uSpectrum.w;
    familyOffset += uStructure.z * 0.07;
    float hue = uHarmony.w + familyOffset + speed * 0.012;
    float saturation = 0.48 + uSpectrum.w * 0.42;
    float lightness = 0.24 + uSpectrum.x * 0.22;
    vec3 color = spectralColor(hue, saturation, lightness);
    vec3 airColor = spectralColor(hue + 0.16, saturation * 0.72, 0.55);
    color = mix(color, airColor, spark * (0.45 + uSpectrum.x * 0.35));
    vec3 vocalColor = spectralColor(hue + 0.24, 0.52, 0.62);
    color = mix(color, vocalColor, uLayers.z * smoothstep(0.52, 1.0, family) * 0.58);
    vLocal = corner;
    vColorAndSmoke = vec4(color, smoke);
    float contour = sin(dot(particlePositionLife.xyz, vec3(1.31, -1.73, 1.09)) +
        uTime.x * 0.12 + sin(particlePositionLife.y * 2.4));
    float organizedRidge = smoothstep(-0.28, 0.72, contour);
    float structure = mix(0.24, organizedRidge, 0.26 + uHarmony.y * 0.64);
    float familyPresence = mix(uLayers.x, uLayers.y, step(0.55, family));
    familyPresence = max(familyPresence, mix(uLayers.w, uLayers.z, family));
    // Stable membership reveals more matter gradually, without respawning the
    // simulation or turning every quiet harmonic layer into a full particle fog.
    float density = 0.16 + 0.80 * smoothstep(0.38, 0.90, uMusic.x);
    float population = 1.0 - smoothstep(density, density + 0.08, hash11(seed + 113.0));
    vIntensity = pulse * structure *
        (0.12 + 0.52 * uMusic.x + 0.52 * spark + 0.24 * familyPresence) *
        uSceneTuning.x * population;
    vDepth = smoothstep(4.0, 12.5, gl_Position.w);
}
