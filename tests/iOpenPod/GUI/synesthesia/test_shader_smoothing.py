"""Source contracts for frame-rate-independent Synesthesia shaders."""

from pathlib import Path

from iOpenPod.GUI.synesthesia import renderer

_SHADER_ROOT = Path(renderer.__file__).with_name("shader_sources")


def _shader_source(name: str) -> str:
    return (_SHADER_ROOT / name).read_text(encoding="utf-8")


def test_feedback_uses_seconds_as_a_60_hz_reference_frame_count() -> None:
    source = _shader_source("feedback.frag")

    assert "clamp(uTime.y * 60.0, 0.0, 2.0)" in source
    assert "normalizedRetention(retentionAt60Hz, frameCount)" in source
    assert "vUv + uvAdvection * frameCount" in source
    assert "erosion * frameCount" in source
    assert "(1.0 - retention) / max(1.0 - retentionAt60Hz, 0.0001)" in source
    assert "current * uFeedback.z * injectionScale" in source
    bloom_accumulation = source.split("accumulated += bloom *", maxsplit=1)[1].split(
        ";",
        maxsplit=1,
    )[0]
    assert "injectionScale" in bloom_accumulation


def test_zero_delta_copies_retained_history_without_processing_it() -> None:
    source = _shader_source("feedback.frag")
    zero_delta_guard = source.split("if (frameCount <= 0.0)", maxsplit=1)[1].split(
        "vec2 centered",
        maxsplit=1,
    )[0]

    assert "texture(previousField, historyCoordinates(vUv))" in zero_delta_guard
    assert "return;" in zero_delta_guard


def test_feedback_orients_retained_history_for_the_framebuffer_backend() -> None:
    source = _shader_source("feedback.frag")
    coordinate_function = source.split(
        "vec2 historyCoordinates(",
        maxsplit=1,
    )[1].split("\n}\n", maxsplit=1)[0]

    assert "sign(uViewport.y)" in coordinate_function
    assert "coordinates.y - 0.5" in coordinate_function
    assert "texture(previousField, historyCoordinates(vUv))" in source
    assert "texture(previousField, historyCoordinates(previousUv))" in source


def test_presentation_grain_is_stable_in_screen_space() -> None:
    source = _shader_source("present.frag")
    grain_function = source.split("float stableScreenGrain(", maxsplit=1)[1].split(
        "\n}\n",
        maxsplit=1,
    )[0]

    assert "uTime" not in grain_function
    assert "stableScreenGrain(floor(gl_FragCoord.xy))" in source
    assert "vUv * uViewport.xy + uTime.x" not in source
    grain_application = source.split(
        "float grain = stableScreenGrain(",
        maxsplit=1,
    )[1].split("fragColor", maxsplit=1)[0]
    assert grain_application.index("color = max(color, vec3(0.0));") < (
        grain_application.index("color = pow(color")
    )


def test_particle_micro_direction_interpolates_between_temporal_cells() -> None:
    source = _shader_source("field_sim.comp")
    micro_force = source.split("float microTime", maxsplit=1)[1].split(
        "force += microDirection",
        maxsplit=1,
    )[0]

    assert "smoothstep(0.0, 1.0, fract(microTime))" in micro_force
    assert "hash31(seed + microCell)" in micro_force
    assert "hash31(seed + microCell + 1.0)" in micro_force
    assert "mix(" in micro_force
    assert "floor(uTime.x * 18.0)" not in source


def test_scene_topology_blends_adjacent_integer_patterns() -> None:
    source = _shader_source("scenes.frag")
    topology_function = source.split(
        "float blendedAngularPattern(",
        maxsplit=1,
    )[1].split("\n}\n", maxsplit=1)[0]

    assert "floor(continuousCount)" in topology_function
    assert "smoothstep(0.0, 1.0, fract(continuousCount))" in topology_function
    assert "lowerCount + 1.0" in topology_function
    assert "mix(lowerPattern, upperPattern, topologyBlend)" in topology_function
    assert "8.0 + uLayers.y * 5.0" in source
    assert "5.0 + uLayers.w * 4.0" in source
    assert "floor(uLayers.y * 5.0)" not in source
    assert "floor(uLayers.w * 4.0)" not in source


def test_warp_tunnel_clamps_music_perturbed_radius_before_logarithms() -> None:
    source = _shader_source("scenes.frag")
    warp_tunnel = source.split("vec3 warpTunnelScene(", maxsplit=1)[1].split(
        "vec3 mirrorWaveScene(",
        maxsplit=1,
    )[0]

    perturbation = warp_tunnel.index("float radialWave = musicWave(")
    positive_domain_guard = warp_tunnel.index(
        "radius = max(0.002, radius + radialWave * 0.008);"
    )
    first_logarithm = warp_tunnel.index("log(radius)")

    assert perturbation < positive_domain_guard < first_logarithm
    assert "radius += musicWave(" not in warp_tunnel
