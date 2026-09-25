from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.library_jump_table_mhod import (
    MhodLibraryJumpTableEntry,
    MhodLibraryJumpTablePayload,
    MhodLibraryJumpTablePrefix,
)
from iPodDB.shared.binary_struct import binary_struct_extent, parse_binary_struct
from iPodDB.shared.types import MhodPayloadParseContext

_ENTRY_SIZE = binary_struct_extent(MhodLibraryJumpTableEntry)


def parse_library_jump_table_payload(
    context: MhodPayloadParseContext[MhodLibraryJumpTablePrefix],
) -> MhodLibraryJumpTablePayload:
    entries_end = context.payload_offset + context.prefix.entry_count * _ENTRY_SIZE
    if entries_end > context.payload_end:
        available = (context.payload_end - context.payload_offset) // _ENTRY_SIZE
        raise ValueError(
            f"MHOD 53 at {context.chunk_offset:#x} declares "
            f"{context.prefix.entry_count} entries, but only {available} fit"
        )

    entries = tuple(
        parse_binary_struct(
            context.data,
            context.payload_offset + index * _ENTRY_SIZE,
            MhodLibraryJumpTableEntry,
            limit=entries_end,
        )
        for index in range(context.prefix.entry_count)
    )

    return MhodLibraryJumpTablePayload(
        entries=entries,
        trailing_data=bytes(context.data[entries_end : context.payload_end]),
    )
