"""Parser bridge — wraps the existing iTunesDB parser to produce ParsedDatabase objects.

The bridge re-walks the raw binary using the parser's chunk boundaries, then
compares against the canonical field_schema to identify every byte the parser
does NOT cover (unknown territory).
"""

from __future__ import annotations

import logging
import struct
from pathlib import Path
from typing import Any

from iTunesDB_Shared.constants import get_version_name

from .field_schema import unknown_ranges
from .models import ChunkRecord, ParsedDatabase, UnknownRegion

logger = logging.getLogger(__name__)

# Minimum chunk header size shared by all iTunesDB chunks.
_MIN_HEADER = 12
_UINT32_LE = struct.Struct("<I")


def ingest(path: str | Path) -> ParsedDatabase:
    """Parse an iTunesDB binary file and return a fully annotated ParsedDatabase.

    This function:
      1. Reads the raw binary.
      2. Recursively walks the chunk tree, building ChunkRecord nodes.
      3. For each chunk, computes the unknown byte regions via field_schema.
      4. Collects every chunk and unknown into the ParsedDatabase.
    """
    path = Path(path)
    data = path.read_bytes()
    file_size = len(data)

    if file_size < _MIN_HEADER:
        raise ValueError(f"File too small to be an iTunesDB: {file_size} bytes")

    tag = data[0:4]
    if tag != b"mhbd":
        raise ValueError(f"Not an iTunesDB file (expected 'mhbd', got {tag!r})")

    all_chunks: list[ChunkRecord] = []
    all_unknowns: list[UnknownRegion] = []

    root = _walk_chunk(data, 0, all_chunks, all_unknowns)

    # Extract top-level metadata from the mhbd record.
    pf = root.parsed_fields
    db_version = pf.get("version", 0)

    return ParsedDatabase(
        file_path=str(path),
        file_size=file_size,
        db_version=db_version,
        db_version_name=get_version_name(db_version),
        platform=pf.get("platform", 0),
        hashing_scheme=pf.get("hashing_scheme", 0),
        root=root,
        all_chunks=all_chunks,
        unknowns=all_unknowns,
    )


# ────────────────────────────────────────────────────────────────────
# Recursive chunk walker
# ────────────────────────────────────────────────────────────────────

# Sets of chunk types that use the third generic-header word as total_length
# vs. child_count.  Items use total_length; lists use child_count.
_TOTAL_LENGTH_CHUNKS = {"mhit", "mhyp", "mhia", "mhii", "mhip", "mhod", "mhbd", "mhsd"}
_CHILD_COUNT_CHUNKS = {"mhlt", "mhla", "mhli", "mhlp"}

# Map chunk type → how to read child structures.
# "total_length": children start at offset + header_length, iterate until total_length consumed.
# "child_count": children start at offset + header_length, iterate child_count times.
# For mhbd: child_count is at 0x14, NOT at 0x08.


def _read_tag(data: bytes, offset: int) -> str:
    """Read the 4-byte ASCII chunk tag at offset."""
    return data[offset:offset + 4].decode("ascii", errors="replace")


def _walk_chunk(
    data: bytes,
    offset: int,
    all_chunks: list[ChunkRecord],
    all_unknowns: list[UnknownRegion],
) -> ChunkRecord:
    """Recursively parse a single chunk and all its children."""
    tag = _read_tag(data, offset)
    header_length = _UINT32_LE.unpack_from(data, offset + 4)[0]
    word3 = _UINT32_LE.unpack_from(data, offset + 8)[0]  # total_length or child_count

    # Determine total_length for navigation and child_count for iteration.
    parsed_fields = _extract_fields(data, offset, tag, header_length)
    total_length, child_count = _resolve_structure(
        tag, header_length, word3, parsed_fields,
    )

    raw_header = bytes(data[offset:offset + min(header_length, len(data) - offset)])

    rec = ChunkRecord(
        chunk_type=tag,
        abs_offset=offset,
        header_length=header_length,
        total_length=total_length,
        parsed_fields=parsed_fields,
        raw_header=raw_header,
    )
    all_chunks.append(rec)

    # Compute unknown regions for this chunk's header.
    for gap_start, gap_end in unknown_ranges(tag, header_length):
        if offset + gap_end <= len(data):
            region = UnknownRegion(
                chunk_type=tag,
                chunk_offset=offset,
                rel_offset=gap_start,
                length=gap_end - gap_start,
                raw_bytes=bytes(data[offset + gap_start:offset + gap_end]),
                header_length=header_length,
            )
            all_unknowns.append(region)

    # Parse children.
    if child_count > 0:
        child_offset = offset + header_length
        end_boundary = offset + total_length if total_length > 0 else len(data)

        for _ in range(child_count):
            if child_offset + _MIN_HEADER > len(data):
                break
            if child_offset >= end_boundary:
                break

            child_tag = _read_tag(data, child_offset)
            child_hl = _UINT32_LE.unpack_from(data, child_offset + 4)[0]
            child_w3 = _UINT32_LE.unpack_from(data, child_offset + 8)[0]
            child_pf = _extract_fields(data, child_offset, child_tag, child_hl)
            child_tl, child_cc = _resolve_structure(
                child_tag, child_hl, child_w3, child_pf,
            )

            child_rec = _walk_chunk(data, child_offset, all_chunks, all_unknowns)
            rec.children.append(child_rec)

            # Advance past this child.
            if child_tl > 0:
                child_offset += child_tl
            else:
                # List containers: use header_length to skip header, then
                # the child_count iteration handles sequential children.
                child_offset += child_hl

    return rec


