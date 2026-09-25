#version 450

layout(location = 0) in vec4 segmentStartDepth;
layout(location = 1) in vec4 segmentEndPhase;

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

layout(location = 0) out vec2 vLine;
layout(location = 1) out float vCharge;
layout(location = 2) out float vHue;

void main()
{
    const vec2 corners[6] = vec2[6](
        vec2(0.0, -1.0), vec2(1.0, -1.0), vec2(1.0, 1.0),
        vec2(0.0, -1.0), vec2(1.0, 1.0), vec2(0.0, 1.0)
    );
    vec2 corner = corners[gl_VertexIndex];
    float phase = segmentEndPhase.w;
    float depth = segmentStartDepth.w;
    float growthFront = fract(
        uAccentPhase.x
        + phase + uStructure.y * 0.11
    );
    float activation = smoothstep(depth * 0.095 - 0.12, depth * 0.095 + 0.08,
        growthFront);
    activation *= 0.68 + 0.32 * sin(uTime.x * 0.7 + phase * 17.0);

    vec3 start = segmentStartDepth.xyz;
    vec3 end = segmentEndPhase.xyz;
    vec3 bend = vec3(
        sin(start.y * 1.7 + uTime.x * 0.21 + phase),
        cos(start.z * 1.3 - uTime.x * 0.17 + phase),
        sin(start.x * 1.5 + uTime.x * 0.13)
    ) * (uMusic.z + uLayers.z * 0.65) * 0.055 * depth;
    bend.x += uSpatial.x * 0.035 * depth;
    start += bend;
    end += bend * 1.17;
    vec4 clipStart = uViewProjection * vec4(start, 1.0);
    vec4 clipEnd = uViewProjection * vec4(end, 1.0);
    vec2 ndcStart = clipStart.xy / max(0.001, clipStart.w);
    vec2 ndcEnd = clipEnd.xy / max(0.001, clipEnd.w);
    vec2 direction = normalize((ndcEnd - ndcStart) * vec2(uTime.w, 1.0) +
        vec2(0.0001));
    vec2 normal = vec2(-direction.y, direction.x) / vec2(uTime.w, 1.0);
    vec4 center = mix(clipStart, clipEnd, corner.x);
    float width = (0.56 + uMusic.w * 1.2 + uSpatial.w * 1.8) *
        uViewport.w * center.w;
    center.xy += normal * corner.y * width;
    gl_Position = center;

    float travelling = fract(
        uAccentPhase.y + phase
    );
    float charge = exp(-abs(corner.x - travelling) * 15.0);
    charge += uHarmony.z * exp(-abs(corner.x - fract(travelling + 0.46)) * 8.0);
    vLine = corner;
    vCharge = activation *
        (0.08 + charge * (1.0 + uLayers.x * 0.82 + uLayers.z * 0.72)) *
        uSceneTuning.z;
    vHue = uHarmony.w + phase * uSpectrum.w * 0.22 + depth * 0.018;
}
