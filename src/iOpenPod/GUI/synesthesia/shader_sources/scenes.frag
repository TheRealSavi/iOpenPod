#version 450

/*
 * Hallmark · macrostructure: Directed Shot Sequence · tone: cinematic-kinetic · anchor hue: music-derived
 * Hallmark · pre-emit critique: P5 H5 E5 S5 R4 V5
 * Atmospheric / cinematic-kinetic / music-derived spectrum / Directed Shot Sequence
 */

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

const float PI = 3.14159265359;
const float TAU = 6.28318530718;

float hash11(float value)
{
    return fract(sin(value * 127.1 + 311.7) * 43758.5453123);
}

float hash21(vec2 value)
{
    return fract(sin(dot(value, vec2(127.1, 311.7))) * 43758.5453123);
}

float valueNoise(vec2 point)
{
    vec2 cell = floor(point);
    vec2 local = fract(point);
    local = local * local * (3.0 - 2.0 * local);
    return mix(
        mix(hash21(cell), hash21(cell + vec2(1.0, 0.0)), local.x),
        mix(hash21(cell + vec2(0.0, 1.0)), hash21(cell + vec2(1.0)), local.x),
        local.y
    );
}

float blendedAngularPattern(
    float angle,
    float phase,
    float continuousCount,
    float sharpness
)
{
    float lowerCount = floor(continuousCount);
    float topologyBlend = smoothstep(0.0, 1.0, fract(continuousCount));
    float lowerPattern = pow(
        abs(cos(angle * lowerCount + phase)),
        sharpness
    );
    float upperPattern = pow(
        abs(cos(angle * (lowerCount + 1.0) + phase)),
        sharpness
    );
    return mix(lowerPattern, upperPattern, topologyBlend);
}

vec2 rotate2d(vec2 value, float angle)
{
    float sine = sin(angle);
    float cosine = cos(angle);
    return mat2(cosine, -sine, sine, cosine) * value;
}

vec3 spectralColor(float hue, float saturation, float lightness)
{
    vec3 phase = vec3(0.00, 0.67, 0.33) + hue;
    vec3 pureColor = 0.5 + 0.5 * cos(TAU * phase);
    return mix(vec3(lightness), pureColor * (0.48 + lightness), saturation);
}

float journeyTime()
{
    // Live rates advance phases on the CPU; never rescale elapsed motion here.
    return uTime.x * 0.18 + uMotionPhase.x * 0.42;
}

float musicWave(float coordinate, float phase)
{
    float beat = TAU * uSpatial.z;
    float fundamental = sin(
        coordinate * (2.2 + uLayers.x * 2.8) + phase +
        uTime.x * 0.30 + uMotionPhase.x * 0.18
    );
    float overtone = sin(
        coordinate * (5.4 + uSpectrum.x * 5.2) + phase * 1.71 -
        (uTime.x * 0.22 + uMusicPhase.w * 0.52)
    );
    float transientWave = sin(coordinate * 11.0 - beat + phase * 0.73);
    float transientGain = uHarmony.z * 0.42 + uSpectrum.y * 0.34 + uSpatial.w * 0.24;
    return (fundamental * 0.58 + overtone * 0.27 + transientWave * transientGain) *
        uSceneMotion1.y;
}

vec3 cameraRay(vec2 point)
{
    vec3 filmOffset =
        point.x * uCameraRight.xyz + point.y * uCameraUp.w * uCameraUp.xyz;
    return normalize(
        uCameraForward.xyz + filmOffset * max(0.01, uCameraPosition.w)
    );
}

vec2 scenePlane(vec2 point, float layerOffset, float sceneScale)
{
    vec3 ray = cameraRay(point);
    float planeDistance = max(0.35, uCameraRight.w + layerOffset);
    float denominator = max(0.10, dot(ray, uCameraForward.xyz));
    float distanceAlongRay = planeDistance / denominator;
    vec3 worldPosition = uCameraPosition.xyz + ray * distanceAlongRay;
    return worldPosition.xy * uSceneMotion1.w / max(0.1, sceneScale);
}

vec2 worldFlow(vec2 point, float travelScale, float orbitScale)
{
    float orbit = uMotionPhase.y * orbitScale;
    vec2 worldPoint = rotate2d(point, orbit);
    worldPoint += uFlowPhase.xy * travelScale;
    return worldPoint;
}

