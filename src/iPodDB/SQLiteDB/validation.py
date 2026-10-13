"""Check a complete generated artifact set before signing and publication."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3


@dataclass(frozen=True, slots=True)
class SQLiteRelationships:
    tracks: frozenset[int]
    containers: frozenset[int]
    membership: tuple[tuple[int, int, int], ...]
    chapters: frozenset[int]
    lyrics: frozenset[int]


def validate_databases(
    library: sqlite3.Connection,
    locations: sqlite3.Connection,
    dynamic: sqlite3.Connection,
    extras: sqlite3.Connection,
    genius: sqlite3.Connection,
    expected: SQLiteRelationships,
) -> None:
    for connection, name in (
        (library, "Library"),
        (locations, "Locations"),
        (dynamic, "Dynamic"),
        (extras, "Extras"),
        (genius, "Genius"),
    ):
        if tuple(row[0] for row in connection.execute("PRAGMA integrity_check")) != (
            "ok",
        ):
            raise ValueError(f"SQLite integrity check failed for {name}.itdb")
    for connection, table, column, identities in (
        (library, "item", "pid", expected.tracks),
        (library, "avformat_info", "item_pid", expected.tracks),
        (locations, "location", "item_pid", expected.tracks),
        (dynamic, "item_stats", "item_pid", expected.tracks),
        (library, "container", "pid", expected.containers),
        (dynamic, "container_ui", "container_pid", expected.containers),
        (extras, "chapter", "item_pid", expected.chapters),
        (extras, "lyrics", "item_pid", expected.lyrics),
    ):
        actual = frozenset(
            row[0] for row in connection.execute(f"SELECT {column} FROM {table}")
        )
        if actual != identities:
            raise ValueError(f"SQLite identity mismatch in {table}")
    actual_membership = Counter(
        connection_row
        for connection_row in library.execute(
            "SELECT item_pid,container_pid,physical_order FROM item_to_container"
        )
    )
    if actual_membership != Counter(expected.membership):
        raise ValueError("SQLite container membership differs from the checked CDB")
    for connection, table in (
        (library, "video_info"),
        (library, "video_characteristics"),
        (library, "podcast_info"),
        (library, "store_info"),
        (dynamic, "rental_info"),
    ):
        referenced = {
            row[0] for row in connection.execute(f"SELECT item_pid FROM {table}")
        }
        if not referenced <= expected.tracks:
            raise ValueError(
                f"SQLite relationship references a missing Track in {table}"
            )
    for table, field, target, target_field in (
        ("item", "album_pid", "album", "pid"),
        ("item", "artist_pid", "artist", "pid"),
        ("item", "track_artist_pid", "track_artist", "pid"),
        ("item", "composer_pid", "composer", "pid"),
        ("item", "genre_id", "genre_map", "id"),
        ("item", "category_id", "category_map", "id"),
        ("album", "artist_pid", "artist", "pid"),
        ("album", "artwork_item_pid", "item", "pid"),
        ("artist", "artwork_album_pid", "album", "pid"),
        ("container", "parent_pid", "container", "pid"),
        ("container_seed", "container_pid", "container", "pid"),
        ("container_seed", "item_pid", "item", "pid"),
        ("db_info", "primary_container_pid", "container", "pid"),
        ("store_info", "store_link_id", "store_link", "id"),
    ):
        if library.execute(
            f"SELECT 1 FROM {table} s LEFT JOIN {target} t ON s.{field}=t.{target_field} "
            f"WHERE s.{field}!=0 AND t.{target_field} IS NULL LIMIT 1"
        ).fetchone():
            raise ValueError(f"SQLite relationship is broken: {table}.{field}")
    bases = {row[0] for row in locations.execute("SELECT id FROM base_location")}
    kinds = {row[0] for row in library.execute("SELECT id FROM location_kind_map")}
    for base, kind in locations.execute(
        "SELECT base_location_id,kind_id FROM location"
    ):
        if base not in bases:
            raise ValueError("SQLite relationship is broken: location.base_location_id")
        if kind and kind not in kinds:
            raise ValueError("SQLite relationship is broken: location.kind_id")
    # The firmware schemas do not declare FOREIGN KEY constraints. PRAGMA
    # foreign_key_check alone therefore cannot establish these relationships.
