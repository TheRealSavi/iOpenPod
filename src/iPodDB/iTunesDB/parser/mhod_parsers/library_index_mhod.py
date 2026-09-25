import struct

from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.library_index_mhod import (
    MhodLibraryIndexPayload,
    MhodLibraryIndexPrefix,
)
from iPodDB.shared.types import MhodPayloadParseContext

_UINT32_LE = struct.Struct("<I")


def parse_library_index_payload(
    context: MhodPayloadParseContext[MhodLibraryIndexPrefix],
) -> MhodLibraryIndexPayload:
    entries_end = context.payload_offset + context.prefix.entry_count * 4
    if entries_end > context.payload_end:
        available = (context.payload_end - context.payload_offset) // 4
        raise ValueError(
            f"MHOD 52 at {context.chunk_offset:#x} declares "
            f"{context.prefix.entry_count} entries, but only {available} fit"
        )

    indices = tuple(
        _UINT32_LE.unpack_from(context.data, context.payload_offset + index * 4)[0]
        for index in range(context.prefix.entry_count)
    )

    return MhodLibraryIndexPayload(
        indices=indices,
        trailing_data=bytes(context.data[entries_end : context.payload_end]),
    )
