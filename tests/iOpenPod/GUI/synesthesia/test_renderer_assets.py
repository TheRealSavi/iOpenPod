# pyright: strict, reportPrivateUsage=false
# These white-box tests intentionally verify the renderer's packed GPU contract.

import math
import re
import struct
from pathlib import Path
from typing import cast

import pytest
from PySide6.QtCore import QByteArray
from PySide6.QtGui import (
    QRhi,
    QRhiBuffer,
    QRhiCommandBuffer,
    QRhiComputePipeline,
    QRhiSampler,
    QRhiShaderResourceBindings,
    QShader,
)
from PySide6.QtWidgets import QApplication

from iOpenPod.GUI.synesthesia import renderer
from iOpenPod.GUI.synesthesia.persistent_world import FieldImpulseCharacter
from iOpenPod.GUI.synesthesia.scene_director import VisualScene


@pytest.mark.parametrize(
    ("name", "minimum_variant_count"),
    [
        ("field_sim.comp.qsb", 5),
        ("particles.vert.qsb", 5),
        ("particles.frag.qsb", 5),
        ("comets.vert.qsb", 5),
        ("comets.frag.qsb", 5),
        ("filaments.vert.qsb", 5),
        ("filaments.frag.qsb", 5),
        ("fullscreen.vert.qsb", 5),
        ("scenes.frag.qsb", 5),
        ("events.frag.qsb", 5),
        ("feedback.frag.qsb", 5),
        ("present.frag.qsb", 5),
    ],
)
def test_packaged_field_shaders_are_portable_qshader_packages(
    name: str,
    minimum_variant_count: int,
) -> None:
    shader_root = Path(renderer.__file__).with_name("shader_sources")
    shader = QShader.fromSerialized(QByteArray((shader_root / name).read_bytes()))

    assert shader.isValid()
    assert len(shader.availableShaders()) >= minimum_variant_count


def test_every_shader_packages_compute_capable_opengl_variants() -> None:
    shader_root = Path(renderer.__file__).with_name("shader_sources")

    for shader_path in shader_root.glob("*.qsb"):
        shader = QShader.fromSerialized(QByteArray(shader_path.read_bytes()))
        glsl_versions = {
            (
                key.sourceVersion().version(),
                bool(key.sourceVersion().flags()),
            )
            for key in shader.availableShaders()
            if key.source() == QShader.Source.GlslShader
        }

        assert (310, True) in glsl_versions, shader_path.name
        assert (430, False) in glsl_versions, shader_path.name


def test_every_shader_and_the_cpu_share_one_field_state_layout() -> None:
    shader_root = Path(renderer.__file__).with_name("shader_sources")
    expected_members = tuple(name for name, _width in renderer._FIELD_STATE_LAYOUT)
    sources = tuple(
        path
        for path in shader_root.iterdir()
        if path.suffix in {".comp", ".frag", ".vert"}
        and "uniform FieldState" in path.read_text(encoding="utf-8")
    )

    assert len(sources) == 8
    for source_path in sources:
        source = source_path.read_text(encoding="utf-8")
        block = re.search(
            r"uniform FieldState \{(?P<body>.*?)\n\};",
            source,
            flags=re.DOTALL,
        )
        assert block is not None, source_path
        members = tuple(re.findall(r"\b(?:mat4|vec4)\s+(u\w+);", block.group("body")))
        assert members == expected_members, source_path

    assert renderer._UNIFORM_FLOAT_COUNT == 140
    assert renderer._UNIFORM_BYTE_COUNT == 560


def test_obsolete_tunnel_shaders_are_not_packaged() -> None:
    shader_root = Path(renderer.__file__).with_name("shader_sources")

    assert not list(shader_root.glob("tunnel.*"))


def test_scene_shader_implements_the_complete_scene_vocabulary() -> None:
    shader_root = Path(renderer.__file__).with_name("shader_sources")
    source = (shader_root / "scenes.frag").read_text(encoding="utf-8")

    assert tuple(int(scene) for scene in VisualScene) == tuple(range(len(VisualScene)))
    for scene in VisualScene:
        if scene is not VisualScene.STAR_CHAMBER:
            assert f"scene == {int(scene)}" in source
    assert "return starChamberScene(point);" in source


