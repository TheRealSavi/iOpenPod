"""Pixel-level regression tests for Synesthesia's multi-pass renderer."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from textwrap import dedent
from typing import TYPE_CHECKING, TypedDict, cast

import pytest

if TYPE_CHECKING:
    from pathlib import Path


class _FeedbackProbeResult(TypedDict):
    backend: str
    framebuffer_y_up: bool
    horizontal_mirror_correlation: float
    luminance_standard_deviation: float
    rendered_frames: int


class _SceneVarietyProbeResult(TypedDict):
    backend: str
    minimum_contrast: float
    minimum_motion: float
    maximum_scene_correlation: float


class _ParticleHeadroomProbeResult(TypedDict):
    backend: str
    coverage: list[float]


_D3D_FEEDBACK_PROBE = dedent(
    """
    import json
    import sys
    from pathlib import Path

    import numpy as np
    from PIL import Image, ImageFilter
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication

    from iOpenPod.GUI.synesthesia.renderer import SynesthesiaRenderer


    def correlation(first, second):
        first_centered = first - first.mean()
        second_centered = second - second.mean()
        denominator = np.sqrt(
            np.sum(first_centered * first_centered)
            * np.sum(second_centered * second_centered)
        )
        if denominator == 0.0:
            return 0.0
        return float(np.sum(first_centered * second_centered) / denominator)


    capture_path = Path(sys.argv[1])
    application = QApplication([])
    widget = SynesthesiaRenderer()
    widget.resize(1000, 840)
    rendered_frames = 0
    capture_pending = False
    failures = []
    loop = QEventLoop()
    timeout = QTimer()
    timeout.setSingleShot(True)


    def capture():
        pixmap = widget.grab()
        if pixmap.isNull() or not pixmap.save(str(capture_path), "PNG"):
            failures.append("The rendered Synesthesia frame could not be captured")
        loop.quit()


    def frame_rendered(_frame):
        global rendered_frames, capture_pending
        rendered_frames += 1
        if rendered_frames >= 60 and not capture_pending:
            capture_pending = True
            QTimer.singleShot(0, capture)


    def timed_out():
        failures.append("The Synesthesia renderer did not produce sixty frames")
        loop.quit()


    widget.failure.connect(failures.append)
    widget.frameChanged.connect(frame_rendered)
    timeout.timeout.connect(timed_out)
    timeout.start(10_000)
    widget.show()
    loop.exec()
    timeout.stop()

    if failures:
        raise RuntimeError("; ".join(failures))
    rhi = widget.rhi()
    if rhi is None:
        raise RuntimeError("The native QRhi backend was not initialized")
    backend = rhi.backend().name
    framebuffer_y_up = rhi.isYUpInFramebuffer()
    widget.hide()
    widget.deleteLater()
    application.processEvents()

    image = Image.open(capture_path).convert("L").filter(ImageFilter.GaussianBlur(5))
    pixels = np.asarray(image, dtype=np.float32)
    half_height = pixels.shape[0] // 2
    top = pixels[:half_height, :]
    bottom = pixels[-half_height:, :]
    mirror_correlation = correlation(top, bottom[::-1, :])
    print(
        json.dumps(
            {
                "backend": backend,
                "framebuffer_y_up": framebuffer_y_up,
                "horizontal_mirror_correlation": mirror_correlation,
                "luminance_standard_deviation": float(pixels.std()),
                "rendered_frames": rendered_frames,
            }
        )
    )
    """
)


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="The regression requires QRhi's framebuffer-down D3D11 backend",
)
def test_d3d_feedback_does_not_mirror_the_frame_horizontally(
    tmp_path: Path,
) -> None:
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "windows"
    capture_path = tmp_path / "synesthesia-feedback.png"
    completed = subprocess.run(
        [sys.executable, "-c", _D3D_FEEDBACK_PROBE, str(capture_path)],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=20,
    )

    assert completed.returncode == 0, completed.stderr
    result = cast("_FeedbackProbeResult", json.loads(completed.stdout))
    assert result["rendered_frames"] >= 60
    assert result["backend"] == "D3D11"
    assert not result["framebuffer_y_up"]
    assert result["luminance_standard_deviation"] > 1.0
    assert result["horizontal_mirror_correlation"] < 0.90


_D3D_SCENE_VARIETY_PROBE = dedent(
    """
    import json
    import sys
    from itertools import combinations
    from pathlib import Path

    import numpy as np
    from PIL import Image, ImageFilter
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication

    from iOpenPod.GUI.synesthesia import renderer
    from iOpenPod.GUI.synesthesia.scene_director import (
        CameraPose, MoodSignature, SceneMoment, VisualScene,
        _SCENE_TUNING, _plan_camera_sequence, plan_scene_motion,
    )

    output = Path(sys.argv[1])
    application = QApplication([])
    widget = renderer.SynesthesiaRenderer()
    widget.resize(800, 480)
    failures = []
    widget.failure.connect(failures.append)
    original_advance = widget._advance_field
    widget._advance_field = lambda _delta: original_advance(1.0 / 60.0)
    mood = MoodSignature(0.68, 0.62, 0.68, 0.62, 0.64, 0.72, 0.30)
    stills = []
    motion_differences = []

    for scene in (VisualScene.CONTOUR_DRIFT, VisualScene.CRYSTAL_SHOAL,
                  VisualScene.BRAIDED_CURRENT, VisualScene.SIGNAL_RAIN):
        sequence = _plan_camera_sequence(
            scene, mood, experience_seed=37, cue_identity=scene.name,
            start_seconds=0.0, duration_seconds=22.0,
        )
        motion = plan_scene_motion(
            scene, mood, experience_seed=37, cue_identity=scene.name,
        )
        # Identical, stationary framing and forcing isolate geometry and motion
        # from differences in authored cameras, palette, or musical input.
        pose = CameraPose((0.0, 0.0, 7.5), (0.0, 0.0, 0.0), 0.0, 52.0)
        moment = SceneMoment(
            scene, scene, 0.0, 0.0, _SCENE_TUNING[scene], motion,
            sequence.shots[0], pose, 0.0, 0.0,
        )
        renderer.idle_scene_moment = lambda: moment
        widget.set_preview(37, 300.0)
        widget.set_playing(True)
        loop = QEventLoop()
        frame_count = [0]
        images = []

        def capture():
            path = output / f"{scene.name}-{len(images)}.png"
            if not widget.grab().save(str(path), "PNG"):
                failures.append("Could not capture scene")
                loop.quit()
                return
            image = Image.open(path).convert("L")
            image = image.filter(ImageFilter.GaussianBlur(2)).resize((160, 96))
            images.append(np.asarray(image, dtype=np.float32))
            if len(images) == 2:
                loop.quit()

        def rendered(_frame):
            frame_count[0] += 1
            if frame_count[0] in (60, 120):
                QTimer.singleShot(0, capture)

        widget.frameChanged.connect(rendered)
        timeout = QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(loop.quit)
        timeout.start(10000)
        widget.show()
        loop.exec()
        timeout.stop()
        widget.frameChanged.disconnect(rendered)
        if failures or len(images) != 2:
            raise RuntimeError((failures, len(images)))
        stills.append(images[0])
        motion_differences.append(float(np.abs(images[1] - images[0]).mean()))

    backend = widget.diagnostics.backend
    widget.close()
    correlations = [
        float(np.corrcoef(first.ravel(), second.ravel())[0, 1])
        for first, second in combinations(stills, 2)
    ]
    print(json.dumps({
        "backend": backend,
        "minimum_contrast": min(float(image.std()) for image in stills),
        "minimum_motion": min(motion_differences),
        "maximum_scene_correlation": max(correlations),
    }))
    """
)


@pytest.mark.skipif(sys.platform != "win32", reason="Requires native QRhi D3D11")
def test_new_scenes_have_distinct_moving_geometry_on_d3d(tmp_path: Path) -> None:
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "windows"
    completed = subprocess.run(
        [sys.executable, "-c", _D3D_SCENE_VARIETY_PROBE, str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=50,
    )

    assert completed.returncode == 0, completed.stderr
    result = cast("_SceneVarietyProbeResult", json.loads(completed.stdout))
    assert result["backend"] == "D3D11"
    assert result["minimum_contrast"] > 8.0
    assert result["minimum_motion"] > 1.0
    assert result["maximum_scene_correlation"] < 0.90


_D3D_PARTICLE_HEADROOM_PROBE = dedent(
    """
    import json
    import sys
    from dataclasses import replace
    from pathlib import Path

    import numpy as np
    from PIL import Image
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtGui import QRhiDepthStencilClearValue
    from PySide6.QtWidgets import QApplication
    from iOpenPod.GUI.synesthesia import renderer
    from iOpenPod.GUI.synesthesia.persistent_world import FieldForcing
    from iOpenPod.GUI.synesthesia.scene_director import (
        CameraPose, SceneTuning, idle_scene_moment,
    )

    output = Path(sys.argv[1])
    application = QApplication([])
    widget = renderer.SynesthesiaRenderer()
    widget.resize(960, 600)
    failures = []
    widget.failure.connect(failures.append)

    def particles_only(cb, particle_index):
        # Isolate the production particle and comet passes from Scene artwork.
        cb.beginPass(widget._scene_target.target, renderer._CLEAR_COLOR,
                     QRhiDepthStencilClearValue(1.0, 0))
        cb.setViewport(renderer._viewport(widget._offscreen_size))
        cb.setGraphicsPipeline(widget._particle_pipeline)
        cb.setShaderResources(widget._particle_bindings)
        cb.setVertexInput(0, [(widget._particle_buffers[particle_index], 0)])
        cb.draw(6, widget._particle_count)
        cb.setGraphicsPipeline(widget._comet_pipeline)
        cb.setShaderResources(widget._particle_bindings)
        cb.draw(6, widget._comet_count)
        cb.endPass()

    widget._draw_scene = particles_only
    moment = replace(
        idle_scene_moment(), tuning=SceneTuning(1.3, 1.0, 0.0, 0.0),
        camera_pose=CameraPose((0.0, 0.0, 7.5), (0.0, 0.0, 0.0), 0.0, 52.0),
    )
    renderer.idle_scene_moment = lambda: moment
    original_advance = widget._advance_field
    widget._advance_field = lambda _delta: original_advance(1.0 / 60.0)
    coverage = []

    for activity in (0.25, 0.50, 0.90):
        widget.set_preview(37, 300.0)

        class Controls:
            def sample(self, _seconds):
                return FieldForcing(
                    activity=activity, low_frequency_mass=0.5,
                    fine_excitation=0.25, harmonic_coherence=0.7,
                    spectral_flux=0.25, percussive_layer=0.65,
                    harmonic_layer=0.65, brightness=0.7,
                    palette_hue=0.54, stereo_width=0.7,
                )

        widget._preview = Controls()
        widget.set_playing(True)
        frames = [0]
        loop = QEventLoop()

        def rendered(_frame):
            frames[0] += 1
            if frames[0] == 90:
                QTimer.singleShot(0, loop.quit)

        widget.frameChanged.connect(rendered)
        timeout = QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(loop.quit)
        timeout.start(10000)
        widget.show()
        loop.exec()
        timeout.stop()
        widget.frameChanged.disconnect(rendered)
        if failures or frames[0] < 90:
            raise RuntimeError((failures, frames[0]))
        path = output / f"particles-{activity}.png"
        if not widget.grab().save(str(path), "PNG"):
            raise RuntimeError("Could not capture particle field")
        pixels = np.asarray(Image.open(path).convert("L"), dtype=np.float32)
        coverage.append(float((pixels > 40).mean()))

    backend = widget.diagnostics.backend
    widget.close()
    print(json.dumps({"backend": backend, "coverage": coverage}))
    """
)


@pytest.mark.skipif(sys.platform != "win32", reason="Requires native QRhi D3D11")
def test_particle_clutter_leaves_headroom_for_musical_peaks(tmp_path: Path) -> None:
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "windows"
    completed = subprocess.run(
        [sys.executable, "-c", _D3D_PARTICLE_HEADROOM_PROBE, str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=40,
    )

    assert completed.returncode == 0, completed.stderr
    result = cast("_ParticleHeadroomProbeResult", json.loads(completed.stdout))
    assert result["backend"] == "D3D11"
    quiet, moderate, peak = result["coverage"]
    assert 0.001 < quiet < moderate < peak
    assert quiet < peak * 0.40
    assert moderate < peak * 0.60
    assert peak > 0.15


_D3D_MOTION_CONTINUITY_PROBE = dedent(
    """
    import json
    import sys
    from dataclasses import replace
    from pathlib import Path

    import numpy as np
    from PIL import Image
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtGui import QRhiDepthStencilClearValue
    from PySide6.QtWidgets import QApplication

    from iOpenPod.GUI.synesthesia import renderer
    from iOpenPod.GUI.synesthesia.motion_phases import MotionPhases
    from iOpenPod.GUI.synesthesia.persistent_world import FieldForcing
    from iOpenPod.GUI.synesthesia.scene_director import (
        CameraPose, MoodSignature, VisualScene, idle_scene_moment, plan_scene_motion,
    )

    output = Path(sys.argv[1])
    application = QApplication([])
    widget = renderer.SynesthesiaRenderer()
    widget.resize(640, 400)
    failures = []
    widget.failure.connect(failures.append)
    mood = MoodSignature(0.68, 0.62, 0.68, 0.62, 0.64, 0.72, 0.30)
    scene = VisualScene.WARP_TUNNEL
    motion = plan_scene_motion(scene, mood, experience_seed=37, cue_identity=scene.name)
    moment = replace(
        idle_scene_moment(), primary=scene, secondary=scene, motion=motion,
        camera_pose=CameraPose((0.0, 0.0, 7.5), (0.0, 0.0, 0.0), 0.0, 52.0),
    )
    renderer.idle_scene_moment = lambda: moment
    probe_time = 0.0
    activity = 0.5


    def advance(_delta):
        widget._latest_frame = replace(
            widget._latest_frame, field_time=probe_time,
            forcing=FieldForcing(
                activity=activity, low_frequency_mass=0.5,
                fine_excitation=0.25, harmonic_coherence=0.7,
                spectral_flux=0.25, percussive_layer=0.65,
                harmonic_layer=0.65, brightness=0.7,
                palette_hue=0.54, stereo_width=0.7,
            ),
        )


    def draw_isolated_scene(cb, _read_index, write_index):
        cb.beginPass(widget._history_targets[write_index].target,
                     renderer._CLEAR_COLOR, QRhiDepthStencilClearValue(1.0, 0))
        cb.setViewport(renderer._viewport(widget._offscreen_size))
        cb.setGraphicsPipeline(widget._scene_pipeline)
        cb.setShaderResources(widget._particle_bindings)
        cb.draw(3)
        cb.endPass()


    widget._advance_field = advance
    widget._draw_feedback = draw_isolated_scene
    widget.set_preview(37, 600.0)
    widget.set_playing(True)
    images = {}
    for probe_time in (1.0, 300.0):
        activity = 0.50
        advance(0.0)
        # Reconstruct five minutes of steady travel without waiting in real time.
        # Both images share that history; only current energy changes.
        widget._motion_phases = MotionPhases()
        widget._motion_phases.advance(probe_time, motion, widget._latest_frame.forcing)
        for activity in (0.50, 0.502):
            frames = [0]
            loop = QEventLoop()

            def rendered(_frame):
                frames[0] += 1
                if frames[0] == 3:
                    QTimer.singleShot(0, loop.quit)

            widget.frameChanged.connect(rendered)
            timeout = QTimer()
            timeout.setSingleShot(True)
            timeout.timeout.connect(loop.quit)
            timeout.start(5000)
            widget.show()
            widget.update()
            loop.exec()
            timeout.stop()
            widget.frameChanged.disconnect(rendered)
            assert frames[0] >= 3 and not failures, failures
            path = output / f"{probe_time}-{activity}.png"
            assert widget.grab().save(str(path), "PNG")
            images[probe_time, activity] = np.asarray(Image.open(path).convert("L"), dtype=float)
    widget.close()
    differences = {
        seconds: float(np.abs(images[seconds, .502] - images[seconds, .50]).mean())
        for seconds in (1.0, 300.0)
    }
    print(json.dumps(differences))

    """
)


@pytest.mark.skipif(sys.platform != "win32", reason="Requires native QRhi D3D11")
def test_small_energy_changes_do_not_reposition_a_long_running_scene(
    tmp_path: Path,
) -> None:
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "windows"
    completed = subprocess.run(
        [sys.executable, "-c", _D3D_MOTION_CONTINUITY_PROBE, str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stderr
    differences = cast("dict[str, float]", json.loads(completed.stdout))
    assert differences["1.0"] < 3.0
    assert differences["300.0"] < 3.0
