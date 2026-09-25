"""Shared default Track order for Album and collection presentation/actions."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from iPodDB.library import Track


def album_track_sort_key(track: Track) -> tuple[str, int, int, str]:
    """Order Albums by name, then Tracks by disc, Track number, and title."""

    return (
        track.album.casefold(),
        track.metadata.disc_number,
        track.track_number,
        track.title.casefold(),
    )
