"""QRhi Adapter for Synesthesia's persistent field of matter and force."""

from __future__ import annotations

import math
import struct
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol, cast

import numpy as np
from PySide6.QtCore import QByteArray, QSize, Qt, Signal, Slot
from PySide6.QtGui import (
    QColor,
    QMatrix4x4,
    QRhi,
    QRhiBuffer,
    QRhiColorAttachment,
    QRhiCommandBuffer,
    QRhiComputePipeline,
    QRhiDepthStencilClearValue,
    QRhiDriverInfo,
    QRhiGraphicsPipeline,
    QRhiRenderPassDescriptor,
    QRhiResourceUpdateBatch,
    QRhiSampler,
    QRhiShaderResourceBinding,
    QRhiShaderResourceBindings,
    QRhiShaderStage,
    QRhiTexture,
    QRhiTextureRenderTarget,
    QRhiTextureRenderTargetDescription,
    QRhiVertexInputAttribute,
    QRhiVertexInputBinding,
    QRhiVertexInputLayout,
    QRhiViewport,
    QShader,
    QVector3D,
)
from PySide6.QtWidgets import QRhiWidget, QSizePolicy, QWidget

from .conductor import FieldConductor, analysis_seed
from .motion_phases import MotionPhases
from .persistent_world import (
    FieldImpulseCharacter,
    PersistentWorld,
    TransportState,
    WorldAdvance,
    WorldConditions,
    WorldFrame,
    WorldGenesis,
)
from .preview import PreviewFieldModel, blend_forcing
from .render_resolution import select_render_resolution
from .scene_director import SceneDirector, SceneMoment, idle_scene_moment

if TYPE_CHECKING:
    from numpy.typing import NDArray
    from PySide6.QtGui import QHideEvent, QShowEvent

    from iOpenPod.app.synesthesia import TrackAnalysis

_SHADER_ROOT: Final = Path(__file__).with_name("shader_sources")
_CORE_PARTICLE_COUNT: Final = 131_072
_CONSERVATIVE_PARTICLE_COUNT: Final = 65_536
_FULL_PARTICLE_COUNT: Final = 262_144
_PARTICLE_STRIDE_BYTES: Final = 32
_FILAMENT_STRIDE_BYTES: Final = 32
_WORKGROUP_SIZE: Final = 256
_COMET_POOL_FRACTION: Final = 0.10
_COMET_PREFIX_MARKER_THRESHOLD: Final = 0.90
_FIELD_STATE_LAYOUT: Final = (
    ("uViewProjection", 16),
    ("uTime", 4),
    ("uMusic", 4),
    ("uHarmony", 4),
    ("uSpectrum", 4),
    ("uLayers", 4),
    ("uStructure", 4),
    ("uSpatial", 4),
    ("uCameraRight", 4),
    ("uCameraUp", 4),
    ("uCameraPosition", 4),
    ("uCameraForward", 4),
    ("uAttractor0", 4),
    ("uAttractor1", 4),
    ("uAttractor2", 4),
    ("uAttractor3", 4),
    ("uWave0", 4),
    ("uWave1", 4),
    ("uWave2", 4),
    ("uWave3", 4),
    ("uWaveAmplitude", 4),
    ("uWaveCharacter", 4),
    ("uScene", 4),
    ("uSceneTuning", 4),
    ("uSceneMotion0", 4),
    ("uSceneMotion1", 4),
    ("uViewport", 4),
    ("uFeedback", 4),
    ("uMotionPhase", 4),
    ("uFlowPhase", 4),
    ("uMusicPhase", 4),
    ("uAccentPhase", 4),
)
_UNIFORM_FLOAT_COUNT: Final = sum(width for _, width in _FIELD_STATE_LAYOUT)
_UNIFORM_BYTE_COUNT: Final = _UNIFORM_FLOAT_COUNT * 4
_MAX_FRAME_DELTA_SECONDS: Final = 1.0 / 30.0
_MAX_PLAYBACK_RATE_CORRECTION: Final = 0.12
_PLAYBACK_CORRECTION_WINDOW_SECONDS: Final = 0.25
_CLEAR_COLOR: Final = QColor.fromRgbF(0.0008, 0.0014, 0.0032, 1.0)
_ANALYSIS_HANDOFF_SECONDS: Final = 2.4


class _Creatable(Protocol):
    def create(self) -> bool: ...


class _BufferUploads(Protocol):
    """Byte-buffer overloads accepted by PySide 6.9 and newer bindings.

    PySide 6.9's generated stubs describe these data arguments as pointers,
    although its bindings accept bytes and copy them into the update batch.
    """

    def updateDynamicBuffer(
        self, buffer: QRhiBuffer, offset: int, size: int, data: bytes
    ) -> None: ...

    def uploadStaticBuffer(self, buffer: QRhiBuffer, data: bytes) -> None: ...


def _buffer_uploads(batch: QRhiResourceUpdateBatch) -> _BufferUploads:
    return cast("_BufferUploads", batch)


@dataclass(slots=True)
class _TextureTarget:
    texture: QRhiTexture
    target: QRhiTextureRenderTarget
    descriptor: QRhiRenderPassDescriptor

    def destroy(self) -> None:
        self.target.destroy()
        self.descriptor.destroy()
        self.texture.destroy()


@dataclass(frozen=True, slots=True)
class SynesthesiaRenderDiagnostics:
    """Describe the active field fidelity without changing its behavior."""

    quality_tier: str
    particle_count: int
    backend: str
    device_type: str


@dataclass(frozen=True, slots=True)
class PresentationResponse:
    history_retention: float
    exposure: float
    source_gain: float
    point_scale: float


@dataclass(slots=True)
class _PlaybackClock:
    """Turn sparse decoder positions into a monotonic render-cadence clock."""

    _duration_seconds: float | None = None
    _musical_time: float = 0.0
    _reported_time: float = 0.0
    _remaining_correction: float = 0.0
    _playing: bool = False
    _has_started: bool = False
    _hold_next_advance: bool = True

    def reset(
        self,
        position_seconds: float,
        *,
        duration_seconds: float | None,
    ) -> float:
        """Relocate exactly and discard correction left from the prior traversal."""

        self._duration_seconds = (
            None if duration_seconds is None else max(0.0, duration_seconds)
        )
        bounded = self._bounded(position_seconds)
        self._musical_time = bounded
        self._reported_time = bounded
        self._remaining_correction = 0.0
        self._has_started = self._playing
        self._hold_next_advance = True
        return bounded

    def relocate(self, position_seconds: float) -> float:
        """Reset within the current Track while retaining its duration bound."""

        return self.reset(
            position_seconds,
            duration_seconds=self._duration_seconds,
        )

    def set_duration(self, duration_seconds: float) -> None:
        """Apply the decoded duration without restarting the live clock."""

        self._duration_seconds = max(
            0.0,
            duration_seconds,
            self._duration_seconds or 0.0,
            self._musical_time,
            self._reported_time,
        )

    def observe(self, position_seconds: float) -> float:
        """Record a decoder sample without stepping the render clock discontinuously."""

        bounded = self._bounded(position_seconds)
        self._reported_time = bounded
        if self._playing:
            self._remaining_correction = bounded - self._musical_time
        return bounded

    def set_playing(self, playing: bool) -> None:
        """Freeze immediately or resume from the newest non-regressing anchor."""

        if self._playing == playing:
            return
        self._playing = playing
        self._remaining_correction = 0.0
        if playing:
            if not self._has_started:
                self._musical_time = self._reported_time
            self._has_started = True
            self._hold_next_advance = True

    def advance(self, delta_seconds: float) -> float:
        """Advance nominally in real time while gently paying down phase error."""

        if not self._playing:
            return self._musical_time
        if self._hold_next_advance:
            self._hold_next_advance = False
            return self._musical_time
        elapsed = max(0.0, delta_seconds)
        if elapsed == 0.0:
            return self._musical_time
        correction_fraction = min(
            1.0,
            elapsed / _PLAYBACK_CORRECTION_WINDOW_SECONDS,
        )
        desired_correction = self._remaining_correction * correction_fraction
        correction_limit = elapsed * _MAX_PLAYBACK_RATE_CORRECTION
        applied_correction = min(
            correction_limit,
            max(-correction_limit, desired_correction),
        )
        self._remaining_correction -= applied_correction
        self._musical_time = self._bounded(
            self._musical_time + elapsed + applied_correction
        )
        if (
            self._duration_seconds is not None
            and self._musical_time >= self._duration_seconds
        ):
            self._remaining_correction = 0.0
        return self._musical_time

    def _bounded(self, seconds: float) -> float:
        bounded = max(0.0, seconds)
        if self._duration_seconds is not None:
            bounded = min(self._duration_seconds, bounded)
        return bounded


