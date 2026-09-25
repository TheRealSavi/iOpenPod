"""MHOD type 102 opaque playlist-settings definition."""

from dataclasses import dataclass

from iPodDB.shared.chunk import MhodPayload


@dataclass(frozen=True, slots=True)
class MhodSettingsField:
    offset: int
    value: int


@dataclass(frozen=True, slots=True)
class MhodSettingsPayload(MhodPayload):
    data: bytes
    nonzero_fields: tuple[MhodSettingsField, ...]
    trailing_data: bytes
