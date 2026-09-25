"""Report retained projection inconsistencies without treating display repairs as edits."""

from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.library._playlist_datasets import structure_issues
from iPodDB.library.models import LibrarySnapshot
from iPodDB.library.writing import IssueSeverity, WriteIssue
from iPodDB.shared.chunk import DatabaseDocument


def source_warnings(
    document: DatabaseDocument[MhbdHeader], snapshot: LibrarySnapshot
) -> tuple[WriteIssue, ...]:
    issues: list[WriteIssue] = list(structure_issues(document))
    datasets = document.find_chunks(MhsdHeader)
    canonical = next(
        (s for kind in (3, 2) for s in datasets if s.chunk.header.dataset_type == kind),
        None,
    )
    playlists = {p.playlist_id: p for p in snapshot.playlists}
    tracks = {t.track_id for t in snapshot.tracks}
    issues.extend(
        WriteIssue(
            "source.playback_positions",
            "The retained playback positions exceed this Track's duration. Unrelated edits preserve them.",
            IssueSeverity.WARNING,
            "source",
            "track",
            track.track_id,
            "metadata.stop_time_ms",
        )
        for track in snapshot.tracks
        if max(
            track.metadata.start_time_ms,
            track.metadata.stop_time_ms,
            track.metadata.bookmark_time_ms,
        )
        > track.length_ms
    )
    if canonical:
        for selection in canonical.find_chunks(MhypHeader):
            header = selection.chunk.header
            playlist = playlists.get(header.playlist_id)
            if playlist is None:
                continue
            if (header.parent_folder_playlist_id or None) != playlist.parent_id:
                issues.append(
                    WriteIssue(
                        "source.repaired_hierarchy",
                        "The browser hides an invalid folder relationship. Its original bytes are retained unless that relationship is edited.",
                        IssueSeverity.WARNING,
                        "source",
                        "playlist",
                        playlist.playlist_id,
                        "parent_id",
                        offset=selection.chunk.offset,
                    )
                )
            if any(
                not item.chunk.header.podcast_group_flag & 0x100
                and item.chunk.header.track_id not in tracks
                for item in selection.find_chunks(MhipHeader)
            ):
                issues.append(
                    WriteIssue(
                        "source.unresolved_entries",
                        "This Playlist has missing Track references hidden by the browser. Unaffected references will be retained.",
                        IssueSeverity.WARNING,
                        "source",
                        "playlist",
                        playlist.playlist_id,
                        "entries",
                        offset=selection.chunk.offset,
                    )
                )
    if not -86400 < document.header.timezone_offset < 86400:
        issues.append(
            WriteIssue(
                "source.invalid_timezone",
                "The source timezone is invalid; unchanged date bytes will be retained.",
                IssueSeverity.WARNING,
                "source",
            )
        )
    return tuple(issues)
