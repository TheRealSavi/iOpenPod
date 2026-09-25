from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.smart_prefs_mhod import (
    MhodSmartPrefsPayload,
    MhodSmartPrefsPrefix,
)
from iPodDB.shared.types import MhodPayloadParseContext


def parse_smart_prefs_payload(
    context: MhodPayloadParseContext[MhodSmartPrefsPrefix],
) -> MhodSmartPrefsPayload:
    if context.payload_offset != context.payload_end:
        raise ValueError(
            f"MHOD 50 at {context.chunk_offset:#x} has "
            f"{context.payload_end - context.payload_offset} unexpected trailing bytes"
        )

    return MhodSmartPrefsPayload()
