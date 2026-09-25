#version 450

layout(location = 0) in vec2 vUv;
layout(location = 0) out vec4 fragColor;

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

float hash11(float value)
{
    return fract(sin(value * 127.1 + 311.7) * 43758.5453123);
}

vec2 rotate2d(vec2 value, float angle)
{
    float sine = sin(angle);
    float cosine = cos(angle);
    return mat2(cosine, -sine, sine, cosine) * value;
}

vec3 spectralColor(float hue)
{
    vec3 phase = vec3(0.00, 0.67, 0.33) + hue;
    return 0.5 + 0.5 * cos(6.2831853 * phase);
}

vec2 projectOrigin(vec3 origin)
{
    vec4 clip = uViewProjection * vec4(origin, 1.0);
    return clip.xy / max(0.001, clip.w) * 0.5 + 0.5;
}

float pressureRing(vec2 point, float radius)
{
    float distanceToRing = abs(length(point) - radius);
    return exp(-distanceToRing * 135.0) + exp(-distanceToRing * 34.0) * 0.17;
}

// Onsets explode into directional starbursts instead of recoloring the field.
float burstSystem(vec2 point, float radius, float seed)
{
    float radialDistance = length(point);
    float angle = atan(point.y, point.x);
    float rays = pow(abs(cos(angle * (5.0 + floor(seed * 4.0)) + seed * 9.0)), 22.0);
    float reach = exp(-radialDistance * 9.0) *
        (1.0 - smoothstep(0.0, radius + 0.16, radialDistance));
    float core = exp(-radialDistance * 46.0);
    return rays * reach * 0.86 + core * 1.7;
}

// Downbeats and rare strong rhythmic accents sweep laser beams across the field.
float laserSystem(vec2 point, float seed)
{
    float angle = seed * 6.2831853 + uTime.x * 0.08 + uAccentPhase.z * 0.05;
    vec2 beamPoint = rotate2d(point, angle);
    float scan = sin(beamPoint.x * 31.0 - uTime.x * 7.0 + seed * 19.0);
    float beam = exp(-abs(beamPoint.y) * 520.0) * (0.72 + 0.28 * scan);
    float glow = exp(-abs(beamPoint.y) * 54.0) * 0.22;
    vec2 crossPoint = rotate2d(point, angle + 1.17 + seed * 0.9);
    float crossBeam = exp(-abs(crossPoint.y) * 360.0) *
        exp(-abs(crossPoint.x) * 1.8) * 0.62;
    return beam + glow + crossBeam;
}

// Section changes tear a jagged chromatic rift through the established field.
float riftSystem(vec2 point, float seed)
{
    vec2 riftPoint = rotate2d(point, seed * 4.7 - 1.1);
    float jagged = sin(riftPoint.x * 47.0 + seed * 31.0) * 0.010;
    jagged += sin(riftPoint.x * 113.0 - seed * 17.0) * 0.004;
    float crackDistance = abs(riftPoint.y - jagged);
    float finiteLength = 1.0 - smoothstep(0.18, 0.68, abs(riftPoint.x));
    float core = exp(-crackDistance * 390.0);
    float aura = exp(-crackDistance * 42.0) * 0.28;
    float branches = exp(-abs(riftPoint.y + jagged * 2.4 - riftPoint.x * 0.16) * 210.0) * 0.18;
    return (core + aura + branches) * finiteLength;
}

// A newly detected source opens a rotating portal-like flare and orbiting arcs.
float sourceFlareSystem(vec2 point, float radius, float seed)
{
    vec2 flarePoint = rotate2d(point, -uTime.x * 0.14 - seed * 3.0);
    float radialDistance = length(flarePoint);
    float angle = atan(flarePoint.y, flarePoint.x);
    float ring = exp(-abs(radialDistance - radius * 0.72 - 0.028) * 105.0);
    float arcs = smoothstep(0.18, 0.94, sin(angle * 3.0 + seed * 21.0));
    float petals = pow(abs(cos(angle * 4.0 - radialDistance * 28.0)), 13.0);
    petals *= exp(-radialDistance * 8.5);
    return ring * arcs * 1.35 + petals * 0.48;
}

void main()
{
    vec4 waves[4] = vec4[4](uWave0, uWave1, uWave2, uWave3);
    float amplitudes[4] = float[4](
        uWaveAmplitude.x, uWaveAmplitude.y,
        uWaveAmplitude.z, uWaveAmplitude.w
    );
    float characters[4] = float[4](
        uWaveCharacter.x, uWaveCharacter.y,
        uWaveCharacter.z, uWaveCharacter.w
    );
    vec3 result = vec3(0.0);

    for (int index = 0; index < 4; ++index) {
        float amplitude = amplitudes[index];
        if (amplitude <= 0.001 || waves[index].w < 0.0) {
            continue;
        }
        vec2 point = vUv - projectOrigin(waves[index].xyz);
        point.x *= uTime.w;
        float radius = clamp(0.018 + waves[index].w * 0.047, 0.018, 0.68);
        float seed = hash11(dot(waves[index].xyz, vec3(13.7, 29.3, 47.1)) + float(index));
        float character = characters[index];
        float phenomenon = pressureRing(point, radius) * 0.31;
        vec3 color = spectralColor(uHarmony.w + seed * uSpectrum.w * 0.35);

        if (character < 1.5) {
            phenomenon += burstSystem(point, radius, seed);
        } else if (character < 2.5) {
            phenomenon += laserSystem(point, seed) * 1.18;
            color = mix(color, vec3(0.56, 0.90, 1.0), 0.48);
        } else if (character < 3.5) {
            phenomenon += riftSystem(point, seed) * 1.42;
            color = mix(color, vec3(1.0, 0.31, 0.77), 0.44);
        } else {
            phenomenon += sourceFlareSystem(point, radius, seed) * 1.24;
            color = mix(color, vec3(0.74, 1.0, 0.73), 0.38);
        }
        result += color * phenomenon * amplitude * (0.35 + uFeedback.y * 0.42);
    }
    result *= uSceneTuning.w;
    fragColor = vec4(result, max(result.r, max(result.g, result.b)));
}
