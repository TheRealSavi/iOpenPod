"""Bounded directory and counted-block codecs for the pinned Classic 2.0.5 UI.

The directory owns resource locations. Callers must not search for matching byte
strings: distinct resources can contain identical data. Input hash qualification
remains the builder's responsibility.
"""

import struct

UI_BANK_OFFSET = 4_249_716
UI_BANK_VERSION = 3
UI_DIRECTORY_BYTES = 97_056
UI_KIND_COUNT = 27
# Shared with the native installer through the generated menu_resources.h.
RESOURCE_SCRATCH_BYTES = 2560
BANK_HEADER = struct.Struct("<III")
KIND_ENTRY = struct.Struct("<4I")
RESOURCE_ENTRY = struct.Struct("<3I")


def stock_resource_locations(raw: bytes) -> dict[tuple[str, int], tuple[int, int]]:
    """Return validated file spans keyed by native resource type and ID."""
    bank = UI_BANK_OFFSET
    if len(raw) < bank + UI_DIRECTORY_BYTES:
        raise ValueError("Truncated Classic UI bank directory")
    if BANK_HEADER.unpack_from(raw, bank) != (
        UI_BANK_VERSION,
        UI_DIRECTORY_BYTES,
        UI_KIND_COUNT,
    ):
        raise ValueError("Unexpected Classic UI bank")
    index_end = BANK_HEADER.size + UI_KIND_COUNT * KIND_ENTRY.size
    result: dict[tuple[str, int], tuple[int, int]] = {}
    kinds: set[str] = set()
    for index in range(UI_KIND_COUNT):
        kind_word, count, _, table = KIND_ENTRY.unpack_from(
            raw, bank + BANK_HEADER.size + index * KIND_ENTRY.size
        )
        try:
            kind = kind_word.to_bytes(4, "big").decode("ascii")
        except UnicodeDecodeError as error:
            raise ValueError("Invalid UI resource type") from error
        if kind in kinds:
            raise ValueError("Duplicate UI resource type")
        kinds.add(kind)
        if (
            table < index_end
            or table + count * RESOURCE_ENTRY.size > UI_DIRECTORY_BYTES
        ):
            raise ValueError("UI resource index exceeds bank directory")
        for item in range(count):
            resource_id, offset, size = RESOURCE_ENTRY.unpack_from(
                raw, bank + table + item * RESOURCE_ENTRY.size
            )
            start = bank + UI_DIRECTORY_BYTES + offset
            key = kind, resource_id
            if start > len(raw) or size > len(raw) - start or key in result:
                raise ValueError("Invalid UI resource entry")
            result[key] = start, size
    return result


def stock_resources(raw: bytes) -> dict[tuple[str, int], bytes]:
    """Read the stock English bank using its validated directory."""
    return {
        key: raw[start : start + size]
        for key, (start, size) in stock_resource_locations(raw).items()
    }


def u32(data: bytes | bytearray, offset: int) -> int:
    return int(struct.unpack_from("<I", data, offset)[0])


def put(data: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<I", data, offset, value)


def blocks(data: bytes) -> list[tuple[int, bytes]]:
    cursor = 4
    output: list[tuple[int, bytes]] = []
    if len(data) < 4:
        raise ValueError("Truncated UI resource")
    for _ in range(u32(data, 0)):
        if cursor + 8 > len(data):
            raise ValueError("Truncated UI block header")
        size, kind = struct.unpack_from("<II", data, cursor)
        start = cursor + 8
        if size > len(data) - start:
            raise ValueError("Truncated UI resource block")
        output.append((kind, data[start : start + size]))
        cursor = (start + size + 3) & ~3
    if cursor != len(data):
        raise ValueError("UI resource has unexpected trailing data")
    return output


def pack_blocks(items: list[tuple[int, bytes]]) -> bytes:
    data = bytearray(struct.pack("<I", len(items)))
    for kind, body in items:
        data.extend(struct.pack("<II", len(body), kind))
        data.extend(body)
        data.extend(bytes(-len(data) % 4))
    return bytes(data)
