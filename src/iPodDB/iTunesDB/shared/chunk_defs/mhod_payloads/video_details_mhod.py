"""MHOD type 32 video-details payload definition."""

from dataclasses import dataclass

from iPodDB.shared.chunk import MhodPayload


@dataclass(frozen=True, slots=True)
class MhodVideoDetailsPayload(MhodPayload):
    """Preserved video descriptor with its one confirmed FourCC field."""

    data: bytes
    codec_fourcc: bytes | None
