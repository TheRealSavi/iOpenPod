"""Complete row filtering with the API provided by the installed Qt version."""

from typing import TYPE_CHECKING, cast

from PySide6.QtCore import QSortFilterProxyModel

if TYPE_CHECKING:
    from collections.abc import Callable


def end_rows_filter_change(model: QSortFilterProxyModel) -> None:
    """Pair beginFilterChange with Qt 6.9 or the newer row-only completion."""
    end_change = cast(
        "Callable[[object], None] | None", getattr(model, "endFilterChange", None)
    )
    if end_change is None:
        model.invalidateRowsFilter()
    else:
        # Direction and endFilterChange were both introduced in Qt 6.10.
        direction = getattr(QSortFilterProxyModel, "Direction", None)
        assert direction is not None
        end_change(direction.Rows)
