"""Inverse of the supported Smart Playlist projection, preserving retained envelopes."""

from collections import defaultdict, deque
from collections.abc import Mapping
from dataclasses import replace

from iPodDB.device_time import TimeConversion, unix_to_mac
from iPodDB.iTunesDB.builder.build_iTunesDB import new_itunes_chunk
from iPodDB.iTunesDB.shared.chunk_defs.mhod import DEFINITION as MHOD
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.smart_prefs_mhod import (
    MhodSmartPrefsPayload,
    MhodSmartPrefsPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.smart_rules_mhod import (
    SMART_RULE_GROUP_MARKER,
    MhodSmartNumericRuleData,
    MhodSmartRule,
    MhodSmartRuleGroupData,
    MhodSmartRulesPayload,
    MhodSmartRulesPrefix,
    MhodSmartStringRuleData,
)
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.library._smart_projection import (
    CHOICE_ACTIONS,
    DATE_IDENTIFIER,
    DESCENDING_SORTS,
    FIELDS,
    LIMIT_SORTS,
    LIMIT_UNITS,
    LOCATION_ACTIONS,
    LOCATION_VALUES,
    MEDIA_KIND_VALUES,
    NUMERIC_ACTIONS,
    RELATIVE_ACTIONS,
    STRING_ACTIONS,
    project_rule,
)
from iPodDB.library.playlists import (
    SmartLocation,
    SmartMatch,
    SmartMediaKind,
    SmartOperator,
    SmartPlaylist,
    SmartPlaylistReference,
    SmartRule,
    SmartRuleGroup,
    UnsupportedSmartRule,
)
from iPodDB.library.smart_rules import (
    BOOLEAN_FIELDS,
    DATE_FIELDS,
    TEXT_FIELDS,
    validate_smart_playlist,
)
from iPodDB.shared.chunk import ParsedChunk


def encode_rule(
    rule: SmartRule | SmartRuleGroup | UnsupportedSmartRule,
    depth: int = 0,
    timezone_offset: TimeConversion = 0,
    existing: MhodSmartRule | None = None,
    playlist_ids: Mapping[int, int] | None = None,
) -> MhodSmartRule:
    if depth > 64:
        raise ValueError("Smart Playlist rule nesting exceeds 64 levels.")
    if isinstance(rule, UnsupportedSmartRule):
        raise ValueError("Unsupported Smart Playlist rules cannot be replaced.")
    if existing is not None and project_rule(existing, timezone_offset) == rule:
        return existing
    if isinstance(rule, SmartRuleGroup):
        data = MhodSmartRuleGroupData(
            b"SLst",
            0x10001,
            len(rule.rules),
            int(rule.match is SmartMatch.ANY),
            bytes(120),
            _encode_rules(
                rule.rules,
                existing.data.rules
                if existing and isinstance(existing.data, MhodSmartRuleGroupData)
                else (),
                timezone_offset,
                depth + 1,
                playlist_ids,
            ),
            b"",
        )
        if existing and isinstance(existing.data, MhodSmartRuleGroupData):
            return replace(
                existing,
                data=replace(
                    existing.data,
                    rules=data.rules,
                    conjunction=data.conjunction,
                    rule_count=data.rule_count,
                ),
            )
        return MhodSmartRule(0, 1, SMART_RULE_GROUP_MARKER, bytes(40), data)
    field = {value: key for key, value in FIELDS.items()}[rule.field]
    if isinstance(rule.value, SmartPlaylistReference):
        playlist_id = (
            rule.value.playlist_id
            if playlist_ids is None
            else playlist_ids.get(rule.value.playlist_id, 0)
        )
        if not 0 < playlist_id <= 0xFFFFFFFFFFFFFFFF:
            raise ValueError("The referenced Playlist is not available for writing.")
        return MhodSmartRule(
            field,
            {v: k for k, v in CHOICE_ACTIONS.items()}[rule.operator],
            0,
            bytes(40),
            MhodSmartNumericRuleData(
                playlist_id,
                0,
                1,
                playlist_id,
                0,
                1,
                0,
                0,
                0,
                0,
                0,
                b"",
            ),
        )
    if isinstance(rule.value, SmartMediaKind):
        value = {v: k for k, v in MEDIA_KIND_VALUES.items()}[rule.value]
        return MhodSmartRule(
            field,
            {v: k for k, v in CHOICE_ACTIONS.items()}[rule.operator],
            0,
            bytes(40),
            MhodSmartNumericRuleData(value, 0, 1, value, 0, 1, 0, 0, 0, 0, 0, b""),
        )
    if isinstance(rule.value, SmartLocation):
        value = {v: k for k, v in LOCATION_VALUES.items()}[rule.value]
        return MhodSmartRule(
            field,
            {v: k for k, v in LOCATION_ACTIONS.items()}[rule.operator],
            0,
            bytes(40),
            MhodSmartNumericRuleData(value, 0, 1, value, 0, 1, 0, 0, 0, 0, 0, b""),
        )
    if rule.field in BOOLEAN_FIELDS:
        return MhodSmartRule(
            field,
            1 if rule.operator is SmartOperator.IS_TRUE else 0x02000001,
            0,
            bytes(40),
            MhodSmartNumericRuleData(0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0, b""),
        )
    if rule.field in DATE_FIELDS and rule.operator in RELATIVE_ACTIONS.values():
        assert isinstance(rule.value, int)
        return MhodSmartRule(
            field,
            {v: k for k, v in RELATIVE_ACTIONS.items()}[rule.operator],
            0,
            bytes(40),
            MhodSmartNumericRuleData(
                DATE_IDENTIFIER,
                -rule.value,
                1,
                DATE_IDENTIFIER,
                0,
                1,
                0,
                0,
                0,
                0,
                0,
                b"",
            ),
        )
    if rule.field in TEXT_FIELDS:
        if (
            not isinstance(rule.value, str)
            or rule.operator not in STRING_ACTIONS.values()
        ):
            raise ValueError(
                "Text Smart Playlist rules require a supported text comparison."
            )
        rule.value.encode("utf-16-be")
        return MhodSmartRule(
            field,
            {v: k for k, v in STRING_ACTIONS.items()}[rule.operator],
            0,
            bytes(40),
            MhodSmartStringRuleData(rule.value, b""),
        )
    if not isinstance(rule.value, int) or rule.operator not in NUMERIC_ACTIONS.values():
        raise ValueError(
            "Numeric Smart Playlist rules require a supported numeric comparison."
        )
    value = rule.value
    upper = rule.upper_value if rule.operator is SmartOperator.BETWEEN else value
    if rule.field in DATE_FIELDS:
        if not isinstance(upper, int):
            raise ValueError("A valid device timezone and date range are required.")
        value = unix_to_mac(value, timezone_offset, missing_zero=False)
        upper = unix_to_mac(upper, timezone_offset, missing_zero=False)
        if not 0 < value <= upper <= 0xFFFFFFFF:
            raise ValueError("The date cannot be represented in the device timezone.")
    if not isinstance(upper, int) or not 0 <= value <= upper <= 0xFFFFFFFFFFFFFFFF:
        raise ValueError(
            "Smart Playlist numeric bounds must be ordered unsigned 64-bit values."
        )
    return MhodSmartRule(
        field,
        {v: k for k, v in NUMERIC_ACTIONS.items()}[rule.operator],
        0,
        bytes(40),
        MhodSmartNumericRuleData(value, 0, 1, upper, 0, 1, 0, 0, 0, 0, 0, b""),
    )


def _encode_rules(
    rules: tuple[SmartRule | SmartRuleGroup | UnsupportedSmartRule, ...],
    existing: tuple[MhodSmartRule, ...],
    timezone_offset: TimeConversion,
    depth: int = 0,
    playlist_ids: Mapping[int, int] | None = None,
) -> tuple[MhodSmartRule, ...]:
    # Preserve each unchanged occurrence, including its private header and payload.
    retained: dict[
        SmartRule | SmartRuleGroup | UnsupportedSmartRule, deque[MhodSmartRule]
    ] = defaultdict(deque)
    for native in existing:
        retained[project_rule(native, timezone_offset)].append(native)
    return tuple(
        encode_rule(
            rule,
            depth,
            timezone_offset,
            retained[rule].popleft()
            if retained[rule]
            else existing[index]
            if index < len(existing) and isinstance(rule, SmartRuleGroup)
            else None,
            playlist_ids,
        )
        for index, rule in enumerate(rules)
    )


def smart_chunks(
    smart: SmartPlaylist,
    existing: tuple[ParsedChunk[MhodHeader], ...],
    timezone_offset: TimeConversion = 0,
    playlist_ids: Mapping[int, int] | None = None,
) -> tuple[ParsedChunk[MhodHeader], ...]:
    if not smart.editable:
        raise ValueError(
            "An unsupported Smart Playlist configuration must remain unchanged."
        )
    validate_smart_playlist(smart)
    prefs_row = next(
        (c for c in existing if isinstance(c.prefix, MhodSmartPrefsPrefix)), None
    )
    rules_row = next(
        (c for c in existing if isinstance(c.payload, MhodSmartRulesPayload)), None
    )
    prefs = prefs_row.prefix if prefs_row else MhodSmartPrefsPrefix()
    assert isinstance(prefs, MhodSmartPrefsPrefix)
    prefs = replace(
        prefs,
        live_update=int(smart.live_update),
        check_rules=int(smart.match_rules),
        match_checked_only=int(smart.checked_only),
        check_limits=int(smart.limit is not None),
    )
    if smart.limit:
        limit = smart.limit
        if not 0 < limit.value <= 0xFFFFFFFF:
            raise ValueError("Smart Playlist limit must be a positive 32-bit value.")
        prefs = replace(
            prefs,
            limit_type={v: k for k, v in LIMIT_UNITS.items()}[limit.unit],
            limit_sort={v: k for k, v in LIMIT_SORTS.items()}[limit.sort],
            limit_value=limit.value,
            reverse_sort=int((limit.sort in DESCENDING_SORTS) != limit.descending),
        )
    prefix = (
        rules_row.prefix
        if rules_row
        else MhodSmartRulesPrefix(magic=b"SLst", unk_0x1C=0x10001)
    )
    payload = rules_row.payload if rules_row else MhodSmartRulesPayload((), b"")
    assert isinstance(prefix, MhodSmartRulesPrefix) and isinstance(
        payload, MhodSmartRulesPayload
    )
    encoded = _encode_rules(
        smart.rules.rules,
        payload.rules,
        timezone_offset,
        playlist_ids=playlist_ids,
    )
    prefix = replace(prefix, conjunction=int(smart.rules.match is SmartMatch.ANY))
    payload = replace(payload, rules=encoded)
    return (
        replace(prefs_row, prefix=prefs)
        if prefs_row
        else new_itunes_chunk(
            MHOD,
            MhodHeader(mhod_type=MhodType.SMART_PLAYLIST_PREFERENCES),
            prefix=prefs,
            payload=MhodSmartPrefsPayload(),
        ),
        replace(rules_row, prefix=prefix, payload=payload)
        if rules_row
        else new_itunes_chunk(
            MHOD,
            MhodHeader(mhod_type=MhodType.SMART_PLAYLIST_RULES),
            prefix=prefix,
            payload=payload,
        ),
    )
