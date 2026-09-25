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

layout(location = 0) out vec2 vComet;
layout(location = 1) out vec3 vColor;
layout(location = 2) out float vIntensity;

float hash11(float value)
{
    return fract(sin(value * 127.1 + 311.7) * 43758.5453123);
}

vec3 spectralColor(float hue)
{
    vec3 phase = vec3(0.00, 0.67, 0.33) + hue;
    return 0.5 + 0.5 * cos(6.2831853 * phase);
}

void main()
{
    const vec2 corners[6] = vec2[6](
        vec2(0.0, -1.0), vec2(1.0, -1.0), vec2(1.0, 1.0),
        vec2(0.0, -1.0), vec2(1.0, 1.0), vec2(0.0, 1.0)
    );
    vec2 corner = corners[gl_VertexIndex];
    float seed = particleVelocitySeed.w;
    // Particle initialization orders this stable marker into a compact prefix.
    // The renderer can therefore draw every comet candidate without submitting
    // the full ambient-particle pool to this pass.
    float species = smoothstep(0.925, 0.995, fract(seed));
    float speed = length(particleVelocitySeed.xyz);
    float kinetic = max(uSpectrum.y, uLayers.y);
    kinetic = max(kinetic, uMusic.w * 0.82);
    float beatGate = 0.44 + 0.56 * pow(
        0.5 + 0.5 * cos(6.2831853 * uSpatial.z), 7.0
    );
    float presence = species * (0.025 + kinetic * 0.78) * beatGate *
        uSceneTuning.y;
    // Percussive share describes timbre, not permission for a dense trail layer.
    presence *= 0.15 + 0.85 * smoothstep(0.40, 0.90, uMusic.x);

    vec3 direction = particleVelocitySeed.xyz / max(speed, 0.001);
    vec3 facing = normalize(cross(uCameraRight.xyz, uCameraUp.xyz));
    vec3 side = cross(direction, facing);
    if (length(side) < 0.001) {
        side = uCameraRight.xyz;
    }
    side = normalize(side);
    float trailLength = (0.055 + speed * 0.18 + kinetic * 0.42) *
        (0.58 + hash11(seed + 19.0) * 0.92);
    float width = (0.004 + kinetic * 0.0065) * uFeedback.w;
    vec3 worldPosition = particlePositionLife.xyz
        - direction * corner.x * trailLength
        + side * corner.y * width * (1.0 - corner.x * 0.72);
    gl_Position = uViewProjection * vec4(worldPosition, 1.0);

    float hue = uHarmony.w + 0.08 + hash11(seed + 51.0) * uSpectrum.w * 0.31;
    vComet = corner;
    vColor = mix(spectralColor(hue), vec3(0.72, 0.91, 1.0), 0.34);
    vIntensity = presence * (0.44 + min(speed, 3.0) * 0.32);
}
