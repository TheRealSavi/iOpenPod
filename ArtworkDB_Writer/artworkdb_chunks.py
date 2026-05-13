"""Binary ArtworkDB chunk parsing and serialization helpers."""

from __future__ import annotations

import logging
import os
import struct
from collections.abc import Mapping

from .artwork_types import ArtworkEntry, ArtworkFormatPayload, ExistingFormatRef, IthmbLocation
from .ithmb_codecs import expected_size_bytes

logger = logging.getLogger(__name__)

IthmbLocationInput = IthmbLocation | tuple[str, int] | int | None

# Header sizes (from real iPod Classic ArtworkDB)
MHFD_HEADER_SIZE = 132
MHSD_HEADER_SIZE = 96
MHLI_HEADER_SIZE = 92
MHLA_HEADER_SIZE = 92
MHLF_HEADER_SIZE = 92
MHII_HEADER_SIZE = 152
MHOD_HEADER_SIZE = 24
MHNI_HEADER_SIZE = 76
MHIF_HEADER_SIZE = 124


def _default_ithmb_filename(format_id: int) -> str:
    return f"F{int(format_id)}_1.ithmb"


def _normalize_ithmb_filename(format_id: int, filename: str | None) -> str:
    """Return the basename stored in an ArtworkDB ithmb filename MHOD."""
    name = (filename or "").strip().replace("\\", "/")
    if ":" in name:
        name = name.split(":")[-1]
    if "/" in name:
        name = name.rsplit("/", 1)[-1]
    return name or _default_ithmb_filename(format_id)


def _ithmb_path_for_filename(artwork_dir: str, format_id: int, filename: str | None) -> str:
    return os.path.join(artwork_dir, _normalize_ithmb_filename(format_id, filename))


def _coerce_ithmb_location(format_id: int, location: IthmbLocationInput) -> IthmbLocation:
    """Accept old offset-only maps while allowing filename-aware locations."""
    if isinstance(location, IthmbLocation):
        return IthmbLocation(
            _normalize_ithmb_filename(format_id, location.filename),
            int(location.offset),
        )
    if isinstance(location, tuple):
        filename, offset = location
        return IthmbLocation(_normalize_ithmb_filename(format_id, filename), int(offset))
    return IthmbLocation(_default_ithmb_filename(format_id), int(location or 0))


def _write_mhod_string(mhod_type: int, string: str) -> bytes:
    """Write an ArtworkDB MHOD string (type 1 or 3)."""
    if mhod_type == 3:
        encoded = string.encode("utf-16-le")
        encoding_byte = 2
    else:
        encoded = string.encode("utf-8")
        encoding_byte = 1

    str_len = len(encoded)
    padding = (4 - (str_len % 4)) % 4

    body = struct.pack("<I", str_len)
    body += struct.pack("<B", encoding_byte)
    body += b"\x00" * 3
    body += b"\x00" * 4
    body += encoded
    body += b"\x00" * padding

    total_len = MHOD_HEADER_SIZE + len(body)
    header = bytearray(MHOD_HEADER_SIZE)
    header[0:4] = b"mhod"
    struct.pack_into("<I", header, 4, MHOD_HEADER_SIZE)
    struct.pack_into("<I", header, 8, total_len)
    struct.pack_into("<H", header, 12, mhod_type)
    return bytes(header) + body


