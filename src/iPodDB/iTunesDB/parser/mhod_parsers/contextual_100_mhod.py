from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.contextual_100_mhod import (
    MhodPlaylistPositionPayload,
    MhodPlaylistPositionPrefix,
)
from iPodDB.shared.types import MhodPayloadParseContext


def parse_playlist_position_payload(
    context: MhodPayloadParseContext[MhodPlaylistPositionPrefix],
) -> MhodPlaylistPositionPayload:
    if context.payload_offset != context.payload_end:
        raise ValueError(
            f"playlist-position MHOD 100 at {context.chunk_offset:#x} has "
            f"{context.payload_end - context.payload_offset} unexpected trailing bytes"
        )

    return MhodPlaylistPositionPayload()
