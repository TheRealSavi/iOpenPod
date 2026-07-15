"""Database storage breakdowns for the Manage Storage screen."""

from __future__ import annotations

import sqlite3
import struct
from dataclasses import dataclass, field
from pathlib import Path

from iopenpod.itunesdb_shared.constants import identifier_readable_map, mhod_type_map

_UINT32_LE = struct.Struct("<I")
_MIN_CHUNK_HEADER = 12
_SQLITE_HEADER = b"SQLite format 3\x00"
_SQLITE_ITLP_RELATIVE = Path("iPod_Control") / "iTunes" / "iTunes Library.itlp"
_SQLITE_DATABASE_ORDER = (
    "Library.itdb",
    "Locations.itdb",
    "Dynamic.itdb",
    "Extras.itdb",
    "Genius.itdb",
    "Locations.itdb.cbk",
)


@dataclass(frozen=True)
class StorageBreakdownNode:
    """One row in a database storage breakdown tree."""

    label: str
    bytes_used: int
    detail: str = ""
    kind: str = ""
    children: tuple[StorageBreakdownNode, ...] = ()

    def find(self, label: str) -> StorageBreakdownNode | None:
        """Return the first node with *label* in this subtree."""
        if self.label == label:
            return self
        for child in self.children:
            found = child.find(label)
            if found is not None:
                return found
        return None


@dataclass(frozen=True)
class DatabaseStorageReport:
    """Storage accounting for a classic iTunesDB/CDB or SQLite database set."""

    mode: str
    physical_bytes: int
    logical_bytes: int
    database_path: str = ""
    roots: tuple[StorageBreakdownNode, ...] = ()
    note: str = ""

    def find(self, label: str) -> StorageBreakdownNode | None:
        """Return the first node with *label* anywhere in the report."""
        for root in self.roots:
            found = root.find(label)
            if found is not None:
                return found
        return None


@dataclass(slots=True)
class _ChunkRecord:
    chunk_type: str
    offset: int
    header_length: int
    total_length: int
    children: list[_ChunkRecord]
    mhod_type: int | None = None
    string_payload_bytes: int = 0


@dataclass(slots=True)
class _DataObjectAccumulator:
    bytes_used: int = 0
    count: int = 0
    payload_bytes: int = 0


@dataclass(slots=True)
class _ContainerAccumulator:
    label: str
    kind: str = "container"
    bytes_used: int = 0
    header_bytes: int = 0
    count: int = 0
    data_objects: dict[str, _DataObjectAccumulator] = field(default_factory=dict)
    children: dict[str, _ContainerAccumulator] = field(default_factory=dict)


def analyze_database_storage(
    database_path: str | Path | None,
    *,
    ipod_root: str | Path | None = None,
    uses_sqlite_db: bool = False,
) -> DatabaseStorageReport:
    """Build a byte-level storage report for the current iPod database.

    Classic firmware stores the library in iTunesDB/iTunesCDB, so the report
    uses the decompressed database stream. SQLite-capable firmware primarily
    uses the ``iTunes Library.itlp`` SQLite files; for those devices the CDB is
    reported only as a physical compatibility file.
    """
    if uses_sqlite_db:
        return _analyze_sqlite_storage(database_path, ipod_root)
    return _analyze_classic_storage(database_path)


def _analyze_classic_storage(
    database_path: str | Path | None,
) -> DatabaseStorageReport:
    path = Path(database_path) if database_path else None
    if path is None:
        return DatabaseStorageReport(
            mode="classic",
            physical_bytes=0,
            logical_bytes=0,
            note="No iTunesDB path available.",
        )

    try:
        raw = path.read_bytes()
    except OSError as exc:
        return DatabaseStorageReport(
            mode="classic",
            physical_bytes=0,
            logical_bytes=0,
            database_path=str(path),
            note=str(exc),
        )

    from iopenpod.itunesdb_parser.parser import decompress_itunescdb

    logical = bytes(decompress_itunescdb(raw))
    root = _build_classic_root(logical, physical_bytes=len(raw))
    return DatabaseStorageReport(
        mode="classic",
        physical_bytes=len(raw),
        logical_bytes=len(logical),
        database_path=str(path),
        roots=(root,) if root is not None else (),
    )


