"""Genius relationships spanning the Library, Dynamic, and Genius companions."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from typing import TYPE_CHECKING

from iPodDB.genius import GeniusConfig, GeniusMetadata, GeniusSimilarities
from iPodDB.SQLiteDB.genius import (
    GeniusData,
    parse_genius_database,
    prune_genius_data,
    read_genius_data,
    write_genius_data,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from iPodDB.SQLiteDB.inputs import SQLiteGeniusUpdate, SQLiteSource


@dataclass(frozen=True, slots=True)
class SQLiteGeniusMixRecord:
    """Firmware state uses persistent item IDs, never Library Track row IDs."""

    container_id: int
    name: str
    item_pids: tuple[int, ...]
    seed_pids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class SQLiteGeniusState:
    data: GeniusData
    track_genius_ids: tuple[tuple[int, int], ...]
    mixes: tuple[SQLiteGeniusMixRecord, ...]


def _s64(value: int) -> int:
    if not 0 <= value < 1 << 64:
        raise ValueError("Genius identity must fit an unsigned 64-bit integer")
    return value if value < 1 << 63 else value - (1 << 64)


def _u64(value: int) -> int:
    return value & ((1 << 64) - 1)


def _open(data: bytes) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    try:
        connection.deserialize(data)
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.setconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_TRIGGER, False)
        if tuple(row[0] for row in connection.execute("PRAGMA integrity_check")) != (
            "ok",
        ):
            raise ValueError("Damaged Genius companion")
        return connection
    except Exception:
        connection.close()
        raise


def _source(sources: tuple[SQLiteSource, ...], name: str) -> bytes | None:
    matching = [source.data for source in sources if source.name == name]
    if len(matching) > 1:
        raise ValueError("Retained SQLite sources must have unique supported names")
    return matching[0] if matching else None


def read_sqlite_genius_state(
    library: bytes, dynamic: bytes, genius: bytes
) -> SQLiteGeniusState:
    """Inspect native Genius state without making SQLite a Library authority."""

    with closing(_open(library)) as connection, closing(_open(dynamic)) as stats:
        assignments = tuple(
            (_u64(pid), _u64(gid))
            for pid, gid in connection.execute(
                "SELECT pid,genius_id FROM item WHERE genius_id!=0 ORDER BY pid"
            )
        )
        dynamic_columns = {
            row[1] for row in stats.execute("PRAGMA table_info(item_stats)")
        }
        if "genius_id" in dynamic_columns:
            dynamic_ids = dict(
                stats.execute("SELECT item_pid,genius_id FROM item_stats")
            )
            if any(dynamic_ids.get(_s64(pid)) != _s64(gid) for pid, gid in assignments):
                raise ValueError("Library and Dynamic Genius identities disagree")
        mixes = tuple(
            SQLiteGeniusMixRecord(
                _u64(pid),
                name or "",
                tuple(
                    _u64(row[0])
                    for row in connection.execute(
                        "SELECT item_pid FROM item_to_container WHERE container_pid=? ORDER BY physical_order,rowid",
                        (pid,),
                    )
                ),
                tuple(
                    _u64(row[0])
                    for row in connection.execute(
                        "SELECT item_pid FROM container_seed WHERE container_pid=? ORDER BY seed_order,rowid",
                        (pid,),
                    )
                ),
            )
            for pid, name in connection.execute(
                "SELECT pid,name FROM container WHERE distinguished_kind=32 ORDER BY name_order,pid"
            )
        )
    return SQLiteGeniusState(parse_genius_database(genius).data, assignments, mixes)


def genius_mix_ids(
    retained: tuple[SQLiteSource, ...], update: SQLiteGeniusUpdate | None
) -> frozenset[int]:
    additions = () if update is None else update.mix_additions
    removals = () if update is None else update.mix_removals
    if update is not None and update.mixes is not None and (additions or removals):
        raise ValueError("Mix replacement and selective edits cannot be combined")
    added = tuple(mix.container_id for mix in additions)
    if len(set(added)) != len(added) or len(set(removals)) != len(removals):
        raise ValueError("Selective Genius Mix identities must be unique")
    for pid in (*added, *removals):
        _s64(pid)
        if not pid:
            raise ValueError("Genius Mix identities must be nonzero")
    if set(added) & set(removals):
        raise ValueError("A Genius Mix cannot be added and removed together")
    if update is not None and update.mixes is not None:
        identities = tuple(mix.container_id for mix in update.mixes)
        if len(set(identities)) != len(identities) or any(
            not pid for pid in identities
        ):
            raise ValueError("Genius Mix identities must be unique and nonzero")
        for pid in identities:
            _s64(pid)
        return frozenset(identities)
    source = _source(retained, "Library.itdb")
    if source is None:
        return frozenset(added)
    with closing(_open(source)) as connection:
        existing = frozenset(
            _u64(row[0])
            for row in connection.execute(
                "SELECT pid FROM container WHERE distinguished_kind=32"
            )
        )
        if existing & set(added):
            raise ValueError("A new Genius Mix collides with a retained Mix")
        return (existing - frozenset(removals)) | frozenset(added)


def project_genius_mixes(
    library: sqlite3.Connection,
    dynamic: sqlite3.Connection,
    retained: tuple[SQLiteSource, ...],
    update: SQLiteGeniusUpdate | None,
    pids: Mapping[int, int],
    replaced_tracks: frozenset[int],
) -> tuple[tuple[int, ...], tuple[tuple[int, int, int], ...]]:
    """Add explicitly authored or retained kind-32 containers to the projection."""

    containers: list[int] = []
    membership: list[tuple[int, int, int]] = []
    library_pids = frozenset(pids.values())
    if update is not None:
        validate_genius_update(update, pids)
    if update is not None and update.mixes is not None:
        existing: dict[int, dict[str, object]] = {}
        source = _source(retained, "Library.itdb")
        if source is not None:
            with closing(_open(source)) as original:
                original.row_factory = sqlite3.Row
                existing = {
                    int(row["pid"]): dict(row)
                    for row in original.execute(
                        "SELECT * FROM container WHERE distinguished_kind=32"
                    )
                }
        for order, mix in enumerate(update.mixes):
            pid = _s64(mix.container_id)
            if pid in existing:
                old = existing[pid]
                columns = tuple(
                    row[1]
                    for row in library.execute("PRAGMA table_info(container)")
                    if row[1] in old
                )
                library.execute(
                    f"INSERT INTO container ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                    tuple(
                        mix.name if name == "name" else old[name] for name in columns
                    ),
                )
            else:
                # Matches the complete new-container layout accepted by the
                # connected nano 7G experiment; retained Mix values stay owned
                # by their source unless an explicit input changes them.
                library.execute(
                    "INSERT INTO container (pid,distinguished_kind,date_created,date_modified,name,name_order,parent_pid,media_kinds,workout_template_id,is_hidden,smart_is_folder,smart_is_genius,smart_is_dynamic,smart_is_filtered,smart_limit_kind,smart_limit_value) VALUES (?,32,0,0,?,?,0,1,0,0,0,1,1,1,2,25)",
                    (pid, mix.name, 800 + 100 * order),
                )
            for position, track_id in enumerate(mix.track_ids):
                member = (_s64(pids[track_id]), pid, position)
                membership.append(member)
                library.execute(
                    "INSERT INTO item_to_container VALUES (?,?,?,0)", member
                )
            containers.append(mix.container_id)
    else:
        source = _source(retained, "Library.itdb")
        if source is not None:
            with closing(_open(source)) as original:
                names = tuple(
                    row[1] for row in library.execute("PRAGMA table_info(container)")
                )
                original.row_factory = sqlite3.Row
                deleted_pids = (
                    frozenset(
                        _u64(row["pid"])
                        for row in original.execute("SELECT pid FROM item")
                    )
                    - library_pids
                )
                live = (
                    frozenset(_s64(pid) for pid in pids.values()) - replaced_tracks
                    if update is None
                    else frozenset(
                        _s64(pids[track.track_id]) for track in update.tracks
                    )
                )
                for row in original.execute(
                    "SELECT * FROM container WHERE distinguished_kind=32"
                ):
                    if update is not None and _u64(row["pid"]) in update.mix_removals:
                        continue
                    members = tuple(
                        original.execute(
                            "SELECT item_pid,physical_order,shuffle_order FROM item_to_container WHERE container_pid=? ORDER BY rowid",
                            (row["pid"],),
                        )
                    )
                    # Only Track deletion removes an emptied retained Mix. A
                    # graph refresh or replacement may temporarily leave no
                    # assigned starting Tracks, but preserves its identity.
                    if (
                        members
                        and any(
                            _u64(item) in deleted_pids
                            for item, _position, _shuffle in members
                        )
                        and not any(
                            _u64(item) in library_pids
                            for item, _position, _shuffle in members
                        )
                    ):
                        continue
                    available = frozenset(row.keys())
                    supplied = tuple(name for name in names if name in available)
                    library.execute(
                        f"INSERT INTO container ({','.join(supplied)}) VALUES ({','.join('?' for _ in supplied)})",
                        tuple(row[name] for name in supplied),
                    )
                    pid = int(row["pid"])
                    containers.append(_u64(pid))
                    for item, position, shuffle in members:
                        if item in live:
                            membership.append((item, pid, position))
                            library.execute(
                                "INSERT INTO item_to_container VALUES (?,?,?,?)",
                                (item, pid, position, shuffle),
                            )
        if update is not None:
            for order, mix in enumerate(update.mix_additions, start=len(containers)):
                pid = _s64(mix.container_id)
                library.execute(
                    "INSERT INTO container (pid,distinguished_kind,date_created,date_modified,name,name_order,parent_pid,media_kinds,workout_template_id,is_hidden,smart_is_folder,smart_is_genius,smart_is_dynamic,smart_is_filtered,smart_limit_kind,smart_limit_value) VALUES (?,32,0,0,?,?,0,1,0,0,0,1,1,1,2,25)",
                    (pid, mix.name, 800 + 100 * order),
                )
                for position, track_id in enumerate(mix.track_ids):
                    member = (_s64(pids[track_id]), pid, position)
                    membership.append(member)
                    library.execute(
                        "INSERT INTO item_to_container VALUES (?,?,?,0)", member
                    )
                containers.append(mix.container_id)
    dynamic.executemany(
        "INSERT INTO container_ui VALUES (?,1,0,52,0,0,0)",
        ((_s64(pid),) for pid in containers),
    )
    return tuple(containers), tuple(membership)


def validate_genius_update(update: SQLiteGeniusUpdate, pids: Mapping[int, int]) -> None:
    """Validate explicit native input against checked semantic Track identities."""

    genius_mix_ids((), update)
    assignments = {track.track_id: track.genius_id for track in update.tracks}
    ids = set(assignments.values())
    if len(assignments) != len(update.tracks) or len(ids) != len(update.tracks):
        raise ValueError(
            "Genius Track assignments must have unique Track and Genius identities"
        )
    if not set(assignments) <= set(pids) or any(not gid for gid in ids):
        raise ValueError(
            "Genius assignments reference missing Tracks or zero Genius identities"
        )
    for gid in ids:
        _s64(gid)
    if {row.genius_id for row in update.data.metadata} != ids or {
        row.genius_id for row in update.data.similarities
    } != ids:
        raise ValueError("Genius graph must describe exactly the assigned Tracks")
    if len(update.data.metadata) != len(ids) or len(update.data.similarities) != len(
        ids
    ):
        raise ValueError("Genius graph identities must be unique")
    for metadata in update.data.metadata:
        if not isinstance(metadata.payload, GeniusMetadata):
            raise ValueError("Authored Genius metadata must use a supported variant")
    for row in update.data.similarities:
        if not isinstance(row.payload, GeniusSimilarities):
            raise ValueError(
                "Authored Genius similarities must use a supported variant"
            )
        if not set(row.payload.candidates) <= ids:
            raise ValueError("Genius candidate references an unassigned Track")
    if ids and not update.data.configs:
        raise ValueError("Authored Genius graph requires a configuration")
    for config in update.data.configs:
        if not isinstance(config.payload, GeniusConfig):
            raise ValueError(
                "Authored Genius configuration must use a supported variant"
            )
        if (
            config.default_num_results is None
            or config.min_num_results is None
            or not 0 <= config.min_num_results <= config.default_num_results
        ):
            raise ValueError("Invalid Genius result thresholds")
    for mix in (*(update.mixes or ()), *update.mix_additions):
        if not mix.track_ids or not set(mix.track_ids) <= set(assignments):
            raise ValueError("Genius Mix seeds must reference assigned Tracks")
        if mix.seed_track_id is not None and mix.seed_track_id not in mix.track_ids:
            raise ValueError("Genius Mix compatibility seed must belong to the Mix")


def reconcile_genius(
    library: sqlite3.Connection,
    dynamic: sqlite3.Connection,
    genius: sqlite3.Connection,
    retained: tuple[SQLiteSource, ...],
    update: SQLiteGeniusUpdate | None,
    pids: Mapping[int, int],
    replaced_tracks: frozenset[int],
) -> None:
    """Apply one coherent update, or prune relationships for removed media."""

    dynamic_columns = {
        row[1] for row in dynamic.execute("PRAGMA table_info(item_stats)")
    }
    if update is not None:
        library.execute("UPDATE item SET genius_id=0")
        if "genius_id" in dynamic_columns:
            dynamic.execute("UPDATE item_stats SET genius_id=0")
        for track in update.tracks:
            values = (_s64(track.genius_id), _s64(pids[track.track_id]))
            library.execute("UPDATE item SET genius_id=? WHERE pid=?", values)
            if "genius_id" in dynamic_columns:
                dynamic.execute(
                    "UPDATE item_stats SET genius_id=? WHERE item_pid=?", values
                )
        write_genius_data(genius, update.data)
        if update.mixes is None:
            # Retention keeps unknown columns and native seed/UI state. A graph
            # refresh only removes compatibility seeds no longer assigned to it.
            library.execute(
                "DELETE FROM container_seed WHERE container_pid IN (SELECT pid FROM container WHERE distinguished_kind=32) AND item_pid NOT IN (SELECT pid FROM item WHERE genius_id!=0)"
            )
        for mix in (*(update.mixes or ()), *update.mix_additions):
            pid = _s64(mix.container_id)
            seed = None if mix.seed_track_id is None else _s64(pids[mix.seed_track_id])
            if seed is None:
                library.execute(
                    "DELETE FROM container_seed WHERE container_pid=?", (pid,)
                )
            else:
                library.execute(
                    "DELETE FROM container_seed WHERE container_pid=? AND item_pid!=?",
                    (pid, seed),
                )
                if not library.execute(
                    "SELECT 1 FROM container_seed WHERE container_pid=? AND item_pid=?",
                    (pid, seed),
                ).fetchone():
                    library.execute(
                        "INSERT INTO container_seed (container_pid,item_pid,seed_order) VALUES (?,?,0)",
                        (pid, seed),
                    )
        return
    source = _source(retained, "Library.itdb")
    if source is None:
        return
    with closing(_open(source)) as original:
        old = dict(
            original.execute("SELECT pid,genius_id FROM item WHERE genius_id!=0")
        )
    for pid in replaced_tracks:
        library.execute("UPDATE item SET genius_id=0 WHERE pid=?", (pid,))
        if "genius_id" in dynamic_columns:
            dynamic.execute(
                "UPDATE item_stats SET genius_id=0 WHERE item_pid=?", (pid,)
            )
        library.execute(
            "DELETE FROM container_seed WHERE item_pid=? AND container_pid IN (SELECT pid FROM container WHERE distinguished_kind=32)",
            (pid,),
        )
    current = dict(library.execute("SELECT pid,genius_id FROM item WHERE genius_id!=0"))
    current_ids = frozenset(current.values())
    removed = frozenset(_u64(gid) for gid in old.values() if gid not in current_ids)
    if removed:
        data = read_genius_data(genius)
        pruned = prune_genius_data(data, removed)
        if pruned != data:
            write_genius_data(genius, pruned)
