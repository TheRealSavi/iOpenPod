"""Merge checked CDB projections into captured, in-memory firmware schemas.

The CDB owns editable Library state. Version rows and metadata absent from that
model remain owned by their SQLite source. No paths or device access live here.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import cast

type SQLValue = int | float | str | bytes | None
type Row = dict[str, SQLValue]

# Columns generated as empty defaults but not represented by the CDB projection.
_RETAIN_COLUMNS: dict[str, frozenset[str]] = {
    "db_info": frozenset(
        {
            "media_folder_url",
            "audio_language",
            "subtitle_language",
            "genius_cuid",
            "bib",
            "rib",
        }
    ),
    "item": frozenset(
        {
            "revision_level",
            "content_rating_level",
            "chosen_by_auto_fill",
            "total_burn_time_ms",
            "radio_stream_status",
            "genius_id",
            "collection_description",
        }
    ),
    "avformat_info": frozenset(
        {"channels", "analysis_inhibit_flags", "audio_fingerprint"}
    ),
    "album": frozenset({"user_rating"}),
    "video_info": frozenset(
        {
            "has_alternate_audio",
            "has_subtitles",
            "characteristics_valid",
            "has_closed_captions",
            "is_self_contained",
            "is_compressed",
            "is_anamorphic",
            "is_hd",
            "audio_language",
            "audio_track_index",
            "audio_track_id",
            "subtitle_language",
            "subtitle_track_index",
            "subtitle_track_id",
            "extended_content_rating",
            "movie_info",
        }
    ),
    "item_stats": frozenset(
        {"play_count_recent", "skip_count_recent", "rental_expired", "genius_id"}
    ),
    "container_ui": frozenset(
        {
            "play_order",
            "is_reversed",
            "album_field_order",
            "repeat_mode",
            "shuffle_items",
            "has_been_shuffled",
        }
    ),
    "container": frozenset({"workout_template_id", "smart_is_genius"}),
    "location": frozenset(
        {"file_creator", "file_type", "num_dir_levels_file", "num_dir_levels_lib"}
    ),
}
_EXTRA_KEYS: dict[str, tuple[str, ...]] = {
    "item_to_container": ("item_pid", "container_pid", "physical_order"),
    "container_seed": ("container_pid", "item_pid"),
    "video_characteristics": ("item_pid", "sub_id", "track_id"),
}
# These newer projection-only calculated columns are absent in Apple's Nano 5
# schema. Its schema and version are retained; no migration is required.
_OPTIONAL_COLUMNS = {
    "item_stats": frozenset({"genius_id"}),
    "album": frozenset({"item_count", "has_movies"}),
    "genre_map": frozenset({"compilation_count_calc"}),
}
_GROUP_LINKS = {
    "album": "album_pid",
    "artist": "artist_pid",
    "track_artist": "track_artist_pid",
    "composer": "composer_pid",
    "genre_map": "genre_id",
    "category_map": "category_id",
}


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _rows(connection: sqlite3.Connection, table: str) -> list[Row]:
    cursor = connection.execute(f"SELECT * FROM {_quote(table)}")
    names = tuple(column[0] for column in cursor.description or ())
    return [
        dict(zip(names, cast("tuple[SQLValue, ...]", tuple(row)), strict=True))
        for row in cursor
    ]


def _columns(connection: sqlite3.Connection, table: str) -> tuple[tuple[str, int], ...]:
    return tuple(
        (str(row[1]), int(row[5]))
        for row in connection.execute(f"PRAGMA table_xinfo({_quote(table)})")
        if row[6] == 0
    )


def _replace_rows(
    connection: sqlite3.Connection,
    table: str,
    rows: list[Row],
    columns: tuple[str, ...],
) -> None:
    connection.execute(f"DELETE FROM {_quote(table)}")
    batches: dict[tuple[str, ...], list[tuple[SQLValue, ...]]] = defaultdict(list)
    for row in rows:
        supplied = tuple(column for column in columns if column in row)
        batches[supplied].append(tuple(row[column] for column in supplied))
    for supplied, values in batches.items():
        connection.executemany(
            f"INSERT INTO {_quote(table)} ({','.join(_quote(c) for c in supplied)}) VALUES ({','.join('?' for _ in supplied)})",
            values,
        )


def _group_rows(
    projected: sqlite3.Connection,
    retained: sqlite3.Connection,
    existing: set[str],
) -> dict[str, dict[SQLValue, Row]]:
    """Match browse groups through surviving Tracks, never recycled local IDs.

    A split or merge has no single predecessor and receives fresh defaults.
    Matching membership also preserves metadata when a group is renamed.
    """
    if "item" not in existing:
        return {}
    old_items = _rows(retained, "item")
    new_items = _rows(projected, "item")
    common = {row["pid"] for row in old_items} & {row["pid"] for row in new_items}
    result: dict[str, dict[SQLValue, Row]] = {}
    for table, reference in _GROUP_LINKS.items():
        if table not in existing:
            continue
        memberships: list[dict[SQLValue, set[SQLValue]]] = []
        for items in (old_items, new_items):
            groups: dict[SQLValue, set[SQLValue]] = defaultdict(set)
            for row in items:
                if row["pid"] in common and row[reference]:
                    groups[row[reference]].add(row["pid"])
            memberships.append(groups)
        old_members, new_members = memberships
        key = "id" if table.endswith("_map") else "pid"
        by_members = {
            frozenset(old_members[row[key]]): row
            for row in _rows(retained, table)
            if old_members.get(row[key])
        }
        result[table] = {
            row[key]: old
            for row in _rows(projected, table)
            if new_members.get(row[key])
            and (old := by_members.get(frozenset(new_members[row[key]]))) is not None
        }
    return result


def retain_database(
    projected: sqlite3.Connection,
    original: bytes,
    *,
    artifact: str,
    tracks: frozenset[int],
    containers: frozenset[int],
    cleared_lyrics: frozenset[int],
    cleared_chapters: frozenset[int],
    replaced_tracks: frozenset[int],
) -> sqlite3.Connection:
    """Return an owned connection; reject unreadable sources instead of erasing them."""
    retained = sqlite3.connect(":memory:")
    try:
        retained.deserialize(original)
        retained.execute("PRAGMA trusted_schema=OFF")
        retained.setconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_TRIGGER, False)
        if tuple(row[0] for row in retained.execute("PRAGMA integrity_check")) != (
            "ok",
        ):
            raise ValueError(f"Cannot preserve damaged {artifact}")
        schemas = {
            str(row[0]): str(row[1])
            for row in projected.execute(
                "SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        existing = {
            str(row[0])
            for row in retained.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        groups = (
            _group_rows(projected, retained, existing)
            if artifact == "Library.itdb"
            else {}
        )
        video_tracks: frozenset[int] = (
            frozenset(
                int(row[0])
                for row in projected.execute("SELECT item_pid FROM video_info")
            )
            if artifact == "Library.itdb"
            else frozenset()
        )
        for table, schema in schemas.items():
            if table not in existing:
                retained.execute(schema)
            elif table == "version_info" or artifact == "Genius.itdb":
                continue
            fresh_columns = _columns(projected, table)
            old_columns = _columns(retained, table)
            column_names = tuple(name for name, _ in old_columns)
            missing = {name for name, _ in fresh_columns} - set(column_names)
            if missing - _OPTIONAL_COLUMNS.get(table, frozenset()):
                raise ValueError(
                    f"Cannot preserve incompatible {artifact} table {table}: missing {sorted(missing)}"
                )
            keys: tuple[str, ...] = tuple(
                name
                for name, rank in sorted(fresh_columns, key=lambda item: item[1])
                if rank
            ) or _EXTRA_KEYS.get(table, ())
            old_rows = _rows(retained, table)
            fresh_rows = _rows(projected, table)
            by_key: dict[tuple[SQLValue, ...], Row] = {}
            if keys:
                by_key = {tuple(row[key] for key in keys): row for row in old_rows}
                if len(by_key) != len(old_rows):
                    raise ValueError(
                        f"Ambiguous retained {artifact} identity in {table}"
                    )

            passthrough = table in {
                "store_info",
                "store_link",
                "container_seed",
                "rental_info",
                "chapter",
                "lyrics",
                "video_characteristics",
            }
            rows: list[Row]
            if passthrough:
                invalidated: frozenset[int] = (
                    cleared_lyrics
                    if table == "lyrics"
                    else cleared_chapters
                    if table == "chapter"
                    else replaced_tracks
                    if table in {"store_info", "rental_info", "video_characteristics"}
                    else frozenset()
                )
                rows = [
                    row
                    for row in old_rows
                    if (
                        "item_pid" not in row
                        or (
                            row["item_pid"] in tracks
                            and row["item_pid"] not in invalidated
                        )
                    )
                    and (
                        "container_pid" not in row or row["container_pid"] in containers
                    )
                    and (
                        table != "video_characteristics"
                        or row["item_pid"] in video_tracks
                    )
                ]
                merged = {tuple(row[key] for key in keys): row for row in rows}
                for row in fresh_rows:
                    identity = tuple(row[key] for key in keys)
                    # Native chapter/lyrics changes take precedence. Store/rental
                    # defaults must never erase an existing account or rental.
                    if table in {"chapter", "lyrics"} or identity not in merged:
                        merged[identity] = {**merged.get(identity, {}), **row}
                rows = list(merged.values())
            else:
                rows = []
                for row in fresh_rows:
                    if table == "db_info" and len(old_rows) == 1:
                        old = old_rows[0]
                    elif table in _GROUP_LINKS:
                        key = "id" if table.endswith("_map") else "pid"
                        old = groups.get(table, {}).get(row[key], {})
                    else:
                        old = (
                            by_key.get(tuple(row[key] for key in keys), {})
                            if keys
                            else {}
                        )
                    if (
                        table in {"avformat_info", "video_info", "location"}
                        and row.get("item_pid") in replaced_tracks
                    ):
                        old = {}
                    owned = {
                        name: value
                        for name, value in row.items()
                        if name not in _RETAIN_COLUMNS.get(table, frozenset())
                        or name not in old
                    }
                    rows.append({**old, **owned})
            _replace_rows(retained, table, rows, column_names)
        retained.commit()
        return retained
    except Exception:
        retained.close()
        raise
