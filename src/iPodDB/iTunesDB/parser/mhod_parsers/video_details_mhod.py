from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.video_details_mhod import (
    MhodVideoDetailsPayload,
)
from iPodDB.shared.types import MhodPayloadParseContext


def parse_video_details_payload(
    context: MhodPayloadParseContext[None],
) -> MhodVideoDetailsPayload:
    data = bytes(context.data[context.payload_offset : context.payload_end])
    codec_fourcc = data[0x0C:0x10] if len(data) >= 0x10 else None

    return MhodVideoDetailsPayload(
        data=data,
        codec_fourcc=codec_fourcc,
    )