def test_scene_shader_uses_music_driven_directional_choreography() -> None:
    shader_root = Path(renderer.__file__).with_name("shader_sources")
    source = (shader_root / "scenes.frag").read_text(encoding="utf-8")
    feedback = (shader_root / "feedback.frag").read_text(encoding="utf-8")

    assert "vec4 uSceneMotion0;" in source
    assert "vec4 uSceneMotion1;" in source
    assert source.count("musicWave(") >= len(VisualScene) + 1
    assert source.count("journeyTime()") >= len(VisualScene) + 1
    assert "journeyDrift" in feedback
    assert "depthWarp" in feedback


def test_scene_shader_projects_the_composition_through_the_real_camera() -> None:
    shader_root = Path(renderer.__file__).with_name("shader_sources")
    source = (shader_root / "scenes.frag").read_text(encoding="utf-8")

    assert "vec4 uCameraPosition;" in source
    assert "vec4 uCameraForward;" in source
    assert "vec3 cameraRay(" in source
    assert "point.y * uCameraUp.w * uCameraUp.xyz" in source
    assert "vec2 scenePlane(" in source
    assert source.count("scenePlane(") >= len(VisualScene) + 1


def test_scene_planes_are_camera_facing_and_cannot_flip_behind_the_viewer() -> None:
    shader_root = Path(renderer.__file__).with_name("shader_sources")
    source = (shader_root / "scenes.frag").read_text(encoding="utf-8")
    scene_plane = source.split("vec2 scenePlane(", maxsplit=1)[1].split(
        "\n}\n",
        maxsplit=1,
    )[0]

    assert "uCameraRight.w + layerOffset" in scene_plane
    assert "dot(ray, uCameraForward.xyz)" in scene_plane
    assert "planeDistance / denominator" in scene_plane
    assert "ray.z" not in scene_plane


def test_comet_candidates_are_packed_into_a_small_draw_prefix() -> None:
    particle_count = 4_096
    particle_data = renderer._initial_particle_data(19, particle_count)
    particles = tuple(struct.iter_unpack("<8f", particle_data))
    comet_count = renderer._comet_instance_count(particle_count)
    markers = tuple(math.modf(particle[7])[0] for particle in particles)

    assert len(particles) == particle_count
    assert comet_count == math.ceil(particle_count * renderer._COMET_POOL_FRACTION)
    assert max(markers[comet_count:]) < 0.925
    assert max(markers[:comet_count]) >= 0.995

    comet_source = (
        Path(renderer.__file__).with_name("shader_sources") / "comets.vert"
    ).read_text(encoding="utf-8")
    assert "smoothstep(0.925, 0.995, fract(seed))" in comet_source
    assert "cb.draw(6, self._comet_count)" in Path(renderer.__file__).read_text(
        encoding="utf-8"
    )


