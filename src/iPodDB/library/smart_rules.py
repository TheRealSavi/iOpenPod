"""Semantic Smart Playlist capabilities shared by editors, matching, and writing.

Dates use Unix seconds; relative periods are positive seconds. Boolean conditions
use IS_TRUE/IS_FALSE with value zero. Native field codes remain private.
"""

from enum import StrEnum

from iPodDB.device_time import MAX_LOCAL_UNIX_TIME, MIN_LOCAL_UNIX_TIME
from iPodDB.library.playlists import (
    SmartField,
    SmartLimitSort,
    SmartLimitUnit,
    SmartLocation,
    SmartMatch,
    SmartMediaKind,
    SmartOperator,
    SmartPlaylist,
    SmartPlaylistReference,
    SmartRule,
    SmartRuleGroup,
)


class SmartValueKind(StrEnum):
    TEXT = "text"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATE = "date"
    CHOICE = "choice"
    PLAYLIST = "playlist"


TEXT_FIELDS = frozenset(
    (
        SmartField.TITLE,
        SmartField.ARTIST,
        SmartField.ALBUM,
        SmartField.GENRE,
        SmartField.FILE_FORMAT,
        SmartField.COMMENT,
        SmartField.COMPOSER,
        SmartField.GROUPING,
        SmartField.DESCRIPTION,
        SmartField.CATEGORY,
        SmartField.ALBUM_ARTIST,
        SmartField.SORT_TITLE,
        SmartField.SORT_ALBUM,
        SmartField.SORT_ARTIST,
        SmartField.SORT_ALBUM_ARTIST,
        SmartField.SORT_COMPOSER,
        SmartField.SORT_SHOW,
    )
)
BOOLEAN_FIELDS = frozenset(
    (
        SmartField.CHECKED,
        SmartField.COMPILATION,
        SmartField.ARTWORK,
        SmartField.PURCHASED,
    )
)
CHOICE_FIELDS = frozenset((SmartField.MEDIA_KIND, SmartField.LOCATION))
PLAYLIST_FIELDS = frozenset((SmartField.PLAYLIST,))
DATE_FIELDS = frozenset(
    (
        SmartField.DATE_MODIFIED,
        SmartField.DATE_ADDED,
        SmartField.LAST_PLAYED,
        SmartField.LAST_SKIPPED,
    )
)


def smart_value_kind(field: SmartField) -> SmartValueKind:
    if field not in tuple(SmartField):
        raise ValueError("This Smart Playlist field is not supported.")
    if field in TEXT_FIELDS:
        return SmartValueKind.TEXT
    if field in BOOLEAN_FIELDS:
        return SmartValueKind.BOOLEAN
    if field in CHOICE_FIELDS:
        return SmartValueKind.CHOICE
    if field in PLAYLIST_FIELDS:
        return SmartValueKind.PLAYLIST
    if field in DATE_FIELDS:
        return SmartValueKind.DATE
    return SmartValueKind.NUMBER


def smart_operators(field: SmartField) -> tuple[SmartOperator, ...]:
    kind = smart_value_kind(field)
    if kind is SmartValueKind.BOOLEAN:
        return (SmartOperator.IS_TRUE, SmartOperator.IS_FALSE)
    if kind in (SmartValueKind.CHOICE, SmartValueKind.PLAYLIST):
        return (SmartOperator.IS, SmartOperator.IS_NOT)
    common = (SmartOperator.IS, SmartOperator.IS_NOT)
    if kind is SmartValueKind.TEXT:
        return (
            *common,
            SmartOperator.CONTAINS,
            SmartOperator.NOT_CONTAINS,
            SmartOperator.BEGINS_WITH,
            SmartOperator.ENDS_WITH,
        )
    numeric = (
        *common,
        SmartOperator.GREATER_THAN,
        SmartOperator.LESS_THAN,
        SmartOperator.BETWEEN,
    )
    if kind is SmartValueKind.DATE:
        return (*numeric, SmartOperator.IN_LAST, SmartOperator.NOT_IN_LAST)
    return numeric


