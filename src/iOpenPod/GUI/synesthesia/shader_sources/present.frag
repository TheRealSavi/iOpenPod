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

layout(binding = 1) uniform sampler2D fieldTexture;

vec3 acesApproximation(vec3 color)
{
    color = max(vec3(0.0), color);
    return clamp(
        (color * (2.51 * color + 0.03)) /
            (color * (2.43 * color + 0.59) + 0.14),
        0.0,
        1.0
    );
}

vec3 spectralColor(float hue)
{
    vec3 phase = vec3(0.00, 0.67, 0.33) + hue;
    return 0.5 + 0.5 * cos(6.2831853 * phase);
}

float stableScreenGrain(vec2 pixelPosition)
{
    return fract(
        52.9829189 * fract(dot(pixelPosition, vec2(0.06711056, 0.00583715)))
    ) - 0.5;
}

void main()
{
    vec3 color = texture(fieldTexture, vUv).rgb;
    vec2 centered = vUv - vec2(0.5 + uSpatial.x * 0.035, 0.5);
    float atmosphere = exp(-dot(centered, centered) *
        mix(7.5, 3.2, uSpatial.y));
    vec3 atmosphereColor = spectralColor(uHarmony.w + 0.09 + uStructure.z * 0.05);
    color += atmosphereColor * atmosphere *
        (0.002 + 0.013 * uStructure.w + 0.010 * uLayers.x);
    const vec3 luminanceWeights = vec3(0.2126, 0.7152, 0.0722);
    float sceneLuminance = dot(color, luminanceWeights);
    color *= uFeedback.y / (1.0 + sceneLuminance * 0.22);
    float compressedLuminance = dot(color, luminanceWeights);
    color = mix(
        vec3(compressedLuminance),
        color,
        1.04 + 0.24 * uSpectrum.w
    );
    float shadowGate = smoothstep(0.004, 0.065, compressedLuminance);
    color *= shadowGate;
    color = acesApproximation(color);
    float vignette = 1.0 - smoothstep(0.26, 0.79, length(centered));
    color *= 0.58 + vignette * 0.42;
    float grain = stableScreenGrain(floor(gl_FragCoord.xy));
    color += grain * (0.003 + 0.004 * uSpectrum.z);
    color = max(color, vec3(0.0));
    color = pow(color, vec3(1.0 / 2.2));
    fragColor = vec4(color, 1.0);
}
