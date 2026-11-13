"""Proportionate Qt row updates for stable-key aggregate projections."""

from collections.abc import Callable, Iterable
from itertools import groupby

from PySide6.QtCore import QAbstractListModel, QModelIndex

_ROOT_INDEX = QModelIndex()


def contiguous_row_ranges(rows: Iterable[int]) -> tuple[tuple[int, int], ...]:
    """Group affected model rows into contiguous Qt notification ranges."""
    ranges: list[tuple[int, int]] = []
    for _, group in groupby(
        enumerate(sorted(rows)), key=lambda pair: pair[1] - pair[0]
    ):
        group_rows = tuple(row for _, row in group)
        ranges.append((group_rows[0], group_rows[-1]))
    return tuple(ranges)


def reconcile_keyed_rows[Row](
    model: QAbstractListModel,
    current: tuple[Row, ...],
    replacement: tuple[Row, ...],
    *,
    key: Callable[[Row], str],
    commit: Callable[[tuple[Row, ...]], None],
) -> None:
    """Apply inserts, removals, moves, and changes without a blanket reset."""

    if current == replacement:
        return
    if not current:
        if replacement:
            model.beginInsertRows(_ROOT_INDEX, 0, len(replacement) - 1)
            commit(replacement)
            model.endInsertRows()
        return
    if not replacement:
        model.beginRemoveRows(_ROOT_INDEX, 0, len(current) - 1)
        commit(())
        model.endRemoveRows()
        return

    old_by_key = {key(item): item for item in current}
    replacement_keys = {key(item) for item in replacement}
    rows = list(current)

    for row in range(len(rows) - 1, -1, -1):
        if key(rows[row]) in replacement_keys:
            continue
        model.beginRemoveRows(_ROOT_INDEX, row, row)
        rows.pop(row)
        commit(tuple(rows))
        model.endRemoveRows()

    for target, replacement_item in enumerate(replacement):
        replacement_key = key(replacement_item)
        if target < len(rows) and key(rows[target]) == replacement_key:
            continue
        source = next(
            (
                row
                for row in range(target + 1, len(rows))
                if key(rows[row]) == replacement_key
            ),
            None,
        )
        if source is None:
            model.beginInsertRows(_ROOT_INDEX, target, target)
            rows.insert(target, replacement_item)
            commit(tuple(rows))
            model.endInsertRows()
            continue
        if not model.beginMoveRows(
            _ROOT_INDEX,
            source,
            source,
            _ROOT_INDEX,
            target,
        ):
            raise RuntimeError("Qt rejected a valid keyed projection row move")
        rows.insert(target, rows.pop(source))
        commit(tuple(rows))
        model.endMoveRows()

    commit(replacement)
    changed_rows = tuple(
        row
        for row, item in enumerate(replacement)
        if key(item) in old_by_key and old_by_key[key(item)] != item
    )
    _emit_changed_rows(model, changed_rows)


def _emit_changed_rows(
    model: QAbstractListModel,
    rows: tuple[int, ...],
) -> None:
    for start, end in contiguous_row_ranges(rows):
        model.dataChanged.emit(model.index(start, 0), model.index(end, 0), [])


__all__ = ["contiguous_row_ranges", "reconcile_keyed_rows"]
