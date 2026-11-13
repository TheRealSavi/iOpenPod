"""Shared retained-Chunk inspection for native Alarm Playlist projections."""

from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.shared.binary_struct import binary_fields
from iPodDB.shared.chunk import ChunkHeader, ParsedChunk


def has_captured_fields(row: ParsedChunk[ChunkHeader], *names: str) -> bool:
    required = set(names)
    return all(
        field.schema.offset + field.schema.size <= row.generic_header.header_length
        for field in binary_fields(row.header)
        if field.attribute_name in required
    )


def dataset_rows(
    dataset: ParsedChunk[MhsdHeader], marker: bytes, issues: list[str]
) -> tuple[ParsedChunk[ChunkHeader], ...]:
    if (
        len(dataset.children) != 1
        or dataset.children[0].generic_header.header_marker != marker
        or dataset.raw_trailing_data
    ):
        issues.append(
            "The native Playlist source has an unsupported dataset structure."
        )
        return ()
    container = dataset.children[0]
    if (
        container.raw_trailing_data
        or container.generic_header.length_or_child_count != len(container.children)
    ):
        issues.append("A native Library container has unrecognized trailing records.")
    return container.children
