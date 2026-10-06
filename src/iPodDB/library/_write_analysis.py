"""Aggregate semantic validation without modifying the retained source."""

from iPodDB.device_time import TimeConversion
from iPodDB.library._field_policy import (
    changed_fields,
    needs_media,
    unclassified_fields,
)
from iPodDB.library._photo_analysis import analyze_photos
from iPodDB.library._smart_writing import smart_chunks
from iPodDB.library._track_writing import validate_track
from iPodDB.library.models import LibrarySnapshot
from iPodDB.library.playlists import PlaylistKind
from iPodDB.library.smart_rules import smart_playlist_references
from iPodDB.library.writing import (
    LibraryChange,
    LibraryDraft,
    LibraryWritePlan,
    WriteChecksum,
    WriteIssue,
    WriteTarget,
)


def analyze(
    source_revision: str,
    original: LibrarySnapshot,
    draft: LibraryDraft,
    target: WriteTarget,
    timezone_offset: TimeConversion = 0,
) -> LibraryWritePlan:
    issues: list[WriteIssue] = []
    changes: list[LibraryChange] = []
    media: list[int] = []
    artwork: list[int] = []
    old_tracks = {t.track_id: t for t in original.tracks}
    tracks = {t.track_id: t for t in draft.snapshot.tracks}
    replacements: set[int] = set()
    retagged: set[int] = set()
    for track_id in draft.retag_tracks:
        if (
            track_id in retagged
            or track_id not in old_tracks
            or track_id not in tracks
            or track_id in draft.replace_media
            or old_tracks[track_id].metadata.location
            != tracks[track_id].metadata.location
        ):
            issues.append(
                WriteIssue(
                    "draft.invalid_retag",
                    "Tag rewrites require one retained Track at its existing location.",
                    subject="track",
                    record_id=track_id,
                    field="retag_tracks",
                )
            )
        else:
            changes.append(
                LibraryChange(
                    "media",
                    track_id,
                    "retag",
                    tracks[track_id].title,
                )
            )
        retagged.add(track_id)
    for track_id in draft.replace_media:
        if track_id in replacements:
            issues.append(
                WriteIssue(
                    "draft.duplicate_media_replacement",
                    "Request media replacement only once per Track.",
                    subject="track",
                    record_id=track_id,
                    field="replace_media",
                )
            )
        elif track_id not in old_tracks or track_id not in tracks:
            issues.append(
                WriteIssue(
                    "draft.invalid_media_replacement",
                    "Media replacement requires an existing source Track retained in the desired Library.",
                    subject="track",
                    record_id=track_id,
                    field="replace_media",
                )
            )
        else:
            changes.append(
                LibraryChange("media", track_id, "replace", tracks[track_id].title)
            )
        replacements.add(track_id)
    issues.extend(
        WriteIssue(
            "draft.unclassified_field",
            "This Library field has no editing policy; preparation is disabled until its ownership is defined.",
            field=path,
        )
        for path in unclassified_fields()
    )
    if draft.source_revision != source_revision:
        issues.append(
            WriteIssue(
                "draft.wrong_source",
                "These changes belong to another loaded Library. Reload its original source.",
            )
        )
    for subject, before, after in (
        ("track", original.tracks, draft.snapshot.tracks),
        ("playlist", original.playlists, draft.snapshot.playlists),
    ):
        identity = subject + "_id"
        previous = {getattr(item, identity): item for item in before}
        desired = {getattr(item, identity): item for item in after}
        for record_id, deleted_record in previous.items():
            if record_id not in desired:
                changes.append(
                    LibraryChange(
                        subject,
                        record_id,
                        "delete",
                        getattr(
                            deleted_record, "title" if subject == "track" else "name"
                        ),
                    )
                )
                if draft.delete_omissions is not True:
                    issues.append(
                        WriteIssue(
                            "draft.deletion_not_enabled",
                            "This record was removed without deletion being authorized. Restore it or explicitly authorize deletion.",
                            subject=subject,
                            record_id=record_id,
                            detail="Authorize deletion only when these removals are intentional.",
                        )
                    )
        for record_id, new in desired.items():
            old = previous.get(record_id)
            if old == new:
                continue
            changes.append(
                LibraryChange(
                    subject,
                    record_id,
                    "add" if old is None else "edit",
                    getattr(new, "title" if subject == "track" else "name"),
                    changed_fields(old, new),
                )
            )
    if original.device_name != draft.snapshot.device_name:
        changes.append(
            LibraryChange(
                "library", None, "edit", draft.snapshot.device_name, ("device_name",)
            )
        )
        try:
            draft.snapshot.device_name.encode("utf-16-le")
        except UnicodeEncodeError:
            issues.append(
                WriteIssue(
                    "library.invalid_name",
                    "The device name contains invalid Unicode.",
                    field="device_name",
                )
            )
    if tuple(t.track_id for t in original.tracks) != tuple(
        t.track_id for t in draft.snapshot.tracks
    ):
        changes.append(
            LibraryChange("library", None, "edit", "Track order", ("tracks",))
        )
    if tuple(p.playlist_id for p in original.playlists) != tuple(
        p.playlist_id for p in draft.snapshot.playlists
    ):
        changes.append(
            LibraryChange("library", None, "edit", "Playlist order", ("playlists",))
        )
    if changes:
        if len({f.format_id for f in target.cover_formats}) != len(
            target.cover_formats
        ):
            issues.append(
                WriteIssue(
                    "target.duplicate_cover_format",
                    "Cover format identities must have one unambiguous layout.",
                )
            )
        if target.artwork_checksum is not WriteChecksum.NONE:
            issues.append(
                WriteIssue(
                    "target.unsupported_artwork_signature",
                    "The ArtworkDB artifact requires an unsupported signature.",
                )
            )
        if (
            target.checksum in (WriteChecksum.HASH58, WriteChecksum.HASHAB)
            or (
                target.sqlite_database
                and target.sqlite_checksum
                in (WriteChecksum.HASH58, WriteChecksum.HASHAB)
            )
        ) and len(target.firewire_guid) != 8:
            issues.append(
                WriteIssue(
                    "target.missing_guid",
                    "Signed output requires the device's eight-byte FireWire GUID.",
                )
            )
        if (
            target.checksum is WriteChecksum.HASH72
            or (
                target.sqlite_database
                and target.sqlite_checksum is WriteChecksum.HASH72
            )
        ) and target.hash72_material is None:
            issues.append(
                WriteIssue(
                    "target.missing_hash72_material",
                    "HASH72 output requires the selected device's retained IV and random bytes.",
                )
            )
    if target.max_database_bytes <= 0 or target.max_artwork_file_bytes <= 0:
        issues.append(
            WriteIssue("target.invalid_limit", "Output size limits must be positive.")
        )
    for track in draft.snapshot.tracks:
        old_track = old_tracks.get(track.track_id)
        if old_track == track and track.track_id not in replacements:
            continue
        issues.extend(validate_track(old_track, track, timezone_offset))
        if track.track_id in replacements or needs_media(old_track, track):
            media.append(track.track_id)
        if track.artwork_id and (
            old_track is None or old_track.artwork_id != track.artwork_id
        ):
            artwork.append(track.artwork_id)
    playlists = {p.playlist_id: p for p in draft.snapshot.playlists}
    old_playlists = {p.playlist_id: p for p in original.playlists}
    for playlist in draft.snapshot.playlists:
        old_playlist = old_playlists.get(playlist.playlist_id)

        def error(
            code: str, message: str, field: str, record_id: int = playlist.playlist_id
        ) -> None:
            issues.append(
                WriteIssue(
                    code,
                    message,
                    subject="playlist",
                    record_id=record_id,
                    field=field,
                )
            )

        if playlist.parent_id is not None:
            parent = playlists.get(playlist.parent_id)
            if parent is None or parent.kind is not PlaylistKind.FOLDER:
                error(
                    "playlist.invalid_parent",
                    "Choose an existing Playlist Folder as the parent.",
                    "parent_id",
                )
        if (
            playlist.kind is PlaylistKind.FOLDER
            and playlist.entries
            and (old_playlist is None or old_playlist.entries != playlist.entries)
        ):
            error(
                "playlist.folder_membership",
                "Folder Tracks are derived from descendant Playlists.",
                "entries",
            )
        seen: set[str] = set()
        original_entries = (
            {}
            if old_playlist is None
            else {e.entry_id: e for e in old_playlist.entries}
        )
        entries_changed = (
            old_playlist is None or old_playlist.entries != playlist.entries
        )
        for position, entry in enumerate(playlist.entries):
            if not entry.entry_id or entry.entry_id in seen:
                error(
                    "playlist.entry_identity",
                    "Every Playlist Entry needs a unique nonempty identity.",
                    "entries",
                )
            seen.add(entry.entry_id)
            if entry.track_id not in tracks:
                error(
                    "playlist.missing_track",
                    f"Playlist references missing Track {entry.track_id}; remove that entry or restore the Track.",
                    "entries",
                )
            prior = original_entries.get(entry.entry_id)
            if prior and prior.track_id != entry.track_id:
                error(
                    "playlist.entry_reassigned",
                    "Create a new entry when replacing a Track occurrence.",
                    "entries",
                )
            # Moving/removing source-bound occurrences retains their private
            # metadata, including Podcast native row IDs. The writer derives
            # final positions. Only a newly supplied conflicting value is invalid.
            if (
                entries_changed
                and entry.position not in (None, position)
                and (prior is None or entry.position != prior.position)
            ):
                error(
                    "playlist.invalid_position",
                    "A supplied Playlist position must match its resulting order or retain that occurrence's source position.",
                    "entries",
                )
        if old_playlist != playlist:
            try:
                playlist.name.encode("utf-16-le")
                playlist.description.encode("utf-16-le")
                if not playlist.name.strip():
                    error("playlist.empty_name", "Give the Playlist a name.", "name")
                if (playlist.kind is PlaylistKind.SMART) != (
                    playlist.smart is not None
                ):
                    error(
                        "playlist.smart_kind",
                        "Only Smart Playlists must contain Smart Playlist rules.",
                        "smart",
                    )
                if playlist.smart is not None and (
                    old_playlist is None or old_playlist.smart != playlist.smart
                ):
                    if (
                        old_playlist
                        and old_playlist.smart
                        and not old_playlist.smart.editable
                    ):
                        error(
                            "playlist.unsupported_rules",
                            "The original unsupported Smart Playlist rules must remain unchanged.",
                            "smart",
                        )
                    else:
                        references = smart_playlist_references(playlist.smart)
                        for reference in references:
                            if reference not in playlists:
                                error(
                                    "playlist.missing_rule_reference",
                                    f"Smart Playlist rule references missing Playlist {reference}.",
                                    "smart",
                                )
                            elif reference == playlist.playlist_id:
                                error(
                                    "playlist.self_rule_reference",
                                    "A Smart Playlist cannot use its own saved membership as a rule.",
                                    "smart",
                                )
                        smart_chunks(
                            playlist.smart,
                            (),
                            timezone_offset,
                            playlist_ids=dict.fromkeys(
                                playlists.keys() | references, 1
                            ),
                        )
            except (ValueError, OverflowError, RecursionError) as exc:
                error(
                    "playlist.invalid_rules_or_text",
                    str(exc),
                    "smart" if playlist.smart else "name",
                )
    visited: set[int] = set()
    for start in playlists:
        path: set[int] = set()
        current: int | None = start
        while current is not None and current in playlists and current not in visited:
            if current in path:
                issues.append(
                    WriteIssue(
                        "playlist.folder_cycle",
                        "Playlist Folders cannot contain a cycle.",
                        subject="playlist",
                        record_id=current,
                        field="parent_id",
                    )
                )
                break
            path.add(current)
            current = playlists[current].parent_id
        visited.update(path)
    structural_tracks = tuple(old_tracks) != tuple(tracks)
    artwork_changed = any(
        t.artwork_id != old_tracks[t.track_id].artwork_id
        for t in draft.snapshot.tracks
        if t.track_id in old_tracks
    )
    photo_changes, photo_issues = analyze_photos(
        original.photos,
        draft.snapshot.photos,
        delete_omissions=draft.delete_omissions,
        tracks=draft.snapshot.tracks,
        target=target,
        replace_photos=draft.replace_photos,
        device_time=timezone_offset,
    )
    changes.extend(photo_changes)
    issues.extend(photo_issues)
    media_ids = frozenset(media)
    original_photo_ids = {
        item.photo_id
        for item in (() if original.photos is None else original.photos.photos)
    }
    return LibraryWritePlan(
        draft,
        target,
        tuple(changes),
        tuple(issues),
        tuple(media),
        tuple(dict.fromkeys(artwork)),
        bool(artwork) or artwork_changed,
        structural_tracks,
        required_photos=tuple(
            photo.photo_id
            for photo in (
                () if draft.snapshot.photos is None else draft.snapshot.photos.photos
            )
            if photo.photo_id in draft.replace_photos
            or photo.photo_id not in original_photo_ids
        ),
        required_lyrics=tuple(
            track.track_id
            for track in draft.snapshot.tracks
            if (
                track.metadata.lyrics
                != (
                    old_tracks[track.track_id].metadata.lyrics
                    if track.track_id in old_tracks
                    else ""
                )
                or (track.track_id in media_ids and bool(track.metadata.lyrics))
                or track.track_id in retagged
            )
        ),
    )