float starLayer(vec2 point, float scale, float drift, float threshold)
{
    vec2 gridPoint = point * scale + vec2(uTime.x * drift, -uTime.x * drift * 0.37);
    vec2 cell = floor(gridPoint);
    vec2 local = fract(gridPoint) - 0.5;
    float starSeed = hash21(cell);
    float star = smoothstep(threshold, 1.0, starSeed);
    float core = exp(-dot(local, local) * mix(38.0, 140.0, starSeed));
    return star * core * (0.55 + 0.45 * sin(uTime.x * 1.7 + starSeed * 41.0));
}

float streamingStars(
    vec2 point,
    float scale,
    float speed,
    float threshold,
    float stretch,
    float parallaxSpeed
)
{
    vec2 direction = normalize(uSceneMotion0.xy + vec2(0.0001));
    vec2 gridPoint = point * scale -
        (uFlowPhase.xy * speed + uFlowPhase.zw * parallaxSpeed);
    vec2 cell = floor(gridPoint);
    vec2 local = fract(gridPoint) - 0.5;
    float seed = hash21(cell);
    float along = dot(local, direction);
    float across = dot(local, vec2(-direction.y, direction.x));
    float star = smoothstep(threshold, 1.0, seed);
    float body = exp(-across * across * 180.0 - along * along * stretch);
    return star * body * (0.48 + 0.52 * sin(uTime.x * 2.1 + seed * 53.0));
}

vec3 magnetosphereScene(vec2 point)
{
    float travel = journeyTime();
    vec2 worldPoint = worldFlow(scenePlane(point, 0.0, 3.4), 0.012, 0.62);
    worldPoint += uSceneMotion0.xy * sin(travel * 0.17) * uSceneMotion1.z * 0.16;
    vec3 color = vec3(0.0006, 0.0010, 0.0024);
    color += spectralColor(uHarmony.w + 0.17, 0.48, 0.55) *
        streamingStars(worldPoint, 35.0, 0.18, 0.962, 48.0, 0.0) * 0.56;
    color += vec3(0.72, 0.88, 1.0) *
        streamingStars(worldPoint, 72.0, 0.42, 0.982, 24.0, 0.0) * 0.78;
    for (int index = 0; index < 4; ++index) {
        float seed = float(index) * 7.91 + uStructure.z * 3.7;
        float depthPhase = fract(
            uMotionPhase.w * 0.026 + float(index) * 0.23 + hash11(seed)
        );
        float flybyScale = mix(0.62, 1.42, depthPhase);
        float layerDepth = mix(-0.85, 0.85, depthPhase);
        vec2 layerPoint = worldFlow(
            scenePlane(point, layerDepth, 3.4),
            0.012,
            0.62
        );
        vec2 center = vec2(
            sin(seed * 1.31 + uTime.x * 0.08 + uMotionPhase.z * 0.18),
            cos(seed * 1.73 - (uTime.x * 0.07 + uMotionPhase.z * 0.15))
        ) * (0.18 + float(index) * 0.12);
        center += uSceneMotion0.xy * (depthPhase - 0.5) * 0.34;
        center.x += uSpatial.x * 0.21;
        vec2 local = (layerPoint - center) / flybyScale;
        float distanceToCore = length(local);
        float angle = atan(local.y, local.x);
        float nucleus = exp(-distanceToCore * (35.0 - uMusic.y * 11.0));
        float halo = exp(-distanceToCore * 8.0) * 0.18;
        float orbitRadius = 0.075 + float(index) * 0.018 + uMusic.y * 0.045 +
            musicWave(angle * 0.8, seed) * 0.006;
        vec2 ellipse = vec2(local.x, local.y * (1.45 + 0.25 * sin(seed)));
        float orbit = exp(-abs(length(ellipse) - orbitRadius) * 155.0);
        orbit *= 0.24 + 0.76 * pow(abs(cos(
            angle * 3.0 + seed + travel * (0.54 + float(index) * 0.08)
        )), 10.0);
        float rays = pow(abs(cos(
            angle * (11.0 + float(index) * 3.0) + seed + travel * 0.26
        )), 38.0);
        rays *= exp(-distanceToCore * 6.0) * (0.18 + uMusic.w * 0.52);
        float pressureFront = exp(-abs(
            distanceToCore - (0.03 + uSpatial.z * (0.34 + uMusic.y * 0.22))
        ) * 72.0) * uHarmony.z;
        vec3 nucleusColor = spectralColor(uHarmony.w + seed * 0.031, 0.72, 0.64);
        color += nucleusColor *
            (nucleus * 1.65 + halo + orbit * 0.70 + rays * 0.52 + pressureFront * 0.24);
        color += vec3(1.0, 0.94, 0.82) * pow(nucleus, 3.0) * 1.8;
    }
    return color;
}

