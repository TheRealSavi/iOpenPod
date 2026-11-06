"""Resolve edited calendar dates before validation, writing and verification."""

from dataclasses import replace
from typing import TYPE_CHECKING

from iPodDB.device_time import DeviceTimeContext, interpret_mac, unix_to_mac
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.library._field_policy import DATE_FIELDS
from iPodDB.library._track_header_expansion import optional_field_available
from iPodDB.library.models import LibrarySnapshot, Track
from iPodDB.library.playlists import (
    Playlist,
    SmartOperator,
    SmartRule,
    SmartRuleGroup,
    UnsupportedSmartRule,
)
from iPodDB.library.smart_rules import DATE_FIELDS as SMART_DATE_FIELDS
from iPodDB.library.smart_rules import MAX_SMART_NUMERIC_VALUE
from iPodDB.library.writing import IssueSeverity, WriteIssue
from iPodDB.shared.chunk import DatabaseDocument

if TYPE_CHECKING:
    from iPodDB.library.photos import Photo


def resolve_dates(
    original: LibrarySnapshot,
    desired: LibrarySnapshot,
    context: DeviceTimeContext,
    document: DatabaseDocument[MhbdHeader],
    database_version: int | None,
) -> tuple[LibrarySnapshot, tuple[WriteIssue, ...]]:
    """Leave retained values alone; make new date intent representable."""
    issues: list[WriteIssue] = []

    def date(
        value: int,
        subject: str,
        identity: int,
        field: str,
        *,
        utc: bool = False,
        missing_zero: bool = True,
    ) -> int:
        encoded = unix_to_mac(value, context, utc=utc, missing_zero=missing_zero)
        interpreted = interpret_mac(encoded, context, utc=utc)
        if interpreted.value != value or interpreted.detail:
            issues.append(
                WriteIssue(
                    "date.approximated",
                    "The date will use the closest supported iPod representation.",
                    IssueSeverity.WARNING,
                    "resolution",
                    subject,
                    identity,
                    field,
                    detail=interpreted.detail
                    or "The date was bounded to the iPod date range.",
                )
            )
        return interpreted.value

    old_tracks = {track.track_id: track for track in original.tracks}
    native_tracks = {
        s.chunk.header.track_id: s.chunk for s in document.find_chunks(MhitHeader)
    }
    tracks: list[Track] = []
    for track in desired.tracks:
        old = old_tracks.get(track.track_id)
        values: dict[str, int] = {}
        for field, native in DATE_FIELDS.items():
            value = getattr(track.metadata, field)
            if value == (getattr(old.metadata, field) if old else 0):
                continue
            if not optional_field_available(
                native_tracks.get(track.track_id), native, database_version
            ):
                values[field] = getattr(old.metadata, field) if old else 0
                issues.append(
                    WriteIssue(
                        "date.approximated",
                        "This iPod layout cannot store the date; its previous value is retained.",
                        IssueSeverity.WARNING,
                        "resolution",
                        "track",
                        track.track_id,
                        "metadata." + field,
                    )
                )
                continue
            values[field] = date(
                getattr(track.metadata, field),
                "track",
                track.track_id,
                "metadata." + field,
                utc=field == "release_date",
            )
        meta = track.metadata
        tracks.append(
            replace(
                track,
                metadata=replace(
                    meta,
                    last_modified=values.get("last_modified", meta.last_modified),
                    last_played=values.get("last_played", meta.last_played),
                    last_skipped=values.get("last_skipped", meta.last_skipped),
                    date_added=values.get("date_added", meta.date_added),
                    release_date=values.get("release_date", meta.release_date),
                ),
            )
            if values
            else track
        )
    photos = desired.photos
    if photos is not None:
        old_photos = (
            {}
            if original.photos is None
            else {p.photo_id: p for p in original.photos.photos}
        )
        resolved_photos: list[Photo] = []
        for photo in photos.photos:
            old_photo = old_photos.get(photo.photo_id)
            values = {
                field: date(getattr(photo, field), "photo", photo.photo_id, field)
                for field in ("original_date", "taken_date")
                if old_photo is None
                or getattr(photo, field) != getattr(old_photo, field)
            }
            resolved_photos.append(
                replace(
                    photo,
                    original_date=values.get("original_date", photo.original_date),
                    taken_date=values.get("taken_date", photo.taken_date),
                )
                if values
                else photo
            )
        photos = replace(photos, photos=tuple(resolved_photos))

    def rule_dates(
        rule: SmartRule | SmartRuleGroup | UnsupportedSmartRule,
        identity: int,
        depth: int = 0,
    ) -> SmartRule | SmartRuleGroup | UnsupportedSmartRule:
        if depth > 64:
            return rule  # Structural validation owns excessive nesting.
        if isinstance(rule, SmartRuleGroup):
            return replace(
                rule,
                rules=tuple(
                    rule_dates(child, identity, depth + 1) for child in rule.rules
                ),
            )
        if not isinstance(rule, SmartRule) or rule.field not in SMART_DATE_FIELDS:
            return rule
        value = rule.value if type(rule.value) is int else 0
        if rule.operator in (SmartOperator.IN_LAST, SmartOperator.NOT_IN_LAST):
            bounded = min(MAX_SMART_NUMERIC_VALUE, max(1, value))
            if bounded != rule.value:
                issues.append(
                    WriteIssue(
                        "date.approximated",
                        "The relative date period was bounded to the supported range.",
                        IssueSeverity.WARNING,
                        "resolution",
                        "playlist",
                        identity,
                        "smart",
                    )
                )
            return replace(rule, value=bounded)
        value = date(value, "playlist", identity, "smart", missing_zero=False)
        if rule.operator is not SmartOperator.BETWEEN:
            return replace(rule, value=value)
        upper = rule.upper_value if type(rule.upper_value) is int else value
        upper = date(upper, "playlist", identity, "smart", missing_zero=False)
        low, high = sorted(
            (value, upper), key=lambda v: unix_to_mac(v, context, missing_zero=False)
        )
        return replace(rule, value=low, upper_value=high)

    old_playlists = {playlist.playlist_id: playlist for playlist in original.playlists}
    playlists: list[Playlist] = []
    for playlist in desired.playlists:
        old_playlist = old_playlists.get(playlist.playlist_id)
        smart = playlist.smart
        if smart is not None and (old_playlist is None or smart != old_playlist.smart):
            rules = rule_dates(smart.rules, playlist.playlist_id)
            assert isinstance(rules, SmartRuleGroup)
            playlist = replace(playlist, smart=replace(smart, rules=rules))
        playlists.append(playlist)
    return replace(
        desired, tracks=tuple(tracks), photos=photos, playlists=tuple(playlists)
    ), tuple(issues)
