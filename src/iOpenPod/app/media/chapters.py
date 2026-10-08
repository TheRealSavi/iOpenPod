"""Translate observed container chapters into chronological Library metadata."""

from __future__ import annotations

from typing import TYPE_CHECKING

from iPodDB.library import TrackChapter

if TYPE_CHECKING:
    from iOpenPod.app.media.models import MediaChapter


def imported_chapters(chapters: tuple[MediaChapter, ...]) -> tuple[TrackChapter, ...]:
    """Container frame order is not playback order; preserve positions and titles.

    Only newly observed chapters use this projection. Explicit Library chapters
    retain their order, and Library validation still checks their duration bounds.
    """
    return tuple(
        TrackChapter(
            next(
                (tag.value for tag in chapter.tags if tag.name.casefold() == "title"),
                "",
            ),
            round(chapter.start_seconds * 1000),
        )
        for chapter in sorted(chapters, key=lambda chapter: chapter.start_seconds)
    )
