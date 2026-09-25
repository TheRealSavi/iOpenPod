"""The understood MHIP-dependent MHOD type 100 layout."""

from dataclasses import dataclass

from iPodDB.shared.chunk import MhodPayload, MhodPayloadPrefix
from iPodDB.shared.chunk_field import chunk_field as cf

# Original iOpenPod write_mhod_playlist_prefs / libgpod mk_long_mhod_id_playlist.
# MHYP's opaque display preferences are unrelated to MHIP position metadata.
# Fixed body only; the shared MHOD writer supplies its header and lengths.
DEFAULT_PLAYLIST_PREFERENCES = bytes.fromhex(
    "000000000000000000000000000000000000000000000000"
    "84000100050000000900000003000000010012000000000000000000"
    "1400640001000000000000000000000014003200010000000000000000000000"
    "14005a0001000000000000000000000014005000010000000000000000000000"
    "15007d0001000000"
) + bytes(500)


@dataclass(frozen=True, slots=True)
class MhodPlaylistPositionPrefix(MhodPayloadPrefix):
    position: int = cf(0x18, "u32")
    padding_0x1C: bytes = cf(0x1C, "raw", size=16)


@dataclass(frozen=True, slots=True)
class MhodPlaylistPositionPayload(MhodPayload):
    pass