vec3 ribbonCascadeScene(vec2 point)
{
    float travel = journeyTime();
    vec3 color = spectralColor(uHarmony.w + 0.22, 0.58, 0.12) * 0.018;
    vec2 turned = worldFlow(scenePlane(point, 0.0, 3.5), 0.20, 0.24);
    turned = rotate2d(turned, -0.18 + uSpatial.x * 0.25);
    for (int index = 0; index < 8; ++index) {
        float order = float(index) - 3.5;
        float phase = order * 0.83 + uStructure.z * 4.0;
        float depthPhase = fract(
            float(index) / 8.0 + uMotionPhase.w * 0.022
        );
        float perspective = mix(0.72, 1.38, depthPhase);
        vec2 ribbonPoint = worldFlow(
            scenePlane(point, order * 0.17, 3.5),
            0.20,
            0.24
        );
        ribbonPoint = rotate2d(
            ribbonPoint,
            -0.18 + uSpatial.x * 0.25
        ) * perspective;
        float wave = musicWave(ribbonPoint.x + travel * 0.16, phase);
        wave += 0.34 * musicWave(ribbonPoint.x * 1.83 - travel * 0.09, -phase * 0.7);
        wave *= 0.085 + uLayers.x * 0.042;
        float center = order * 0.072 + wave +
            sin(travel * 0.12 + phase) * (0.07 + uSpatial.y * 0.035);
        float distanceToRibbon = abs(ribbonPoint.y - center);
        float thread = exp(-distanceToRibbon * (115.0 - uSpatial.y * 28.0));
        float veil = exp(-distanceToRibbon * 18.0) * 0.13;
        float travelling = 0.55 + 0.45 * sin(
            ribbonPoint.x * 13.0 - (travel * 2.4 + uMusicPhase.x * 1.8) + phase
        );
        vec3 ribbonColor = spectralColor(
            uHarmony.w + order * 0.035 * uSpectrum.w,
            0.62 + uSpectrum.w * 0.25,
            0.46
        );
        float depthLight = mix(0.42, 1.28, depthPhase);
        color += ribbonColor *
            (thread * (0.48 + travelling * 0.82) + veil) * depthLight;
    }
    float crossing = exp(-abs(
        turned.x + musicWave(turned.y * 1.7, travel * 0.13) * 0.10
    ) * 18.0);
    color += spectralColor(uHarmony.w + 0.34, 0.52, 0.55) * crossing * 0.13;
    return color;
}

vec3 warpTunnelScene(vec2 point)
{
    float travel = journeyTime();
    vec2 vanishingPoint = uSceneMotion0.xy * vec2(
        sin(travel * 0.23),
        cos(travel * 0.19)
    ) * (0.08 + uSceneMotion1.z * 0.045);
    vanishingPoint.x += uSpatial.x * 0.16;
    vec2 tunnelPoint = rotate2d(
        scenePlane(point, 0.0, 3.6) - vanishingPoint,
        uMotionPhase.y * 0.48
    );
    float radius = length(tunnelPoint) + 0.002;
    float angle = atan(tunnelPoint.y, tunnelPoint.x);
    float radialWave = musicWave(angle * 0.72, uStructure.z * 2.0);
    radius = max(0.002, radius + radialWave * 0.008);
    float spin = angle + uTime.x * 0.18 + uMotionPhase.z * 0.72 +
        log(radius) * 0.72;
    float spokes = blendedAngularPattern(
        spin,
        0.0,
        8.0 + uLayers.y * 5.0,
        34.0
    );
    float depthTravel = uMusicPhase.y * 0.62 + uMusicPhase.z * 0.48;
    float rings = exp(-abs(fract(log(radius) * 3.4 - depthTravel) - 0.5) * 17.0);
    float throat = exp(-radius * 7.5);
    float velocity = spokes * rings * smoothstep(0.04, 0.92, radius);
    float corridors = spokes * smoothstep(0.08, 0.92, radius);
    float streaks = pow(abs(sin(
        spin * 29.0 + hash11(floor(radius * 18.0 - depthTravel * 4.0)) * 5.0
    )), 44.0);
    streaks *= smoothstep(0.12, 1.0, radius) * (0.24 + uSpectrum.y * 0.76);
    vec3 cool = spectralColor(uHarmony.w + 0.08, 0.82, 0.47);
    vec3 hot = spectralColor(uHarmony.w - 0.16, 0.88, 0.60);
    vec3 color = mix(cool, hot, rings) *
        (velocity * 1.18 + corridors * 0.24 + rings * 0.10 + streaks * 0.30);
    color += vec3(0.75, 0.92, 1.0) * throat * (0.12 + uMusic.w * 0.55);
    return color;
}

