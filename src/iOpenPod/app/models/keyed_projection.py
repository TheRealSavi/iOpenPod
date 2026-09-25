"""Proportionate Qt row updates for stable-key aggregate projections."""

from collections.abc import Callable

from PySide6.QtCore import QAbstractListModel, QModelIndex

_ROOT_INDEX = QModelIndex()


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
    if not rows:
        return
    start = end = rows[0]
    for row in rows[1:]:
        if row == end + 1:
            end = row
            continue
        model.dataChanged.emit(model.index(start, 0), model.index(end, 0), [])
        start = end = row
    model.dataChanged.emit(model.index(start, 0), model.index(end, 0), [])


__all__ = ["reconcile_keyed_rows"]
