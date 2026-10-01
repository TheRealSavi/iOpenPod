"""Read-only, path-free preferences presentation for the Active iPod."""

from dataclasses import dataclass
from enum import StrEnum


class PreferenceFileStatus(StrEnum):
    AVAILABLE = "available"
    MISSING = "missing"
    UNREADABLE = "unreadable"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class IPodPreference:
    key: str
    title: str
    value: str


@dataclass(frozen=True, slots=True)
class IPodPreferenceSection:
    key: str
    title: str
    status: PreferenceFileStatus
    rows: tuple[IPodPreference, ...] = ()
    detail: str = ""
