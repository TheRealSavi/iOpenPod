from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.contextual_100_mhod import (
    MhodPlaylistPositionPayload,
    MhodPlaylistPositionPrefix,
)
from iPodDB.shared.diagnostics import retain_unknown_bytes
from iPodDB.shared.types import MhodPayloadParseContext


def parse_playlist_position_payload(
    context: MhodPayloadParseContext[MhodPlaylistPositionPrefix],
) -> MhodPlaylistPositionPayload:
    return MhodPlaylistPositionPayload(
        trailing_data=retain_unknown_bytes(
            context.data,
            context.payload_offset,
            context.payload_end,
            "MHOD 100 position suffix",
        ),
    )
