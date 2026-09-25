from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.url_mhod import (
    MhodUrlPayload,
)
from iPodDB.shared.types import (
    MhodPayloadParseContext,
)


def parse_url_payload(
    context: MhodPayloadParseContext[None],
) -> MhodUrlPayload:
    raw = bytes(context.data[context.payload_offset : context.payload_end])

    value: str = raw.decode("utf-8", errors="replace").rstrip("\x00")

    return MhodUrlPayload(
        value=value,
    )
