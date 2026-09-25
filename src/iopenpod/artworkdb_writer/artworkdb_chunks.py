"""Binary ArtworkDB chunk parsing and serialization helpers."""

from __future__ import annotations

import logging
import os
import struct
from collections.abc import Mapping

from iopenpod.artworkdb_shared.binary import read_chunk_header, read_u16, read_u32, read_u64, total_length_is_valid
from iopenpod.artworkdb_shared.constants import (
    MHFD_HEADER_SIZE,
    MHIF_HEADER_SIZE,
    MHII_HEADER_SIZE,
    MHLA_HEADER_SIZE,
    MHLF_HEADER_SIZE,
    MHLI_HEADER_SIZE,
    MHNI_HEADER_SIZE,
    MHOD_HEADER_SIZE,
    MHSD_HEADER_SIZE,
    ArtworkDatasetType,
    ArtworkMhodType,
)
from iopenpod.artworkdb_shared.ithmb_paths import (
    ithmb_filename,
    ithmb_path_for_filename,
    normalize_ithmb_filename,
)
from iopenpod.artworkdb_shared.mhni import read_mhni_fields
from iopenpod.artworkdb_shared.mhod import decode_mhod_string_chunk, encode_mhod_string_body
from iopenpod.device.write_guard import DeviceWriteSafetyError

from .artwork_types import ArtworkEntry, ArtworkFormatPayload, ExistingFormatRef, IthmbLocation
from .ithmb_codecs import expected_size_bytes

logger = logging.getLogger(__name__)

IthmbLocationInput = IthmbLocation | tuple[str, int] | int | None


def _default_ithmb_filename(format_id: int) -> str:
    return ithmb_filename(format_id)


def _normalize_ithmb_filename(format_id: int, filename: str | None) -> str:
    """Return the basename stored in an ArtworkDB ithmb filename MHOD."""
    return normalize_ithmb_filename(format_id, filename)


def _ithmb_path_for_filename(artwork_dir: str, format_id: int, filename: str | None) -> str:
    return ithmb_path_for_filename(artwork_dir, format_id, filename)


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
    body = encode_mhod_string_body(mhod_type, string)
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
        children.append(_write_mhod_container(ArtworkMhodType.THUMBNAIL_IMAGE, _write_mhni(fmt_id, location, payload)))

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
    ds1 = _write_mhsd(ArtworkDatasetType.IMAGE_LIST, _write_mhli(entries, format_locations_map))
    ds2 = _write_mhsd(ArtworkDatasetType.PHOTO_ALBUM_LIST, _write_mhla())
    ds3 = _write_mhsd(ArtworkDatasetType.FILE_LIST, _write_mhlf(format_ids, image_sizes))
    return _write_mhfd([ds1, ds2, ds3], next_mhii_id, reference_mhfd)


def read_existing_artwork(artworkdb_path: str, artwork_dir: str) -> dict[int, dict]:
    """Read existing ArtworkDB entries as typed ithmb location refs."""
    try:
        with open(artworkdb_path, "rb") as f:
            data = f.read()
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise DeviceWriteSafetyError(
            "The existing ArtworkDB could not be read safely. iOpenPod stopped "
            f"before replacing artwork metadata: {exc}"
        ) from exc

    if len(data) < 32 or data[:4] != b"mhfd":
        raise _invalid_artworkdb("missing or truncated mhfd header")

    entries = {}
    try:
        mhfd_header = read_chunk_header(data, 0)
    except (ValueError, struct.error) as exc:
        raise _invalid_artworkdb(str(exc)) from exc
    mhfd_header_size = mhfd_header.header_size
    mhfd_total_size = mhfd_header.length_or_count
    child_count = read_u32(data, 20)
    if not total_length_is_valid(
        data,
        0,
        mhfd_header_size,
        mhfd_total_size,
        32,
    ):
        raise _invalid_artworkdb(
            f"invalid mhfd size header={mhfd_header_size} total={mhfd_total_size}"
        )

    offset = mhfd_header_size
    database_end = mhfd_total_size
    for child_index in range(child_count):
        if (
            offset + 14 > database_end
            or data[offset:offset + 4] != b"mhsd"
        ):
            raise _invalid_artworkdb(
                f"missing mhsd child {child_index} at offset {offset}"
            )
        mhsd_chunk = read_chunk_header(data, offset)
        mhsd_header = mhsd_chunk.header_size
        mhsd_total = mhsd_chunk.length_or_count
        ds_type = read_u16(data, offset + 12)
        if not total_length_is_valid(
            data,
            offset,
            mhsd_header,
            mhsd_total,
            14,
            database_end,
        ):
            raise _invalid_artworkdb(f"invalid mhsd chunk at offset {offset}")

        if ds_type == ArtworkDatasetType.IMAGE_LIST:
            dataset_end = offset + mhsd_total
            mhli_offset = offset + mhsd_header
            if (
                mhli_offset + 12 > dataset_end
                or data[mhli_offset:mhli_offset + 4] != b"mhli"
            ):
                raise _invalid_artworkdb(
                    f"missing mhli image list at offset {mhli_offset}"
                )
            mhli_chunk = read_chunk_header(data, mhli_offset)
            mhli_header = mhli_chunk.header_size
            mhii_count = mhli_chunk.length_or_count
            if mhli_header < 12 or mhli_offset + mhli_header > dataset_end:
                raise _invalid_artworkdb(
                    f"invalid mhli chunk at offset {mhli_offset}"
                )
            mhii_offset = mhli_offset + mhli_header
            for entry_index in range(mhii_count):
                if (
                    mhii_offset + 52 > dataset_end
                    or data[mhii_offset:mhii_offset + 4] != b"mhii"
                ):
                    raise _invalid_artworkdb(
                        f"missing mhii entry {entry_index} at offset {mhii_offset}"
                    )
                mhii_total = read_u32(data, mhii_offset + 8)
                if mhii_total < 52 or mhii_offset + mhii_total > dataset_end:
                    raise _invalid_artworkdb(
                        f"invalid mhii chunk at offset {mhii_offset}"
                    )
                entry = _parse_mhii_existing(
                    data,
                    mhii_offset,
                    mhii_total,
                    artwork_dir,
                )
                if entry:
                    entries[entry["img_id"]] = entry
                mhii_offset += mhii_total

        offset += mhsd_total

    return entries


