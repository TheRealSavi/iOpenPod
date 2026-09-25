"""ArtworkDB MHOD payload containing one nested MHNI Chunk."""

from dataclasses import dataclass

from iPodDB.ArtworkDB.shared.chunk_defs.mhni import MhniHeader
from iPodDB.shared.chunk import MhodPayload, ParsedChunk


@dataclass(frozen=True, slots=True)
class MhodContainerPayload(MhodPayload):
    child: ParsedChunk[MhniHeader]
    trailing_data: bytes
