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


# Identical 332-byte payload in all seven Podcast playlist counterparts in the
# four Finder captures (2026-10-18). The words remain opaque, not named settings.
# The shared encoder builds their bytes from these typed fields.
DEFAULT_PODCAST_SETTINGS = MhodSettingsPayload(
    data=bytes(332),
    nonzero_fields=(
        MhodSettingsField(0, 1),
        MhodSettingsField(8, 1),
        MhodSettingsField(76, 4),
        MhodSettingsField(140, 120),
    ),
    trailing_data=b"",
)
