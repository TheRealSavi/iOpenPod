"""Preserve or explicitly repair supplemental firmware video descriptors."""

from __future__ import annotations

import sqlite3
from contextlib import closing, suppress
from typing import TYPE_CHECKING

from iPodDB.library.video import SubtitleSelection, is_video_track

if TYPE_CHECKING:
    from collections.abc import Mapping

    from iPodDB.library.models import LibrarySnapshot
    from iPodDB.library.video import VideoPlaybackMetadata
    from iPodDB.SQLiteDB.inputs import SQLiteSource

_COLUMNS = (
    "has_subtitles,has_closed_captions,characteristics_valid,"
    "subtitle_language,subtitle_track_index,subtitle_track_id"
)


def video_metadata_required(
    snapshot: LibrarySnapshot, sources: tuple[SQLiteSource, ...]
) -> frozenset[int]:
    """Find incomplete descriptors; never infer absence from missing metadata."""
    videos = tuple(t for t in snapshot.tracks if is_video_track(t))
    if not videos:
        return frozenset()
    source = next((s for s in sources if s.name == "Library.itdb"), None)
    rows = {} if source is None else _retained_rows(source.data)
    return frozenset(
        t.track_id
        for t in videos
        if not _complete(
            rows.get(_signed(t.ipod.db_track_id if t.ipod else t.track_id))
        )
    )


def _retained_rows(data: bytes) -> dict[int, tuple[object, ...]]:
    try:
        with closing(sqlite3.connect(":memory:")) as connection:
            connection.deserialize(data)
            connection.setconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_TRIGGER, False)
            connection.execute("PRAGMA trusted_schema=OFF")
            connection.execute("PRAGMA query_only=ON")
            # Full retention validation still rejects corrupt/unsafe sources
            # before publication. Older absent columns need repair.
            with suppress(sqlite3.DatabaseError):
                return {
                    row[0]: tuple(row[1:])
                    for row in connection.execute(
                        f"SELECT item_pid,{_COLUMNS} FROM video_info"
                    )
                }
        return {}
    except sqlite3.DatabaseError as error:
        raise ValueError("SQLite Library generation failed") from error


def _signed(value: int) -> int:
    return value - (1 << 64) if value >= 1 << 63 else value


def _complete(row: tuple[object, ...] | None) -> bool:
    if row is None:
        return False
    subtitles, captions, valid, language, index, identity = row
    if subtitles not in (0, 1) or captions not in (0, 1) or valid != 1:
        return False
    if subtitles == 0:
        return True
    if not all(type(value) is int for value in (language, index, identity)):
        return False
    assert (
        isinstance(identity, int)
        and isinstance(index, int)
        and isinstance(language, int)
    )
    try:
        SubtitleSelection(identity, index, language)
    except ValueError:
        return False
    return True


def apply_video_metadata(
    connection: sqlite3.Connection,
    values: Mapping[int, VideoPlaybackMetadata],
    pids: Mapping[int, int],
) -> None:
    """Apply checked observations after retention, preserving all unrelated fields."""
    for identity, metadata in values.items():
        selection = metadata.subtitle
        row = (
            int(selection is not None),
            int(metadata.has_closed_captions),
            1,
            selection.language if selection else None,
            selection.track_index if selection else None,
            selection.track_id if selection else None,
        )
        pid = _signed(pids[identity])
        connection.execute(
            "UPDATE video_info SET has_subtitles=?,has_closed_captions=?,"
            "characteristics_valid=?,subtitle_language=?,subtitle_track_index=?,"
            "subtitle_track_id=? WHERE item_pid=?",
            (*row, pid),
        )
        actual = connection.execute(
            f"SELECT {_COLUMNS} FROM video_info WHERE item_pid=?", (pid,)
        ).fetchall()
        if actual != [row]:
            raise ValueError(
                "SQLite video playback metadata did not survive projection"
            )