class SynesthesiaRenderer(QRhiWidget):
    """Render a deep force field whose particles carry momentum between causes."""

    failure = Signal(str)
    frameChanged = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        # QRhiWidget requires the API choice before it joins a widget hierarchy.
        super().__init__(None)
        self._select_platform_api()
        if parent is not None:
            self.setParent(parent)
        self.setObjectName("synesthesiaRenderer")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(560, 360)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)

        self._analysis: TrackAnalysis | None = None
        self._preview: PreviewFieldModel | None = None
        self._handoff_seconds: float | None = None
        self._conductor: FieldConductor | None = None
        self._scene_director: SceneDirector | None = None
        self._playing = False
        self._position_seconds = 0.0
        self._playback_clock = _PlaybackClock()
        self._transport_epoch = 0
        self._advanced_epoch: int | None = None
        self._advanced_musical_time = 0.0
        self._experience_time = 0.0
        self._last_frame_clock = time.monotonic()
        self._world = PersistentWorld.create(WorldGenesis(experience_seed=0))
        self._latest_forcing = WorldConditions()
        self._latest_frame = self._initial_frame()
        self._motion_phases = MotionPhases()

        self._quality_tier = "core"
        self._particle_count = _CORE_PARTICLE_COUNT
        self._comet_count = _comet_instance_count(self._particle_count)
        self._backend_name = "uninitialized"
        self._device_type_name = QRhiDriverInfo.DeviceType.UnknownDevice.name

        self._bound_rhi: QRhi | None = None
        self._uniform_buffer: QRhiBuffer | None = None
        self._particle_buffers: list[QRhiBuffer] = []
        self._filament_buffer: QRhiBuffer | None = None
        self._sampler: QRhiSampler | None = None
        self._compute_bindings: list[QRhiShaderResourceBindings] = []
        self._compute_pipeline: QRhiComputePipeline | None = None
        self._particle_bindings: QRhiShaderResourceBindings | None = None
        self._filament_bindings: QRhiShaderResourceBindings | None = None
        self._feedback_bindings: list[QRhiShaderResourceBindings] = []
        self._present_bindings: list[QRhiShaderResourceBindings] = []
        self._particle_pipeline: QRhiGraphicsPipeline | None = None
        self._scene_pipeline: QRhiGraphicsPipeline | None = None
        self._comet_pipeline: QRhiGraphicsPipeline | None = None
        self._filament_pipeline: QRhiGraphicsPipeline | None = None
        self._event_pipeline: QRhiGraphicsPipeline | None = None
        self._feedback_pipeline: QRhiGraphicsPipeline | None = None
        self._present_pipeline: QRhiGraphicsPipeline | None = None
        self._scene_target: _TextureTarget | None = None
        self._history_targets: list[_TextureTarget] = []
        self._offscreen_size = QSize()
        self._particle_read_index = 0
        self._history_read_index = 0
        self._history_needs_clear = True
        self._particle_reset_pending = True
        self._filament_reset_pending = True
        self._filament_data, self._filament_count = _build_filaments(0)
        self._failed_detail = ""
        self.renderFailed.connect(self._platform_render_failed)

    @property
    def latest_frame(self) -> WorldFrame:
        """Expose the semantic field frame for diagnostics and UI continuity."""

        return self._latest_frame

    @property
    def particle_count(self) -> int:
        """Return the particle-pool size selected for the active GPU."""

        return self._particle_count

    @property
    def quality_tier(self) -> str:
        """Return the fidelity tier selected for the active GPU."""

        return self._quality_tier

    @property
    def diagnostics(self) -> SynesthesiaRenderDiagnostics:
        """Return stable, read-only renderer diagnostics for support surfaces."""

        return SynesthesiaRenderDiagnostics(
            quality_tier=self._quality_tier,
            particle_count=self._particle_count,
            backend=self._backend_name,
            device_type=self._device_type_name,
        )

    def set_preview(self, seed: int, duration_seconds: float | None) -> None:
        """Start a Track-bound field immediately, without reading its audio."""

        self._analysis = None
        self._conductor = None
        self._scene_director = None
        self._preview = PreviewFieldModel(seed)
        self._handoff_seconds = None
        self._reset_field(seed, duration_seconds)

    def set_analysis(self, analysis: TrackAnalysis | None) -> None:
        """Install Track Analysis, blending into an active preview if present."""

        if analysis is not None and self._preview is not None:
            self._analysis = analysis
            self._conductor = FieldConductor(analysis)
            self._scene_director = SceneDirector(
                analysis, experience_seed=self._world.genesis.experience_seed
            )
            self._playback_clock.set_duration(analysis.metadata.duration_seconds)
            self._handoff_seconds = 0.0
            self.update()
            return

        seed = analysis_seed(analysis) if analysis is not None else 0
        self._analysis = analysis
        self._preview = None
        self._handoff_seconds = None
        self._conductor = FieldConductor(analysis) if analysis is not None else None
        self._scene_director = (
            SceneDirector(analysis, experience_seed=seed)
            if analysis is not None
            else None
        )
        duration_seconds = (
            analysis.metadata.duration_seconds if analysis is not None else None
        )
        self._reset_field(seed, duration_seconds)

    def _reset_field(self, seed: int, duration_seconds: float | None) -> None:
        self._position_seconds = self._playback_clock.reset(
            0.0,
            duration_seconds=duration_seconds,
        )
        self._transport_epoch = 0
        self._advanced_epoch = None
        self._advanced_musical_time = 0.0
        self._experience_time = 0.0
        self._last_frame_clock = time.monotonic()
        self._world = PersistentWorld.create(WorldGenesis(experience_seed=seed))
        self._latest_forcing = WorldConditions()
        self._latest_frame = self._initial_frame()
        self._motion_phases = MotionPhases()
        self._filament_data, self._filament_count = _build_filaments(seed)
        self._particle_read_index = 0
        self._history_read_index = 0
        self._particle_reset_pending = True
        self._filament_reset_pending = True
        self._history_needs_clear = True
        self.update()

    def set_position_ms(self, milliseconds: int) -> None:
        """Observe the decoder's ordinary playback position."""

        self._position_seconds = self._playback_clock.observe(milliseconds / 1_000.0)

    def set_playing(self, playing: bool) -> None:
        """Freeze or resume field time without accumulating pause debt."""

        if self._playing == playing:
            return
        self._playing = playing
        self._playback_clock.set_playing(playing)
        self._last_frame_clock = time.monotonic()
        self.update()

    def relocate(self, position_ms: int, transport_epoch: int) -> None:
        """Re-anchor causes and screen history while retaining world momentum."""

        if transport_epoch < self._transport_epoch:
            return
        self._transport_epoch = transport_epoch
        self._position_seconds = self._playback_clock.relocate(position_ms / 1_000.0)
        self._history_read_index = 0
        self._history_needs_clear = True
        self._last_frame_clock = time.monotonic()
        self.update()

    def initialize(self, cb: QRhiCommandBuffer) -> None:
        try:
            self._initialize_resources(cb)
        except Exception as error:
            self._destroy_resources()
            self._report_failure(error)

    def render(self, cb: QRhiCommandBuffer) -> None:  # type: ignore[override]
        try:
            self._render_frame(cb)
        except Exception as error:
            self._report_failure(error)

    def releaseResources(self) -> None:
        self._destroy_resources()

    def showEvent(self, event: QShowEvent) -> None:
        self._last_frame_clock = time.monotonic()
        super().showEvent(event)
        self.update()

    def hideEvent(self, event: QHideEvent) -> None:
        self._last_frame_clock = time.monotonic()
        super().hideEvent(event)

    def _select_platform_api(self) -> None:
        if sys.platform == "win32":
            self.setApi(QRhiWidget.Api.Direct3D11)
        elif sys.platform == "darwin":
            self.setApi(QRhiWidget.Api.Metal)
        else:
            self.setApi(QRhiWidget.Api.OpenGL)

    def _initial_frame(self) -> WorldFrame:
        transport = self._transport_state()
        forcing = WorldConditions()
        if self._preview is not None:
            forcing = self._preview.sample(0.0)
        elif self._conductor is not None:
            conducted = self._conductor.advance(
                musical_time=0.0,
                delta_seconds=0.0,
                transport_state=transport,
                transport_epoch=self._transport_epoch,
            )
            forcing = conducted.forcing
        self._latest_forcing = forcing
        frame = self._world.advance(
            WorldAdvance(
                experience_time=0.0,
                musical_time=0.0,
                transport_state=transport,
                transport_epoch=self._transport_epoch,
                forcing=forcing,
            )
        )
        self._advanced_epoch = self._transport_epoch
        self._advanced_musical_time = 0.0
        return frame

    def _initialize_resources(self, cb: QRhiCommandBuffer) -> None:
        rhi = self.rhi()
        if self._simulation_resources_ready(rhi):
            # QRhiWidget calls initialize() again when its backing texture changes
            # size. Rebuild the size-dependent render targets and pipelines while
            # preserving the live particle buffers and their momentum.
            self._create_graphics_resources()
            self._failed_detail = ""
            return
        self._destroy_resources()
        if (
            not rhi.isFeatureSupported(QRhi.Feature.Compute)
            or rhi.resourceLimit(QRhi.ResourceLimit.MaxThreadGroupsPerDimension) <= 0
        ):
            raise RuntimeError("This graphics backend does not provide compute fields")
        driver_info = rhi.driverInfo()
        device_type = QRhiDriverInfo.DeviceType(driver_info.deviceType)
        self._quality_tier, self._particle_count = _quality_profile(device_type)
        self._comet_count = _comet_instance_count(self._particle_count)
        self._backend_name = rhi.backend().name
        self._device_type_name = device_type.name
        self._bound_rhi = rhi

        particle_usage = (
            QRhiBuffer.UsageFlag.StorageBuffer | QRhiBuffer.UsageFlag.VertexBuffer
        )
        self._particle_buffers = [
            rhi.newBuffer(
                QRhiBuffer.Type.Static,
                particle_usage,
                self._particle_count * _PARTICLE_STRIDE_BYTES,
            )
            for _ in range(2)
        ]
        for index, buffer in enumerate(self._particle_buffers):
            _require_created(buffer, f"particle state buffer {index}")
        self._uniform_buffer = rhi.newBuffer(
            QRhiBuffer.Type.Dynamic,
            QRhiBuffer.UsageFlag.UniformBuffer,
            _UNIFORM_BYTE_COUNT,
        )
        _require_created(self._uniform_buffer, "field uniform buffer")
        self._filament_buffer = rhi.newBuffer(
            QRhiBuffer.Type.Static,
            QRhiBuffer.UsageFlag.VertexBuffer,
            max(_FILAMENT_STRIDE_BYTES, len(self._filament_data)),
        )
        _require_created(self._filament_buffer, "recursive filament buffer")
        self._sampler = rhi.newSampler(
            QRhiSampler.Filter.Linear,
            QRhiSampler.Filter.Linear,
            QRhiSampler.Filter.None_,
            QRhiSampler.AddressMode.ClampToEdge,
            QRhiSampler.AddressMode.ClampToEdge,
        )
        _require_created(self._sampler, "linear field sampler")

        compute_stage = QRhiShaderResourceBinding.StageFlag.ComputeStage
        for read_index in range(2):
            bindings = rhi.newShaderResourceBindings()
            bindings.setBindings(
                [
                    QRhiShaderResourceBinding.uniformBuffer(
                        0, compute_stage, self._uniform_buffer
                    ),
                    QRhiShaderResourceBinding.bufferLoad(
                        1, compute_stage, self._particle_buffers[read_index]
                    ),
                    QRhiShaderResourceBinding.bufferStore(
                        2, compute_stage, self._particle_buffers[1 - read_index]
                    ),
                ]
            )
            _require_created(bindings, f"particle compute bindings {read_index}")
            self._compute_bindings.append(bindings)
        self._compute_pipeline = rhi.newComputePipeline()
        self._compute_pipeline.setShaderStage(
            QRhiShaderStage(
                QRhiShaderStage.Type.Compute,
                _load_shader(_SHADER_ROOT / "field_sim.comp.qsb"),
            )
        )
        self._compute_pipeline.setShaderResourceBindings(self._compute_bindings[0])
        _require_created(self._compute_pipeline, "particle force pipeline")

        graphics_stages = (
            QRhiShaderResourceBinding.StageFlag.VertexStage
            | QRhiShaderResourceBinding.StageFlag.FragmentStage
        )
        self._particle_bindings = _uniform_bindings(
            rhi, self._uniform_buffer, graphics_stages, "particle draw bindings"
        )
        self._filament_bindings = _uniform_bindings(
            rhi, self._uniform_buffer, graphics_stages, "filament draw bindings"
        )
        self._create_graphics_resources()
        self._upload_reset_state(cb)
        self._failed_detail = ""

    def _create_graphics_resources(self) -> None:
        rhi = self._require_rhi()
        self._destroy_graphics_resources()
        target_size = self.renderTarget().pixelSize()
        resolution = select_render_resolution(
            max(1, target_size.width()),
            max(1, target_size.height()),
            _display_refresh_rate(self),
        )
        self._offscreen_size = QSize(
            resolution.width_pixels,
            resolution.height_pixels,
        )
        self._scene_target = _create_texture_target(rhi, self._offscreen_size)
        self._history_targets = [
            _create_texture_target(rhi, self._offscreen_size) for _ in range(2)
        ]
        self._history_needs_clear = True

        assert self._uniform_buffer is not None
        assert self._sampler is not None
        assert self._particle_bindings is not None
        assert self._filament_bindings is not None
        graphics_stages = (
            QRhiShaderResourceBinding.StageFlag.VertexStage
            | QRhiShaderResourceBinding.StageFlag.FragmentStage
        )
        fragment_stage = QRhiShaderResourceBinding.StageFlag.FragmentStage
        for history_read_index in range(2):
            feedback = rhi.newShaderResourceBindings()
            feedback.setBindings(
                [
                    QRhiShaderResourceBinding.uniformBuffer(
                        0, graphics_stages, self._uniform_buffer
                    ),
                    QRhiShaderResourceBinding.sampledTexture(
                        1,
                        fragment_stage,
                        self._scene_target.texture,
                        self._sampler,
                    ),
                    QRhiShaderResourceBinding.sampledTexture(
                        2,
                        fragment_stage,
                        self._history_targets[history_read_index].texture,
                        self._sampler,
                    ),
                ]
            )
            _require_created(feedback, f"feedback bindings {history_read_index}")
            self._feedback_bindings.append(feedback)

            present = rhi.newShaderResourceBindings()
            present.setBindings(
                [
                    QRhiShaderResourceBinding.uniformBuffer(
                        0, graphics_stages, self._uniform_buffer
                    ),
                    QRhiShaderResourceBinding.sampledTexture(
                        1,
                        fragment_stage,
                        self._history_targets[history_read_index].texture,
                        self._sampler,
                    ),
                ]
            )
            _require_created(present, f"present bindings {history_read_index}")
            self._present_bindings.append(present)

        self._scene_pipeline = _create_fullscreen_pipeline(
            rhi,
            "scenes.frag.qsb",
            self._particle_bindings,
            self._scene_target.descriptor,
        )
        self._particle_pipeline = self._create_instance_pipeline(
            vertex_name="particles.vert.qsb",
            fragment_name="particles.frag.qsb",
            bindings=self._particle_bindings,
            descriptor=self._scene_target.descriptor,
        )
        self._comet_pipeline = self._create_instance_pipeline(
            vertex_name="comets.vert.qsb",
            fragment_name="comets.frag.qsb",
            bindings=self._particle_bindings,
            descriptor=self._scene_target.descriptor,
        )
        self._filament_pipeline = self._create_instance_pipeline(
            vertex_name="filaments.vert.qsb",
            fragment_name="filaments.frag.qsb",
            bindings=self._filament_bindings,
            descriptor=self._scene_target.descriptor,
        )
        self._event_pipeline = _create_fullscreen_pipeline(
            rhi,
            "events.frag.qsb",
            self._particle_bindings,
            self._scene_target.descriptor,
            additive=True,
        )
        self._feedback_pipeline = _create_fullscreen_pipeline(
            rhi,
            "feedback.frag.qsb",
            self._feedback_bindings[0],
            self._history_targets[0].descriptor,
        )
        self._present_pipeline = _create_fullscreen_pipeline(
            rhi,
            "present.frag.qsb",
            self._present_bindings[0],
            self.renderTarget().renderPassDescriptor(),
        )

    def _create_instance_pipeline(
        self,
        *,
        vertex_name: str,
        fragment_name: str,
        bindings: QRhiShaderResourceBindings,
        descriptor: QRhiRenderPassDescriptor,
    ) -> QRhiGraphicsPipeline:
        rhi = self._require_rhi()
        layout = QRhiVertexInputLayout()
        layout.setBindings(
            [
                QRhiVertexInputBinding(
                    _PARTICLE_STRIDE_BYTES,
                    QRhiVertexInputBinding.Classification.PerInstance,
                )
            ]
        )
        layout.setAttributes(
            [
                QRhiVertexInputAttribute(
                    0, 0, QRhiVertexInputAttribute.Format.Float4, 0
                ),
                QRhiVertexInputAttribute(
                    0, 1, QRhiVertexInputAttribute.Format.Float4, 16
                ),
            ]
        )
        blend = QRhiGraphicsPipeline.TargetBlend()
        blend.enable = True
        one = cast("int", QRhiGraphicsPipeline.BlendFactor.One)
        blend.srcColor = one
        blend.dstColor = one
        blend.srcAlpha = one
        blend.dstAlpha = one
        pipeline = rhi.newGraphicsPipeline()
        pipeline.setTopology(QRhiGraphicsPipeline.Topology.Triangles)
        pipeline.setCullMode(QRhiGraphicsPipeline.CullMode.None_)
        pipeline.setDepthTest(False)
        pipeline.setDepthWrite(False)
        pipeline.setTargetBlends([blend])
        pipeline.setShaderStages(
            [
                QRhiShaderStage(
                    QRhiShaderStage.Type.Vertex,
                    _load_shader(_SHADER_ROOT / vertex_name),
                ),
                QRhiShaderStage(
                    QRhiShaderStage.Type.Fragment,
                    _load_shader(_SHADER_ROOT / fragment_name),
                ),
            ]
        )
        pipeline.setVertexInputLayout(layout)
        pipeline.setShaderResourceBindings(bindings)
        pipeline.setRenderPassDescriptor(descriptor)
        _require_created(pipeline, f"{vertex_name} graphics pipeline")
        return pipeline

    def _render_frame(self, cb: QRhiCommandBuffer) -> None:
        if not self._resources_ready():
            self._clear_widget(cb)
            return
        target_size = self.renderTarget().pixelSize()
        resolution = select_render_resolution(
            max(1, target_size.width()),
            max(1, target_size.height()),
            _display_refresh_rate(self),
        )
        desired_size = QSize(
            resolution.width_pixels,
            resolution.height_pixels,
        )
        if desired_size != self._offscreen_size:
            self._create_graphics_resources()

        now = time.monotonic()
        delta_seconds = min(
            _MAX_FRAME_DELTA_SECONDS,
            max(0.0, now - self._last_frame_clock),
        )
        self._last_frame_clock = now
        self._advance_field(delta_seconds)
        simulation_delta = (
            delta_seconds if self._transport_state() is TransportState.PLAYING else 0.0
        )

        rhi = self._require_rhi()
        assert self._uniform_buffer is not None
        updates = rhi.nextResourceUpdateBatch()
        uploads = _buffer_uploads(updates)
        uniform_data = self._uniform_bytes(rhi, simulation_delta)
        uploads.updateDynamicBuffer(
            self._uniform_buffer,
            0,
            len(uniform_data),
            uniform_data,
        )
        if self._particle_reset_pending:
            particle_data = _initial_particle_data(
                self._latest_frame.experience_seed,
                self._particle_count,
            )
            for buffer in self._particle_buffers:
                uploads.uploadStaticBuffer(buffer, particle_data)
            self._particle_reset_pending = False
        if self._filament_reset_pending:
            assert self._filament_buffer is not None
            uploads.uploadStaticBuffer(self._filament_buffer, self._filament_data)
            self._filament_reset_pending = False
        cb.resourceUpdate(updates)

        particle_draw_index = self._particle_read_index
        if simulation_delta > 0.0:
            assert self._compute_pipeline is not None
            compute_bindings = self._compute_bindings[self._particle_read_index]
            cb.beginComputePass()
            cb.setComputePipeline(self._compute_pipeline)
            cb.setShaderResources(compute_bindings)
            cb.dispatch(math.ceil(self._particle_count / _WORKGROUP_SIZE), 1, 1)
            cb.endComputePass()
            particle_draw_index = 1 - self._particle_read_index

        if self._history_needs_clear:
            for target in self._history_targets:
                cb.beginPass(
                    target.target,
                    _CLEAR_COLOR,
                    QRhiDepthStencilClearValue(1.0, 0),
                )
                cb.endPass()
            self._history_needs_clear = False

        self._draw_scene(cb, particle_draw_index)
        history_write_index = 1 - self._history_read_index
        self._draw_feedback(cb, self._history_read_index, history_write_index)
        self._draw_present(cb, history_write_index)
        if simulation_delta > 0.0:
            self._particle_read_index = particle_draw_index
        self._history_read_index = history_write_index
        self.frameChanged.emit(self._latest_frame)
        if self._transport_state() is TransportState.PLAYING:
            self.update()

    def _draw_scene(self, cb: QRhiCommandBuffer, particle_index: int) -> None:
        assert self._scene_target is not None
        assert self._particle_pipeline is not None
        assert self._scene_pipeline is not None
        assert self._comet_pipeline is not None
        assert self._particle_bindings is not None
        assert self._filament_pipeline is not None
        assert self._filament_bindings is not None
        assert self._filament_buffer is not None
        assert self._event_pipeline is not None
        cb.beginPass(
            self._scene_target.target,
            _CLEAR_COLOR,
            QRhiDepthStencilClearValue(1.0, 0),
        )
        cb.setViewport(_viewport(self._offscreen_size))
        cb.setGraphicsPipeline(self._scene_pipeline)
        cb.setShaderResources(self._particle_bindings)
        cb.draw(3)
        cb.setGraphicsPipeline(self._particle_pipeline)
        cb.setShaderResources(self._particle_bindings)
        cb.setVertexInput(0, [(self._particle_buffers[particle_index], 0)])
        cb.draw(6, self._particle_count)
        cb.setGraphicsPipeline(self._comet_pipeline)
        cb.setShaderResources(self._particle_bindings)
        cb.setVertexInput(0, [(self._particle_buffers[particle_index], 0)])
        cb.draw(6, self._comet_count)
        cb.setGraphicsPipeline(self._filament_pipeline)
        cb.setShaderResources(self._filament_bindings)
        cb.setVertexInput(0, [(self._filament_buffer, 0)])
        cb.draw(6, self._filament_count)
        cb.setGraphicsPipeline(self._event_pipeline)
        cb.setShaderResources(self._particle_bindings)
        cb.draw(3)
        cb.endPass()

    def _draw_feedback(
        self,
        cb: QRhiCommandBuffer,
        history_read_index: int,
        history_write_index: int,
    ) -> None:
        assert self._feedback_pipeline is not None
        target = self._history_targets[history_write_index]
        cb.beginPass(
            target.target,
            _CLEAR_COLOR,
            QRhiDepthStencilClearValue(1.0, 0),
        )
        cb.setViewport(_viewport(self._offscreen_size))
        cb.setGraphicsPipeline(self._feedback_pipeline)
        cb.setShaderResources(self._feedback_bindings[history_read_index])
        cb.draw(3)
        cb.endPass()

    def _draw_present(self, cb: QRhiCommandBuffer, history_index: int) -> None:
        assert self._present_pipeline is not None
        cb.beginPass(
            self.renderTarget(),
            _CLEAR_COLOR,
            QRhiDepthStencilClearValue(1.0, 0),
        )
        cb.setViewport(_viewport(self.renderTarget().pixelSize()))
        cb.setGraphicsPipeline(self._present_pipeline)
        cb.setShaderResources(self._present_bindings[history_index])
        cb.draw(3)
        cb.endPass()

    def _advance_field(self, delta_seconds: float) -> None:
        self._experience_time += delta_seconds
        transport = self._transport_state()
        if self._analysis is None:
            musical_time = (
                self._playback_clock.advance(delta_seconds)
                if self._preview is not None
                else self._experience_time
            )
            forcing = (
                self._preview.sample(musical_time)
                if self._preview is not None
                else WorldConditions()
            )
        else:
            musical_time = self._playback_clock.advance(delta_seconds)
            assert self._conductor is not None
            conducted = self._conductor.advance(
                musical_time=musical_time,
                delta_seconds=delta_seconds,
                transport_state=transport,
                transport_epoch=self._transport_epoch,
            )
            forcing = conducted.forcing
            if self._preview is not None and self._handoff_seconds is not None:
                if transport is TransportState.PLAYING:
                    self._handoff_seconds += delta_seconds
                blend = min(1.0, self._handoff_seconds / _ANALYSIS_HANDOFF_SECONDS)
                forcing = blend_forcing(
                    self._preview.sample(musical_time), forcing, blend
                )
                if blend >= 1.0:
                    self._preview = None
                    self._handoff_seconds = None
        self._latest_forcing = forcing
        self._latest_frame = self._world.advance(
            WorldAdvance(
                experience_time=self._experience_time,
                musical_time=musical_time,
                transport_state=transport,
                transport_epoch=self._transport_epoch,
                forcing=forcing,
            )
        )
        self._advanced_epoch = self._transport_epoch
        self._advanced_musical_time = musical_time
        self._motion_phases.advance(
            self._latest_frame.delta_seconds,
            self._scene_moment().motion,
            self._latest_frame.forcing,
        )

    def _scene_moment(self) -> SceneMoment:
        scene = (
            self._scene_director.sample(self._latest_frame.musical_time)
            if self._scene_director is not None
            else idle_scene_moment()
        )
        if self._preview is not None and self._handoff_seconds is not None:
            scene = _blend_preview_scene(
                idle_scene_moment(),
                scene,
                self._handoff_seconds / _ANALYSIS_HANDOFF_SECONDS,
            )
        return scene

    def _uniform_bytes(self, rhi: QRhi, simulation_delta: float) -> bytes:
        frame = self._latest_frame
        forcing = frame.forcing
        field_time = frame.field_time
        target_size = self.renderTarget().pixelSize()
        aspect = target_size.width() / max(1, target_size.height())
        scene = self._scene_moment()
        camera_pose = scene.camera_pose
        camera = QVector3D(*camera_pose.position)
        target = QVector3D(*camera_pose.target)
        camera_to_target = target - camera
        focus_distance = max(0.35, camera_to_target.length())
        forward = camera_to_target.normalized()
        reference_up = QVector3D(0.0, 1.0, 0.0)
        if abs(QVector3D.dotProduct(forward, reference_up)) > 0.98:
            reference_up = QVector3D(1.0, 0.0, 0.0)
        unrolled_right = QVector3D.crossProduct(forward, reference_up).normalized()
        unrolled_up = QVector3D.crossProduct(unrolled_right, forward).normalized()
        roll_sine = math.sin(camera_pose.roll_radians)
        roll_cosine = math.cos(camera_pose.roll_radians)
        right = unrolled_right * roll_cosine + unrolled_up * roll_sine
        camera_up = unrolled_up * roll_cosine - unrolled_right * roll_sine
        field_of_view = min(72.0, max(24.0, camera_pose.field_of_view_degrees))
        projection = QMatrix4x4()
        projection.perspective(
            field_of_view,
            max(1.0 / 16.0, aspect),
            0.08,
            40.0,
        )
        view = QMatrix4x4()
        view.lookAt(camera, target, camera_up)
        view_projection = rhi.clipSpaceCorrMatrix() * projection * view
        tangent_half_fov = math.tan(math.radians(field_of_view) * 0.5)

        poles = list(frame.poles[:4])
        default_poles = (
            (-1.8, 0.7, 0.1, 0.9),
            (1.7, -0.8, -0.5, 0.7),
            (0.2, 1.9, 0.8, -0.42),
            (-0.4, -1.6, 0.5, 0.35),
        )
        pole_values: list[float] = []
        for index, default in enumerate(default_poles):
            if index < len(poles):
                pole = poles[index]
                pole_values.extend(
                    (
                        pole.position.x,
                        pole.position.y,
                        pole.position.z,
                        pole.strength,
                    )
                )
            else:
                pole_values.extend(default)

        impulses = sorted(
            frame.impulses,
            key=lambda impulse: impulse.strength,
            reverse=True,
        )[:4]
        wave_values: list[float] = []
        amplitudes: list[float] = []
        characters: list[float] = []
        for index in range(4):
            if index < len(impulses):
                impulse = impulses[index]
                wave_values.extend(
                    (
                        impulse.origin.x,
                        impulse.origin.y,
                        impulse.origin.z,
                        impulse.radius,
                    )
                )
                amplitudes.append(impulse.strength)
                characters.append(_impulse_character_code(impulse.character))
            else:
                wave_values.extend((0.0, 0.0, 0.0, -1.0))
                amplitudes.append(0.0)
                characters.append(0.0)

        energy = forcing.energy
        bass = forcing.gravity
        flow = forcing.curl
        high = forcing.sparks
        tension = forcing.tension
        coherence = forcing.harmonic_coherence
        onset = max(amplitudes, default=0.0)
        hue = forcing.palette_hue
        presentation = presentation_response(
            activity=forcing.activity,
            energy=energy,
            target_height=target_size.height(),
        )
        # Fullscreen passes need the framebuffer's Y direction when they reread a
        # prior render target. Keep uViewport.y's magnitude as the pixel height
        # and use its sign for that backend orientation.
        signed_viewport_height = float(self._offscreen_size.height()) * (
            1.0 if rhi.isYUpInFramebuffer() else -1.0
        )
        values = (
            *view_projection.data(),
            field_time,
            simulation_delta,
            float(self._particle_count),
            aspect,
            energy,
            bass,
            flow,
            high,
            tension,
            coherence,
            forcing.rhythmic_pulse,
            hue,
            forcing.brightness,
            forcing.spectral_flux,
            forcing.timbral_noise,
            forcing.palette_spread,
            forcing.harmonic_layer,
            forcing.percussive_layer,
            forcing.vocal_layer,
            forcing.bass_layer,
            forcing.section_novelty,
            forcing.section_progress,
            forcing.section_identity,
            forcing.section_energy,
            forcing.lateral_bias,
            forcing.stereo_width,
            forcing.beat_phase,
            onset,
            right.x(),
            right.y(),
            right.z(),
            focus_distance,
            camera_up.x(),
            camera_up.y(),
            camera_up.z(),
            1.0 if rhi.isYUpInNDC() else -1.0,
            camera.x(),
            camera.y(),
            camera.z(),
            tangent_half_fov,
            forward.x(),
            forward.y(),
            forward.z(),
            scene.camera_motion,
            *pole_values,
            *wave_values,
            *amplitudes,
            *characters,
            float(scene.primary),
            float(scene.secondary),
            scene.blend,
            scene.transition_energy,
            scene.tuning.particles,
            scene.tuning.comets,
            scene.tuning.filaments,
            scene.tuning.events,
            scene.motion.direction_x,
            scene.motion.direction_y,
            scene.motion.travel_rate,
            scene.motion.orbit_rate,
            scene.motion.depth_rate,
            scene.motion.waveform_gain,
            scene.motion.parallax,
            scene.motion.world_scale,
            float(self._offscreen_size.width()),
            signed_viewport_height,
            1.0 / max(1, self._offscreen_size.width()),
            1.0 / max(1, self._offscreen_size.height()),
            presentation.history_retention,
            presentation.exposure,
            presentation.source_gain,
            presentation.point_scale,
            *self._motion_phases.uniform_values(),
        )
        if len(values) != _UNIFORM_FLOAT_COUNT:
            raise AssertionError(f"field uniform layout has {len(values)} floats")
        return struct.pack(f"<{_UNIFORM_FLOAT_COUNT}f", *values)

    def _transport_state(self) -> TransportState:
        if (self._analysis is None and self._preview is None) or self._playing:
            return TransportState.PLAYING
        return TransportState.PAUSED

    def _upload_reset_state(self, cb: QRhiCommandBuffer) -> None:
        rhi = self._require_rhi()
        assert self._uniform_buffer is not None
        assert self._filament_buffer is not None
        particle_data = _initial_particle_data(
            self._latest_frame.experience_seed,
            self._particle_count,
        )
        updates = rhi.nextResourceUpdateBatch()
        uploads = _buffer_uploads(updates)
        for buffer in self._particle_buffers:
            uploads.uploadStaticBuffer(buffer, particle_data)
        uploads.uploadStaticBuffer(self._filament_buffer, self._filament_data)
        uniform_data = self._uniform_bytes(rhi, 0.0)
        uploads.updateDynamicBuffer(
            self._uniform_buffer,
            0,
            len(uniform_data),
            uniform_data,
        )
        cb.resourceUpdate(updates)
        self._particle_reset_pending = False
        self._filament_reset_pending = False

    def _resources_ready(self) -> bool:
        return (
            self._bound_rhi is not None
            and len(self._particle_buffers) == 2
            and self._uniform_buffer is not None
            and self._filament_buffer is not None
            and self._compute_pipeline is not None
            and self._scene_pipeline is not None
            and self._particle_pipeline is not None
            and self._comet_pipeline is not None
            and self._filament_pipeline is not None
            and self._event_pipeline is not None
            and self._feedback_pipeline is not None
            and self._present_pipeline is not None
            and self._scene_target is not None
            and len(self._history_targets) == 2
        )

    def _simulation_resources_ready(self, rhi: QRhi) -> bool:
        return (
            self._bound_rhi is rhi
            and len(self._particle_buffers) == 2
            and self._uniform_buffer is not None
            and self._filament_buffer is not None
            and self._sampler is not None
            and len(self._compute_bindings) == 2
            and self._compute_pipeline is not None
            and self._particle_bindings is not None
            and self._filament_bindings is not None
        )

    def _require_rhi(self) -> QRhi:
        if self._bound_rhi is None:
            raise RuntimeError("Synesthesia has no active QRhi backend")
        return self._bound_rhi

    def _clear_widget(self, cb: QRhiCommandBuffer) -> None:
        cb.beginPass(
            self.renderTarget(),
            _CLEAR_COLOR,
            QRhiDepthStencilClearValue(1.0, 0),
        )
        cb.endPass()

    def _destroy_graphics_resources(self) -> None:
        for pipeline in (
            self._present_pipeline,
            self._feedback_pipeline,
            self._event_pipeline,
            self._filament_pipeline,
            self._comet_pipeline,
            self._particle_pipeline,
            self._scene_pipeline,
        ):
            if pipeline is not None:
                pipeline.destroy()
        self._present_pipeline = None
        self._feedback_pipeline = None
        self._event_pipeline = None
        self._filament_pipeline = None
        self._comet_pipeline = None
        self._particle_pipeline = None
        self._scene_pipeline = None
        for bindings in (*self._present_bindings, *self._feedback_bindings):
            bindings.destroy()
        self._present_bindings.clear()
        self._feedback_bindings.clear()
        for target in self._history_targets:
            target.destroy()
        self._history_targets.clear()
        if self._scene_target is not None:
            self._scene_target.destroy()
        self._scene_target = None
        self._offscreen_size = QSize()

    def _destroy_resources(self) -> None:
        self._destroy_graphics_resources()
        if self._compute_pipeline is not None:
            self._compute_pipeline.destroy()
        self._compute_pipeline = None
        for bindings in self._compute_bindings:
            bindings.destroy()
        self._compute_bindings.clear()
        for optional_bindings in (
            self._filament_bindings,
            self._particle_bindings,
        ):
            if optional_bindings is not None:
                optional_bindings.destroy()
        self._filament_bindings = None
        self._particle_bindings = None
        if self._sampler is not None:
            self._sampler.destroy()
        self._sampler = None
        if self._filament_buffer is not None:
            self._filament_buffer.destroy()
        self._filament_buffer = None
        if self._uniform_buffer is not None:
            self._uniform_buffer.destroy()
        self._uniform_buffer = None
        for buffer in self._particle_buffers:
            buffer.destroy()
        self._particle_buffers.clear()
        self._bound_rhi = None

    @Slot()
    def _platform_render_failed(self) -> None:
        self._report_failure(
            RuntimeError("Qt could not initialize the selected graphics backend")
        )

    def _report_failure(self, error: Exception) -> None:
        detail = "".join(
            traceback.format_exception(type(error), error, error.__traceback__)
        ).strip()
        if not detail:
            detail = str(error) or type(error).__name__
        if detail == self._failed_detail:
            return
        self._failed_detail = detail
        self.failure.emit(detail)


