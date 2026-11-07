"""Decode the bounded native Genius seed layout and retain other variants."""

from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.genius_seed_mhod import (
    MhodGeniusSeedFields,
    MhodGeniusSeedPayload,
)
from iPodDB.shared.binary_struct import binary_struct_extent, parse_binary_struct
from iPodDB.shared.diagnostics import retain_unknown_bytes
from iPodDB.shared.types import MhodPayloadParseContext


def parse_genius_seed_payload(
    context: MhodPayloadParseContext[None],
) -> MhodGeniusSeedPayload:
    if context.payload_end - context.payload_offset == binary_struct_extent(
        MhodGeniusSeedFields
    ):
        return MhodGeniusSeedPayload(
            seed=parse_binary_struct(
                context.data,
                context.payload_offset,
                MhodGeniusSeedFields,
                limit=context.payload_end,
            )
        )
    return MhodGeniusSeedPayload(
        unknown_data=retain_unknown_bytes(
            context.data,
            context.payload_offset,
            context.payload_end,
            "MHOD 54 unknown Genius seed layout",
        )
    )