def _resolve_structure(
    tag: str,
    header_length: int,
    word3: int,
    parsed_fields: dict[str, Any],
) -> tuple[int, int]:
    """Return (total_length, child_count) for a chunk.

    For mhbd: total_length=word3 (file size), child_count is at 0x14.
    For mhsd: total_length=word3, child_count=1 (always one child list).
    For items (mhit, mhyp, mhia, mhii, mhip): total_length=word3,
        child_count from parsed_fields.
    For mhod: total_length=word3, no children.
    For lists (mhlt, mhla, mhli, mhlp): total_length=0 (no enclosing
        length), child_count=word3.
    """
    if tag == "mhbd":
        return word3, parsed_fields.get("child_count", 0)
    if tag == "mhsd":
        return word3, 1  # always exactly 1 child
    if tag == "mhod":
        return word3, 0  # leaf node
    if tag in _CHILD_COUNT_CHUNKS:
        return 0, word3  # word3 is child_count
    # Items: word3 is total_length, child_count is in parsed_fields.
    if tag == "mhyp":
        # mhyp has two child groups: mhod + mhip
        mhod_cc = parsed_fields.get("mhod_child_count", 0)
        mhip_cc = parsed_fields.get("mhip_child_count", 0)
        return word3, mhod_cc + mhip_cc
    child_count = parsed_fields.get("child_count", 0)
    return word3, child_count


# ────────────────────────────────────────────────────────────────────
# Field extraction — re-reads known fields from raw binary
# ────────────────────────────────────────────────────────────────────

def _extract_fields(
    data: bytes,
    offset: int,
    tag: str,
    header_length: int,
) -> dict[str, Any]:
    """Extract known fields from a chunk using direct struct reads.

    This intentionally mirrors the defs layer but stays self-contained
    so the analysis module has zero coupling to the parser's internal
    import structure.
    """
    if tag == "mhbd":
        return _extract_mhbd(data, offset, header_length)
    if tag == "mhsd":
        return _extract_mhsd(data, offset)
    if tag == "mhit":
        return _extract_mhit(data, offset, header_length)
    if tag == "mhyp":
        return _extract_mhyp(data, offset, header_length)
    if tag == "mhia":
        return _extract_mhia(data, offset)
    if tag == "mhii":
        return _extract_mhii(data, offset)
    if tag == "mhip":
        return _extract_mhip(data, offset)
    if tag == "mhod":
        return _extract_mhod(data, offset)
    # Lists (mhlt, mhla, mhli, mhlp) — no fields beyond generic header.
    return {}


def _u32(data: bytes, off: int) -> int:
    return _UINT32_LE.unpack_from(data, off)[0]


def _u16(data: bytes, off: int) -> int:
    return struct.unpack_from("<H", data, off)[0]


def _u64(data: bytes, off: int) -> int:
    return struct.unpack_from("<Q", data, off)[0]


def _i32(data: bytes, off: int) -> int:
    return struct.unpack_from("<i", data, off)[0]


def _f32(data: bytes, off: int) -> float:
    return struct.unpack_from("<f", data, off)[0]


def _extract_mhbd(data: bytes, off: int, hl: int) -> dict[str, Any]:
    f: dict[str, Any] = {
        "compressed": _u32(data, off + 0x0C),
        "version": _u32(data, off + 0x10),
        "child_count": _u32(data, off + 0x14),
        "db_id": _u64(data, off + 0x18),
        "platform": _u16(data, off + 0x20),
        "unk0x22": _u16(data, off + 0x22),
        "db_id_2": _u64(data, off + 0x24),
        "unk0x2c": _u32(data, off + 0x2C),
        "hashing_scheme": _u16(data, off + 0x30),
        "language": _u16(data, off + 0x46),
        "db_persistent_id": _u64(data, off + 0x48),
        "unk0x50": _u32(data, off + 0x50),
        "unk0x54": _u32(data, off + 0x54),
        "timezone_offset": _i32(data, off + 0x6C),
        "hash_type_indicator": _u16(data, off + 0x70),
    }
    if hl >= 0xA2:
        f["audio_language"] = _u16(data, off + 0xA0)
    if hl >= 0xA4:
        f["subtitle_language"] = _u16(data, off + 0xA2)
    if hl >= 0xA6:
        f["unk0xa4"] = _u16(data, off + 0xA4)
    if hl >= 0xA8:
        f["unk0xa6"] = _u16(data, off + 0xA6)
    if hl >= 0xAA:
        f["cdb_flag"] = _u16(data, off + 0xA8)
    return f


