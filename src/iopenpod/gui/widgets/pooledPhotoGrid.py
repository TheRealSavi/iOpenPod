"""Compatibility exports for the shared pooled grid."""

from collections.abc import Hashable

from PyQt6.QtGui import QPixmap

from .gridItem import GridItemModel
from .pooledGrid import PooledGridView


class PhotoTileModel(GridItemModel):
    """Legacy constructor that maps ``pixmap`` onto shared ``image``."""

    def __init__(
        self,
        key: Hashable,
        title: str,
        pixmap: QPixmap | None = None,
        checked: bool = False,
        dominant_color: tuple[int, int, int] | None = None,
    ) -> None:
        super().__init__(
            key=key,
            title=title,
            image=pixmap,
            checked=checked,
            dominant_color=dominant_color,
            placeholder_glyph="photo",
        )


PooledPhotoGridView = PooledGridView

__all__ = [
    "GridItemModel",
    "PhotoTileModel",
    "PooledGridView",
    "PooledPhotoGridView",
]
