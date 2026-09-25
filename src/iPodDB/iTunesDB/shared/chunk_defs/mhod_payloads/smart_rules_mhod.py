"""MHOD type 51 smart-playlist rule definitions."""

from dataclasses import dataclass

from iPodDB.shared.chunk import BinaryStruct, MhodPayload, MhodPayloadPrefix
from iPodDB.shared.chunk_field import chunk_field as cf

SMART_RULE_STRING_FIELD_IDS = frozenset(
    {
        0x02,
        0x03,
        0x04,
        0x08,
        0x09,
        0x0E,
        0x12,
        0x27,
        0x36,
        0x37,
        0x3E,
        0x47,
        0x4E,
        0x4F,
        0x50,
        0x51,
        0x52,
        0x53,
        0x59,
        0x9F,
        0xA0,
    }
)

SMART_RULE_NUMERIC_FIELD_IDS = frozenset(
    {
        0x05,
        0x06,
        0x07,
        0x0A,
        0x0B,
        0x0C,
        0x0D,
        0x10,
        0x16,
        0x17,
        0x18,
        0x19,
        0x1D,
        0x1F,
        0x23,
        0x25,
        0x28,
        0x29,
        0x39,
        0x3C,
        0x3F,
        0x44,
        0x45,
        0x5A,
        0x85,
        0x86,
        0x9A,
        0x9C,
        0xA1,
    }
)

SMART_RULE_GROUP_MARKER = 0x01000000


@dataclass(frozen=True, slots=True)
class MhodSmartRulesPrefix(MhodPayloadPrefix):
    magic: bytes = cf(0x18, "raw", size=4)
    unk_0x1C: int = cf(0x1C, "be_u32")
    rule_count: int = cf(0x20, "be_u32")
    conjunction: int = cf(0x24, "be_u32")
    header_data: bytes = cf(0x28, "raw", size=120)


@dataclass(frozen=True, slots=True)
class MhodSmartRulesContainerHeader(BinaryStruct):
    """An SLst header embedded inside a group rule's data."""

    magic: bytes = cf(0x00, "raw", size=4)
    unk_0x04: int = cf(0x04, "be_u32")
    rule_count: int = cf(0x08, "be_u32")
    conjunction: int = cf(0x0C, "be_u32")
    header_data: bytes = cf(0x10, "raw", size=120)


@dataclass(frozen=True, slots=True)
class MhodSmartRuleHeader(BinaryStruct):
    field_id: int = cf(0x00, "be_u32")
    action_id: int = cf(0x04, "be_u32")
    group_marker: int = cf(0x08, "be_u32")
    header_data: bytes = cf(0x0C, "raw", size=40)
    data_length: int = cf(0x34, "be_u32")


@dataclass(frozen=True, slots=True)
class MhodSmartNumericRuleFields(BinaryStruct):
    from_value: int = cf(0x00, "be_u64")
    from_date: int = cf(0x08, "be_i64")
    from_units: int = cf(0x10, "be_u64")
    to_value: int = cf(0x18, "be_u64")
    to_date: int = cf(0x20, "be_i64")
    to_units: int = cf(0x28, "be_u64")
    unk_0x30: int = cf(0x30, "be_u32")
    unk_0x34: int = cf(0x34, "be_u32")
    unk_0x38: int = cf(0x38, "be_u32")
    unk_0x3C: int = cf(0x3C, "be_u32")
    unk_0x40: int = cf(0x40, "be_u32")


@dataclass(frozen=True, slots=True)
class MhodSmartStringRuleData:
    value: str
    raw_data: bytes


@dataclass(frozen=True, slots=True)
class MhodSmartNumericRuleData:
    from_value: int
    from_date: int
    from_units: int
    to_value: int
    to_date: int
    to_units: int
    unk_0x30: int
    unk_0x34: int
    unk_0x38: int
    unk_0x3C: int
    unk_0x40: int
    raw_data: bytes


@dataclass(frozen=True, slots=True)
class MhodSmartRawRuleData:
    raw_data: bytes


@dataclass(frozen=True, slots=True)
class MhodSmartRuleGroupData:
    magic: bytes
    unk_0x04: int
    rule_count: int
    conjunction: int
    header_data: bytes
    rules: tuple["MhodSmartRule", ...]
    trailing_data: bytes


type MhodSmartRuleData = (
    MhodSmartStringRuleData
    | MhodSmartNumericRuleData
    | MhodSmartRawRuleData
    | MhodSmartRuleGroupData
)


@dataclass(frozen=True, slots=True)
class MhodSmartRule:
    field_id: int
    action_id: int
    group_marker: int
    header_data: bytes
    data: MhodSmartRuleData


@dataclass(frozen=True, slots=True)
class MhodSmartRulesPayload(MhodPayload):
    rules: tuple[MhodSmartRule, ...]
    trailing_data: bytes
