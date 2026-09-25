"""Pure, deterministic previews of editable Smart Playlist rules."""

from collections.abc import Callable
from random import Random
from time import time

from iPodDB.library import (
    MediaType,
    Playlist,
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
    SmartValueKind,
    Track,
    smart_playlist_references,
    smart_value_kind,
    validate_smart_playlist,
)

_FIELDS: dict[SmartField, Callable[[Track], str | int]] = {
    SmartField.TITLE: lambda track: track.title,
    SmartField.ARTIST: lambda track: track.artist,
    SmartField.ALBUM: lambda track: track.album,
    SmartField.GENRE: lambda track: track.genre,
    SmartField.YEAR: lambda track: track.year,
    SmartField.RATING: lambda track: track.rating,
    SmartField.PLAY_COUNT: lambda track: track.play_count,
    SmartField.BITRATE: lambda t: t.bitrate_kbps,
    SmartField.SAMPLE_RATE: lambda t: t.metadata.sample_rate_hz,
    SmartField.FILE_FORMAT: lambda t: t.metadata.file_format,
    SmartField.TRACK_NUMBER: lambda t: t.track_number,
    SmartField.SIZE: lambda t: t.size_bytes,
    SmartField.DURATION: lambda t: t.length_ms,
    SmartField.COMMENT: lambda t: t.metadata.comment,
    SmartField.COMPOSER: lambda t: t.metadata.composer,
    SmartField.DISC_NUMBER: lambda t: t.metadata.disc_number,
    SmartField.CHECKED: lambda t: t.metadata.checked,
    SmartField.COMPILATION: lambda t: t.metadata.compilation,
    SmartField.ARTWORK: lambda t: t.artwork_id != 0 or t.metadata.artwork_count > 0,
    SmartField.BPM: lambda t: t.metadata.bpm,
    SmartField.GROUPING: lambda t: t.metadata.grouping,
    SmartField.DESCRIPTION: lambda t: t.metadata.description,
    SmartField.CATEGORY: lambda t: t.metadata.category,
    SmartField.SKIP_COUNT: lambda t: t.metadata.skip_count,
    SmartField.ALBUM_ARTIST: lambda t: t.album_artist,
    SmartField.SORT_TITLE: lambda t: t.metadata.sort_title,
    SmartField.SORT_ALBUM: lambda t: t.metadata.sort_album,
    SmartField.SORT_ARTIST: lambda t: t.metadata.sort_artist,
    SmartField.SORT_ALBUM_ARTIST: lambda t: t.metadata.sort_album_artist,
    SmartField.SORT_COMPOSER: lambda t: t.metadata.sort_composer,
    SmartField.SORT_SHOW: lambda t: t.metadata.sort_show,
    SmartField.DATE_MODIFIED: lambda t: t.metadata.last_modified,
    SmartField.DATE_ADDED: lambda t: t.metadata.date_added,
    SmartField.LAST_PLAYED: lambda t: t.metadata.last_played,
    SmartField.LAST_SKIPPED: lambda t: t.metadata.last_skipped,
    SmartField.PURCHASED: lambda t: bool(t.ipod and t.ipod.purchased_aac_flag),
}
_SORT_KEYS: dict[SmartLimitSort, Callable[[Track], str | int]] = {
    SmartLimitSort.TITLE: lambda track: track.title.casefold(),
    SmartLimitSort.ALBUM: lambda track: track.album.casefold(),
    SmartLimitSort.ARTIST: lambda track: track.artist.casefold(),
    SmartLimitSort.GENRE: lambda track: track.genre.casefold(),
    SmartLimitSort.DATE_ADDED: lambda track: track.metadata.date_added,
    SmartLimitSort.PLAY_COUNT: lambda track: track.play_count,
    SmartLimitSort.LAST_PLAYED: lambda track: track.metadata.last_played,
    SmartLimitSort.RATING: lambda track: track.rating,
}


def preview_smart_playlist(
    tracks: tuple[Track, ...],
    smart: SmartPlaylist,
    *,
    playlists: tuple[Playlist, ...] = (),
    now: int | None = None,
) -> tuple[Track, ...]:
    """Evaluate an explicitly created or edited definition, without any source writes.

    Imported playlists use their stored membership until the user edits their
    rules. Random selection uses a fixed seed so reopening a preview is stable.
    """

    validate_smart_playlist(smart)
    memberships = _saved_memberships(playlists)
    missing = smart_playlist_references(smart) - memberships.keys()
    if missing:
        raise ValueError(
            f"Smart Playlist rule references missing Playlist {min(missing)}."
        )
    instant = int(time()) if now is None else now
    selected = [
        track
        for track in tracks
        if (not smart.checked_only or track.metadata.checked)
        and (
            not smart.match_rules
            or not smart.rules.rules
            or _matches_group(track, smart.rules, instant, memberships)
        )
    ]
    limit = smart.limit
    if limit is None:
        return tuple(selected)
    if limit.sort == SmartLimitSort.RANDOM:
        Random(0).shuffle(selected)
    else:
        selected.sort(key=_SORT_KEYS[limit.sort], reverse=limit.descending)
    return _apply_limit(selected, limit)


def _matches_group(
    track: Track,
    group: SmartRuleGroup,
    now: int,
    memberships: dict[int, frozenset[int]],
) -> bool:
    matches = all if group.match is SmartMatch.ALL else any
    return matches(
        _matches_group(track, rule, now, memberships)
        if isinstance(rule, SmartRuleGroup)
        else _matches(track, rule, now, memberships)
        for rule in group.rules
        if isinstance(rule, (SmartRule, SmartRuleGroup))
    )


