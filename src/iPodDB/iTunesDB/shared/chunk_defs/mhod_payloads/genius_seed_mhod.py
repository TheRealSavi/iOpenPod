"""MHOD 54 Genius Playlist seed, observed on Classic firmware.

The eight-byte body matches the saved Genius Playlist's seedTrackPersistentID.
Other body sizes remain Unknown Data; they still identify a native Genius
Playlist but do not provide an understood seed.
"""

from dataclasses import dataclass

from iPodDB.shared.chunk import BinaryStruct, MhodPayload
from iPodDB.shared.chunk_field import chunk_field as cf


@dataclass(frozen=True, slots=True)
class MhodGeniusSeedFields(BinaryStruct):
    seed_track_persistent_id: int = cf(0, "u64")


@dataclass(frozen=True, slots=True)
class MhodGeniusSeedPayload(MhodPayload):
    seed: MhodGeniusSeedFields | None = None
    unknown_data: bytes = b""

    def __post_init__(self) -> None:
        if self.seed is not None and self.unknown_data:
            raise ValueError("a Genius seed cannot also contain an unknown layout")
