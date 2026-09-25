"""Pure helpers for reconciling playlist-folder rows before persistence."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .playlist_kinds import (
    is_playlist_folder,
    is_podcast_playlist,
    playlist_kind_flags,
)


def _row_id(row: Mapping[str, Any]) -> int:
    try:
        return int(row.get("playlist_id", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        return 0


def _parent_id(row: Mapping[str, Any]) -> int:
    try:
        return int(
            row.get(
                "parent_folder_playlist_id",
                row.get("unk0x30_playlist_ref", 0),
            )
            or 0
        )
    except (TypeError, ValueError, OverflowError):
        return 0


def _item_key(item: object) -> tuple[object, ...]:
    if not isinstance(item, Mapping):
        return ("value", repr(item))
    for field in (
        "db_track_id",
        "db_id",
        "track_persistent_id",
        "track_id",
    ):
        value = item.get(field)
        if value not in (None, "", 0, "0"):
            return (field, str(value))
    source_path = item.get("source_path", item.get("_source_path"))
    if source_path:
        return ("source_path", str(source_path).casefold())
    return ("mapping", repr(sorted(item.items(), key=lambda pair: str(pair[0]))))


def _default_folder_prefs() -> dict[str, Any]:
    return {
        "live_update": True,
        "check_rules": True,
        "check_limits": False,
        "limit_type": 3,
        "limit_sort": 2,
        "limit_value": 25,
        "match_checked_only": False,
    }


def _normalize_hierarchy_rows(
    rows: Iterable[Mapping[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    set[int],
    dict[int, list[dict[str, Any]]],
    set[int],
]:
    copied = [dict(row) for row in rows]
    folder_ids = {
        playlist_id
        for row in copied
        if (playlist_id := _row_id(row)) and is_playlist_folder(row)
    }
    for row in copied:
        kind_flags = playlist_kind_flags(row)
        row["playlist_kind_flags"] = kind_flags
        row["podcast_flag"] = kind_flags
        row["is_folder"] = is_playlist_folder(kind_flags)
        row["is_podcast"] = is_podcast_playlist(kind_flags)

        parent_id = _parent_id(row)
        if parent_id not in folder_ids or parent_id == _row_id(row):
            parent_id = 0
        row["parent_folder_playlist_id"] = parent_id
        row["unk0x30_playlist_ref"] = parent_id

    parent_by_folder_id = {
        _row_id(row): _parent_id(row)
        for row in copied
        if _row_id(row) in folder_ids
    }
    cyclic_folder_ids: set[int] = set()
    for start_id in folder_ids:
        path: list[int] = []
        path_index: dict[int, int] = {}
        current_id = start_id
        while current_id in parent_by_folder_id and current_id:
            if current_id in path_index:
                cyclic_folder_ids.update(path[path_index[current_id]:])
                break
            path_index[current_id] = len(path)
            path.append(current_id)
            current_id = parent_by_folder_id[current_id]

    if cyclic_folder_ids:
        for row in copied:
            if _row_id(row) in cyclic_folder_ids:
                row["parent_folder_playlist_id"] = 0
                row["unk0x30_playlist_ref"] = 0

    children: dict[int, list[dict[str, Any]]] = {
        playlist_id: [] for playlist_id in folder_ids
    }
    for row in copied:
        parent_id = _parent_id(row)
        if parent_id in children and parent_id != _row_id(row):
            children[parent_id].append(row)
    return copied, folder_ids, children, cyclic_folder_ids


def _rebuild_folder_contents(
    folder: dict[str, Any],
    child_rows: list[dict[str, Any]],
) -> None:
    child_items: list[Any] = []
    child_item_keys: set[tuple[object, ...]] = set()
    for child in child_rows:
        for item in child.get("items", []) or []:
            key = _item_key(item)
            if key in child_item_keys:
                continue
            child_item_keys.add(key)
            child_items.append(dict(item) if isinstance(item, Mapping) else item)

    items: list[Any] = []
    seen_items: set[tuple[object, ...]] = set()
    for item in folder.get("items", []) or []:
        key = _item_key(item)
        if key not in child_item_keys or key in seen_items:
            continue
        seen_items.add(key)
        items.append(dict(item) if isinstance(item, Mapping) else item)
    for item in child_items:
        key = _item_key(item)
        if key in seen_items:
            continue
        seen_items.add(key)
        items.append(item)
    folder["items"] = items
    folder["mhip_child_count"] = len(items)

    prefs = _default_folder_prefs()
    existing_prefs = folder.get("smart_playlist_data")
    if isinstance(existing_prefs, Mapping):
        prefs.update(existing_prefs)
    folder["smart_playlist_data"] = prefs
    folder["smart_playlist_rules"] = {
        "conjunction": "OR",
        "unk004": 0x00010001,
        "rules": [
            {
                "field_id": 0x28,
                "action_id": 1,
                "from_value": child_id,
                "from_units": 1,
                "to_value": child_id,
                "to_units": 1,
            }
            for child in child_rows
            if (child_id := _row_id(child))
        ],
    }


def _folder_preorder(
    copied: list[dict[str, Any]],
    folder_ids: set[int],
    children: dict[int, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    ordered: list[dict[str, Any]] = []
    emitted: set[int] = set()

    def emit(row: dict[str, Any]) -> None:
        identity = id(row)
        if identity in emitted:
            return
        emitted.add(identity)
        ordered.append(row)
        for child in children.get(_row_id(row), ()):
            emit(child)

    for row in copied:
        if _parent_id(row) not in folder_ids:
            emit(row)
    for row in copied:
        emit(row)
    return ordered


def reconcile_playlist_hierarchy(
    rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return copied playlist rows in stable folder preorder.

    Reconciliation is intentionally pure: callers may use the returned rows as
    a save payload without mutating the cache or UI models they started with.
    """

    copied, folder_ids, children, _cyclic_folder_ids = _normalize_hierarchy_rows(
        rows
    )

    rebuilt: set[int] = set()

    def rebuild_folder(folder: dict[str, Any]) -> None:
        identity = id(folder)
        if identity in rebuilt:
            return
        rebuilt.add(identity)

        child_rows = children.get(_row_id(folder), [])
        for child in child_rows:
            if is_playlist_folder(child):
                rebuild_folder(child)

        _rebuild_folder_contents(folder, child_rows)

    for row in copied:
        if is_playlist_folder(row):
            rebuild_folder(row)

    return _folder_preorder(copied, folder_ids, children)