def _uniform_bindings(
    rhi: QRhi,
    uniform_buffer: QRhiBuffer,
    stages: QRhiShaderResourceBinding.StageFlag,
    label: str,
) -> QRhiShaderResourceBindings:
    bindings = rhi.newShaderResourceBindings()
    bindings.setBindings(
        [QRhiShaderResourceBinding.uniformBuffer(0, stages, uniform_buffer)]
    )
    _require_created(bindings, label)
    return bindings


def _quality_profile(
    device_type: QRhiDriverInfo.DeviceType,
) -> tuple[str, int]:
    if device_type in (
        QRhiDriverInfo.DeviceType.DiscreteDevice,
        QRhiDriverInfo.DeviceType.ExternalDevice,
    ):
        return "full", _FULL_PARTICLE_COUNT
    if device_type in (
        QRhiDriverInfo.DeviceType.VirtualDevice,
        QRhiDriverInfo.DeviceType.CpuDevice,
    ):
        return "core", _CONSERVATIVE_PARTICLE_COUNT
    return "core", _CORE_PARTICLE_COUNT


def presentation_response(
    *,
    activity: float,
    energy: float,
    target_height: int,
) -> PresentationResponse:
    """Keep retained light bounded while music changes motion and fine structure."""

    bounded_activity = min(1.0, max(0.0, activity))
    bounded_energy = min(1.0, max(0.0, energy))
    return PresentationResponse(
        history_retention=0.892 + 0.026 * bounded_activity,
        exposure=0.80 + 0.20 * math.sqrt(bounded_energy),
        source_gain=0.190 - 0.035 * bounded_activity,
        point_scale=0.72 + 0.32 * min(1.0, 720.0 / max(360, target_height)),
    )