def _build_classic_root(
    data: bytes,
    *,
    physical_bytes: int,
) -> StorageBreakdownNode | None:
    if len(data) < _MIN_CHUNK_HEADER:
        return StorageBreakdownNode(
            "iTunesDB",
            len(data),
            detail="File is too small to inspect.",
            kind="error",
        )

    root, _next_offset = _walk_chunk(data, 0, len(data))
    if root is None:
        return StorageBreakdownNode(
            "iTunesDB",
            len(data),
            detail="Could not read chunk headers.",
            kind="error",
        )

    detail = f"{len(data):,} logical bytes"
    if physical_bytes != len(data):
        detail = f"{physical_bytes:,} physical bytes; {detail}"
    accumulator = _ContainerAccumulator("iTunesDB", kind="classic_database")
    _accumulate_container(accumulator, root)
    return _container_node(
        accumulator,
        detail=detail,
        kind="classic_database",
    )


def _accumulate_container(
    accumulator: _ContainerAccumulator,
    chunk: _ChunkRecord,
) -> None:
    accumulator.bytes_used += max(0, chunk.total_length)
    accumulator.header_bytes += max(0, chunk.header_length)
    accumulator.count += 1

    for child in chunk.children:
        if child.chunk_type == "mhod":
            label = _mhod_label(child.mhod_type)
            stats = accumulator.data_objects.setdefault(
                label,
                _DataObjectAccumulator(),
            )
            stats.bytes_used += max(0, child.total_length)
            stats.count += 1
            stats.payload_bytes += max(0, child.string_payload_bytes)
            continue

        label = _chunk_label(child.chunk_type)
        child_accumulator = accumulator.children.setdefault(
            label,
            _ContainerAccumulator(label),
        )
        _accumulate_container(child_accumulator, child)


def _container_node(
    accumulator: _ContainerAccumulator,
    *,
    detail: str | None = None,
    kind: str | None = None,
) -> StorageBreakdownNode:
    children: list[StorageBreakdownNode] = []
    if accumulator.header_bytes:
        children.append(
            StorageBreakdownNode(
                "Header",
                accumulator.header_bytes,
                detail=_count_detail(accumulator.count, "chunk"),
                kind="chunk_header",
            )
        )

    data_object_total = sum(
        stats.bytes_used for stats in accumulator.data_objects.values()
    )
    if accumulator.data_objects:
        data_object_count = sum(
            stats.count for stats in accumulator.data_objects.values()
        )
        children.append(
            StorageBreakdownNode(
                "Data objects",
                data_object_total,
                detail=_count_detail(data_object_count, "MHOD"),
                kind="mhod_group",
                children=_data_object_nodes(accumulator.data_objects),
            )
        )

    child_nodes = [
        _container_node(child)
        for child in sorted(
            accumulator.children.values(),
            key=lambda value: (-value.bytes_used, value.label.lower()),
        )
    ]
    children.extend(child_nodes)

    accounted = (
        accumulator.header_bytes
        + data_object_total
        + sum(child.bytes_used for child in accumulator.children.values())
    )
    if accumulator.bytes_used > accounted:
        children.append(
            StorageBreakdownNode(
                "Unattributed bytes",
                accumulator.bytes_used - accounted,
                detail="Padding, unsupported payloads, or unread chunk bodies.",
                kind="unknown",
            )
        )

    return StorageBreakdownNode(
        accumulator.label,
        accumulator.bytes_used,
        detail=detail or _count_detail(accumulator.count, "chunk"),
        kind=kind or accumulator.kind,
        children=tuple(children),
    )


def _data_object_nodes(
    data_objects: dict[str, _DataObjectAccumulator],
) -> tuple[StorageBreakdownNode, ...]:
    return tuple(
        StorageBreakdownNode(
            label,
            stats.bytes_used,
            detail=_mhod_detail(stats.count, stats.payload_bytes),
            kind="mhod",
        )
        for label, stats in sorted(
            data_objects.items(),
            key=lambda item: (-item[1].bytes_used, item[0].lower()),
        )
    )


