"""Translate understood smart conditions without exposing binary format codes."""

from dataclasses import replace

from iPodDB.device_time import TimeConversion, mac_to_unix
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.smart_prefs_mhod import (
    MhodSmartPrefsPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.smart_rules_mhod import (
    MhodSmartNumericRuleData,
    MhodSmartRule,
    MhodSmartRuleGroupData,
    MhodSmartRulesPayload,
    MhodSmartRulesPrefix,
    MhodSmartStringRuleData,
)
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.library.playlists import (
    SmartField,
    SmartLimitSort,
    SmartLimitUnit,
    SmartLocation,
    SmartMatch,
    SmartMediaKind,
    SmartOperator,
    SmartPlaylist,
    SmartPlaylistLimit,
    SmartPlaylistReference,
    SmartRule,
    SmartRuleGroup,
    UnsupportedSmartRule,
)
from iPodDB.library.smart_rules import (
    BOOLEAN_FIELDS,
    CHOICE_FIELDS,
    DATE_FIELDS,
    PLAYLIST_FIELDS,
    TEXT_FIELDS,
    validate_smart_playlist,
)
from iPodDB.shared.chunk import ParsedChunk

FIELDS = {
    0x02: SmartField.TITLE,
    0x03: SmartField.ALBUM,
    0x04: SmartField.ARTIST,
    0x07: SmartField.YEAR,
    0x08: SmartField.GENRE,
    0x16: SmartField.PLAY_COUNT,
    0x19: SmartField.RATING,
    0x05: SmartField.BITRATE,
    0x06: SmartField.SAMPLE_RATE,
    0x09: SmartField.FILE_FORMAT,
    0x0A: SmartField.DATE_MODIFIED,
    0x0B: SmartField.TRACK_NUMBER,
    0x0C: SmartField.SIZE,
    0x0D: SmartField.DURATION,
    0x0E: SmartField.COMMENT,
    0x10: SmartField.DATE_ADDED,
    0x12: SmartField.COMPOSER,
    0x17: SmartField.LAST_PLAYED,
    0x18: SmartField.DISC_NUMBER,
    0x1D: SmartField.CHECKED,
    0x1F: SmartField.COMPILATION,
    0x23: SmartField.BPM,
    0x25: SmartField.ARTWORK,
    0x27: SmartField.GROUPING,
    0x36: SmartField.DESCRIPTION,
    0x37: SmartField.CATEGORY,
    0x44: SmartField.SKIP_COUNT,
    0x45: SmartField.LAST_SKIPPED,
    0x47: SmartField.ALBUM_ARTIST,
    0x4E: SmartField.SORT_TITLE,
    0x4F: SmartField.SORT_ALBUM,
    0x50: SmartField.SORT_ARTIST,
    0x51: SmartField.SORT_ALBUM_ARTIST,
    0x52: SmartField.SORT_COMPOSER,
    0x53: SmartField.SORT_SHOW,
    0x28: SmartField.PLAYLIST,
    0x29: SmartField.PURCHASED,
    0x3C: SmartField.MEDIA_KIND,
    0x85: SmartField.LOCATION,
}
STRING_ACTIONS = {
    0x01000001: SmartOperator.IS,
    0x03000001: SmartOperator.IS_NOT,
    0x01000002: SmartOperator.CONTAINS,
    0x03000002: SmartOperator.NOT_CONTAINS,
    0x01000004: SmartOperator.BEGINS_WITH,
    0x01000008: SmartOperator.ENDS_WITH,
}
NUMERIC_ACTIONS = {
    0x00000001: SmartOperator.IS,
    0x02000001: SmartOperator.IS_NOT,
    0x00000010: SmartOperator.GREATER_THAN,
    0x00000040: SmartOperator.LESS_THAN,
    0x00000100: SmartOperator.BETWEEN,
}
LIMIT_UNITS = {
    1: SmartLimitUnit.MINUTES,
    2: SmartLimitUnit.MEGABYTES,
    3: SmartLimitUnit.TRACKS,
    4: SmartLimitUnit.HOURS,
    5: SmartLimitUnit.GIGABYTES,
}
LIMIT_SORTS = {
    2: SmartLimitSort.RANDOM,
    3: SmartLimitSort.TITLE,
    4: SmartLimitSort.ALBUM,
    5: SmartLimitSort.ARTIST,
    7: SmartLimitSort.GENRE,
    16: SmartLimitSort.DATE_ADDED,
    20: SmartLimitSort.PLAY_COUNT,
    21: SmartLimitSort.LAST_PLAYED,
    23: SmartLimitSort.RATING,
}
DESCENDING_SORTS = {
    SmartLimitSort.DATE_ADDED,
    SmartLimitSort.PLAY_COUNT,
    SmartLimitSort.LAST_PLAYED,
    SmartLimitSort.RATING,
}
RELATIVE_ACTIONS = {
    0x00000200: SmartOperator.IN_LAST,
    0x02000200: SmartOperator.NOT_IN_LAST,
}
CHOICE_ACTIONS = {
    0x00000001: SmartOperator.IS,
    0x02000001: SmartOperator.IS_NOT,
}
LOCATION_ACTIONS = {
    0x00000400: SmartOperator.IS,
    0x02000400: SmartOperator.IS_NOT,
}
MEDIA_KIND_VALUES = {
    0x00000001: SmartMediaKind.MUSIC,
    0x00000020: SmartMediaKind.MUSIC_VIDEO,
    0x00000002: SmartMediaKind.MOVIE,
    0x00000040: SmartMediaKind.TV_SHOW,
    0x00000004: SmartMediaKind.PODCAST,
    0x00000008: SmartMediaKind.AUDIOBOOK,
    0x00100000: SmartMediaKind.VOICE_MEMO,
    0x00010000: SmartMediaKind.ITUNES_EXTRA,
}
LOCATION_VALUES = {1: SmartLocation.LOCAL, 2: SmartLocation.CLOUD}
DATE_IDENTIFIER = 0x2DAE2DAE2DAE2DAE


def project_rule(
    rule: MhodSmartRule,
    timezone_offset: TimeConversion = 0,
) -> SmartRule | SmartRuleGroup | UnsupportedSmartRule:
    data = rule.data
    if isinstance(data, MhodSmartRuleGroupData):
        return _project_group(data.conjunction, data.rules, timezone_offset)
    field = FIELDS.get(rule.field_id)
    if field is None:
        return UnsupportedSmartRule()
    if isinstance(data, MhodSmartStringRuleData) and field in TEXT_FIELDS:
        action = STRING_ACTIONS.get(rule.action_id)
        if action is not None:
            return SmartRule(field, action, data.value)
    if isinstance(data, MhodSmartNumericRuleData) and field not in TEXT_FIELDS:
        if field in BOOLEAN_FIELDS:
            if rule.action_id in (1, 0x02000001):
                return SmartRule(
                    field,
                    SmartOperator.IS_TRUE
                    if rule.action_id == 1
                    else SmartOperator.IS_FALSE,
                    0,
                )
            return UnsupportedSmartRule()
        if field in PLAYLIST_FIELDS:
            action = CHOICE_ACTIONS.get(rule.action_id)
            if (
                action is not None
                and data.from_value != 0
                and data.from_date == data.to_date == 0
            ):
                return SmartRule(
                    field,
                    action,
                    SmartPlaylistReference(data.from_value),
                )
            return UnsupportedSmartRule()
        if field is SmartField.MEDIA_KIND:
            action = CHOICE_ACTIONS.get(rule.action_id)
            media_value = MEDIA_KIND_VALUES.get(data.from_value)
            if action is not None and media_value is not None:
                return SmartRule(field, action, media_value)
            return UnsupportedSmartRule()
        if field is SmartField.LOCATION:
            action = LOCATION_ACTIONS.get(rule.action_id)
            location_value = LOCATION_VALUES.get(data.from_value)
            if action is not None and location_value is not None:
                return SmartRule(field, action, location_value)
            return UnsupportedSmartRule()
        if field in CHOICE_FIELDS:
            return UnsupportedSmartRule()
        if field in DATE_FIELDS and rule.action_id in RELATIVE_ACTIONS:
            if (
                data.from_value == data.to_value == DATE_IDENTIFIER
                and data.from_date < 0
                and data.from_units > 0
            ):
                return SmartRule(
                    field,
                    RELATIVE_ACTIONS[rule.action_id],
                    -data.from_date * data.from_units,
                )
            return UnsupportedSmartRule()
        action = NUMERIC_ACTIONS.get(rule.action_id)
        if action is not None and data.from_date == data.to_date == 0:
            if field in DATE_FIELDS and data.from_value == 0:
                # Native zero means a missing date, not an absolute instant.
                return UnsupportedSmartRule()
            if field in DATE_FIELDS and (
                action in (SmartOperator.IS, SmartOperator.IS_NOT)
                and data.to_value not in (0, data.from_value)
            ):
                return UnsupportedSmartRule()
            try:
                lower = (
                    mac_to_unix(data.from_value, timezone_offset)
                    if field in DATE_FIELDS
                    else data.from_value
                )
                upper = (
                    (
                        mac_to_unix(data.to_value, timezone_offset)
                        if field in DATE_FIELDS
                        else data.to_value
                    )
                    if action is SmartOperator.BETWEEN
                    else None
                )
            except ValueError:
                return UnsupportedSmartRule()
            return SmartRule(field, action, lower, upper)
    return UnsupportedSmartRule()


def _project_group(
    conjunction: int,
    rules: tuple[MhodSmartRule, ...],
    timezone_offset: TimeConversion = 0,
) -> SmartRuleGroup:
    if conjunction not in (0, 1):
        return SmartRuleGroup(rules=(UnsupportedSmartRule(),))
    return SmartRuleGroup(
        SmartMatch.ALL if conjunction == 0 else SmartMatch.ANY,
        tuple(project_rule(rule, timezone_offset) for rule in rules),
    )


def _supported(group: SmartRuleGroup) -> bool:
    pending = [group]
    while pending:
        for rule in pending.pop().rules:
            if isinstance(rule, UnsupportedSmartRule):
                return False
            if isinstance(rule, SmartRuleGroup):
                pending.append(rule)
    return True


def project_smart(
    metadata: tuple[ParsedChunk[MhodHeader], ...], timezone_offset: TimeConversion = 0
) -> SmartPlaylist:
    """Keep incomplete, unknown, or ambiguous configurations explicitly uneditable."""

    prefs_rows = tuple(
        row
        for row in metadata
        if row.header.mhod_type == MhodType.SMART_PLAYLIST_PREFERENCES
    )
    rules_rows = tuple(
        row for row in metadata if row.header.mhod_type == MhodType.SMART_PLAYLIST_RULES
    )
    rules = SmartRuleGroup(rules=(UnsupportedSmartRule(),))
    prefs = None
    if len(prefs_rows) == 1 and isinstance(prefs_rows[0].prefix, MhodSmartPrefsPrefix):
        prefs = prefs_rows[0].prefix
    if len(rules_rows) == 1:
        prefix, payload = rules_rows[0].prefix, rules_rows[0].payload
        if isinstance(prefix, MhodSmartRulesPrefix) and isinstance(
            payload, MhodSmartRulesPayload
        ):
            rules = _project_group(prefix.conjunction, payload.rules, timezone_offset)
    if prefs is None:
        return SmartPlaylist(rules=rules, editable=False)

    supported_prefs = all(
        flag in (0, 1)
        for flag in (
            prefs.live_update,
            prefs.check_rules,
            prefs.check_limits,
            prefs.match_checked_only,
            prefs.reverse_sort,
        )
    )
    result = SmartPlaylist(
        rules=rules,
        live_update=bool(prefs.live_update),
        match_rules=bool(prefs.check_rules),
        checked_only=bool(prefs.match_checked_only),
        editable=supported_prefs and _supported(rules),
    )
    if not prefs.check_limits:
        return _validated(result)
    unit = LIMIT_UNITS.get(prefs.limit_type)
    sort = LIMIT_SORTS.get(prefs.limit_sort)
    if unit is None or sort is None or prefs.limit_value <= 0:
        return replace(result, editable=False)
    descending = (sort in DESCENDING_SORTS) != bool(prefs.reverse_sort)
    return _validated(
        replace(
            result,
            limit=SmartPlaylistLimit(prefs.limit_value, unit, sort, descending),
        )
    )


def _validated(smart: SmartPlaylist) -> SmartPlaylist:
    try:
        validate_smart_playlist(smart)
    except ValueError:
        return replace(smart, editable=False)
    return smart