def _write_mhni(
    format_id: int,
    location: IthmbLocation,
    payload: ArtworkFormatPayload,
) -> bytes:
    """Write an MHNI chunk for one format payload."""
    filename = _normalize_ithmb_filename(format_id, location.filename)
    mhod3 = _write_mhod_string(3, f":{filename}")
    total_len = MHNI_HEADER_SIZE + len(mhod3)

    visible_h = int(payload.height)
    visible_w = int(payload.width)
    img_size = int(payload.size)
    stride = max(visible_w, int(payload.stride_pixels))
    vertical_padding = max(0, int(payload.vpad))
    horizontal_padding = max(0, int(payload.hpad))
    if vertical_padding == 0 and horizontal_padding == 0:
        expected_size = expected_size_bytes(format_id, visible_w, visible_h, stride_pixels=stride)
        if expected_size > 0 and expected_size != img_size:
            logger.debug(
                "ART: MHNI size mismatch for fmt %d: size=%d expected=%d; preserving stored dims",
                format_id,
                img_size,
                expected_size,
            )

    header = bytearray(MHNI_HEADER_SIZE)
    header[0:4] = b"mhni"
    struct.pack_into("<I", header, 4, MHNI_HEADER_SIZE)
    struct.pack_into("<I", header, 8, total_len)
    struct.pack_into("<I", header, 12, 1)
    struct.pack_into("<I", header, 16, format_id)
    struct.pack_into("<I", header, 20, int(location.offset))
    struct.pack_into("<I", header, 24, img_size)
    if vertical_padding > 0x7FFF or horizontal_padding > 0x7FFF:
        raise ValueError(
            f"MHNI padding too large for format {format_id}: vpad={vertical_padding} hpad={horizontal_padding}"
        )
    struct.pack_into("<h", header, 28, vertical_padding)
    struct.pack_into("<h", header, 30, horizontal_padding)
    struct.pack_into("<H", header, 32, visible_h)
    struct.pack_into("<H", header, 34, visible_w)
    struct.pack_into("<I", header, 40, img_size)
    return bytes(header) + mhod3


def _write_mhod_container(mhod_type: int, mhni_data: bytes) -> bytes:
    """Write a container MHOD wrapping an MHNI."""
    total_len = MHOD_HEADER_SIZE + len(mhni_data)
    header = bytearray(MHOD_HEADER_SIZE)
    header[0:4] = b"mhod"
    struct.pack_into("<I", header, 4, MHOD_HEADER_SIZE)
    struct.pack_into("<I", header, 8, total_len)
    struct.pack_into("<H", header, 12, mhod_type)
    return bytes(header) + mhni_data


def _write_mhii(entry: ArtworkEntry, format_locations: Mapping[int, IthmbLocationInput]) -> bytes:
    """Write an MHII image item chunk."""
    children = []
    for fmt_id in sorted(entry.formats.keys()):
        payload = entry.formats[fmt_id]
        location = _coerce_ithmb_location(fmt_id, format_locations.get(fmt_id, 0))
        children.append(_write_mhod_container(2, _write_mhni(fmt_id, location, payload)))

    children_data = b"".join(children)
    total_len = MHII_HEADER_SIZE + len(children_data)

    header = bytearray(MHII_HEADER_SIZE)
    header[0:4] = b"mhii"
    struct.pack_into("<I", header, 4, MHII_HEADER_SIZE)
    struct.pack_into("<I", header, 8, total_len)
    struct.pack_into("<I", header, 12, len(children))
    struct.pack_into("<I", header, 16, entry.img_id)
    struct.pack_into("<Q", header, 20, entry.db_track_id)
    struct.pack_into("<I", header, 48, entry.src_img_size)
    return bytes(header) + children_data


def _write_mhli(
    entries: list[ArtworkEntry],
    format_locations_map: Mapping[int, Mapping[int, IthmbLocationInput]],
) -> bytes:
    """Write MHLI containing all MHII entries."""
    children_data = b"".join(_write_mhii(entry, format_locations_map[entry.img_id]) for entry in entries)
    header = bytearray(MHLI_HEADER_SIZE)
    header[0:4] = b"mhli"
    struct.pack_into("<I", header, 4, MHLI_HEADER_SIZE)
    struct.pack_into("<I", header, 8, len(entries))
    return bytes(header) + children_data


def _write_mhla() -> bytes:
    """Write empty MHLA album list."""
    header = bytearray(MHLA_HEADER_SIZE)
    header[0:4] = b"mhla"
    struct.pack_into("<I", header, 4, MHLA_HEADER_SIZE)
    struct.pack_into("<I", header, 8, 0)
    return bytes(header)