def _walk_chunk(
    data: bytes,
    offset: int,
    boundary: int,
) -> tuple[_ChunkRecord | None, int]:
    if offset + _MIN_CHUNK_HEADER > len(data) or offset >= boundary:
        return None, offset

    chunk_type = data[offset:offset + 4].decode("ascii", errors="replace")
    header_length = _u32_at(data, offset + 4, default=0)
    word3 = _u32_at(data, offset + 8, default=0)
    if header_length < _MIN_CHUNK_HEADER:
        return None, offset
    if offset + header_length > len(data):
        return None, len(data)

    total_length, child_count = _resolve_chunk_shape(
        data,
        offset,
        chunk_type,
        header_length,
        word3,
    )
    max_length = max(0, min(total_length, len(data) - offset))
    if chunk_type == "mhbd":
        max_length = len(data) - offset
    if chunk_type in {"mhlt", "mhla", "mhli", "mhlp"}:
        max_length = header_length

    children: list[_ChunkRecord] = []
    child_offset = offset + header_length
    if chunk_type in {"mhlt", "mhla", "mhli", "mhlp"}:
        child_boundary = boundary
    else:
        child_boundary = min(len(data), offset + max_length) if max_length else boundary
    for _ in range(max(0, child_count)):
        child, next_offset = _walk_chunk(data, child_offset, child_boundary)
        if child is None or next_offset <= child_offset:
            break
        children.append(child)
        child_offset = next_offset

    if chunk_type in {"mhlt", "mhla", "mhli", "mhlp"}:
        max_length = max(header_length, child_offset - offset)

    mhod_type = _u32_at(data, offset + 0x0C) if chunk_type == "mhod" else None
    string_payload_bytes = (
        _mhod_string_payload_bytes(data, offset, max_length, mhod_type)
        if chunk_type == "mhod"
        else 0
    )
    record = _ChunkRecord(
        chunk_type=chunk_type,
        offset=offset,
        header_length=header_length,
        total_length=max_length,
        children=children,
        mhod_type=mhod_type,
        string_payload_bytes=string_payload_bytes,
    )
    return record, offset + max_length


def _resolve_chunk_shape(
    data: bytes,
    offset: int,
    chunk_type: str,
    header_length: int,
    word3: int,
) -> tuple[int, int]:
    if chunk_type == "mhbd":
        child_count = _u32_at(data, offset + 0x14, default=0)
        return max(word3, header_length), child_count
    if chunk_type == "mhsd":
        dataset_type = _u32_at(data, offset + 0x0C, default=0)
        return max(word3, header_length), 0 if dataset_type == 9 else 1
    if chunk_type in {"mhlt", "mhla", "mhli", "mhlp"}:
        return header_length, word3
    if chunk_type == "mhyp":
        mhod_count = _u32_at(data, offset + 0x0C, default=0)
        mhip_count = _u32_at(data, offset + 0x10, default=0)
        return max(word3, header_length), mhod_count + mhip_count
    if chunk_type == "mhod":
        return max(word3, header_length), 0
    if chunk_type in {"mhit", "mhia", "mhii", "mhip"}:
        return max(word3, header_length), _u32_at(data, offset + 0x0C, default=0)
    return max(word3, header_length), 0


def _u32_at(data: bytes, offset: int, *, default: int = 0) -> int:
    if offset < 0 or offset + 4 > len(data):
        return default
    return _UINT32_LE.unpack_from(data, offset)[0]


def _mhod_string_payload_bytes(
    data: bytes,
    offset: int,
    total_length: int,
    mhod_type: int | None,
) -> int:
    if mhod_type is None:
        return 0
    if 0 < mhod_type < 15 or 17 < mhod_type < 45 or 199 < mhod_type < 205 or mhod_type == 300:
        length = _u32_at(data, offset + 0x1C, default=0)
        return max(0, min(length, max(0, total_length - 0x28)))
    if mhod_type in {15, 16}:
        return max(0, total_length - 24)
    return 0


def _chunk_label(chunk_type: str) -> str:
    return identifier_readable_map.get(chunk_type, chunk_type)


def _mhod_label(mhod_type: int | None) -> str:
    if mhod_type is None:
        return "Unknown MHOD"
    return mhod_type_map.get(mhod_type, f"MHOD {mhod_type}")


def _sorted_totals(totals: dict[str, int]) -> list[tuple[str, int]]:
    return sorted(totals.items(), key=lambda item: (-item[1], item[0].lower()))


def _count_detail(count: int, noun: str) -> str:
    suffix = "" if count == 1 else "s"
    return f"{count:,} {noun}{suffix}"


def _mhod_detail(count: int, payload_bytes: int) -> str:
    detail = _count_detail(count, "MHOD")
    if payload_bytes:
        detail += f"; {payload_bytes:,} string bytes"
    return detail


