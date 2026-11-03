"""Immutable Phase activity shared with the isolated analysis worker."""

from dataclasses import dataclass
from enum import StrEnum


class PhaseStage(StrEnum):
    CAPTURING = "capturing"
    DECODING = "decoding"
    LOADING = "loading"
    SOURCES = "sources"
    ACOUSTIC = "acoustic"
    COMBINING = "combining"
    ENCODING = "encoding"
    VERIFYING = "verifying"
    REUSING = "reusing"
    FINALIZING = "finalizing"


@dataclass(frozen=True, slots=True)
class PhaseActivity:
    stage: PhaseStage
    backend: str = ""
    device_name: str = ""
    parallel_mix: bool = False
