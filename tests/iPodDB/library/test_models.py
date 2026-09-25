"""Contract invariants shared by every Library Source."""

import pytest

from iPodDB.library import LibrarySnapshot, Track


def test_snapshot_preserves_source_order_and_accepts_zero_as_a_track_id() -> None:
    tracks = (
        Track(7, "First", "", "", 1),
        Track(0, "Second", "", "", 1),
        Track(2, "Third", "", "", 1),
    )

    assert LibrarySnapshot(tracks).tracks == tracks


@pytest.mark.parametrize("second_title", ("First", "Different media"))
def test_snapshot_rejects_repeated_ids_even_when_metadata_matches(
    second_title: str,
) -> None:
    with pytest.raises(ValueError, match=r"Duplicate Track ID.*7"):
        LibrarySnapshot(
            (
                Track(7, "First", "", "", 1),
                Track(7, second_title, "", "", 1),
            )
        )