def _create_texture_target(rhi: QRhi, size: QSize) -> _TextureTarget:
    texture = rhi.newTexture(
        QRhiTexture.Format.RGBA16F,
        size,
        1,
        QRhiTexture.Flag.RenderTarget,
    )
    _require_created(texture, "HDR field texture")
    target = rhi.newTextureRenderTarget(
        QRhiTextureRenderTargetDescription(QRhiColorAttachment(texture))
    )
    descriptor = target.newCompatibleRenderPassDescriptor()
    target.setRenderPassDescriptor(descriptor)
    _require_created(target, "HDR field render target")
    return _TextureTarget(texture, target, descriptor)


def _create_fullscreen_pipeline(
    rhi: QRhi,
    fragment_name: str,
    bindings: QRhiShaderResourceBindings,
    descriptor: QRhiRenderPassDescriptor,
    *,
    additive: bool = False,
) -> QRhiGraphicsPipeline:
    layout = QRhiVertexInputLayout()
    layout.setBindings([])
    layout.setAttributes([])
    pipeline = rhi.newGraphicsPipeline()
    pipeline.setTopology(QRhiGraphicsPipeline.Topology.Triangles)
    pipeline.setCullMode(QRhiGraphicsPipeline.CullMode.None_)
    if additive:
        blend = QRhiGraphicsPipeline.TargetBlend()
        blend.enable = True
        one = cast("int", QRhiGraphicsPipeline.BlendFactor.One)
        blend.srcColor = one
        blend.dstColor = one
        blend.srcAlpha = one
        blend.dstAlpha = one
        pipeline.setTargetBlends([blend])
    pipeline.setShaderStages(
        [
            QRhiShaderStage(
                QRhiShaderStage.Type.Vertex,
                _load_shader(_SHADER_ROOT / "fullscreen.vert.qsb"),
            ),
            QRhiShaderStage(
                QRhiShaderStage.Type.Fragment,
                _load_shader(_SHADER_ROOT / fragment_name),
            ),
        ]
    )
    pipeline.setVertexInputLayout(layout)
    pipeline.setShaderResourceBindings(bindings)
    pipeline.setRenderPassDescriptor(descriptor)
    _require_created(pipeline, f"{fragment_name} fullscreen pipeline")
    return pipeline


