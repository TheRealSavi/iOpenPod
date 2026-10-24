"""Prepare a new empty Library through the shared definition and write paths."""

from dataclasses import replace
from secrets import randbits

from iPodDB.iTunesDB.builder.build_iTunesDB import (
    new_itunes_chunk,
    new_iTunesDB,
    new_string_mhod,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhla import DEFINITION as MHLA
from iPodDB.iTunesDB.shared.chunk_defs.mhli import DEFINITION as MHLI
from iPodDB.iTunesDB.shared.chunk_defs.mhlp import DEFINITION as MHLP
from iPodDB.iTunesDB.shared.chunk_defs.mhlt import DEFINITION as MHLT
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import DEFINITION as MHSD
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import DEFINITION as MHYP
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.iTunesDB.shared.constants import MhodType
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library._playlist_writing import playlist_preferences
from iPodDB.library.database import IPodLibrary
from iPodDB.library.writing import LibraryWriteResult, WriteTarget
from iPodDB.shared.chunk import EmptyChunkHeader


def create_empty_library(
    device_name: str,
    target: WriteTarget,
    *,
    supports_podcasts: bool,
    mac_formatted: bool = False,
) -> LibraryWriteResult:
    """Return verified, signed artifacts without accessing a device.

    Creation requires an explicit Device Profile version. The unnamed seed is
    private: naming its Master Playlists runs ordinary Library preparation,
    including signature verification, CDB framing and the complete SQLite set.
    Existing database bytes never enter this API.
    """
    version = target.database_version
    if version is None or not 0 < version <= 0xFFFFFFFF:
        raise ValueError("Empty Library creation requires a database version")
    if not device_name.strip():
        raise ValueError("An empty Library requires an iPod name")
    database_id = randbits(64) or 1
    secondary_id = randbits(64) or 1
    master_id = randbits(64) or 1
    master = new_itunes_chunk(
        MHYP,
        MhypHeader(
            master_flag=1,
            playlist_id=master_id,
            playlist_id_2=master_id,
            db_id_2=secondary_id,
            sort_order=5,
            string_mhod_child_count=1,
        ),
        children=(new_string_mhod(MhodType.TITLE, ""), playlist_preferences()),
    )
    tracks = new_itunes_chunk(MHLT, EmptyChunkHeader())
    playlists = new_itunes_chunk(MHLP, EmptyChunkHeader(), children=(master,))
    # Original iOpenPod omits newer artist/stub datasets on older firmware.
    datasets = [
        (1, tracks),
        *(((3, playlists),) if supports_podcasts else ()),
        (2, playlists),
        (4, new_itunes_chunk(MHLA, EmptyChunkHeader())),
        *(
            (
                (8, new_itunes_chunk(MHLI, EmptyChunkHeader())),
                (6, tracks),
                (10, tracks),
            )
            if version > 0x19
            else ()
        ),
        (5, new_itunes_chunk(MHLP, EmptyChunkHeader())),
    ]
    document = new_iTunesDB(
        MhbdHeader(
            version=version,
            db_id=database_id,
            db_id_2=secondary_id,
            db_persistent_id=database_id,
            platform=1 if mac_formatted else 2,
        ),
        datasets=tuple(
            new_itunes_chunk(MHSD, MhsdHeader(dataset_type=kind), children=(child,))
            for kind, child in datasets
        ),
    )
    source = IPodLibrary.parse(write_iTunesDB(document))
    draft = source.begin_draft(replace(source.snapshot, device_name=device_name))
    return source.prepare(source.analyze(draft, target))
