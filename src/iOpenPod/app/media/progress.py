"""Measured, phase-scoped Host media preparation activity."""

from dataclasses import dataclass
from enum import StrEnum


class MediaPreparationPhase(StrEnum):
    READING = "reading"
    INSPECTING = "inspecting"
    CONVERTING = "converting"
    METADATA = "metadata"
    VERIFYING = "verifying"


@dataclass(frozen=True, slots=True)
class MediaPreparationProgress:
    """Time measurements apply only to this phase, never the whole preparation."""

    phase: MediaPreparationPhase
    message: str
    processed_seconds: float | None = None
    duration_seconds: float | None = None
    speed: float | None = None
