from iPodDB.PhotosDB.shared.chunk_defs.mhod_payloads.opaque_mhod import (
    MhodOpaquePayload,
)
from iPodDB.shared.types import MhodPayloadParseContext


def parse_opaque_payload(
    context: MhodPayloadParseContext[None],
) -> MhodOpaquePayload:
    return MhodOpaquePayload(
        data=bytes(context.data[context.payload_offset : context.payload_end]),
    )
