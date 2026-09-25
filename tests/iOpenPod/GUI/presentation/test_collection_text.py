"""Presentation text for Artist and Genre collection browsing."""

import pytest

from iOpenPod.app.models.collection_list_model import (
    CollectionKind,
    CollectionSummary,
)
from iOpenPod.GUI.presentation.collection_text import collection_summary_text


@pytest.mark.parametrize("kind", [CollectionKind.ARTIST, CollectionKind.GENRE])
def test_artist_and_genre_summaries_name_albums_and_tracks(
    kind: CollectionKind,
) -> None:
    summary = CollectionSummary(
        kind=kind,
        key="collection",
        title="Collection",
        track_count=12,
        item_count=3,
        duration_ms=1,
        artwork_ids=(0, 0, 0, 0),
        artwork_seed=1,
    )

    assert collection_summary_text(summary) == "3 albums · 12 tracks"


def test_collection_summary_uses_singular_labels() -> None:
    summary = CollectionSummary(
        kind=CollectionKind.ARTIST,
        key="solo",
        title="Solo",
        track_count=1,
        item_count=1,
        duration_ms=1,
        artwork_ids=(0, 0, 0, 0),
        artwork_seed=1,
    )

    assert collection_summary_text(summary) == "1 album · 1 track"