def _extract_mhsd(data: bytes, off: int) -> dict[str, Any]:
    return {"dataset_type": _u32(data, off + 0x0C)}


def _extract_mhit(data: bytes, off: int, hl: int) -> dict[str, Any]:
    f: dict[str, Any] = {
        "child_count": _u32(data, off + 0x0C),
        "track_id": _u32(data, off + 0x10),
        "visible": _u32(data, off + 0x14),
        "filetype": _u32(data, off + 0x18),
        "vbr_flag": data[off + 0x1C],
        "mp3_flag": data[off + 0x1D],
        "compilation_flag": data[off + 0x1E],
        "rating": data[off + 0x1F],
        "last_modified": _u32(data, off + 0x20),
        "size": _u32(data, off + 0x24),
        "length": _u32(data, off + 0x28),
        "track_number": _u32(data, off + 0x2C),
        "total_tracks": _u32(data, off + 0x30),
        "year": _u32(data, off + 0x34),
        "bitrate": _u32(data, off + 0x38),
        "sample_rate_1": _u32(data, off + 0x3C),
        "volume": _i32(data, off + 0x40),
        "start_time": _u32(data, off + 0x44),
        "stop_time": _u32(data, off + 0x48),
        "sound_check": _u32(data, off + 0x4C),
        "play_count_1": _u32(data, off + 0x50),
        "play_count_2": _u32(data, off + 0x54),
        "last_played": _u32(data, off + 0x58),
        "disc_number": _u32(data, off + 0x5C),
        "total_discs": _u32(data, off + 0x60),
        "user_id": _u32(data, off + 0x64),
        "date_added": _u32(data, off + 0x68),
        "bookmark_time": _u32(data, off + 0x6C),
        "db_id": _u64(data, off + 0x70),
        "checked_flag": data[off + 0x78],
        "app_rating": data[off + 0x79],
        "bpm": _u16(data, off + 0x7A),
        "artwork_count": _u16(data, off + 0x7C),
        "audio_format_flag": _u16(data, off + 0x7E),
        "artwork_size": _u32(data, off + 0x80),
        "unk0x84": _u32(data, off + 0x84),
        "sample_rate_2": _f32(data, off + 0x88),
        "date_released": _u32(data, off + 0x8C),
        "mpeg_audio_type": _u16(data, off + 0x90),
        "explicit_flag": data[off + 0x92],
        "purchased_aac_flag": data[off + 0x93],
        "unk0x94": _u32(data, off + 0x94),
        "genius_category_id": _u32(data, off + 0x98),
    }
    # Extended fields — guarded by header_length.
    _cond = {
        0xA0: ("skip_count", lambda: _u32(data, off + 0x9C)),
        0xA4: ("last_skipped", lambda: _u32(data, off + 0xA0)),
        0xA5: ("has_artwork", lambda: data[off + 0xA4]),
        0xA6: ("skip_when_shuffling", lambda: data[off + 0xA5]),
        0xA7: ("remember_position", lambda: data[off + 0xA6]),
        0xA8: ("use_podcast_now_playing_flag", lambda: data[off + 0xA7]),
        0xB0: ("db_id_2", lambda: _u64(data, off + 0xA8)),
        0xB1: ("lyrics_flag", lambda: data[off + 0xB0]),
        0xB2: ("movie_flag", lambda: data[off + 0xB1]),
        0xB3: ("not_played_flag", lambda: data[off + 0xB2]),
        0xB4: ("unk0xB3", lambda: data[off + 0xB3]),
        0xB8: ("unk0xB4", lambda: _u32(data, off + 0xB4)),
        0xBC: ("pregap", lambda: _u32(data, off + 0xB8)),
        0xC4: ("sample_count", lambda: _u64(data, off + 0xBC)),
        0xC8: ("unk0xC4", lambda: _u32(data, off + 0xC4)),
        0xCC: ("postgap", lambda: _u32(data, off + 0xC8)),
        0xD0: ("encoder", lambda: _u32(data, off + 0xCC)),
        0xD4: ("media_type", lambda: _u32(data, off + 0xD0)),
        0xD8: ("season_number", lambda: _u32(data, off + 0xD4)),
        0xDC: ("episode_number", lambda: _u32(data, off + 0xD8)),
        0xE0: ("date_added_to_itunes", lambda: _u32(data, off + 0xDC)),
        0xE4: ("store_track_id", lambda: _u32(data, off + 0xE0)),
        0xE8: ("store_encoder_version", lambda: _u32(data, off + 0xE4)),
        0xEC: ("store_artist_id", lambda: _u32(data, off + 0xE8)),
        0xF0: ("unk0xEC", lambda: _u32(data, off + 0xEC)),
        0xF4: ("store_album_id", lambda: _u32(data, off + 0xF0)),
        0xF8: ("store_content_flag", lambda: _u32(data, off + 0xF4)),
        0xFC: ("gapless_audio_payload_size", lambda: _u32(data, off + 0xF8)),
        0x100: ("unk0xFC", lambda: _u32(data, off + 0xFC)),
        0x102: ("gapless_track_flag", lambda: _u16(data, off + 0x100)),
        0x104: ("gapless_album_flag", lambda: _u16(data, off + 0x102)),
        0x11C: ("unk0x118", lambda: _u32(data, off + 0x118)),
        0x120: ("unk0x11C", lambda: _u32(data, off + 0x11C)),
        0x124: ("album_id", lambda: _u32(data, off + 0x120)),
        0x12C: ("mhbd_id_ref", lambda: _u64(data, off + 0x124)),
        0x130: ("size_2", lambda: _u32(data, off + 0x12C)),
        0x134: ("unk0x130", lambda: _u32(data, off + 0x130)),
        0x164: ("artwork_id_ref", lambda: _u32(data, off + 0x160)),
        0x1E4: ("artist_id_ref", lambda: _u32(data, off + 0x1E0)),
        0x1F8: ("composer_id", lambda: _u32(data, off + 0x1F4)),
    }
    for min_hl, (name, reader) in _cond.items():
        if hl >= min_hl:
            f[name] = reader()
    return f


