"""Compact CPU-side causes for Synesthesia's GPU-resident Coupled Field.

The renderer owns the high-volume simulation state.  This module owns only the
small state that must survive presentation details: a deterministic seed, stable
force-pole identities, transport clocks, idempotent cause delivery, and a bounded
biography of accepted causes.  It deliberately contains no topology, scene,
interpretation, or camera model.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Final, Self

_ACTIVE_IMPULSE_LIMIT: Final = 8
_CAUSE_RECORD_LIMIT: Final = 256
_CLOCK_EPSILON: Final = 1e-6
_IMPULSE_MINIMUM_STRENGTH: Final = 0.012
_POLE_COUNT: Final = 3


class FieldWorldError(ValueError):
    """Base class for rejected Coupled Field input."""


class InvalidFieldAdvanceError(FieldWorldError):
    """Raised when a field advance contains malformed values."""


class ExperienceTimeRegressionError(FieldWorldError):
    """Raised when the monotonic presentation clock moves backward."""


class UnclassifiedTransportJumpError(FieldWorldError):
    """Raised when musical transport moves without a new Transport Epoch."""


class ConflictingFieldImpulseError(FieldWorldError):
    """Raised when one impulse identity is reused with different content."""


class TransportState(StrEnum):
    """Playback state supplied at the presentation boundary."""

    PLAYING = "playing"
    PAUSED = "paused"
    ENDED = "ended"


class FieldImpulseCharacter(StrEnum):
    """Presentation character retained for one discrete musical cause."""

    BURST = "burst"
    LASER = "laser"
    RIFT = "rift"
    SOURCE_FLARE = "source-flare"


@dataclass(frozen=True, slots=True)
class Vec3:
    """Small immutable vector crossing the renderer boundary."""

    x: float
    y: float
    z: float

    def __post_init__(self) -> None:
        if not all(math.isfinite(value) for value in (self.x, self.y, self.z)):
            raise ValueError("Vec3 components must be finite")

    def __add__(self, other: Vec3) -> Vec3:
        return Vec3(self.x + other.x, self.y + other.y, self.z + other.z)

    def scaled(self, amount: float) -> Vec3:
        if not math.isfinite(amount):
            raise ValueError("Vector scale must be finite")
        return Vec3(self.x * amount, self.y * amount, self.z * amount)


@dataclass(frozen=True, slots=True)
class FieldGenesis:
    """Stable identity for one ephemeral Coupled Field runtime."""

    experience_seed: int

    def __post_init__(self) -> None:
        if type(self.experience_seed) is not int:
            raise ValueError("experience_seed must be an integer")


@dataclass(frozen=True, slots=True)
class FieldImpulse:
    """One identity-bearing spatial cause delivered at most once."""

    impulse_id: str
    musical_event_id: str
    transport_epoch: int
    origin: Vec3
    amplitude: float
    character: FieldImpulseCharacter = FieldImpulseCharacter.BURST
    speed: float = 1.0
    decay_seconds: float = 2.4
    age_seconds: float = 0.0

    def __post_init__(self) -> None:
        if not self.impulse_id.strip():
            raise ValueError("A Field Impulse requires an identity")
        if not self.musical_event_id.strip():
            raise ValueError("A Field Impulse requires a musical event identity")
        if type(self.transport_epoch) is not int:
            raise ValueError("Field Impulse epoch must be an integer")
        if self.transport_epoch < 0:
            raise ValueError("Field Impulse epoch must be non-negative")
        if type(self.character) is not FieldImpulseCharacter:
            raise ValueError("Field Impulse character must be a FieldImpulseCharacter")
        _validate_unit_values(("amplitude", self.amplitude))
        if not math.isfinite(self.speed) or self.speed <= 0.0:
            raise ValueError("Field Impulse speed must be positive and finite")
        if not math.isfinite(self.decay_seconds) or self.decay_seconds <= 0.0:
            raise ValueError("Field Impulse decay must be positive and finite")
        if not math.isfinite(self.age_seconds) or self.age_seconds < 0.0:
            raise ValueError("Field Impulse age must be non-negative and finite")

    @property
    def radius(self) -> float:
        """Current world-space pressure-front radius."""

        return self.speed * self.age_seconds

    @property
    def strength(self) -> float:
        """Current exponentially decayed pressure strength."""

        return self.amplitude * math.exp(-self.age_seconds / self.decay_seconds)

    @property
    def causal_signature(self) -> tuple[object, ...]:
        """Stable content used to detect identity collisions."""

        return (
            self.musical_event_id,
            self.transport_epoch,
            self.origin,
            self.amplitude,
            self.character,
            self.speed,
            self.decay_seconds,
        )

    def aged(self, seconds: float) -> Self:
        if not math.isfinite(seconds) or seconds < 0.0:
            raise ValueError("Impulse age delta must be non-negative and finite")
        return replace(self, age_seconds=self.age_seconds + seconds)


@dataclass(frozen=True, slots=True)
class ForcePole:
    """One stable attractor or repulsor sampled by the GPU simulation."""

    pole_id: str
    position: Vec3
    strength: float
    radius: float
    swirl: float

    def __post_init__(self) -> None:
        if not self.pole_id.strip():
            raise ValueError("A force pole requires an identity")
        if not math.isfinite(self.strength) or not -1.0 <= self.strength <= 1.0:
            raise ValueError("Force-pole strength must be in [-1, 1]")
        if not math.isfinite(self.radius) or self.radius <= 0.0:
            raise ValueError("Force-pole radius must be positive and finite")
        if not math.isfinite(self.swirl) or not -1.0 <= self.swirl <= 1.0:
            raise ValueError("Force-pole swirl must be in [-1, 1]")


@dataclass(frozen=True, slots=True)
class FieldForcing:
    """Compact musical controls offered to the GPU-resident Coupled Field."""

    activity: float = 0.08
    low_frequency_mass: float = 0.0
    fine_excitation: float = 0.02
    harmonic_coherence: float = 0.5
    palette_hue: float = 0.58
    palette_spread: float = 0.35
    brightness: float = 0.35
    spectral_flux: float = 0.0
    timbral_noise: float = 0.0
    stereo_width: float = 0.0
    lateral_bias: float = 0.0
    rhythmic_pulse: float = 0.0
    beat_phase: float = 0.0
    harmonic_layer: float = 0.0
    percussive_layer: float = 0.0
    vocal_layer: float = 0.0
    bass_layer: float = 0.0
    section_novelty: float = 0.0
    section_progress: float = 0.0
    section_identity: float = 0.0
    section_energy: float = 0.0
    poles: tuple[ForcePole, ...] = ()
    impulses: tuple[FieldImpulse, ...] = ()

    def __post_init__(self) -> None:
        _validate_unit_values(
            ("activity", self.activity),
            ("low_frequency_mass", self.low_frequency_mass),
            ("fine_excitation", self.fine_excitation),
            ("harmonic_coherence", self.harmonic_coherence),
            ("palette_hue", self.palette_hue),
            ("palette_spread", self.palette_spread),
            ("brightness", self.brightness),
            ("spectral_flux", self.spectral_flux),
            ("timbral_noise", self.timbral_noise),
            ("stereo_width", self.stereo_width),
            ("rhythmic_pulse", self.rhythmic_pulse),
            ("beat_phase", self.beat_phase),
            ("harmonic_layer", self.harmonic_layer),
            ("percussive_layer", self.percussive_layer),
            ("vocal_layer", self.vocal_layer),
            ("bass_layer", self.bass_layer),
            ("section_novelty", self.section_novelty),
            ("section_progress", self.section_progress),
            ("section_identity", self.section_identity),
            ("section_energy", self.section_energy),
        )
        if not math.isfinite(self.lateral_bias) or not -1.0 <= self.lateral_bias <= 1.0:
            raise ValueError("lateral_bias must be finite and in [-1, 1]")
        if len(self.poles) > _POLE_COUNT:
            raise ValueError(f"Field Forcing supports at most {_POLE_COUNT} poles")
        if len({pole.pole_id for pole in self.poles}) != len(self.poles):
            raise ValueError("Field Forcing pole identities must be unique")
        if len(self.impulses) > _ACTIVE_IMPULSE_LIMIT:
            raise ValueError(
                f"Field Forcing supports at most {_ACTIVE_IMPULSE_LIMIT} impulses"
            )
        if len({item.impulse_id for item in self.impulses}) != len(self.impulses):
            raise ValueError("Field Forcing impulse identities must be unique")

    @property
    def energy(self) -> float:
        return self.activity

    @property
    def bass(self) -> float:
        return self.low_frequency_mass

    @property
    def gravity(self) -> float:
        return self.low_frequency_mass

    @property
    def high(self) -> float:
        return self.fine_excitation

    @property
    def sparks(self) -> float:
        return self.fine_excitation

    @property
    def coherence(self) -> float:
        return self.harmonic_coherence

    @property
    def tension(self) -> float:
        return 1.0 - self.harmonic_coherence

    @property
    def curl(self) -> float:
        return _unit(
            0.16 + 0.58 * self.activity + 0.26 * (1.0 - self.harmonic_coherence)
        )

    @property
    def flow(self) -> float:
        return self.curl

    @property
    def hue(self) -> float:
        return self.palette_hue

    @property
    def impulse_intensity(self) -> float:
        return max((item.amplitude for item in self.impulses), default=0.0)

    @property
    def onset(self) -> float:
        return self.impulse_intensity

    def without_world_state(self) -> Self:
        """Return continuous conductor targets without materialized world state."""

        return replace(self, poles=(), impulses=())


@dataclass(frozen=True, slots=True)
class FieldCauseRecord:
    """One compact, immutable biography entry for an accepted cause."""

    record_id: int
    cause_id: str
    musical_event_id: str
    transport_epoch: int
    origin: Vec3
    amplitude: float
    accepted_field_time: float
    accepted_musical_time: float


@dataclass(frozen=True, slots=True, init=False)
class FieldAdvance:
    """One ordered request to advance or observe the Coupled Field."""

    experience_time: float
    musical_time: float
    transport_state: TransportState
    transport_epoch: int
    forcing: FieldForcing

    def __init__(
        self,
        experience_time: float,
        musical_time: float,
        transport_state: TransportState,
        transport_epoch: int,
        forcing: FieldForcing | None = None,
        *,
        conditions: FieldForcing | None = None,
    ) -> None:
        if forcing is not None and conditions is not None and forcing != conditions:
            raise InvalidFieldAdvanceError(
                "Specify either forcing or compatibility conditions, not both"
            )
        selected = forcing if forcing is not None else conditions
        object.__setattr__(self, "experience_time", experience_time)
        object.__setattr__(self, "musical_time", musical_time)
        object.__setattr__(self, "transport_state", transport_state)
        object.__setattr__(self, "transport_epoch", transport_epoch)
        object.__setattr__(
            self, "forcing", selected if selected is not None else FieldForcing()
        )
        self.__post_init__()

    def __post_init__(self) -> None:
        if type(self.transport_state) is not TransportState:
            raise InvalidFieldAdvanceError("transport_state must be a TransportState")
        if type(self.forcing) is not FieldForcing:
            raise InvalidFieldAdvanceError("forcing must be FieldForcing")
        if not math.isfinite(self.experience_time) or self.experience_time < 0.0:
            raise InvalidFieldAdvanceError(
                "experience_time must be non-negative and finite"
            )
        if not math.isfinite(self.musical_time) or self.musical_time < 0.0:
            raise InvalidFieldAdvanceError(
                "musical_time must be non-negative and finite"
            )
        if type(self.transport_epoch) is not int:
            raise InvalidFieldAdvanceError("transport_epoch must be an integer")
        if self.transport_epoch < 0:
            raise InvalidFieldAdvanceError("transport_epoch must be non-negative")

    @property
    def conditions(self) -> FieldForcing:
        """Compatibility spelling for the former presentation boundary."""

        return self.forcing


@dataclass(frozen=True, slots=True)
class FieldFrame:
    """Small immutable CPU publication; GPU field buffers are not included."""

    revision: int
    field_time: float
    delta_seconds: float
    musical_time: float
    transport_state: TransportState
    transport_epoch: int
    experience_seed: int
    forcing: FieldForcing
    active_impulses: tuple[FieldImpulse, ...]
    cause_records: tuple[FieldCauseRecord, ...]
    total_cause_count: int
    diagnostics: tuple[str, ...] = ()

    @property
    def world_time(self) -> float:
        """Compatibility alias for code moving from the topology proof."""

        return self.field_time

    @property
    def conditions(self) -> FieldForcing:
        return self.forcing

    @property
    def poles(self) -> tuple[ForcePole, ...]:
        return self.forcing.poles

    @property
    def impulses(self) -> tuple[FieldImpulse, ...]:
        """All still-visible waves, including already delivered causes."""

        return self.active_impulses

    @property
    def new_impulses(self) -> tuple[FieldImpulse, ...]:
        """Causes accepted in this advance and safe to inject exactly once."""

        return self.forcing.impulses

    @property
    def event_records(self) -> tuple[FieldCauseRecord, ...]:
        return self.cause_records

    @property
    def scar(self) -> FieldCauseRecord | None:
        """Temporary page compatibility: an accepted cause means altered."""

        return self.cause_records[-1] if self.cause_records else None


@dataclass(frozen=True, slots=True)
class _PoleSeed:
    pole_id: str
    position: Vec3
    radius: float
    handedness: float


class FieldWorld:
    """Own compact field identity and causal biography, never GPU volume state."""

    def __init__(self, genesis: FieldGenesis) -> None:
        self._genesis = genesis
        self._pole_seeds = _make_pole_seeds(genesis.experience_seed)
        self._experience_time: float | None = None
        self._musical_time: float | None = None
        self._transport_state: TransportState | None = None
        self._transport_epoch: int | None = None
        self._field_time = 0.0
        self._continuous_forcing = FieldForcing()
        self._active_impulses: tuple[FieldImpulse, ...] = ()
        self._accepted_signatures: dict[str, tuple[object, ...]] = {}
        self._cause_records: tuple[FieldCauseRecord, ...] = ()
        self._total_cause_count = 0
        self._frame: FieldFrame | None = None

    @classmethod
    def create(cls, genesis: FieldGenesis) -> Self:
        return cls(genesis)

    @property
    def genesis(self) -> FieldGenesis:
        return self._genesis

    def advance(self, request: FieldAdvance) -> FieldFrame:
        """Advance compact causes while pause and seek preserve GPU continuity."""

        self._validate_clocks(request)
        same_epoch = (
            self._transport_epoch is not None
            and request.transport_epoch == self._transport_epoch
        )
        active_delta = (
            request.experience_time - self._experience_time
            if self._experience_time is not None
            and self._transport_state is TransportState.PLAYING
            and request.transport_state is TransportState.PLAYING
            and same_epoch
            else 0.0
        )
        if active_delta < -_CLOCK_EPSILON:
            raise ExperienceTimeRegressionError("experience_time cannot move backward")
        active_delta = max(0.0, active_delta)

        aged_candidates = tuple(
            item.aged(active_delta) for item in self._active_impulses
        )
        aged = tuple(
            item
            for item in aged_candidates
            if item.strength >= _IMPULSE_MINIMUM_STRENGTH
        )
        if request.transport_state is TransportState.PLAYING:
            next_continuous_forcing = request.forcing.without_world_state()
            accepted = self._accept_impulses(
                request.forcing.impulses,
                request=request,
                accepted_field_time=self._field_time + active_delta,
            )
            self._continuous_forcing = next_continuous_forcing
        else:
            if request.forcing.impulses:
                raise InvalidFieldAdvanceError(
                    "Paused or ended transport cannot deliver Field Impulses"
                )
            accepted = ()

        self._active_impulses = (*aged, *accepted)[-_ACTIVE_IMPULSE_LIMIT:]
        self._field_time += active_delta
        poles = self._materialize_poles(self._continuous_forcing)
        published_forcing = replace(
            self._continuous_forcing,
            poles=poles,
            impulses=accepted,
        )
        diagnostics = (
            ("field-biography-compacted",)
            if self._total_cause_count > len(self._cause_records)
            else ()
        )
        next_revision = 1 if self._frame is None else self._frame.revision + 1
        candidate = FieldFrame(
            revision=next_revision,
            field_time=self._field_time,
            delta_seconds=active_delta,
            musical_time=request.musical_time,
            transport_state=request.transport_state,
            transport_epoch=request.transport_epoch,
            experience_seed=self._genesis.experience_seed,
            forcing=published_forcing,
            active_impulses=self._active_impulses,
            cause_records=self._cause_records,
            total_cause_count=self._total_cause_count,
            diagnostics=diagnostics,
        )
        if (
            self._frame is not None
            and replace(candidate, revision=self._frame.revision) == self._frame
        ):
            candidate = self._frame

        self._experience_time = request.experience_time
        self._musical_time = request.musical_time
        self._transport_state = request.transport_state
        self._transport_epoch = request.transport_epoch
        self._frame = candidate
        return candidate

    def _accept_impulses(
        self,
        impulses: tuple[FieldImpulse, ...],
        *,
        request: FieldAdvance,
        accepted_field_time: float,
    ) -> tuple[FieldImpulse, ...]:
        novel: list[FieldImpulse] = []
        for impulse in impulses:
            if impulse.transport_epoch != request.transport_epoch:
                raise InvalidFieldAdvanceError(
                    "Field Impulse epoch must match the current Transport Epoch"
                )
            if impulse.age_seconds != 0.0:
                raise InvalidFieldAdvanceError(
                    "New Field Impulses must be delivered at age zero"
                )
            previous = self._accepted_signatures.get(impulse.impulse_id)
            if previous is not None:
                if previous != impulse.causal_signature:
                    raise ConflictingFieldImpulseError(
                        f"Field Impulse {impulse.impulse_id!r} changed content"
                    )
                continue
            novel.append(impulse)

        accepted: list[FieldImpulse] = []
        for impulse in novel:
            self._accepted_signatures[impulse.impulse_id] = impulse.causal_signature
            accepted.append(impulse)
            self._total_cause_count += 1
            record = FieldCauseRecord(
                record_id=self._total_cause_count,
                cause_id=impulse.impulse_id,
                musical_event_id=impulse.musical_event_id,
                transport_epoch=impulse.transport_epoch,
                origin=impulse.origin,
                amplitude=impulse.amplitude,
                accepted_field_time=accepted_field_time,
                accepted_musical_time=request.musical_time,
            )
            self._cause_records = (*self._cause_records, record)[-_CAUSE_RECORD_LIMIT:]
        return tuple(accepted)

    def _materialize_poles(self, forcing: FieldForcing) -> tuple[ForcePole, ...]:
        mass, order, excitation = self._pole_seeds
        spread = 0.28 * forcing.stereo_width
        drift = 0.22 * forcing.lateral_bias
        return (
            ForcePole(
                pole_id=mass.pole_id,
                position=Vec3(
                    mass.position.x - spread + drift,
                    mass.position.y,
                    mass.position.z,
                ),
                strength=0.12 + 0.88 * forcing.low_frequency_mass,
                radius=mass.radius,
                swirl=mass.handedness * forcing.curl,
            ),
            ForcePole(
                pole_id=order.pole_id,
                position=Vec3(
                    order.position.x + drift * 0.5,
                    order.position.y + 0.08 * forcing.harmonic_layer,
                    order.position.z,
                ),
                strength=(forcing.harmonic_coherence - 0.5) * 1.8,
                radius=order.radius,
                swirl=order.handedness * (1.0 - forcing.harmonic_coherence),
            ),
            ForcePole(
                pole_id=excitation.pole_id,
                position=Vec3(
                    excitation.position.x + spread + drift,
                    excitation.position.y,
                    excitation.position.z,
                ),
                strength=-(0.08 + 0.82 * forcing.fine_excitation),
                radius=excitation.radius,
                swirl=excitation.handedness * _unit(0.22 + 0.78 * forcing.activity),
            ),
        )

    def _validate_clocks(self, request: FieldAdvance) -> None:
        if self._experience_time is not None and (
            request.experience_time + _CLOCK_EPSILON < self._experience_time
        ):
            raise ExperienceTimeRegressionError("experience_time cannot move backward")
        if self._transport_epoch is None:
            return
        if request.transport_epoch < self._transport_epoch:
            raise UnclassifiedTransportJumpError("Transport Epoch cannot move backward")
        same_epoch = request.transport_epoch == self._transport_epoch
        if not same_epoch:
            return
        assert self._musical_time is not None
        if request.musical_time + _CLOCK_EPSILON < self._musical_time:
            raise UnclassifiedTransportJumpError(
                "Backward musical movement requires a new Transport Epoch"
            )
        if (
            self._transport_state is TransportState.PAUSED
            and abs(request.musical_time - self._musical_time) > _CLOCK_EPSILON
        ):
            raise UnclassifiedTransportJumpError(
                "Paused musical movement requires a new Transport Epoch"
            )
        if (
            self._transport_state is TransportState.ENDED
            and request.transport_state is TransportState.PLAYING
        ):
            raise UnclassifiedTransportJumpError(
                "Restart after end requires a new Transport Epoch"
            )


def _make_pole_seeds(experience_seed: int) -> tuple[_PoleSeed, ...]:
    return (
        _PoleSeed(
            pole_id="pole.mass",
            position=Vec3(
                -0.48 + 0.18 * _stable_signed(experience_seed, "mass.x"),
                -0.16 + 0.12 * _stable_signed(experience_seed, "mass.y"),
                0.08 + 0.18 * _stable_signed(experience_seed, "mass.z"),
            ),
            radius=0.62 + 0.12 * _stable_fraction(experience_seed, "mass.radius"),
            handedness=-1.0,
        ),
        _PoleSeed(
            pole_id="pole.order",
            position=Vec3(
                0.05 + 0.18 * _stable_signed(experience_seed, "order.x"),
                0.38 + 0.12 * _stable_signed(experience_seed, "order.y"),
                -0.18 + 0.16 * _stable_signed(experience_seed, "order.z"),
            ),
            radius=0.48 + 0.13 * _stable_fraction(experience_seed, "order.radius"),
            handedness=1.0,
        ),
        _PoleSeed(
            pole_id="pole.excitation",
            position=Vec3(
                0.44 + 0.16 * _stable_signed(experience_seed, "spark.x"),
                -0.28 + 0.12 * _stable_signed(experience_seed, "spark.y"),
                0.14 * _stable_signed(experience_seed, "spark.z"),
            ),
            radius=0.34 + 0.1 * _stable_fraction(experience_seed, "spark.radius"),
            handedness=-1.0
            if _stable_fraction(experience_seed, "spark.hand") < 0.5
            else 1.0,
        ),
    )


def _stable_fraction(experience_seed: int, label: str) -> float:
    digest = hashlib.blake2s(
        f"{experience_seed}:{label}".encode(), digest_size=8
    ).digest()
    return int.from_bytes(digest, "big") / float((1 << 64) - 1)


def _stable_signed(experience_seed: int, label: str) -> float:
    return _stable_fraction(experience_seed, label) * 2.0 - 1.0


def _validate_unit_values(*items: tuple[str, float]) -> None:
    for name, value in items:
        if not math.isfinite(value) or not 0.0 <= value <= 1.0:
            raise ValueError(f"{name} must be finite and in [0, 1]")


def _unit(value: float) -> float:
    return min(1.0, max(0.0, value))


# Transitional names keep the page and renderer importable during the field-proof
# integration.  They are aliases, not a second topology-based model.
PersistentWorld = FieldWorld
WorldAdvance = FieldAdvance
WorldConditions = FieldForcing
WorldFrame = FieldFrame
WorldGenesis = FieldGenesis


__all__ = [
    "ConflictingFieldImpulseError",
    "ExperienceTimeRegressionError",
    "FieldAdvance",
    "FieldCauseRecord",
    "FieldForcing",
    "FieldFrame",
    "FieldGenesis",
    "FieldImpulse",
    "FieldImpulseCharacter",
    "FieldWorld",
    "FieldWorldError",
    "ForcePole",
    "InvalidFieldAdvanceError",
    "PersistentWorld",
    "TransportState",
    "UnclassifiedTransportJumpError",
    "Vec3",
    "WorldAdvance",
    "WorldConditions",
    "WorldFrame",
    "WorldGenesis",
]