vec3 mirrorWaveScene(vec2 point)
{
    float travel = journeyTime();
    vec2 wavePoint = worldFlow(scenePlane(point, 0.12, 3.35), 0.055, 0.48);
    wavePoint += musicWave(travel * 0.08, 0.0) * uSceneMotion0.xy * 0.018;
    vec2 folded = abs(rotate2d(
        wavePoint,
        0.22 * sin(travel * 0.16) + uMotionPhase.y * 0.18
    ));
    folded = rotate2d(folded, PI * 0.25);
    folded = abs(folded);
    vec3 color = vec3(0.0008, 0.0011, 0.0020);
    for (int index = 0; index < 7; ++index) {
        float order = float(index);
        float phase = order * 0.57 + uStructure.z * 2.4;
        float wave = musicWave(
            folded.x * (1.35 + order * 0.16) + travel * 0.10,
            phase
        );
        wave += sin(
            folded.x * 19.0 - (travel * 0.78 + uMusicPhase.x) + phase * 2.1
        ) * uSpectrum.y * 0.18;
        float contour = abs(folded.y - (0.055 + order * 0.060 + wave * (0.018 + uLayers.y * 0.022)));
        float line = exp(-contour * 230.0);
        float echo = exp(-contour * 38.0) * 0.12;
        vec3 lineColor = spectralColor(uHarmony.w + order * 0.026, 0.74, 0.58);
        color += lineColor * (line * (0.48 + uHarmony.z * 0.75) + echo);
    }
    float axis = exp(-min(abs(wavePoint.x), abs(wavePoint.y)) * 190.0) * 0.11;
    color += vec3(0.68, 0.90, 1.0) * axis;
    return color;
}

vec3 prismaticVeilScene(vec2 point)
{
    float travel = journeyTime();
    vec2 cameraPoint = worldFlow(scenePlane(point, 0.0, 3.5), 0.085, 0.34);
    float cloud = valueNoise(
        cameraPoint * 2.4 + uFlowPhase.xy * 0.09
    );
    vec3 background = spectralColor(uHarmony.w + 0.29, 0.88, 0.25);
    background *= 0.035 + cloud * (0.075 + uMusic.x * 0.10);
    vec3 color = background;
    for (int index = 0; index < 6; ++index) {
        float order = float(index) - 2.5;
        float depthPhase = fract(
            float(index) / 6.0 + uMotionPhase.w * 0.032
        );
        float perspective = mix(0.58, 1.54, depthPhase);
        vec2 sheetPoint = worldFlow(
            scenePlane(point, order * 0.24, 3.5),
            0.085,
            0.34
        );
        vec2 local = rotate2d(
            sheetPoint * perspective,
            order * 0.18 + sin(travel * 0.08 + order) * 0.12
        );
        float fold = musicWave(
            local.x * (0.82 + float(index) * 0.12) + travel * 0.07,
            order
        );
        fold += cos(
            local.x * 6.1 - local.y * 1.3 - travel * 0.42
        ) * (0.22 + uSpectrum.y * 0.18);
        float sheetPosition = fold * 0.12 + order * 0.09;
        float sheet = exp(-abs(local.y - sheetPosition) * 31.0);
        float edge = exp(-abs(local.y - sheetPosition) * 145.0);
        vec3 sheetColor = spectralColor(
            uHarmony.w + order * 0.075 + uStructure.z * 0.04,
            0.72,
            0.54
        );
        color += sheetColor *
            (sheet * 0.12 + edge * 0.46) * mix(0.46, 1.34, depthPhase);
    }
    return color;
}