def _extract_mhyp(data: bytes, off: int, hl: int) -> dict[str, Any]:
    f: dict[str, Any] = {
        "mhod_child_count": _u32(data, off + 0x0C),
        "mhip_child_count": _u32(data, off + 0x10),
        "master_flag": data[off + 0x14],
        "flag1": data[off + 0x15],
        "flag2": data[off + 0x16],
        "flag3": data[off + 0x17],
        "timestamp": _u32(data, off + 0x18),
        "playlist_id": _u64(data, off + 0x1C),
        "unk0x24": _u32(data, off + 0x24),
        "string_mhod_child_count": _u16(data, off + 0x28),
        "podcast_flag": _u16(data, off + 0x2A),
        "sort_order": _u32(data, off + 0x2C),
    }
    if hl >= 0x44:
        f["db_id_2"] = _u64(data, off + 0x3C)
    if hl >= 0x4C:
        f["playlist_id_2"] = _u64(data, off + 0x44)
    if hl >= 0x52:
        f["mhsd5_type"] = _u16(data, off + 0x50)
    if hl >= 0x5C:
        f["timestamp_2"] = _u32(data, off + 0x58)
    return f


def _extract_mhia(data: bytes, off: int) -> dict[str, Any]:
    return {
        "child_count": _u32(data, off + 0x0C),
        "album_id": _u32(data, off + 0x10),
        "sql_id": _u64(data, off + 0x14),
        "platform_flag": _u16(data, off + 0x1C),
        "album_compilation_flag": _u16(data, off + 0x1E),
    }


def _extract_mhii(data: bytes, off: int) -> dict[str, Any]:
    return {
        "child_count": _u32(data, off + 0x0C),
        "artist_id": _u32(data, off + 0x10),
        "sql_id": _u64(data, off + 0x14),
        "platform_flag": _u32(data, off + 0x1C),
    }


def _extract_mhip(data: bytes, off: int) -> dict[str, Any]:
    return {
        "child_count": _u32(data, off + 0x0C),
        "podcast_group_flag": _u16(data, off + 0x10),
        "unk0x12": _u16(data, off + 0x12),
        "group_id": _u32(data, off + 0x14),
        "track_id": _u32(data, off + 0x18),
        "timestamp": _u32(data, off + 0x1C),
        "group_id_ref": _u32(data, off + 0x20),
    }


def _extract_mhod(data: bytes, off: int) -> dict[str, Any]:
    return {
        "mhod_type": _u32(data, off + 0x0C),
        "unk0x10": _u32(data, off + 0x10),
        "unk0x14": _u32(data, off + 0x14),
    }
