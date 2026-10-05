import struct

from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.settings_mhod import (
    MhodSettingsField,
    MhodSettingsPayload,
)
from iPodDB.shared.diagnostics import report_unknown_data
from iPodDB.shared.types import MhodPayloadParseContext

_UINT32_LE = struct.Struct("<I")


def parse_settings_payload(
    context: MhodPayloadParseContext[None],
) -> MhodSettingsPayload:
    data = bytes(context.data[context.payload_offset : context.payload_end])
    report_unknown_data(
        f"MHOD {int(context.mhod_type)} settings data",
        context.payload_offset,
        len(data),
    )
    aligned_length = len(data) - len(data) % _UINT32_LE.size
    fields: list[MhodSettingsField] = []

    for offset in range(0, aligned_length, _UINT32_LE.size):
        value = _UINT32_LE.unpack_from(data, offset)[0]
        if value:
            fields.append(MhodSettingsField(offset=offset, value=value))

    return MhodSettingsPayload(
        data=data,
        nonzero_fields=tuple(fields),
        trailing_data=data[aligned_length:],
    )
