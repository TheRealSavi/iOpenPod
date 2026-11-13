"""Nano 5 Alarm choices from captured SQLite companions, without device I/O.

The firmware joins Library.container to Dynamic.container_ui in name_order,
then moves an eligible primary container to the front. Its temporary On-The-Go
row is created later; every eligible captured row is retained here.
"""

import sqlite3
from contextlib import closing

from iPodDB.library.alarm_playlists import AlarmPlaylist, AlarmPlaylistCatalog

_QUERY = """
SELECT container.pid, distinguished_kind, name, parent_pid, media_kinds,
       is_hidden, smart_is_folder, smart_is_dynamic, smart_is_filtered,
       smart_is_genius, smart_is_limited, smart_limit_kind, smart_limit_order,
       smart_limit_value, smart_reverse_limit_order, smart_criteria,
       description, container_ui.play_order, container_ui.is_reversed
FROM container, container_ui
WHERE container.pid IS NOT NULL AND name IS NOT NULL
  AND container.pid = container_ui.container_pid
ORDER BY name_order
"""
_MAPPED_MEDIA = (
    (1 << 0)
    | (1 << 1)
    | (1 << 2)
    | (1 << 3)
    | (1 << 5)
    | (1 << 6)
    | (1 << 8)
    | (1 << 15)
    | (1 << 20)
    | (1 << 21)
)
_AUDIO_MEDIA = (
    (1 << 0) | (1 << 2) | (1 << 3) | (1 << 5) | (1 << 8) | (1 << 20) | (1 << 21)
)


def project_sqlite_alarm_playlists(
    library: bytes, dynamic: bytes
) -> AlarmPlaylistCatalog:
    """Read the native user vector; source failures never yield partial indices."""
    try:
        with closing(sqlite3.connect(":memory:")) as connection:
            connection.deserialize(library)
            connection.execute("ATTACH DATABASE ':memory:' AS Dynamic")
            connection.deserialize(dynamic, name="Dynamic")
            connection.execute("PRAGMA trusted_schema=OFF")
            connection.setconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_TRIGGER, False)
            connection.execute("PRAGMA query_only=ON")
            for schema in ("main", "Dynamic"):
                if tuple(
                    row[0]
                    for row in connection.execute(f"PRAGMA {schema}.integrity_check")
                ) != ("ok",):
                    raise ValueError("The saved SQLite Playlist source is damaged.")
            info_rows = connection.execute(
                "SELECT pid, primary_container_pid, audio_language, subtitle_language FROM db_info"
            ).fetchmany(2)
            if len(info_rows) > 1:
                raise ValueError("The primary SQLite Playlist source is ambiguous.")
            info = info_rows[0] if info_rows else None
            primary = info[1] if info else 0
            if primary is None:
                primary = 0
            if type(primary) is not int:
                raise ValueError("The primary SQLite Playlist identity is unsupported.")
            rows: list[tuple[int, str]] = []
            identities: set[int] = set()
            orders = dict(connection.execute("SELECT pid,name_order FROM container"))
            selected_orders: set[int | None] = set()
            for row in connection.execute(_QUERY):
                pid, kind, name, _parent, media, hidden = row[:6]
                if not all(
                    type(value) is int for value in (pid, kind, media, hidden)
                ) or not isinstance(name, str):
                    raise ValueError(
                        "A saved SQLite Playlist has unsupported native values."
                    )
                if not pid or pid in identities:
                    raise ValueError("Saved SQLite Playlist identities are ambiguous.")
                identities.add(pid)
                if kind & 0xFFFFFFFF not in (0, 17, 101, 20, 25) or hidden & 0xFF:
                    continue
                if media & _MAPPED_MEDIA and not media & _AUDIO_MEDIA:
                    continue
                order = orders[pid]
                if order is not None and type(order) is not int:
                    raise ValueError(
                        "A saved SQLite Playlist has an unsupported sort position."
                    )
                if pid != primary:
                    # Native SQLite 3.5.9 specifies no tie-break here. Hidden
                    # rows and the primary moved to the front cannot create an
                    # ambiguity in the remaining user-vector positions.
                    if order in selected_orders:
                        raise ValueError(
                            "Saved SQLite Playlists have ambiguous Alarm sort positions."
                        )
                    selected_orders.add(order)
                entry = (pid, name)
                if pid == primary:
                    rows.insert(0, entry)
                else:
                    rows.append(entry)
            return AlarmPlaylistCatalog(
                tuple(
                    AlarmPlaylist(index, pid & 0xFFFFFFFFFFFFFFFF, name, False)
                    for index, (pid, name) in enumerate(rows)
                ),
                has_master=False,
            )
    except (sqlite3.Error, ValueError, OverflowError) as error:
        return AlarmPlaylistCatalog(
            issues=(f"Alarm Playlists: {error}",), has_master=False
        )
