#version 450

// Hallmark · pre-emit critique: P5 H4 E4 S5 R5 V4

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

layout(binding = 1) uniform sampler2D currentField;
layout(binding = 2) uniform sampler2D previousField;

float referenceFrameCount()
{
    return clamp(uTime.y * 60.0, 0.0, 2.0);
}

float normalizedRetention(float retentionAt60Hz, float frameCount)
{
    return pow(clamp(retentionAt60Hz, 0.0001, 1.0), frameCount);
}

vec2 historyCoordinates(vec2 coordinates)
{
    float historyY = 0.5 + (coordinates.y - 0.5) * sign(uViewport.y);
    return vec2(coordinates.x, historyY);
}

void main()
{
    float frameCount = referenceFrameCount();
    if (frameCount <= 0.0) {
        fragColor = vec4(
            texture(previousField, historyCoordinates(vUv)).rgb,
            1.0
        );
        return;
    }

    vec2 centered = vUv - 0.5;
    float radius = length(centered);
    vec2 tangent = vec2(-centered.y, centered.x);
    float sceneIdentity = mix(uScene.x, uScene.y, uScene.z) / 7.0;
    vec2 curlWarp = tangent *
        (0.00022 + uMusic.z * 0.0009 + uLayers.x * 0.00065) *
        sin(uTime.x * 0.16 + uMotionPhase.y * 0.11 +
            radius * mix(13.0, 27.0, sceneIdentity));
    vec2 breathing = centered * (uMusic.y - 0.42) * 0.00075;
    vec2 stereoDrift = vec2(uSpatial.x, 0.0) * uSpatial.y * 0.0007;
    vec2 journeyDrift = uSceneMotion0.xy *
        (0.00018 + uSceneMotion0.z * 0.00038) *
        (0.44 + uMusic.x * 0.56);
    vec2 depthWarp = centered * uSceneMotion1.x *
        (0.00010 + uHarmony.z * 0.00024);
    vec2 uvAdvection =
        -curlWarp + breathing - stereoDrift - journeyDrift + depthWarp;
    vec2 previousUv = clamp(
        vUv + uvAdvection * frameCount,
        vec2(0.002),
        vec2(0.998)
    );
    vec3 history = texture(previousField, historyCoordinates(previousUv)).rgb;
    vec3 current = texture(currentField, vUv).rgb;

    vec2 texel = uViewport.zw;
    vec3 neighborhood = vec3(0.0);
    neighborhood += texture(currentField, vUv + vec2(texel.x * 3.0, 0.0)).rgb;
    neighborhood += texture(currentField, vUv - vec2(texel.x * 3.0, 0.0)).rgb;
    neighborhood += texture(currentField, vUv + vec2(0.0, texel.y * 3.0)).rgb;
    neighborhood += texture(currentField, vUv - vec2(0.0, texel.y * 3.0)).rgb;
    neighborhood *= 0.25;

    const vec3 luminanceWeights = vec3(0.2126, 0.7152, 0.0722);
    float neighborhoodLuminance = dot(neighborhood, luminanceWeights);
    float bloomGate = smoothstep(0.72, 1.65, neighborhoodLuminance);
    vec3 bloom = neighborhood * bloomGate;

    float historyLuminance = dot(history, luminanceWeights);
    float brightHistoryRetention = normalizedRetention(
        1.0 / (1.0 + historyLuminance * 0.075),
        frameCount
    );
    history *= brightHistoryRetention;
    float cameraMotion = clamp(uCameraForward.w, 0.0, 1.0);
    float retentionAt60Hz = clamp(
        uFeedback.x - uSpatial.w * 0.025 - uStructure.x * 0.018 -
            uScene.w * 0.14 - cameraMotion * 0.16,
        0.68,
        0.94
    );
    float retention = normalizedRetention(retentionAt60Hz, frameCount);
    float injectionScale =
        (1.0 - retention) / max(1.0 - retentionAt60Hz, 0.0001);
    float erosion = mix(0.0035, 0.010, smoothstep(0.08, 0.8, historyLuminance));
    erosion += cameraMotion * 0.009;
    history = max(history - vec3(erosion * frameCount), vec3(0.0));

    float currentLuminance = dot(current, luminanceWeights);
    current /= 1.0 + currentLuminance * 0.16;
    vec3 accumulated =
        history * retention + current * uFeedback.z * injectionScale;
    accumulated += bloom *
        (0.045 + uMusic.w * 0.04 + uLayers.z * 0.028 + uSpectrum.y * 0.035) *
        injectionScale;
    float accumulatedLuminance = dot(accumulated, luminanceWeights);
    accumulated *= normalizedRetention(
        1.0 / (1.0 + accumulatedLuminance * 0.055),
        frameCount
    );
    fragColor = vec4(accumulated, 1.0);
}
