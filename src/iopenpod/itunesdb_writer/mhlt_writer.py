"""MHLT Writer — Write track list chunks for iTunesDB.

MHLT (track list) wraps all MHIT (track) chunks and provides
the track count in its header.

Header layout (MHLT_HEADER_SIZE = 92 bytes):
    +0x00: 'mhlt' magic (4B)
    +0x04: header_length (4B)
    +0x08: track_count (4B)

Cross-referenced against:
  - src/iopenpod/itunesdb_parser/mhlt_parser.py
  - libgpod itdb_itunesdb.c: mk_mhlt()
"""

from iopenpod.itunesdb_shared.field_base import MHLT_HEADER_SIZE, write_list_chunk

from .mhit_writer import TrackInfo, write_mhit


def write_mhlt(tracks: list[TrackInfo], start_track_id: int, db_id_2: int,
               capabilities=None, db_version: int = 0) -> tuple[bytes, int]:
    """
    Write a complete MHLT chunk with all tracks.

    Args:
        tracks: List of TrackInfo objects
        start_track_id: Starting track ID (increments for each track)
        db_id_2: Database-wide ID from MHBD (written into every MHIT db_id_2_ref at offset 0x124)
        capabilities: Optional DeviceCapabilities for gapless/video filtering
        db_version: Database version — forwarded to write_mhit for header sizing

    Returns:
        Tuple of (complete MHLT chunk bytes, next available track ID)
    """

    # Build all track chunks first
    track_chunks = []
    track_id = start_track_id

    for track in tracks:
        try:
            mhit_data = write_mhit(track, track_id, db_id_2, capabilities=capabilities,
                                   db_version=db_version)
        except Exception as exc:
            raise type(exc)(
                f"{exc} (track #{track_id}: {track.artist!r} – {track.title!r})"
            ) from exc
        track_chunks.append(mhit_data)
        track_id += 1

    return write_list_chunk(b'mhlt', MHLT_HEADER_SIZE, track_chunks), track_id
