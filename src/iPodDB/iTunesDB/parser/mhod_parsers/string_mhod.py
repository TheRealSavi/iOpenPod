from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
    MhodStringPrefix,
)
from iPodDB.shared.types import (
    MhodPayloadParseContext,
)


def parse_string_payload(
    context: MhodPayloadParseContext[MhodStringPrefix],
) -> MhodStringPayload:
    prefix: MhodStringPrefix = context.prefix

    string_end: int = context.payload_offset + prefix.string_length

    if string_end > context.payload_end:
        raise ValueError(
            f"MHOD Type: {int(context.mhod_type)} (String)"
            f"Length exceeds payload: "
            f"{string_end:#x} > "
            f"{context.payload_end:#x}"
        )

    raw = bytes(context.data[context.payload_offset : string_end])

    if prefix.encoding_indicator == 2:
        value: str = raw.decode("utf-8", errors="replace")
    else:
        if prefix.string_length % 2 != 0:
            raise ValueError(
                f"MHOD Type: {int(context.mhod_type)} (String)"
                f"Encoding Indicator: {prefix.encoding_indicator} (UTF-16)"
                f"has an odd byte length"
            )
        value = raw.decode("utf-16-le", errors="replace")

    return MhodStringPayload(
        value=value,
    )
