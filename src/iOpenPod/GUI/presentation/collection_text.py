"""User-facing summary text shared by collection presentations."""

from typing import cast

from PySide6.QtCore import QT_TRANSLATE_NOOP, QCoreApplication

from iOpenPod.app.models.collection_list_model import (
    CollectionKind,
    CollectionSummary,
)

_CONTEXT = "CollectionPresentation"
_ONE_ALBUM_SOURCE = cast(
    "str",
    QT_TRANSLATE_NOOP("CollectionPresentation", "1 album"),
)
_ALBUMS_SOURCE = cast(
    "str",
    QT_TRANSLATE_NOOP("CollectionPresentation", "%n albums"),
)
_ONE_TRACK_SOURCE = cast(
    "str",
    QT_TRANSLATE_NOOP("CollectionPresentation", "1 track"),
)
_TRACKS_SOURCE = cast(
    "str",
    QT_TRANSLATE_NOOP("CollectionPresentation", "%n tracks"),
)
_ONE_ITEM_SOURCE = cast(
    "str",
    QT_TRANSLATE_NOOP("CollectionPresentation", "1 item"),
)
_ITEMS_SOURCE = cast(
    "str",
    QT_TRANSLATE_NOOP("CollectionPresentation", "%n items"),
)


def collection_summary_text(summary: CollectionSummary) -> str:
    """Describe the useful scale of one collection without generic "items"."""

    if summary.kind in {CollectionKind.ARTIST, CollectionKind.GENRE}:
        return " · ".join(
            (
                _count_text(summary.item_count, _ONE_ALBUM_SOURCE, _ALBUMS_SOURCE),
                _count_text(summary.track_count, _ONE_TRACK_SOURCE, _TRACKS_SOURCE),
            )
        )
    return _count_text(summary.item_count, _ONE_ITEM_SOURCE, _ITEMS_SOURCE)


def _count_text(value: int, singular: str, plural: str) -> str:
    count = max(0, value)
    source = singular if count == 1 else plural
    return QCoreApplication.translate(_CONTEXT, source, None, count)


__all__ = ["collection_summary_text"]
