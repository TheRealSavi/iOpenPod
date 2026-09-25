"""Pooled grid specialization for photo selection."""

from collections.abc import Hashable

from PyQt6.QtGui import QPixmap

from .gridItem import GridItemModel
from .pooledGrid import SectionedPooledGridView


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


class PooledPhotoGridView(SectionedPooledGridView):
    """A virtualized photo grid that can separate selected records."""

    def __init__(self, **kwargs) -> None:
        super().__init__(
            section_titles=("Selected", "Unselected"),
            section_header_object_names={
                "Selected": "selectedPhotoSectionHeader",
                "Unselected": "unselectedPhotoSectionHeader",
            },
            **kwargs,
        )

    def setGroupBySelected(self, enabled: bool) -> None:
        """Enable or disable selected/unselected photo sections."""

        self.setSectionGroupingEnabled(enabled)

    def isGroupedBySelected(self) -> bool:
        """Return whether selected and unselected photo sections are visible."""

        return self.isSectionGroupingEnabled()

    def _section_title_for_record(self, record: object) -> str:
        if isinstance(record, GridItemModel) and record.checked:
            return "Selected"
        return "Unselected"


__all__ = [
    "GridItemModel",
    "PhotoTileModel",
    "PooledPhotoGridView",
]