def _impulse_character_code(character: FieldImpulseCharacter) -> float:
    return {
        FieldImpulseCharacter.BURST: 1.0,
        FieldImpulseCharacter.LASER: 2.0,
        FieldImpulseCharacter.RIFT: 3.0,
        FieldImpulseCharacter.SOURCE_FLARE: 4.0,
    }[character]


def _initial_particle_data(seed: int, count: int) -> bytes:
    rng = np.random.default_rng(seed & 0xFFFF_FFFF_FFFF_FFFF)
    cloud = rng.integers(0, 3, size=count)
    centers = np.asarray(
        ((-1.8, 0.7, 0.1), (1.7, -0.8, -0.5), (0.0, 0.4, -1.7)),
        dtype=np.float32,
    )
    directions = rng.normal(0.0, 1.0, size=(count, 3)).astype(np.float32)
    directions /= np.maximum(
        np.linalg.norm(directions, axis=1, keepdims=True),
        np.float32(1e-6),
    )
    radii = (rng.random(count, dtype=np.float32) ** np.float32(0.62)) * 3.2
    positions = centers[cloud] * np.float32(0.45) + directions * radii[:, None]
    velocities = np.cross(
        positions,
        np.asarray((0.21, 0.91, 0.35), dtype=np.float32),
    )
    velocities *= np.float32(0.075) / np.maximum(
        np.linalg.norm(velocities, axis=1, keepdims=True),
        np.float32(0.2),
    )
    particles = np.empty((count, 8), dtype=np.float32)
    particles[:, 0:3] = positions
    particles[:, 3] = rng.random(count, dtype=np.float32)
    particles[:, 4:7] = velocities
    seed_bases = rng.integers(0, 8_192, size=count, dtype=np.int32).astype(np.float32)
    comet_markers = (
        (np.arange(count, dtype=np.float32) + np.float32(0.5))
        / np.float32(count)
        * np.float32(0.998)
    )
    rng.shuffle(comet_markers)
    particles[:, 7] = seed_bases + comet_markers
    # Comet candidates occupy one stable prefix, so the comet pass can skip the
    # roughly ninety percent of particles its vertex shader would otherwise reject.
    comet_candidates = np.flatnonzero(
        comet_markers >= np.float32(_COMET_PREFIX_MARKER_THRESHOLD)
    )
    ambient_particles = np.flatnonzero(
        comet_markers < np.float32(_COMET_PREFIX_MARKER_THRESHOLD)
    )
    comet_order = np.concatenate((comet_candidates, ambient_particles))
    return particles[comet_order].tobytes()


