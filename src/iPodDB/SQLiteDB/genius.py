"""Lossless, filesystem-independent Genius tables in Genius.itdb or Extras.itdb."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from iPodDB.genius import (
    GeniusSimilarities,
    OpaqueGeniusPayload,
    parse_genius_config,
    parse_genius_metadata,
    parse_genius_similarities,
    serialize_genius_config,
    serialize_genius_metadata,
    serialize_genius_similarities,
)
from iPodDB.shared.diagnostics import log_unknown_data
from iPodDB.SQLiteDB.schema import GENIUS_SCHEMA

if TYPE_CHECKING:
    from iPodDB.genius import (
        GeniusConfigPayload,
        GeniusMetadataPayload,
        GeniusSimilaritiesPayload,
    )


@dataclass(frozen=True, slots=True)
class GeniusConfigRow:
    row_id: int
    version: int | None
    default_num_results: int | None
    min_num_results: int | None
    payload: GeniusConfigPayload | None


@dataclass(frozen=True, slots=True)
class GeniusMetadataRow:
    genius_id: int
    version: int | None
    payload: GeniusMetadataPayload | None


@dataclass(frozen=True, slots=True)
class GeniusSimilaritiesRow:
    genius_id: int
    version: int | None
    payload: GeniusSimilaritiesPayload | None


@dataclass(frozen=True, slots=True)
class GeniusData:
    """Native graph and constraints, independent of recommendation policy."""

    configs: tuple[GeniusConfigRow, ...] = ()
    metadata: tuple[GeniusMetadataRow, ...] = ()
    similarities: tuple[GeniusSimilaritiesRow, ...] = ()


@dataclass(frozen=True, slots=True)
class GeniusDatabase:
    """Typed Genius state with its complete source schema and Unknown Data."""

    data: GeniusData
    original_bytes: bytes = b""


def _s64(value: int) -> int:
    if not 0 <= value < 1 << 64:
        raise ValueError("Genius identity must fit an unsigned 64-bit integer")
    return value if value < 1 << 63 else value - (1 << 64)


def _u64(value: object) -> int:
    if not isinstance(value, int):
        raise ValueError("Genius identity is not an integer")
    return value & ((1 << 64) - 1)


def _integer(value: object) -> int | None:
    if value is not None and not isinstance(value, int):
        raise ValueError("Genius version or threshold is not an integer")
    return value


def _blob(value: object) -> bytes:
    if not isinstance(value, bytes):
        raise ValueError("Genius payload is not a BLOB")
    return value


def _open(data: bytes = b"") -> sqlite3.Connection:
    # A private memdb VFS gives new companions normal SQLite file bookkeeping
    # without disk access. Deserialized captures retain their original headers.
    connection = (
        sqlite3.connect(":memory:")
        if data
        else sqlite3.connect("file:iopenpod-genius?vfs=memdb", uri=True)
    )
    try:
        if data:
            connection.deserialize(data)
        else:
            connection.execute("PRAGMA journal_mode=OFF")
            connection.execute("PRAGMA synchronous=OFF")
            connection.execute("PRAGMA encoding='UTF-8'")
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.setconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_TRIGGER, False)
        if tuple(row[0] for row in connection.execute("PRAGMA integrity_check")) != (
            "ok",
        ):
            raise ValueError("Damaged Genius SQLite database")
    except Exception:
        connection.close()
        raise
    return connection


@log_unknown_data("Genius database")
def read_genius_data(connection: sqlite3.Connection) -> GeniusData:
    """Read known tables without interpreting unrelated SQLite state."""

    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    configs: list[GeniusConfigRow] = []
    metadata: list[GeniusMetadataRow] = []
    similarities: list[GeniusSimilaritiesRow] = []
    if "genius_config" in tables:
        for row in connection.execute(
            "SELECT id,version,default_num_results,min_num_results,data FROM genius_config ORDER BY id"
        ):
            version = _integer(row[1])
            configs.append(
                GeniusConfigRow(
                    _u64(row[0]),
                    version,
                    _integer(row[2]),
                    _integer(row[3]),
                    None
                    if row[4] is None
                    else parse_genius_config(_blob(row[4]), version=version),
                )
            )
    if "genius_metadata" in tables:
        for row in connection.execute(
            "SELECT genius_id,version,data FROM genius_metadata ORDER BY genius_id"
        ):
            version = _integer(row[1])
            metadata.append(
                GeniusMetadataRow(
                    _u64(row[0]),
                    version,
                    None
                    if row[2] is None
                    else parse_genius_metadata(_blob(row[2]), version=version),
                )
            )
    if "genius_similarities" in tables:
        for row in connection.execute(
            "SELECT genius_id,version,data FROM genius_similarities ORDER BY genius_id"
        ):
            version = _integer(row[1])
            similarities.append(
                GeniusSimilaritiesRow(
                    _u64(row[0]),
                    version,
                    None
                    if row[2] is None
                    else parse_genius_similarities(_blob(row[2]), version=version),
                )
            )
    return GeniusData(tuple(configs), tuple(metadata), tuple(similarities))


def parse_genius_database(data: bytes) -> GeniusDatabase:
    """Read a Genius companion without acquiring filesystem authority."""

    if not data:
        raise ValueError("Invalid Genius SQLite database")
    try:
        with closing(_open(data)) as connection:
            return GeniusDatabase(read_genius_data(connection), data)
    except sqlite3.DatabaseError as error:
        raise ValueError("Invalid Genius SQLite database") from error


def write_genius_data(connection: sqlite3.Connection, data: GeniusData) -> None:
    """Replace known rows while retaining source schemas and unknown row columns."""

    rows: dict[str, tuple[tuple[object, ...], ...]] = {
        "genius_config": tuple(
            (
                _s64(row.row_id),
                row.version,
                row.default_num_results,
                row.min_num_results,
                None if row.payload is None else serialize_genius_config(row.payload),
            )
            for row in data.configs
        ),
        "genius_metadata": tuple(
            (
                _s64(row.genius_id),
                row.version,
                None if row.payload is None else serialize_genius_metadata(row.payload),
            )
            for row in data.metadata
        ),
        "genius_similarities": tuple(
            (
                _s64(row.genius_id),
                row.version,
                None
                if row.payload is None
                else serialize_genius_similarities(row.payload),
            )
            for row in data.similarities
        ),
    }
    all_rows: tuple[
        GeniusConfigRow | GeniusMetadataRow | GeniusSimilaritiesRow, ...
    ] = (*data.configs, *data.metadata, *data.similarities)
    for row in all_rows:
        if row.payload is not None and row.version != row.payload.version:
            raise ValueError("Genius row version differs from its payload version")
    existing = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    with closing(_open()) as definitions:
        definitions.executescript(GENIUS_SCHEMA)
        schemas = dict(
            definitions.execute("SELECT name,sql FROM sqlite_master WHERE type='table'")
        )
    for table, values in rows.items():
        if len({row[0] for row in values}) != len(values):
            raise ValueError(f"Duplicate Genius identity in {table}")
        if table not in existing:
            connection.execute(schemas[table])
        columns = (
            ("id", "version", "default_num_results", "min_num_results", "data")
            if table == "genius_config"
            else ("genius_id", "version", "data")
        )
        # UPDATE retains unknown columns; INSERT lets the source schema provide
        # defaults for newly authored rows. Delete omissions before UNIQUE swaps.
        identities = {row[0] for row in values}
        for (identity,) in connection.execute(
            f"SELECT {columns[0]} FROM {table}"
        ).fetchall():
            if identity not in identities:
                connection.execute(
                    f"DELETE FROM {table} WHERE {columns[0]}=?", (identity,)
                )
        # Config versions have a UNIQUE constraint and can swap identities.
        if table == "genius_config":
            connection.execute("UPDATE genius_config SET version=NULL")
        for value in values:
            changed = connection.execute(
                f"UPDATE {table} SET {','.join(c + '=?' for c in columns[1:])} WHERE {columns[0]}=?",
                (*value[1:], value[0]),
            ).rowcount
            if not changed:
                connection.execute(
                    f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                    value,
                )


def serialize_genius_database(
    document: GeniusDatabase, data: GeniusData | None = None
) -> bytes:
    """Return exact source bytes for no-op writes, including opaque variants."""

    desired = document.data if data is None else data
    if (
        document.original_bytes
        and parse_genius_database(document.original_bytes).data == desired
    ):
        return document.original_bytes
    try:
        with closing(_open(document.original_bytes)) as connection:
            write_genius_data(connection, desired)
            connection.commit()
            return connection.serialize()
    except sqlite3.DatabaseError as error:
        raise ValueError("Cannot write Genius SQLite database") from error


def prune_genius_data(data: GeniusData, removed_ids: frozenset[int]) -> GeniusData:
    """Remove known Track relationships; opaque graph edges cannot be repaired."""

    if not removed_ids:
        return data
    similarities: list[GeniusSimilaritiesRow] = []
    for row in data.similarities:
        if row.genius_id in removed_ids:
            continue
        if isinstance(row.payload, OpaqueGeniusPayload):
            raise ValueError(
                "Cannot remove Genius Tracks while opaque similarities remain"
            )
        if isinstance(row.payload, GeniusSimilarities):
            if row.payload.payload_tail or row.payload.trailing_data:
                raise ValueError(
                    "Cannot remove Genius Tracks with unknown similarity extensions"
                )
            row = replace(
                row,
                payload=replace(
                    row.payload,
                    candidates=tuple(
                        gid for gid in row.payload.candidates if gid not in removed_ids
                    ),
                ),
            )
        similarities.append(row)
    return replace(
        data,
        metadata=tuple(
            row for row in data.metadata if row.genius_id not in removed_ids
        ),
        similarities=tuple(similarities),
    )
