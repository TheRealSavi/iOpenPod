"""Opaque ArtworkDB MHOD payload definition."""

from dataclasses import dataclass

from iPodDB.shared.chunk import MhodPayload

# Exact empty type-6 body from Original iOpenPod and the captured Nano 5/7
# databases. The inner words are not generic Chunk extents; retain them opaque.
EMPTY_MHAF_BODY = bytes.fromhex("6d686166 60000000 3c000000") + bytes(84)


@dataclass(frozen=True, slots=True)
class MhodOpaquePayload(MhodPayload):
    data: bytes