def _write_mhif(format_id: int, image_size: int) -> bytes:
    """Write one MHIF file-info entry."""
    header = bytearray(MHIF_HEADER_SIZE)
    header[0:4] = b"mhif"
    struct.pack_into("<I", header, 4, MHIF_HEADER_SIZE)
    struct.pack_into("<I", header, 8, MHIF_HEADER_SIZE)
    struct.pack_into("<I", header, 16, format_id)
    struct.pack_into("<I", header, 20, image_size)
    return bytes(header)


def _write_mhlf(format_ids: list[int], image_sizes: dict[int, int]) -> bytes:
    """Write MHLF containing MHIF entries."""
    children_data = b"".join(_write_mhif(fmt_id, image_sizes[fmt_id]) for fmt_id in format_ids)
    header = bytearray(MHLF_HEADER_SIZE)
    header[0:4] = b"mhlf"
    struct.pack_into("<I", header, 4, MHLF_HEADER_SIZE)
    struct.pack_into("<I", header, 8, len(format_ids))
    return bytes(header) + children_data


def _write_mhsd(ds_type: int, child_data: bytes) -> bytes:
    """Write MHSD dataset wrapper."""
    total_len = MHSD_HEADER_SIZE + len(child_data)
    header = bytearray(MHSD_HEADER_SIZE)
    header[0:4] = b"mhsd"
    struct.pack_into("<I", header, 4, MHSD_HEADER_SIZE)
    struct.pack_into("<I", header, 8, total_len)
    struct.pack_into("<H", header, 12, ds_type)
    return bytes(header) + child_data


def _write_mhfd(datasets: list[bytes], next_mhii_id: int, reference_mhfd: bytes | None = None) -> bytes:
    """Write the ArtworkDB MHFD root chunk."""
    all_data = b"".join(datasets)
    total_len = MHFD_HEADER_SIZE + len(all_data)
    header = bytearray(MHFD_HEADER_SIZE)
    header[0:4] = b"mhfd"
    struct.pack_into("<I", header, 4, MHFD_HEADER_SIZE)
    struct.pack_into("<I", header, 8, total_len)
    struct.pack_into("<I", header, 16, 2)
    struct.pack_into("<I", header, 20, len(datasets))
    struct.pack_into("<I", header, 28, next_mhii_id)

    if reference_mhfd and len(reference_mhfd) >= 48:
        header[32:48] = reference_mhfd[32:48]

    struct.pack_into("<I", header, 48, 2)

    if reference_mhfd and len(reference_mhfd) >= 68:
        header[60:68] = reference_mhfd[60:68]

    return bytes(header) + all_data


def build_artworkdb(
    entries: list[ArtworkEntry],
    format_locations_map: Mapping[int, Mapping[int, IthmbLocationInput]],
    format_ids: list[int],
    image_sizes: dict[int, int],
    next_mhii_id: int,
    reference_mhfd: bytes | None = None,
) -> bytes:
    """Serialize a complete ArtworkDB binary."""
    ds1 = _write_mhsd(1, _write_mhli(entries, format_locations_map))
    ds2 = _write_mhsd(2, _write_mhla())
    ds3 = _write_mhsd(3, _write_mhlf(format_ids, image_sizes))
    return _write_mhfd([ds1, ds2, ds3], next_mhii_id, reference_mhfd)


