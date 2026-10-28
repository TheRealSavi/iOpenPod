"""Host artwork scheduling without changes to retained device time keys."""

import pytest

from iOpenPod.app.playback.artwork import artwork_time_at, playback_artwork_times


@pytest.mark.parametrize(
    ("position", "expected"),
    [(-1, None), (0, None), (9, None), (10, 10), (11, 10), (49, 10), (50, 50)],
)
def test_artwork_selection_never_uses_a_future_frame(
    position: int, expected: int | None
) -> None:
    assert artwork_time_at((10, 50), position) == expected


def test_playback_timeline_excludes_special_keys_without_retiming() -> None:
    assert playback_artwork_times((0xFFFFFFFF, 50, 1, 0, 50)) == (0, 1, 50)
    assert artwork_time_at((), 0) is None
    assert artwork_time_at(playback_artwork_times((0xFFFFFFFF,)), 0xFFFFFFFF) is None
