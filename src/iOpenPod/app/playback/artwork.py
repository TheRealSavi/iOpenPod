"""Host playback selection over retained Artwork Display Times."""

from bisect import bisect_right


def playback_artwork_times(display_times: tuple[int, ...]) -> tuple[int, ...]:
    """Keep ordered ordinary time keys; the retained sentinel has no schedule."""

    return tuple(sorted({time for time in display_times if 0 <= time < 0xFFFFFFFF}))


def artwork_time_at(display_times: tuple[int, ...], position_ms: int) -> int | None:
    """Select the latest reached key from an ordered Host playback timeline."""

    index = bisect_right(display_times, position_ms) - 1
    return display_times[index] if index >= 0 else None