def read_existing_artwork(artworkdb_path: str, artwork_dir: str) -> dict[int, dict]:
    """Read existing ArtworkDB entries as typed ithmb location refs."""
    if not os.path.exists(artworkdb_path):
        return {}

    try:
        with open(artworkdb_path, "rb") as f:
            data = f.read()
    except Exception as exc:
        logger.warning("ART: failed to read existing ArtworkDB: %s", exc)
        return {}

    if len(data) < 32 or data[:4] != b"mhfd":
        return {}

    entries = {}
    mhfd_header_size = struct.unpack_from("<I", data, 4)[0]
    child_count = struct.unpack_from("<I", data, 20)[0]
    if mhfd_header_size < 32 or mhfd_header_size > len(data):
        logger.warning("ART: invalid ArtworkDB mhfd header size %d", mhfd_header_size)
        return {}

    offset = mhfd_header_size
    for _ in range(child_count):
        if offset + 14 > len(data) or data[offset:offset + 4] != b"mhsd":
            break
        mhsd_header = struct.unpack_from("<I", data, offset + 4)[0]
        mhsd_total = struct.unpack_from("<I", data, offset + 8)[0]
        ds_type = struct.unpack_from("<H", data, offset + 12)[0]
        if mhsd_header < 14 or mhsd_total < mhsd_header or offset + mhsd_total > len(data):
            logger.warning("ART: invalid ArtworkDB mhsd chunk at offset %d", offset)
            break

        if ds_type == 1:
            dataset_end = offset + mhsd_total
            mhli_offset = offset + mhsd_header
            if mhli_offset + 12 <= dataset_end and data[mhli_offset:mhli_offset + 4] == b"mhli":
                mhli_header = struct.unpack_from("<I", data, mhli_offset + 4)[0]
                mhii_count = struct.unpack_from("<I", data, mhli_offset + 8)[0]
                if mhli_header < 12 or mhli_offset + mhli_header > dataset_end:
                    logger.warning("ART: invalid ArtworkDB mhli chunk at offset %d", mhli_offset)
                    break
                mhii_offset = mhli_offset + mhli_header
                for _ in range(mhii_count):
                    if mhii_offset + 52 > dataset_end or data[mhii_offset:mhii_offset + 4] != b"mhii":
                        break
                    mhii_total = struct.unpack_from("<I", data, mhii_offset + 8)[0]
                    if mhii_total < 52 or mhii_offset + mhii_total > dataset_end:
                        logger.warning("ART: invalid ArtworkDB mhii chunk at offset %d", mhii_offset)
                        break
                    entry = _parse_mhii_existing(data, mhii_offset, mhii_total, artwork_dir)
                    if entry:
                        entries[entry["img_id"]] = entry
                    mhii_offset += mhii_total

        offset += mhsd_total

    return entries