def test_same_backend_resize_preserves_live_simulation_buffers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ResourceProbe:
        def __init__(self) -> None:
            self.destroyed = False

        def destroy(self) -> None:
            self.destroyed = True

    application = QApplication.instance()
    if not isinstance(application, QApplication):
        application = QApplication([])
    widget = renderer.SynesthesiaRenderer()
    same_rhi = cast("QRhi", object())
    particle_probes = [ResourceProbe(), ResourceProbe()]
    simulation_probes = [
        ResourceProbe(),
        ResourceProbe(),
        ResourceProbe(),
        ResourceProbe(),
        ResourceProbe(),
        ResourceProbe(),
        ResourceProbe(),
        ResourceProbe(),
        *particle_probes,
    ]
    widget._bound_rhi = same_rhi
    widget._particle_buffers = [
        cast("QRhiBuffer", resource) for resource in particle_probes
    ]
    widget._uniform_buffer = cast("QRhiBuffer", simulation_probes[0])
    widget._filament_buffer = cast("QRhiBuffer", simulation_probes[1])
    widget._sampler = cast("QRhiSampler", simulation_probes[2])
    widget._compute_bindings = [
        cast("QRhiShaderResourceBindings", simulation_probes[3]),
        cast("QRhiShaderResourceBindings", simulation_probes[4]),
    ]
    widget._compute_pipeline = cast("QRhiComputePipeline", simulation_probes[5])
    widget._particle_bindings = cast("QRhiShaderResourceBindings", simulation_probes[6])
    widget._filament_bindings = cast("QRhiShaderResourceBindings", simulation_probes[7])
    widget._particle_read_index = 1
    original_buffers = tuple(widget._particle_buffers)
    rebuild_count = 0

    def rebuild_graphics_resources() -> None:
        nonlocal rebuild_count
        rebuild_count += 1

    monkeypatch.setattr(widget, "rhi", lambda: same_rhi)
    monkeypatch.setattr(
        widget,
        "_create_graphics_resources",
        rebuild_graphics_resources,
    )
    command_buffer = cast("QRhiCommandBuffer", object())

    widget._initialize_resources(command_buffer)
    widget._initialize_resources(command_buffer)

    assert rebuild_count == 2
    assert tuple(widget._particle_buffers) == original_buffers
    assert widget._particle_read_index == 1
    assert not any(resource.destroyed for resource in simulation_probes)

    widget.releaseResources()

    assert all(resource.destroyed for resource in simulation_probes)
    assert cast("QRhi | None", widget._bound_rhi) is None
    assert widget._particle_buffers == []
    widget.close()


def test_relocation_clears_screen_history_without_resetting_the_world() -> None:
    application = QApplication.instance()
    if not isinstance(application, QApplication):
        application = QApplication([])
    widget = renderer.SynesthesiaRenderer()
    world = widget._world
    widget._history_needs_clear = False
    widget._history_read_index = 1

    widget.relocate(9_000, 1)

    assert widget._history_needs_clear is True
    assert widget._history_read_index == 0
    assert widget._world is world
    assert widget._position_seconds == pytest.approx(9.0)
    assert widget._transport_epoch == 1
    widget.close()


@pytest.mark.parametrize(
    ("character", "expected"),
    [
        (FieldImpulseCharacter.BURST, 1.0),
        (FieldImpulseCharacter.LASER, 2.0),
        (FieldImpulseCharacter.RIFT, 3.0),
        (FieldImpulseCharacter.SOURCE_FLARE, 4.0),
    ],
)
def test_impulse_characters_have_distinct_gpu_codes(
    character: FieldImpulseCharacter,
    expected: float,
) -> None:
    assert renderer._impulse_character_code(character) == expected


def test_presentation_response_preserves_headroom_as_activity_rises() -> None:
    calm = renderer.presentation_response(
        activity=0.0,
        energy=0.0,
        target_height=720,
    )
    intense = renderer.presentation_response(
        activity=1.0,
        energy=1.0,
        target_height=720,
    )

    assert 0.88 <= calm.history_retention < intense.history_retention <= 0.92
    assert 0.79 <= calm.exposure < intense.exposure <= 1.01
    assert 0.15 <= intense.source_gain < calm.source_gain <= 0.20
    assert calm.point_scale == intense.point_scale == pytest.approx(1.04)


def test_presentation_response_clamps_out_of_range_inputs() -> None:
    clipped_low = renderer.presentation_response(
        activity=-3.0,
        energy=-2.0,
        target_height=0,
    )
    clipped_high = renderer.presentation_response(
        activity=4.0,
        energy=9.0,
        target_height=10_000,
    )

    assert clipped_low.history_retention == pytest.approx(0.892)
    assert clipped_high.history_retention == pytest.approx(0.918)
    assert clipped_low.exposure == pytest.approx(0.80)
    assert clipped_high.exposure == pytest.approx(1.00)
    assert clipped_low.source_gain == pytest.approx(0.190)
    assert clipped_high.source_gain == pytest.approx(0.155)
