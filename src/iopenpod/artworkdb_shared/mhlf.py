"""MHLF/MHIF helpers for ArtworkDB file-format lists."""

from __future__ import annotations

from .binary import read_chunk_header, read_u16, read_u32, total_length_is_valid
from .constants import ArtworkDatasetType


def extract_format_ids(data: bytes | bytearray) -> list[int]:
    """Extract correlation IDs from MHIF entries in an ArtworkDB binary."""
    if len(data) < 32 or data[:4] != b"mhfd":
        return []

    result: list[int] = []
    mhfd_header = read_chunk_header(data, 0)
    child_count = read_u32(data, 20)
    offset = mhfd_header.header_size

    for _ in range(child_count):
        if offset + 14 > len(data) or data[offset:offset + 4] != b"mhsd":
            break
        mhsd_header = read_chunk_header(data, offset)
        mhsd_total = mhsd_header.length_or_count
        ds_type = read_u16(data, offset + 12)
        if not total_length_is_valid(data, offset, mhsd_header.header_size, mhsd_total, 14):
            break

        if ds_type == ArtworkDatasetType.FILE_LIST:
            dataset_end = offset + mhsd_total
            mhlf_offset = offset + mhsd_header.header_size
            if mhlf_offset + 12 <= dataset_end and data[mhlf_offset:mhlf_offset + 4] == b"mhlf":
                mhlf_header = read_chunk_header(data, mhlf_offset)
                mhif_count = mhlf_header.length_or_count
                mhif_offset = mhlf_offset + mhlf_header.header_size
                for _ in range(mhif_count):
                    if mhif_offset + 20 > dataset_end or data[mhif_offset:mhif_offset + 4] != b"mhif":
                        break
                    mhif_size = read_u32(data, mhif_offset + 4)
                    if mhif_size < 20 or mhif_offset + mhif_size > dataset_end:
                        break
                    result.append(read_u32(data, mhif_offset + 16))
                    mhif_offset += mhif_size

        offset += mhsd_total

    return result