vec3 latticeCathedralScene(vec2 point)
{
    float travel = journeyTime();
    vec2 local = rotate2d(
        scenePlane(point, 0.0, 3.45),
        uMotionPhase.y * 0.12
    );
    local.x += uSceneMotion0.x * sin(travel * 0.17) * 0.16;
    local.y += 0.18 + musicWave(travel * 0.09, 1.7) * 0.018;
    float depth = 1.0 / max(0.055, abs(local.y));
    float forwardTravel = uMusicPhase.y * 0.16 + uMusicPhase.z * 0.12;
    float perspectiveX = local.x * depth + uFlowPhase.x * 0.12;
    float verticalGrid = exp(-abs(fract(perspectiveX * 0.34) - 0.5) * 54.0);
    float horizontalGrid = exp(-abs(
        fract(depth * 0.24 + forwardTravel) - 0.5
    ) * 48.0);
    float verticalGlow = exp(-abs(fract(perspectiveX * 0.34) - 0.5) * 13.0);
    float horizontalGlow = exp(-abs(
        fract(depth * 0.24 + forwardTravel) - 0.5
    ) * 12.0);
    float horizon = exp(-abs(local.y) * 150.0);
    float archRadius = length(vec2(local.x, local.y * 1.42 + 0.12));
    archRadius += musicWave(atan(local.y, local.x), 0.4) * 0.008;
    float arches = exp(-abs(fract(
        archRadius * 5.4 - forwardTravel * 0.18
    ) - 0.5) * 62.0);
    arches *= smoothstep(-0.48, 0.12, local.y);
    float frame = verticalGrid * 0.62 + horizontalGrid * 0.50 + arches * 0.54;
    float frameGlow = verticalGlow * 0.12 + horizontalGlow * 0.10;
    frame = (frame + frameGlow) * (0.34 + uHarmony.y * 0.78);

    vec2 foreground = rotate2d(
        scenePlane(point, -1.6, 3.45),
        -uMotionPhase.y * 0.07
    );
    foreground.y += 0.26 + musicWave(travel * 0.07, 3.1) * 0.012;
    float aisle = exp(-abs(fract(
        foreground.x * 0.19 + forwardTravel * 0.025
    ) - 0.5) * 34.0);
    float vaultRadius = length(vec2(foreground.x * 0.72, foreground.y + 0.16));
    float vault = exp(-abs(fract(
        vaultRadius * 3.1 - forwardTravel * 0.08
    ) - 0.5) * 38.0);
    vault *= smoothstep(-0.62, 0.20, foreground.y);

    vec3 lineColor = spectralColor(uHarmony.w + 0.12, 0.62, 0.68);
    vec3 color = lineColor * (frame + aisle * 0.20 + vault * 0.18);
    color += vec3(0.62, 0.84, 1.0) * horizon * (0.22 + uMusic.w * 0.68);
    color += lineColor * starLayer(
        scenePlane(point, 2.4, 3.45),
        48.0,
        0.0,
        0.989
    ) * 0.22;
    return color;
}

vec3 solarBloomScene(vec2 point)
{
    float travel = journeyTime();
    vec2 bodyPlane = scenePlane(point, 0.0, 3.35);
    vec2 flyby = uSceneMotion0.xy * sin(travel * 0.21) * 0.24;
    flyby += vec2(
        cos(uMotionPhase.y * 0.42),
        sin(uMotionPhase.y * 0.36)
    ) * uSceneMotion1.z * 0.09;
    vec2 local = rotate2d(
        bodyPlane - flyby,
        uMotionPhase.y * 0.44
    );
    float radius = length(local) + 0.001;
    float angle = atan(local.y, local.x);
    float radialWave = musicWave(angle * 0.74, uStructure.z * 2.0);
    radius += radialWave * (0.012 + uMusic.y * 0.009);
    float turbulence = valueNoise(vec2(
        angle * 3.3 + travel * 0.08,
        radius * 7.0 - travel * 0.52
    ));
    float petals = blendedAngularPattern(
        angle,
        sin(radius * 8.0) - travel * 0.46,
        5.0 + uLayers.w * 4.0,
        9.0
    );
    petals *= exp(-radius * (2.4 + (1.0 - uMusic.x) * 1.8));
    float corona = exp(-abs(radius - 0.22 - turbulence * 0.075) * 18.0);
    float core = exp(-radius * 10.0);
    float flare = pow(abs(cos(angle * 13.0 + travel * 0.42)), 28.0) *
        exp(-radius * 3.8);
    float pressureFront = exp(-abs(
        radius - (0.06 + uSpatial.z * (0.62 + uMusic.y * 0.22))
    ) * 42.0) * (uHarmony.z * 0.58 + uSpatial.w * 0.72);
    vec3 ember = spectralColor(0.02 + uHarmony.w * 0.10, 0.92, 0.54);
    vec3 gold = vec3(1.0, 0.54, 0.12);
    vec3 color = mix(ember, gold, 0.58) *
        (petals * 0.84 + corona * 0.44 + flare * (0.18 + uMusic.w * 0.62) +
         pressureFront * 0.34);
    color += vec3(1.0, 0.90, 0.62) * core * 1.25;
    color += ember * valueNoise(
        scenePlane(point, -0.55, 3.35) * 3.0 + uTime.x * 0.02
    ) *
        exp(-radius * 1.7) * 0.045;
    return color;
}