def _parse_mhii_existing(data: bytes, offset: int, total_len: int, artwork_dir: str) -> dict | None:
    """Parse one MHII entry from an existing ArtworkDB."""
    entry_end = offset + total_len
    if offset + 52 > entry_end:
        return None

    header_size = struct.unpack_from("<I", data, offset + 4)[0]
    child_count = struct.unpack_from("<I", data, offset + 12)[0]
    img_id = struct.unpack_from("<I", data, offset + 16)[0]
    song_id = struct.unpack_from("<Q", data, offset + 20)[0]
    src_img_size = struct.unpack_from("<I", data, offset + 48)[0]
    if header_size < 52 or header_size > total_len:
        logger.warning("ART: invalid ArtworkDB mhii header size %d at offset %d", header_size, offset)
        return None

    formats: dict[int, ExistingFormatRef] = {}
    child_offset = offset + header_size
    for _ in range(child_count):
        if child_offset + 14 > entry_end or data[child_offset:child_offset + 4] != b"mhod":
            break
        mhod_header = struct.unpack_from("<I", data, child_offset + 4)[0]
        mhod_total = struct.unpack_from("<I", data, child_offset + 8)[0]
        mhod_type = struct.unpack_from("<H", data, child_offset + 12)[0]
        if mhod_header < 14 or mhod_total < mhod_header or child_offset + mhod_total > entry_end:
            logger.warning("ART: invalid ArtworkDB mhod chunk at offset %d", child_offset)
            break

        if mhod_type == 2:
            mhni_offset = child_offset + mhod_header
            child_end = child_offset + mhod_total
            if mhni_offset + MHNI_HEADER_SIZE <= child_end and data[mhni_offset:mhni_offset + 4] == b"mhni":
                format_id = struct.unpack_from("<I", data, mhni_offset + 16)[0]
                ithmb_offset = struct.unpack_from("<I", data, mhni_offset + 20)[0]
                img_size = struct.unpack_from("<I", data, mhni_offset + 24)[0]
                ithmb_filename = _parse_mhni_filename(data, mhni_offset, child_end)
                ithmb_filename = _normalize_ithmb_filename(format_id, ithmb_filename)
                ithmb_path = _ithmb_path_for_filename(artwork_dir, format_id, ithmb_filename)
                if os.path.exists(ithmb_path) and img_size > 0:
                    formats[format_id] = ExistingFormatRef(
                        path=ithmb_path,
                        ithmb_offset=ithmb_offset,
                        size=img_size,
                        width=max(1, int(struct.unpack_from("<H", data, mhni_offset + 34)[0])),
                        height=max(1, int(struct.unpack_from("<H", data, mhni_offset + 32)[0])),
                        hpad=max(0, int(struct.unpack_from("<h", data, mhni_offset + 30)[0])),
                        vpad=max(0, int(struct.unpack_from("<h", data, mhni_offset + 28)[0])),
                        ithmb_filename=ithmb_filename,
                    )

        child_offset += mhod_total

    if not formats:
        return None

    return {
        "img_id": img_id,
        "song_id": song_id,
        "src_img_size": src_img_size,
        "formats": formats,
    }


def _parse_mhod_string(data: bytes, offset: int, total_len: int) -> str | None:
    """Parse an ArtworkDB string MHOD body."""
    if offset + MHOD_HEADER_SIZE + 12 > offset + total_len:
        return None
    header_size = struct.unpack_from("<I", data, offset + 4)[0]
    if header_size < MHOD_HEADER_SIZE or header_size > total_len:
        return None
    body_offset = offset + header_size
    body_end = offset + total_len
    if body_offset + 12 > body_end:
        return None

    str_len = struct.unpack_from("<I", data, body_offset)[0]
    encoding_byte = data[body_offset + 4]
    raw_start = body_offset + 12
    raw_end = min(body_end, raw_start + str_len)
    raw = data[raw_start:raw_end]
    try:
        if encoding_byte == 2:
            return raw.decode("utf-16-le", errors="replace").rstrip("\x00")
        return raw.decode("utf-8", errors="replace").rstrip("\x00")
    except UnicodeError:
        return None


def _parse_mhni_filename(data: bytes, mhni_offset: int, container_end: int) -> str | None:
    """Read the MHOD type=3 filename child from an MHNI chunk."""
    if mhni_offset + 12 > container_end:
        return None
    mhni_header = struct.unpack_from("<I", data, mhni_offset + 4)[0]
    mhni_total = struct.unpack_from("<I", data, mhni_offset + 8)[0]
    if mhni_header < MHNI_HEADER_SIZE:
        mhni_header = MHNI_HEADER_SIZE
    mhni_end = min(container_end, mhni_offset + mhni_total)
    child_offset = mhni_offset + mhni_header

    while child_offset + MHOD_HEADER_SIZE <= mhni_end:
        if data[child_offset:child_offset + 4] != b"mhod":
            break
        mhod_header = struct.unpack_from("<I", data, child_offset + 4)[0]
        mhod_total = struct.unpack_from("<I", data, child_offset + 8)[0]
        mhod_type = struct.unpack_from("<H", data, child_offset + 12)[0]
        if mhod_header < MHOD_HEADER_SIZE or mhod_total < mhod_header:
            break
        if child_offset + mhod_total > mhni_end:
            break
        if mhod_type == 3:
            return _parse_mhod_string(data, child_offset, mhod_total)
        child_offset += mhod_total

    return None
