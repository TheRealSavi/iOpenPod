"""Preserve positional playback evidence across changes to the Track table.

Format evidence: libgpod's playcounts_read and process_OTG_file in
https://github.com/gtkpod/libgpod/blob/master/src/itdb_itunesdb.c.
Rows and unknown header bytes are retained, not interpreted as new history.
"""

from __future__ import annotations

import struct

from iPodDB.sidecars.codec import parse_positional_sidecar


def remap_playback_sidecar(
    data: bytes, original_ids: tuple[int, ...], desired_ids: tuple[int, ...]
) -> bytes:
    """Remap mhdp rows or mhpo indexes, retaining every surviving opaque byte.

    Play Counts may cover only the original prefix of the Track table. New Tracks
    after that prefix need no invented playback record. An insertion inside that
    prefix is rejected because its unknown per-record fields have no known default.
    """
    table = parse_positional_sidecar(data)
    endian = table.byte_order
    counts = data[:4] in (b"mhdp", b"pdhm")
    header, count = table.header_size, len(table.rows)
    if len(set(original_ids)) != len(original_ids) or len(set(desired_ids)) != len(
        desired_ids
    ):
        raise ValueError("Playback preservation requires unique Track identities.")
    rows = table.rows
    output: list[bytes] = []
    if counts:
        if count > len(original_ids):
            raise ValueError(
                "Play Counts contains more entries than the original Track table."
            )
        by_id = dict(zip(original_ids[:count], rows, strict=True))
        gap = False
        for identity in desired_ids:
            row = by_id.get(identity)
            if row is None:
                gap = True
            elif gap:
                raise ValueError(
                    "New Tracks must follow Tracks with pending Play Counts."
                )
            else:
                output.append(row)
    else:
        positions = {identity: index for index, identity in enumerate(desired_ids)}
        for row in rows:
            position = int(struct.unpack_from(endian + "I", row)[0])
            if position >= len(original_ids):
                raise ValueError(
                    "On-The-Go Playlist references an unavailable Track position."
                )
            replacement = positions.get(original_ids[position])
            if replacement is not None:
                output.append(struct.pack(endian + "I", replacement) + row[4:])
    result = bytearray(data[:header])
    struct.pack_into(endian + "I", result, 12, len(output))
    return bytes(result) + b"".join(output)
