"""Read-only chapter timing shared by Player presentation and transport policy."""

from bisect import bisect_right

from iPodDB.library import Track, TrackChapter


def playback_chapters(track: Track | None) -> tuple[TrackChapter, ...]:
    """Order reachable chapter starts without altering retained Library metadata."""

    if track is None:
        return ()
    by_start: dict[int, TrackChapter] = {}
    for chapter in track.metadata.chapters:
        if 0 <= chapter.start_ms < track.length_ms:
            by_start.setdefault(chapter.start_ms, chapter)
    return tuple(by_start[start] for start in sorted(by_start))


def chapter_at(
    chapters: tuple[TrackChapter, ...], position_ms: int
) -> TrackChapter | None:
    """Find the chapter whose start is at or immediately before this position."""

    index = (
        bisect_right(chapters, position_ms, key=lambda chapter: chapter.start_ms) - 1
    )
    return chapters[index] if index >= 0 else None
