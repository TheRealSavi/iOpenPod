"""Verify the explicit Podcast output contract after serialization and reparse."""

from collections import Counter

from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhia import MhiaHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.contextual_100_mhod import (
    MhodPlaylistPositionPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.library_index_mhod import (
    MhodLibraryIndexPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.library._browse_groups import podcast_groups
from iPodDB.library._group_verification import group_text
from iPodDB.library._playlist_datasets import is_master, playlist_rows
from iPodDB.library._projection import project_tracks
from iPodDB.library.writing import WriteIssue
from iPodDB.shared.chunk import DatabaseDocument


def verify_normalized_podcasts(
    original: DatabaseDocument[MhbdHeader],
    checked: DatabaseDocument[MhbdHeader],
    *,
    sqlite: bool = False,
) -> tuple[WriteIssue, ...]:
    tracks = project_tracks(checked)
    issues: list[WriteIssue] = []

    def fail(detail: str) -> None:
        issues.append(
            WriteIssue(
                "verification.podcast_structure",
                detail,
                phase="verification",
                artifact="iTunesDB",
            )
        )

    try:
        groups = podcast_groups(tracks)
    except ValueError as error:
        fail(str(error))
        return tuple(issues)
    if not groups:
        return ()
    podcast_ids = {track.track_id for members in groups.values() for track in members}
    if not checked.header.db_id_2 or (
        original.header.db_id_2 and checked.header.db_id_2 != original.header.db_id_2
    ):
        fail("Podcast normalization changed or omitted the retained root identity.")
    has_albums = any(
        s.chunk.header.dataset_type == 4 for s in checked.find_chunks(MhsdHeader)
    )
    albums = [s.chunk for s in checked.find_chunks(MhiaHeader)]
    for title, members in groups.items():
        if not has_albums:
            continue
        refs = {t.ipod.album_id for t in members if t.ipod}
        rows = [r for r in albums if r.header.album_id in refs]
        if len(refs) != 1 or 0 in refs or len(rows) != 1:
            fail(f"Podcast show {title!r} does not have one unambiguous album.")
            continue
        row = rows[0]
        owners = {t.ipod.db_track_id for t in members if t.ipod}
        if (
            row.header.content_type_flag != 3
            or row.header.album_track_db_id not in owners
        ):
            fail(
                f"Podcast show {title!r} has an invalid album classification or backlink."
            )
        if group_text(row, MhodType.ALBUM_ITEM_ALBUM) != title:
            fail(f"Podcast show {title!r} has a mismatched album title.")
        feed = next(
            (t.metadata.podcast_rss_url for t in members if t.metadata.podcast_rss_url),
            "",
        )
        if feed and group_text(row, MhodType.ALBUM_ITEM_PODCAST_URL) != feed:
            fail(f"Podcast show {title!r} has a mismatched album feed.")
        owner_ids = {t.track_id for t in members}
        if any(
            t.ipod and t.ipod.album_id in refs and t.track_id not in owner_ids
            for t in tracks
        ):
            fail(f"Podcast show {title!r} shares an album with an unrelated Track.")
        if any(
            r is not row
            and group_text(r, MhodType.ALBUM_ITEM_ALBUM) == title
            and not r.header.album_track_db_id
            and all(
                isinstance(c.header, MhodHeader) and c.header.mhod_type == 200
                for c in r.children
            )
            for r in albums
        ):
            fail(f"Podcast show {title!r} retains a redundant name-only album.")
    seen_groups: set[int] = set()
    special: Counter[int] = Counter()
    for kind, selection in playlist_rows(checked):
        playlist = selection.chunk
        if (
            not sqlite
            and is_master(kind, playlist.header)
            and any(
                isinstance(c.header, MhipHeader) and c.header.track_id in podcast_ids
                for c in playlist.children
            )
            and (
                sum(
                    isinstance(c.prefix, MhodLibraryIndexPrefix)
                    and c.prefix.sort_type == 36
                    for c in playlist.children
                )
                != 1
            )
        ):
            fail("A normalized Podcast library must have one sort-36 index per Master.")
        if (
            kind not in (2, 3)
            or not playlist.header.playlist_kind_flags & 1
            or playlist.header.playlist_kind_flags & 0x100
        ):
            continue
        special[kind] += 1
        if (
            playlist.header.sort_order != 24
            or playlist.header.phase_game_flag & 0x1FF != 0x10B
            or playlist.header.db_id_2 != checked.header.db_id_2
        ):
            fail(
                "A normalized Podcasts Playlist has inconsistent sort, flags or database identity."
            )
        for item in selection.find_chunks(MhipHeader):
            h = item.chunk.header
            if h.podcast_group_flag & 0x100:
                if (
                    not h.group_persistent_id
                    or h.group_persistent_id in seen_groups
                    or not h.unk_mhip_0x12
                ):
                    fail(
                        "A Podcast show is missing unique persistent identity or group metadata."
                    )
                seen_groups.add(h.group_persistent_id)
            elif {
                c.prefix.position
                for c in item.chunk.children
                if isinstance(c.prefix, MhodPlaylistPositionPrefix)
            } != {h.group_id}:
                fail(
                    "A normalized Podcast Episode position differs from its row identity."
                )
        if sqlite:
            by_id = {t.track_id: t for t in tracks}
            dates: dict[str, list[int]] = {}
            for item in selection.find_chunks(MhipHeader):
                track = by_id.get(item.chunk.header.track_id)
                if track is not None:
                    dates.setdefault(track.album, []).append(
                        track.metadata.release_date
                    )
            if any(
                values != sorted(values, key=lambda d: (not d, d))
                for values in dates.values()
            ):
                fail(
                    "SQLite Podcast Episodes must store ascending publication dates per show."
                )
    if not special[3]:
        fail("Podcast normalization omitted the grouped Podcasts Playlist.")
    return tuple(issues)
