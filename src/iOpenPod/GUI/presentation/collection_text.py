"""User-facing summary text shared by collection presentations."""

from iOpenPod.app.models.collection_list_model import (
    CollectionKind,
    CollectionSummary,
)
from iOpenPod.GUI.presentation.i18n.text import (
    album_count_text,
    item_count_text,
    track_count_text,
)


def collection_summary_text(summary: CollectionSummary) -> str:
    """Describe the useful scale of one collection without generic "items"."""

    if summary.kind in {CollectionKind.ARTIST, CollectionKind.GENRE}:
        return " · ".join(
            (
                album_count_text(summary.item_count),
                track_count_text(summary.track_count),
            )
        )
    return item_count_text(summary.item_count)


__all__ = ["collection_summary_text"]
