"""Measured, phase-scoped Host media preparation activity."""

from dataclasses import dataclass, field
from enum import StrEnum


class MediaPreparationPhase(StrEnum):
    READING = "reading"
    INSPECTING = "inspecting"
    CONVERTING = "converting"
    METADATA = "metadata"
    VERIFYING = "verifying"
    ANALYZING = "analyzing"


@dataclass(frozen=True, slots=True)
class MediaPreparationProgress:
    """Byte/time measurements apply only to this phase, never the whole preparation."""

    phase: MediaPreparationPhase
    message: str
    processed_seconds: float | None = None
    duration_seconds: float | None = None
    speed: float | None = None
    processed_bytes: int | None = field(default=None, kw_only=True)
    total_bytes: int | None = field(default=None, kw_only=True)