def _comet_instance_count(particle_count: int) -> int:
    return max(1, math.ceil(particle_count * _COMET_POOL_FRACTION))


def _build_filaments(seed: int) -> tuple[bytes, int]:
    rng = np.random.default_rng((seed ^ 0xE1EC_7A11) & 0xFFFF_FFFF_FFFF_FFFF)
    segments: list[tuple[float, ...]] = []
    anchors = np.asarray(
        ((-1.8, 0.7, 0.1), (1.7, -0.8, -0.5), (0.0, 0.4, -1.7)),
        dtype=np.float64,
    )
    for root_index in range(6):
        source = anchors[root_index % len(anchors)]
        destination = anchors[(root_index + 1 + root_index // 3) % len(anchors)]
        start = source * float(rng.uniform(0.48, 0.76))
        start += rng.normal(0.0, 0.34, size=3)
        chord = _normalized(destination * 0.72 - start)
        orbit = _normalized(np.cross(chord, rng.normal(0.0, 1.0, size=3)))
        direction = _normalized(
            chord * float(rng.uniform(0.68, 0.92))
            + orbit * float(rng.uniform(-0.64, 0.64))
            + rng.normal(0.0, 0.12, size=3)
        )
        stack = [
            (
                start,
                direction,
                float(rng.uniform(0.94, 1.28)),
                0,
                float(rng.random()),
            )
        ]
        while stack:
            branch_start, branch_direction, length, depth, phase = stack.pop()
            jitter = rng.normal(0.0, 0.13 + depth * 0.018, size=3)
            end = branch_start + _normalized(branch_direction + jitter) * length
            segments.append(
                (
                    float(branch_start[0]),
                    float(branch_start[1]),
                    float(branch_start[2]),
                    float(depth),
                    float(end[0]),
                    float(end[1]),
                    float(end[2]),
                    phase,
                )
            )
            if depth >= 7:
                continue
            tangent = _normalized(
                np.cross(branch_direction, rng.normal(0.0, 1.0, size=3))
            )
            for side in (-1.0, 1.0):
                child_direction = _normalized(
                    branch_direction * (0.84 + float(rng.uniform(-0.08, 0.08)))
                    + tangent * side * float(rng.uniform(0.28, 0.52))
                    + rng.normal(0.0, 0.08, size=3)
                )
                stack.append(
                    (
                        end,
                        child_direction,
                        length * float(rng.uniform(0.69, 0.77)),
                        depth + 1,
                        (phase + side * 0.071 + depth * 0.013) % 1.0,
                    )
                )
    array = np.asarray(segments, dtype=np.float32)
    return array.tobytes(), len(segments)


def _normalized(vector: NDArray[np.float64]) -> NDArray[np.float64]:
    length = float(np.linalg.norm(vector))
    if length <= 1e-12:
        return np.asarray((1.0, 0.0, 0.0), dtype=np.float64)
    return vector / length


def _load_shader(path: Path) -> QShader:
    shader = QShader.fromSerialized(QByteArray(path.read_bytes()))
    if not shader.isValid():
        raise RuntimeError(f"Invalid packaged Synesthesia shader: {path.name}")
    return shader


def _require_created(resource: _Creatable, label: str) -> None:
    if not resource.create():
        raise RuntimeError(f"The graphics backend could not create the {label}")


def _viewport(size: QSize) -> QRhiViewport:
    return QRhiViewport(0.0, 0.0, float(size.width()), float(size.height()))


def _blend_preview_scene(
    preview: SceneMoment,
    analyzed: SceneMoment,
    amount: float,
) -> SceneMoment:
    """Move the camera and scene from preview to the analyzed composition."""

    amount = min(1.0, max(0.0, amount))
    if amount >= 1.0:
        return analyzed
    dominant = analyzed.primary if analyzed.blend < 0.5 else analyzed.secondary
    return SceneMoment(
        primary=preview.primary,
        secondary=dominant,
        blend=amount * amount * (3.0 - 2.0 * amount),
        transition_energy=0.0,
        tuning=preview.tuning.interpolated(analyzed.tuning, amount),
        motion=preview.motion.interpolated(analyzed.motion, amount),
        camera_shot=analyzed.camera_shot,
        camera_pose=preview.camera_pose.interpolated(analyzed.camera_pose, amount),
        camera_progress=(
            preview.camera_progress
            + (analyzed.camera_progress - preview.camera_progress) * amount
        ),
        camera_motion=(
            preview.camera_motion
            + (analyzed.camera_motion - preview.camera_motion) * amount
        ),
    )


def _display_refresh_rate(widget: QWidget) -> float:
    refresh_rate = float(widget.screen().refreshRate())
    if math.isfinite(refresh_rate) and refresh_rate > 0.0:
        return refresh_rate
    return 60.0


__all__ = [
    "PresentationResponse",
    "SynesthesiaRenderDiagnostics",
    "SynesthesiaRenderer",
    "presentation_response",
]