vec3 starChamberScene(vec2 point)
{
    float travel = journeyTime();
    vec2 slowPoint = worldFlow(scenePlane(point, 0.0, 3.8), 0.028, 0.42);
    vec2 farPoint = worldFlow(scenePlane(point, 2.4, 3.8), 0.028, 0.42);
    vec2 nearPoint = worldFlow(scenePlane(point, -1.8, 3.8), 0.028, 0.42);
    float depthPulse = 1.0 + sin(travel * 0.12) * uSceneMotion1.x * 0.055;
    slowPoint *= depthPulse;
    float farStars = streamingStars(
        farPoint,
        25.0,
        0.34,
        0.925,
        62.0,
        0.08
    );
    float nearStars = streamingStars(
        nearPoint,
        58.0,
        0.86,
        0.972,
        15.0,
        0.16
    );
    float dust = valueNoise(
        slowPoint * 2.2 + uFlowPhase.xy * 0.055
    );
    dust *= valueNoise(
        slowPoint * 5.7 - uFlowPhase.xy * 0.092
    );
    float horizonShape = slowPoint.y + sin(slowPoint.x * 2.4 + uTime.x * 0.025) * 0.07;
    horizonShape +=
        (valueNoise(slowPoint * 1.6 + uFlowPhase.xy * 0.025) - 0.5) *
        0.16;
    horizonShape += musicWave(slowPoint.x, 2.1) * 0.012;
    float nebula = smoothstep(0.22, 0.58, dust) * exp(-dot(slowPoint, slowPoint) * 0.48);
    float dustLane = exp(-abs(horizonShape) * 5.6) * (0.25 + 0.75 * dust);
    vec2 beaconPoint = worldFlow(scenePlane(point, -0.8, 3.8), 0.016, 0.18);
    vec2 beaconDelta = beaconPoint - vec2(0.42, -0.08);
    float beaconRadius = length(beaconDelta) + 0.001;
    float beaconAngle = atan(beaconDelta.y, beaconDelta.x);
    float beaconCore = exp(-beaconRadius * 19.0);
    float beaconHalo = exp(-abs(beaconRadius - 0.17) * 31.0);
    float beaconRays = pow(abs(cos(beaconAngle * 7.0 + travel * 0.055)), 26.0) *
        exp(-beaconRadius * 5.2);
    vec3 nebulaColor = spectralColor(uHarmony.w + 0.21, 0.68, 0.32);
    vec3 beaconColor = spectralColor(uHarmony.w - 0.11, 0.48, 0.76);
    vec3 color = vec3(0.0024, 0.0038, 0.0090);
    color += nebulaColor *
        (nebula * (0.15 + uSpectrum.x * 0.18) + dustLane * 0.18);
    color += spectralColor(uHarmony.w - 0.08, 0.36, 0.72) * farStars * 1.58;
    color += vec3(0.82, 0.91, 1.0) * nearStars * 2.04;
    color += beaconColor *
        (beaconCore * 0.88 + beaconHalo * 0.15 + beaconRays * 0.10);
    float horizon = exp(-abs(horizonShape) * 34.0);
    color += nebulaColor * horizon * 0.24;
    return color;
}

// Pixel-aware strokes retain their shape through close inspection and pullbacks.
float sceneStroke(float distanceToLine, float width)
{
    float feather = max(fwidth(distanceToLine), 0.0006);
    return 1.0 - smoothstep(width, width + feather, abs(distanceToLine));
}

