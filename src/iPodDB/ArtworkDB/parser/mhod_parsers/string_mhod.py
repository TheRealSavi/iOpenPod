from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
    MhodStringPrefix,
    decode_artwork_string,
)
from iPodDB.shared.types import MhodPayloadParseContext


def parse_string_payload(
    context: MhodPayloadParseContext[MhodStringPrefix],
) -> MhodStringPayload:
    prefix = context.prefix
    string_end = context.payload_offset + prefix.string_byte_length

    if string_end > context.payload_end:
        raise ValueError(
            f"ArtworkDB MHOD type {int(context.mhod_type)} string length "
            f"extends past its payload: {string_end:#x} > {context.payload_end:#x}"
        )

    raw = bytes(context.data[context.payload_offset : string_end])
    try:
        value = decode_artwork_string(raw, prefix.encoding_indicator)
    except ValueError as exc:
        raise ValueError(
            f"ArtworkDB MHOD type {int(context.mhod_type)}: {exc}"
        ) from exc

    return MhodStringPayload(
        value=value,
        raw_value=raw,
        trailing_data=bytes(context.data[string_end : context.payload_end]),
    )