def refresh_playlist_hierarchy_ancestors(
    rows: Iterable[Mapping[str, Any]],
    affected_folder_ids: Iterable[int],
) -> list[dict[str, Any]]:
    """Refresh only changed folders and their recursive ancestors.

    This is the mutation-path counterpart to full reconciliation. It performs
    cheap topology validation over the dataset but rebuilds aggregate items and
    smart rules only for folders whose descendants changed.
    """

    copied, folder_ids, children, cyclic_folder_ids = _normalize_hierarchy_rows(
        rows
    )
    affected = {
        int(folder_id)
        for folder_id in affected_folder_ids
        if int(folder_id) in folder_ids
    }
    affected.update(cyclic_folder_ids)
    parent_by_id = {_row_id(row): _parent_id(row) for row in copied}

    pending = list(affected)
    while pending:
        parent_id = parent_by_id.get(pending.pop(), 0)
        if parent_id in folder_ids and parent_id not in affected:
            affected.add(parent_id)
            pending.append(parent_id)

    def depth(folder_id: int) -> int:
        result = 0
        seen: set[int] = set()
        parent_id = parent_by_id.get(folder_id, 0)
        while parent_id in folder_ids and parent_id not in seen:
            seen.add(parent_id)
            result += 1
            parent_id = parent_by_id.get(parent_id, 0)
        return result

    rows_by_id = {_row_id(row): row for row in copied if _row_id(row)}
    for folder_id in sorted(affected, key=depth, reverse=True):
        folder = rows_by_id.get(folder_id)
        if folder is not None:
            _rebuild_folder_contents(folder, children.get(folder_id, []))

    return _folder_preorder(copied, folder_ids, children)