def _invalid_artworkdb(detail: str) -> DeviceWriteSafetyError:
    return DeviceWriteSafetyError(
        "The existing ArtworkDB is malformed or truncated. iOpenPod stopped "
        f"before replacing artwork metadata ({detail})."
    )


def _parse_mhii_existing(data: bytes, offset: int, total_len: int, artwork_dir: str) -> dict | None:
    """Parse one MHII entry from an existing ArtworkDB."""
    entry_end = offset + total_len
    if offset + 52 > entry_end:
        raise _invalid_artworkdb(f"truncated mhii header at offset {offset}")

    header_size = read_u32(data, offset + 4)
    child_count = read_u32(data, offset + 12)
    img_id = read_u32(data, offset + 16)
    song_id = read_u64(data, offset + 20)
    src_img_size = read_u32(data, offset + 48)
    if header_size < 52 or header_size > total_len:
        raise _invalid_artworkdb(
            f"invalid mhii header size {header_size} at offset {offset}"
        )

    formats: dict[int, ExistingFormatRef] = {}
    child_offset = offset + header_size
    for child_index in range(child_count):
        if (
            child_offset + 14 > entry_end
            or data[child_offset:child_offset + 4] != b"mhod"
        ):
            raise _invalid_artworkdb(
                f"missing mhod child {child_index} at offset {child_offset}"
            )
        mhod_chunk = read_chunk_header(data, child_offset)
        mhod_header = mhod_chunk.header_size
        mhod_total = mhod_chunk.length_or_count
        mhod_type = read_u16(data, child_offset + 12)
        if not total_length_is_valid(data, child_offset, mhod_header, mhod_total, 14, entry_end):
            raise _invalid_artworkdb(
                f"invalid mhod chunk at offset {child_offset}"
            )

        if mhod_type == ArtworkMhodType.THUMBNAIL_IMAGE:
            mhni_offset = child_offset + mhod_header
            child_end = child_offset + mhod_total
            if (
                mhni_offset + MHNI_HEADER_SIZE > child_end
                or data[mhni_offset:mhni_offset + 4] != b"mhni"
            ):
                raise _invalid_artworkdb(
                    f"invalid mhni thumbnail at offset {mhni_offset}"
                )
            fields = read_mhni_fields(data, mhni_offset)
            format_id = fields.format_id
            ithmb_offset = fields.ithmb_offset
            img_size = fields.image_size
            ithmb_filename = _parse_mhni_filename(data, mhni_offset, child_end)
            ithmb_filename = _normalize_ithmb_filename(format_id, ithmb_filename)
            ithmb_path = _ithmb_path_for_filename(
                artwork_dir,
                format_id,
                ithmb_filename,
            )
            if os.path.exists(ithmb_path) and img_size > 0:
                formats[format_id] = ExistingFormatRef(
                    path=ithmb_path,
                    ithmb_offset=ithmb_offset,
                    size=img_size,
                    width=max(1, int(fields.image_width)),
                    height=max(1, int(fields.image_height)),
                    hpad=max(0, int(fields.horizontal_padding)),
                    vpad=max(0, int(fields.vertical_padding)),
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
    return decode_mhod_string_chunk(data, offset, total_len)


def _parse_mhni_filename(data: bytes, mhni_offset: int, container_end: int) -> str | None:
    """Read the MHOD type=3 filename child from an MHNI chunk."""
    if mhni_offset + 12 > container_end:
        return None
    mhni_chunk = read_chunk_header(data, mhni_offset)
    mhni_header = mhni_chunk.header_size
    mhni_total = mhni_chunk.length_or_count
    if mhni_header < MHNI_HEADER_SIZE:
        mhni_header = MHNI_HEADER_SIZE
    mhni_end = min(container_end, mhni_offset + mhni_total)
    child_offset = mhni_offset + mhni_header

    while child_offset + MHOD_HEADER_SIZE <= mhni_end:
        if data[child_offset:child_offset + 4] != b"mhod":
            break
        mhod_chunk = read_chunk_header(data, child_offset)
        mhod_header = mhod_chunk.header_size
        mhod_total = mhod_chunk.length_or_count
        mhod_type = read_u16(data, child_offset + 12)
        if mhod_header < MHOD_HEADER_SIZE or mhod_total < mhod_header:
            break
        if child_offset + mhod_total > mhni_end:
            break
        if mhod_type == ArtworkMhodType.FILE_NAME:
            return _parse_mhod_string(data, child_offset, mhod_total)
        child_offset += mhod_total

    return None