def validate_smart_playlist(smart: SmartPlaylist) -> None:
    """Reject unsupported, ill-typed, or unrepresentable edits before applying them."""
    if not smart.editable:
        raise ValueError("These Smart Playlist rules are read-only.")
    if any(
        type(value) is not bool
        for value in (
            smart.match_rules,
            smart.live_update,
            smart.checked_only,
            smart.editable,
        )
    ):
        raise ValueError("Smart Playlist preferences must be booleans.")
    pending = [(smart.rules, 0)]
    count = 0
    while pending:
        group, depth = pending.pop()
        if depth > 64:
            raise ValueError("Smart Playlist rule nesting exceeds 64 levels.")
        if group.match not in tuple(SmartMatch):
            raise ValueError("Choose whether all or any rules must match.")
        for rule in group.rules:
            count += 1
            if count > 10_000:
                raise ValueError(
                    "A Smart Playlist cannot exceed 10,000 rules and groups."
                )
            if isinstance(rule, SmartRuleGroup):
                pending.append((rule, depth + 1))
            elif isinstance(rule, SmartRule):
                _validate_rule(rule)
            else:
                raise ValueError("Unsupported Smart Playlist rules are read-only.")
    limit = smart.limit
    if limit is not None:
        if type(limit.value) is not int or not 0 < limit.value <= 0xFFFFFFFF:
            raise ValueError(
                "The limit must be a positive whole number up to 4,294,967,295."
            )
        if limit.unit not in tuple(SmartLimitUnit) or limit.sort not in tuple(
            SmartLimitSort
        ):
            raise ValueError(
                "This Smart Playlist limit or selection order is unsupported."
            )
        if type(limit.descending) is not bool:
            raise ValueError("The selection direction must be a boolean.")


def smart_playlist_references(smart: SmartPlaylist) -> frozenset[int]:
    """Return every Playlist ID referenced by a supported recursive rule tree."""

    references: set[int] = set()
    pending = [smart.rules]
    while pending:
        for rule in pending.pop().rules:
            if isinstance(rule, SmartRuleGroup):
                pending.append(rule)
            elif isinstance(rule, SmartRule) and isinstance(
                rule.value, SmartPlaylistReference
            ):
                references.add(rule.value.playlist_id)
    return frozenset(references)


def _validate_rule(rule: SmartRule) -> None:
    kind = smart_value_kind(rule.field)
    if rule.operator not in smart_operators(rule.field):
        raise ValueError("Choose a supported comparison for this Smart Playlist field.")
    if rule.operator is not SmartOperator.BETWEEN and rule.upper_value is not None:
        raise ValueError("Only a between comparison accepts a second value.")
    if kind is SmartValueKind.TEXT:
        if not isinstance(rule.value, str):
            raise ValueError("Text comparisons require text.")
        rule.value.encode("utf-16-be")
        if "\0" in rule.value:
            raise ValueError("Smart Playlist text cannot contain a null character.")
        return
    if kind is SmartValueKind.CHOICE:
        expected = (
            SmartMediaKind if rule.field is SmartField.MEDIA_KIND else SmartLocation
        )
        if not isinstance(rule.value, expected):
            raise ValueError("Choose a supported value for this Smart Playlist field.")
        return
    if kind is SmartValueKind.PLAYLIST:
        if (
            not isinstance(rule.value, SmartPlaylistReference)
            or type(rule.value.playlist_id) is not int
            or rule.value.playlist_id == 0
        ):
            raise ValueError("Choose a Playlist for this Smart Playlist rule.")
        return
    if type(rule.value) is not int:
        raise ValueError("Choose a numeric comparison and a whole number.")
    if kind is SmartValueKind.BOOLEAN:
        if rule.value != 0:
            raise ValueError("Boolean conditions do not accept a value.")
        return
    relative = rule.operator in (SmartOperator.IN_LAST, SmartOperator.NOT_IN_LAST)
    lower = 1 if relative else MIN_LOCAL_UNIX_TIME if kind is SmartValueKind.DATE else 0
    maximum = (
        0x7FFFFFFFFFFFFFFF
        if relative
        else MAX_LOCAL_UNIX_TIME
        if kind is SmartValueKind.DATE
        else 100
        if rule.field is SmartField.RATING
        else 0xFFFFFFFFFFFFFFFF
    )
    if not lower <= rule.value <= maximum:
        raise ValueError("Smart Playlist value is outside the supported range.")
    if rule.operator is SmartOperator.BETWEEN and (
        type(rule.upper_value) is not int
        or not rule.value <= rule.upper_value <= maximum
    ):
        raise ValueError(
            "The upper value must be in range and at least the lower value."
        )