vec3 contourDriftScene(vec2 point)
{
    float travel = journeyTime();
    vec3 color = vec3(0.0015, 0.0025, 0.004);
    for (int layer = 0; layer < 3; ++layer) {
        float order = float(layer);
        vec2 p = worldFlow(scenePlane(point, order * 0.65 - 0.65, 3.8), 0.055, 0.18);
        p += vec2(order * 0.71, order * -0.48);
        // A domain-warped height field produces asymmetric contour islands,
        // saddles and channels instead of concentric rings around a focal sun.
        vec2 warp = vec2(valueNoise(p * 1.4 + travel * 0.022),
                         valueNoise(p * 1.7 - travel * 0.018 + 8.4));
        float height = valueNoise(p * 2.1 + warp * 1.7);
        height += valueNoise(p * 4.6 - warp) * (0.15 + uLayers.w * 0.12);
        height += musicWave(p.x * 0.8 + p.y * 0.6, order) * 0.035;
        float levels = height * 9.0;
        float contour = sceneStroke(sin(levels * PI), 0.032);
        float crest = pow(max(0.0, cos(levels * PI)), 18.0);
        float charge = 0.5 + 0.5 * sin(p.x * 3.0 + p.y * 4.0 - travel * 0.7);
        vec3 ink = spectralColor(uHarmony.w + order * 0.12 + height * 0.10, 0.76, 0.45);
        color += ink * (contour * (0.40 + charge * 0.38) + crest * 0.045) /
            (1.0 + order * 0.55);
    }
    return color;
}

vec3 crystalShoalScene(vec2 point)
{
    float travel = journeyTime();
    vec3 color = vec3(0.001, 0.002, 0.005);
    for (int layer = 0; layer < 3; ++layer) {
        float order = float(layer);
        vec2 p = scenePlane(point, order * 0.85 - 0.85, 3.6);
        p = worldFlow(p, 0.075 + order * 0.018, 0.16);
        p *= 3.0 + order * 1.25;
        p += vec2(order * 11.3, order * 4.7);
        vec2 cell = floor(p);
        vec2 local = fract(p) - 0.5;
        float seed = hash21(cell + order * 31.0);
        vec2 center = vec2(hash21(cell + 3.1), hash21(cell + 8.7)) - 0.5;
        local -= center * 0.25;
        local = rotate2d(local, seed * TAU + travel * (seed - 0.5) * 0.24);
        // Faceted, elongated diamonds tumble on separate depth slices.
        float size = 0.14 + seed * 0.11 + uLayers.w * 0.025;
        float diamond = abs(local.x) * 1.6 + abs(local.y) * 0.8;
        float edge = sceneStroke(diamond - size, 0.008);
        float inside = 1.0 - smoothstep(size - 0.015, size + 0.015, diamond);
        float facet = smoothstep(-0.05, 0.05, local.x + local.y * 0.35);
        float seam = sceneStroke(local.x + local.y * 0.35, 0.006) * inside;
        float glint = pow(max(0.0, sin(seed * 19.0 + travel * 0.65)), 12.0);
        float wave = 0.65 + 0.25 * musicWave(cell.x * 0.4, seed * TAU);
        float population = smoothstep(0.20, 0.38, seed);
        vec3 glass = spectralColor(uHarmony.w + seed * 0.20 + order * 0.11, 0.70, 0.53);
        color += glass * population * wave *
            (edge * (0.68 + glint * uSpectrum.y) + inside * (0.055 + facet * 0.17) + seam * 0.20) /
            (1.0 + order * 0.40);
    }
    return color;
}

