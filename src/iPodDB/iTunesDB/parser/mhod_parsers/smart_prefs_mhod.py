from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.smart_prefs_mhod import (
    MhodSmartPrefsPayload,
    MhodSmartPrefsPrefix,
)
from iPodDB.shared.diagnostics import retain_unknown_bytes
from iPodDB.shared.types import MhodPayloadParseContext


def parse_smart_prefs_payload(
    context: MhodPayloadParseContext[MhodSmartPrefsPrefix],
) -> MhodSmartPrefsPayload:
    return MhodSmartPrefsPayload(
        trailing_data=retain_unknown_bytes(
            context.data,
            context.payload_offset,
            context.payload_end,
            "MHOD 50 preferences suffix",
        ),
    )
