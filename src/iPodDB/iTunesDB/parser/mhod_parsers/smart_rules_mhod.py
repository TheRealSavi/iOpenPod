from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.smart_rules_mhod import (
    SMART_RULE_GROUP_MARKER,
    SMART_RULE_NUMERIC_FIELD_IDS,
    SMART_RULE_STRING_FIELD_IDS,
    MhodSmartNumericRuleData,
    MhodSmartNumericRuleFields,
    MhodSmartRawRuleData,
    MhodSmartRule,
    MhodSmartRuleData,
    MhodSmartRuleGroupData,
    MhodSmartRuleHeader,
    MhodSmartRulesContainerHeader,
    MhodSmartRulesPayload,
    MhodSmartRulesPrefix,
    MhodSmartStringRuleData,
)
from iPodDB.shared.binary_struct import binary_struct_extent, parse_binary_struct
from iPodDB.shared.diagnostics import report_unknown_data, retain_unknown_bytes
from iPodDB.shared.errors import UnknownMhodLayoutError
from iPodDB.shared.types import MhodPayloadParseContext

_SLST_HEADER_SIZE = binary_struct_extent(MhodSmartRulesContainerHeader)
_RULE_HEADER_SIZE = binary_struct_extent(MhodSmartRuleHeader)
_NUMERIC_DATA_SIZE = binary_struct_extent(MhodSmartNumericRuleFields)


def _parse_rules(
    data: bytes | bytearray,
    offset: int,
    container_end: int,
    rule_count: int,
) -> tuple[tuple[MhodSmartRule, ...], int]:
    rules: list[MhodSmartRule] = []
    rule_offset = offset

    for rule_index in range(rule_count):
        header_end = rule_offset + _RULE_HEADER_SIZE
        if header_end > container_end:
            raise ValueError(
                f"SLst declares {rule_count} rules, but rule {rule_index} "
                f"at {rule_offset:#x} has no complete header"
            )

        header = parse_binary_struct(
            data,
            rule_offset,
            MhodSmartRuleHeader,
            limit=container_end,
        )
        data_offset = header_end
        data_end = data_offset + header.data_length

        if data_end > container_end:
            raise ValueError(
                f"SLst rule {rule_index} at {rule_offset:#x} declares "
                f"{header.data_length} data bytes past its container"
            )

        raw_data = bytes(data[data_offset:data_end])

        rule_data: MhodSmartRuleData

        if (
            header.field_id == 0
            and header.action_id == 1
            and header.group_marker == SMART_RULE_GROUP_MARKER
            and raw_data.startswith(b"SLst")
        ):
            rule_data = _parse_group(data, data_offset, data_end)

        elif header.group_marker:
            rule_data = MhodSmartRawRuleData(raw_data=raw_data)

        elif header.field_id in SMART_RULE_STRING_FIELD_IDS or (
            header.field_id not in SMART_RULE_NUMERIC_FIELD_IDS
            and (not raw_data or bool(header.action_id & 0x01000000))
        ):
            rule_data = MhodSmartStringRuleData(
                value=raw_data.decode("utf-16-be", errors="replace"),
                raw_data=raw_data,
            )

        elif len(raw_data) >= _NUMERIC_DATA_SIZE:
            fields = parse_binary_struct(
                data,
                data_offset,
                MhodSmartNumericRuleFields,
                limit=data_end,
            )
            rule_data = MhodSmartNumericRuleData(
                from_value=fields.from_value,
                from_date=fields.from_date,
                from_units=fields.from_units,
                to_value=fields.to_value,
                to_date=fields.to_date,
                to_units=fields.to_units,
                unk_0x30=fields.unk_0x30,
                unk_0x34=fields.unk_0x34,
                unk_0x38=fields.unk_0x38,
                unk_0x3C=fields.unk_0x3C,
                unk_0x40=fields.unk_0x40,
                raw_data=raw_data,
            )

        else:
            rule_data = MhodSmartRawRuleData(raw_data=raw_data)

        if isinstance(rule_data, MhodSmartRawRuleData):
            report_unknown_data(
                "opaque Smart Playlist rule", data_offset, len(raw_data)
            )
        elif (
            isinstance(rule_data, MhodSmartNumericRuleData)
            and len(raw_data) > _NUMERIC_DATA_SIZE
        ):
            report_unknown_data(
                "Smart Playlist numeric rule suffix",
                data_offset + _NUMERIC_DATA_SIZE,
                len(raw_data) - _NUMERIC_DATA_SIZE,
            )
        rules.append(
            MhodSmartRule(
                field_id=header.field_id,
                action_id=header.action_id,
                group_marker=header.group_marker,
                header_data=header.header_data,
                data=rule_data,
            )
        )
        rule_offset = data_end

    return tuple(rules), rule_offset


def _parse_group(
    data: bytes | bytearray,
    offset: int,
    container_end: int,
) -> MhodSmartRuleGroupData:
    header_end = offset + _SLST_HEADER_SIZE
    if header_end > container_end:
        raise ValueError(
            f"nested SLst at {offset:#x} is too short for its 136-byte header"
        )

    header = parse_binary_struct(
        data,
        offset,
        MhodSmartRulesContainerHeader,
        limit=container_end,
    )
    if header.magic != b"SLst":
        raise ValueError(
            f"nested smart-rules group at {offset:#x} expected b'SLst', "
            f"got {header.magic!r}"
        )

    rules, rules_end = _parse_rules(
        data,
        header_end,
        container_end,
        header.rule_count,
    )

    return MhodSmartRuleGroupData(
        magic=header.magic,
        unk_0x04=header.unk_0x04,
        rule_count=header.rule_count,
        conjunction=header.conjunction,
        header_data=header.header_data,
        rules=rules,
        trailing_data=retain_unknown_bytes(
            data, rules_end, container_end, "Smart Playlist group suffix"
        ),
    )


def parse_smart_rules_payload(
    context: MhodPayloadParseContext[MhodSmartRulesPrefix],
) -> MhodSmartRulesPayload:
    if context.prefix.magic != b"SLst":
        raise UnknownMhodLayoutError("unrecognized Smart Playlist rules layout")

    rules, rules_end = _parse_rules(
        context.data,
        context.payload_offset,
        context.payload_end,
        context.prefix.rule_count,
    )

    return MhodSmartRulesPayload(
        rules=rules,
        trailing_data=retain_unknown_bytes(
            context.data, rules_end, context.payload_end, "MHOD 51 rules suffix"
        ),
    )
