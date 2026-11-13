"""Standalone Alarm wire and Library fixtures shared by codec and workflow tests."""

import sqlite3
import struct
from contextlib import closing
from dataclasses import replace

from iPodDB.iTunesDB.builder.build_iTunesDB import (
    new_itunes_chunk,
    new_iTunesDB,
    new_string_mhod,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhip import DEFINITION as MHIP
from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import DEFINITION as MHIT
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhlp import DEFINITION as MHLP
from iPodDB.iTunesDB.shared.chunk_defs.mhlt import DEFINITION as MHLT
from iPodDB.iTunesDB.shared.chunk_defs.mhod import DEFINITION as MHOD
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.smart_prefs_mhod import (
    MhodSmartPrefsPayload,
    MhodSmartPrefsPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import DEFINITION as MHSD
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import DEFINITION as MHYP
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import IPodLibrary
from iPodDB.shared.chunk import ChunkHeader, EmptyChunkHeader, ParsedChunk
from iPodDB.SQLiteDB.schema import DYNAMIC_SCHEMA, LIBRARY_SCHEMA


def playlist_chunk(
    pid: int,
    *,
    master: int = 0,
    flags: int = 0,
    items: tuple[MhipHeader, ...] = (),
    smart: bool = False,
) -> ParsedChunk[MhypHeader]:
    metadata = (
        (
            new_itunes_chunk(
                MHOD,
                MhodHeader(mhod_type=MhodType.SMART_PLAYLIST_PREFERENCES),
                prefix=MhodSmartPrefsPrefix(),
                payload=MhodSmartPrefsPayload(),
            ),
        )
        if smart
        else ()
    )
    return new_itunes_chunk(
        MHYP,
        MhypHeader(playlist_id=pid, master_flag=master, playlist_kind_flags=flags),
        children=(
            new_string_mhod(MhodType.TITLE, str(pid)),
            *metadata,
            *(new_itunes_chunk(MHIP, item) for item in items),
        ),
    )


def playlist_dataset(
    kind: int, rows: tuple[ParsedChunk[ChunkHeader], ...]
) -> ParsedChunk[MhsdHeader]:
    container = MHLT if kind == 1 else MHLP
    return new_itunes_chunk(
        MHSD,
        MhsdHeader(dataset_type=kind),
        children=(new_itunes_chunk(container, EmptyChunkHeader(), children=rows),),
    )


def playlist_library(*datasets: ParsedChunk[MhsdHeader]) -> IPodLibrary:
    return IPodLibrary.parse(
        write_iTunesDB(new_iTunesDB(MhbdHeader(), datasets=datasets))
    )


def track_dataset(*headers: MhitHeader) -> ParsedChunk[MhsdHeader]:
    return playlist_dataset(
        1, tuple(new_itunes_chunk(MHIT, header) for header in headers)
    )


def named_playlist_chunk(
    pid: int,
    name: str,
    *,
    master: bool = False,
    smart: bool = True,
    parent: int = 0,
    kind: int = 0,
) -> ParsedChunk[MhypHeader]:
    row = playlist_chunk(pid, master=int(master), smart=smart)
    return replace(
        row,
        header=replace(
            row.header, parent_folder_playlist_id=parent, phase_game_flag=kind
        ),
        children=(new_string_mhod(MhodType.TITLE, name), *row.children[1:]),
    )


def mini_alarm_source(*, mode: int = 8, playlist: int = 0) -> bytes:
    data = bytearray(0xB3C)
    struct.pack_into("<I", data, 0, 0x16)
    struct.pack_into("<H", data, 0xB18, 0xA5A0 | mode)
    struct.pack_into("<H", data, 0xB22, 0xD05A)
    struct.pack_into("<Q", data, 0xB24, playlist)
    return bytes(data)


def clock_field(tag: int, payload: bytes) -> bytes:
    return (
        struct.pack("<II", tag, len(payload))
        + payload
        + struct.pack("<I", 0x80000000 | tag)
    )


def nano5_sources(*, primary: int = 100) -> tuple[bytes, bytes]:
    with (
        closing(sqlite3.connect(":memory:")) as library,
        closing(sqlite3.connect(":memory:")) as dynamic,
    ):
        library.executescript(LIBRARY_SCHEMA)
        dynamic.executescript(DYNAMIC_SCHEMA)
        library.execute(
            "INSERT INTO db_info(pid,primary_container_pid) VALUES(1,?)", (primary,)
        )
        # Source PID/name order deliberately disagree. The final saved OTG stays.
        library.executemany(
            "INSERT INTO container(pid,name,name_order,distinguished_kind,media_kinds,is_hidden) VALUES(?,?,?,?,?,?)",
            (
                (100, "Library", 0, 0, 1, 1),
                (20, "Zebra", 1, 0, 1, 0),
                (30, "Alpha", 2, 17, 0, 0),
                (40, "Video", 3, 0, 2, 0),
                (50, "Podcasts", 4, 2, 4, 0),
                (60, "Hidden", 5, 0, 1, 1),
                (70, "On-The-Go 1", 6, 0, 1, 0),
            ),
        )
        dynamic.executemany(
            "INSERT INTO container_ui(container_pid) VALUES(?)",
            ((pid,) for pid in (100, 20, 30, 40, 50, 60, 70)),
        )
        library.commit()
        dynamic.commit()
        return library.serialize(), dynamic.serialize()