def _matches(
    track: Track,
    rule: SmartRule,
    now: int,
    memberships: dict[int, frozenset[int]],
) -> bool:
    value = rule.value
    if isinstance(value, SmartPlaylistReference):
        member = track.track_id in memberships[value.playlist_id]
        return member if rule.operator is SmartOperator.IS else not member
    if isinstance(value, SmartMediaKind):
        match = _media_kind(track) is value
        return match if rule.operator is SmartOperator.IS else not match
    if isinstance(value, SmartLocation):
        # The Library Workspace contains locally managed Tracks. This matches the
        # Original evaluator's evidence-backed legacy Location interpretation.
        match = value is SmartLocation.LOCAL
        return match if rule.operator is SmartOperator.IS else not match
    field = _FIELDS[rule.field](track)
    if rule.operator in (SmartOperator.IS_TRUE, SmartOperator.IS_FALSE):
        return bool(field) == (rule.operator is SmartOperator.IS_TRUE)
    if rule.operator in (SmartOperator.IN_LAST, SmartOperator.NOT_IN_LAST):
        assert isinstance(field, int) and isinstance(value, int)
        recent = field != 0 and field > now - value
        return recent if rule.operator is SmartOperator.IN_LAST else not recent
    if smart_value_kind(rule.field) is SmartValueKind.DATE and field == 0:
        # Zero in Track metadata means an absent native timestamp, not Unix epoch.
        return rule.operator in (SmartOperator.IS_NOT, SmartOperator.LESS_THAN)
    if isinstance(field, str) and isinstance(value, str):
        field, value = field.casefold(), value.casefold()
        match rule.operator:
            case SmartOperator.IS:
                return field == value
            case SmartOperator.IS_NOT:
                return field != value
            case SmartOperator.CONTAINS:
                return value in field
            case SmartOperator.NOT_CONTAINS:
                return value not in field
            case SmartOperator.BEGINS_WITH:
                return field.startswith(value)
            case SmartOperator.ENDS_WITH:
                return field.endswith(value)
            case _:
                pass
    elif isinstance(field, int) and isinstance(value, int):
        match rule.operator:
            case SmartOperator.IS:
                return field == value
            case SmartOperator.IS_NOT:
                return field != value
            case SmartOperator.GREATER_THAN:
                return field > value
            case SmartOperator.LESS_THAN:
                return field < value
            case SmartOperator.BETWEEN:
                upper = rule.upper_value
                return isinstance(upper, int) and value <= field <= upper
            case _:
                pass
    raise ValueError("This Smart Playlist comparison is not supported yet.")


def _media_kind(track: Track) -> SmartMediaKind:
    kinds = set(track.media_types)
    if MediaType.ITUNES_EXTRA in kinds:
        return SmartMediaKind.ITUNES_EXTRA
    if MediaType.MEMO in kinds:
        return SmartMediaKind.VOICE_MEMO
    if MediaType.PODCAST in kinds or MediaType.VIDEO_PODCAST in kinds:
        return SmartMediaKind.PODCAST
    if MediaType.AUDIOBOOK in kinds:
        return SmartMediaKind.AUDIOBOOK
    if MediaType.TV_SHOW in kinds:
        return SmartMediaKind.TV_SHOW
    if MediaType.MUSIC_VIDEO in kinds:
        return SmartMediaKind.MUSIC_VIDEO
    if MediaType.VIDEO in kinds:
        return SmartMediaKind.MOVIE
    return SmartMediaKind.MUSIC


def _saved_memberships(
    playlists: tuple[Playlist, ...],
) -> dict[int, frozenset[int]]:
    """Resolve saved membership, including Playlist Folder descendants."""

    by_id = {playlist.playlist_id: playlist for playlist in playlists}
    children: dict[int, list[int]] = {identity: [] for identity in by_id}
    for playlist in playlists:
        if playlist.parent_id in children:
            children[playlist.parent_id].append(playlist.playlist_id)
    memberships: dict[int, frozenset[int]] = {}
    for identity in by_id:
        tracks: set[int] = set()
        pending = [identity]
        visited: set[int] = set()
        while pending:
            current = pending.pop()
            if current in visited:
                continue
            visited.add(current)
            playlist = by_id[current]
            tracks.update(playlist.track_ids)
            pending.extend(children[current])
        memberships[identity] = frozenset(tracks)
    return memberships


def _apply_limit(tracks: list[Track], limit: SmartPlaylistLimit) -> tuple[Track, ...]:
    if limit.unit == SmartLimitUnit.TRACKS:
        return tuple(tracks[: limit.value])
    duration_limit = limit.unit in (SmartLimitUnit.MINUTES, SmartLimitUnit.HOURS)
    if duration_limit:
        factor = 60_000 if limit.unit == SmartLimitUnit.MINUTES else 3_600_000
    else:
        factor = (
            1024 * 1024
            if limit.unit == SmartLimitUnit.MEGABYTES
            else 1024 * 1024 * 1024
        )
    budget = limit.value * factor
    result: list[Track] = []
    for track in tracks:
        cost = max(0, track.length_ms if duration_limit else track.size_bytes)
        if cost <= budget:
            result.append(track)
            budget -= cost
    return tuple(result)