vec3 braidedCurrentScene(vec2 point)
{
    float travel = journeyTime();
    vec3 color = vec3(0.002, 0.001, 0.004);
    for (int strand = 0; strand < 6; ++strand) {
        float order = float(strand);
        float phase = order * TAU / 3.0;
        float bundle = floor(order / 3.0) - 0.5;
        vec2 p = scenePlane(point, sin(phase + travel * 0.15) * 0.65, 3.5);
        p = rotate2d(p, -0.32 + uSpatial.x * 0.12);
        float along = p.y + travel * 0.14;
        float twist = along * 3.6 + phase + travel * 0.28;
        float depth = 0.5 + 0.5 * cos(twist);
        float center = bundle * 1.05 + sin(twist) * (0.19 + uLayers.w * 0.13);
        center += musicWave(along * 0.7, bundle * 2.0) * 0.095;
        float delta = p.x - center;
        float width = mix(0.010, 0.026, depth);
        float rope = sceneStroke(delta, width);
        float halo = exp(-abs(delta) * 38.0) * 0.12;
        float beadPhase = along * 13.0 - (travel * 1.6 + uMusicPhase.x) + phase;
        float beads = pow(max(0.0, cos(beadPhase)), 14.0);
        vec3 thread = spectralColor(uHarmony.w + order * 0.045 + bundle * 0.18, 0.76, 0.51);
        // The near strand shades the far strand at each crossing.
        float occlusion = rope * depth * 0.70;
        color *= 1.0 - occlusion;
        color += thread * (rope * (0.38 + depth * 0.55 + beads * 0.62) + halo);
        color += vec3(0.75, 0.87, 1.0) * rope * beads * depth * uSpectrum.y * 0.30;
    }
    return color;
}

vec3 signalRainScene(vec2 point)
{
    float travel = journeyTime();
    vec3 color = vec3(0.001, 0.003, 0.004);
    for (int layer = 0; layer < 3; ++layer) {
        float order = float(layer);
        vec2 p = scenePlane(point, order * 0.8 - 0.8, 3.8);
        p.x += musicWave(p.y * 0.45, order * 2.3) * 0.035;
        p.x += uFlowPhase.x * 0.025 + order * 5.7;
        float columns = 17.0 + order * 8.0;
        float column = floor(p.x * columns);
        float seed = hash11(column + order * 93.4);
        float across = fract(p.x * columns) - 0.5;
        float speed = 0.35 + seed * 0.48 + order * 0.12;
        float fall = p.y * 0.65 + (travel * 0.7 + uMusicPhase.x * 0.5) * speed + seed * 7.0;
        float trail = fract(fall);
        // Both ends vanish at wrap, so a streak can re-enter without a flash.
        float envelope = smoothstep(0.0, 0.035, trail) *
            (1.0 - smoothstep(0.10, 0.72, trail));
        float head = exp(-abs(trail - 0.055) * 105.0);
        float rail = sceneStroke(across, 0.032 + order * 0.004);
        float dashes = 0.30 + 0.70 * smoothstep(0.30, 0.48, abs(sin(p.y * 65.0 + seed * 9.0)));
        float population = smoothstep(0.18, 0.40, seed);
        vec3 rain = spectralColor(uHarmony.w + order * 0.13 + seed * 0.08, 0.73, 0.51);
        color += rain * population * rail * envelope * dashes * (0.70 + uLayers.y * 0.40) /
            (1.0 + order * 0.55);
        color += vec3(0.72, 0.91, 1.0) * population * rail * head * 0.75;
    }
    return color;
}

vec3 renderScene(int scene, vec2 point)
{
    if (scene == 0) {
        return magnetosphereScene(point);
    }
    if (scene == 1) {
        return ribbonCascadeScene(point);
    }
    if (scene == 2) {
        return warpTunnelScene(point);
    }
    if (scene == 3) {
        return mirrorWaveScene(point);
    }
    if (scene == 4) {
        return prismaticVeilScene(point);
    }
    if (scene == 5) {
        return latticeCathedralScene(point);
    }
    if (scene == 6) {
        return solarBloomScene(point);
    }
    if (scene == 8) {
        return contourDriftScene(point);
    }
    if (scene == 9) {
        return crystalShoalScene(point);
    }
    if (scene == 10) {
        return braidedCurrentScene(point);
    }
    if (scene == 11) {
        return signalRainScene(point);
    }
    return starChamberScene(point);
}

void main()
{
    vec2 point = vUv * 2.0 - 1.0;
    point.x *= uTime.w;
    int primary = int(floor(uScene.x + 0.5));
    int secondary = int(floor(uScene.y + 0.5));
    float blend = smoothstep(0.0, 1.0, uScene.z);
    vec3 first = renderScene(primary, point);
    vec3 second = secondary == primary ? first : renderScene(secondary, point);
    vec3 color = mix(first, second, blend);
    float transitionVeil = exp(-abs(length(point) - mix(0.0, 1.15, blend)) * 9.0);
    color += spectralColor(uHarmony.w + 0.31, 0.42, 0.62) *
        transitionVeil * uScene.w * 0.12;
    fragColor = vec4(color, 1.0);
}