def _analyze_sqlite_storage(
    database_path: str | Path | None,
    ipod_root: str | Path | None,
) -> DatabaseStorageReport:
    db_path = Path(database_path) if database_path else None
    physical_cdb_bytes = _path_size(db_path)
    itlp_dir = _find_itlp_dir(db_path, ipod_root)
    sqlite_nodes = _sqlite_file_nodes(itlp_dir) if itlp_dir else ()

    children: list[StorageBreakdownNode] = list(sqlite_nodes)
    if physical_cdb_bytes:
        children.append(
            StorageBreakdownNode(
                "Legacy iTunesCDB",
                physical_cdb_bytes,
                detail="Compatibility database; counted as physical bytes for SQLite iPods.",
                kind="legacy_cdb",
            )
        )

    total = sum(child.bytes_used for child in children)
    root = StorageBreakdownNode(
        "SQLite databases",
        total,
        detail=str(itlp_dir) if itlp_dir else "No iTunes Library.itlp directory found.",
        kind="sqlite_database_set",
        children=tuple(children),
    )
    return DatabaseStorageReport(
        mode="sqlite",
        physical_bytes=total,
        logical_bytes=total,
        database_path=str(db_path) if db_path else "",
        roots=(root,),
    )


def _find_itlp_dir(
    database_path: Path | None,
    ipod_root: str | Path | None,
) -> Path | None:
    candidates: list[Path] = []
    if ipod_root:
        candidates.append(Path(ipod_root) / _SQLITE_ITLP_RELATIVE)
    if database_path:
        for parent in (database_path.parent, *database_path.parents):
            candidates.append(parent / "iTunes Library.itlp")
        if len(database_path.parents) >= 3:
            candidates.append(database_path.parents[2] / _SQLITE_ITLP_RELATIVE)

    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def _sqlite_file_nodes(itlp_dir: Path) -> tuple[StorageBreakdownNode, ...]:
    paths = {path.name: path for path in itlp_dir.iterdir() if path.is_file()}
    ordered_names = [name for name in _SQLITE_DATABASE_ORDER if name in paths]
    ordered_names.extend(sorted(set(paths) - set(ordered_names)))
    nodes = [
        _sqlite_file_node(paths[name])
        for name in ordered_names
        if paths[name].suffix == ".itdb" or name.endswith(".itdb.cbk")
    ]
    return tuple(sorted(nodes, key=lambda node: (-node.bytes_used, node.label.lower())))


def _sqlite_file_node(path: Path) -> StorageBreakdownNode:
    size = _path_size(path)
    if not _looks_like_sqlite(path):
        return StorageBreakdownNode(
            path.name,
            size,
            detail="Non-SQLite companion file.",
            kind="file",
        )

    object_nodes = _sqlite_object_nodes(path)
    return StorageBreakdownNode(
        path.name,
        size,
        detail=_count_detail(len(object_nodes), "object") if object_nodes else "SQLite database",
        kind="sqlite_file",
        children=object_nodes,
    )


def _looks_like_sqlite(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(len(_SQLITE_HEADER)) == _SQLITE_HEADER
    except OSError:
        return False


def _sqlite_object_nodes(path: Path) -> tuple[StorageBreakdownNode, ...]:
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return ()
    try:
        table_counts = _sqlite_table_counts(conn)
        page_bytes = _sqlite_dbstat_bytes(conn)
        nodes: list[StorageBreakdownNode] = []
        labels = set(table_counts) | set(page_bytes)
        for label in labels:
            rows = table_counts.get(label)
            detail = _row_detail(rows) if rows is not None else "SQLite object"
            kind = "sqlite_table" if rows is not None else "sqlite_index"
            nodes.append(
                StorageBreakdownNode(
                    label,
                    page_bytes.get(label, 0),
                    detail=detail,
                    kind=kind,
                )
            )
        return tuple(sorted(nodes, key=lambda node: (-node.bytes_used, node.label.lower())))
    finally:
        conn.close()


def _sqlite_table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name"
    ).fetchall()
    counts: dict[str, int] = {}
    for (table_name,) in rows:
        try:
            quoted = '"' + str(table_name).replace('"', '""') + '"'
            counts[str(table_name)] = int(
                conn.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0]
            )
        except sqlite3.Error:
            counts[str(table_name)] = 0
    return counts


def _sqlite_dbstat_bytes(conn: sqlite3.Connection) -> dict[str, int]:
    try:
        rows = conn.execute(
            "SELECT name, SUM(pgsize) FROM dbstat GROUP BY name"
        ).fetchall()
    except sqlite3.Error:
        return {}
    return {str(name): int(size or 0) for name, size in rows}


def _row_detail(rows: int | None) -> str:
    if rows is None:
        return "SQLite object"
    return f"{rows:,} row" if rows == 1 else f"{rows:,} rows"


def _path_size(path: Path | None) -> int:
    if path is None:
        return 0
    try:
        return path.stat().st_size
    except OSError:
        return 0
