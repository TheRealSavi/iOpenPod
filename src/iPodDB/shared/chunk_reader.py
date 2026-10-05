import struct
from dataclasses import replace
from typing import Any

from iPodDB.shared.binary_struct import (
    binary_struct_extent,
    parse_binary_struct,
    read_child_counts,
)
from iPodDB.shared.chunk import (
    ChunkAncestor,
    ChunkHeader,
    ChunkPayload,
    GenericHeader,
    MhodChunkHeader,
    MhodPayload,
    MhodPayloadPrefix,
    MhsdChunkHeader,
    ParsedChunk,
    ParsedMhodPayload,
    RawPayload,
    UnknownChunkHeader,
    UnknownMhodPayload,
    chunk_as,
)
from iPodDB.shared.diagnostics import log_unknown_data, report_unknown_data
from iPodDB.shared.errors import (
    InvalidChunkDataError,
    InvalidChunkLengthError,
    TruncatedChunkError,
    UnexpectedHeaderMarkerError,
    UnknownMhodLayoutError,
    iPodDBParseError,
)
from iPodDB.shared.types import (
    ChunkDefinition,
    ContextualMhodPayloadSpec,
    DatabaseParserDefinition,
    MhodPayloadParseContext,
    MhodPayloadSpecSelectionContext,
    MHODTypeID,
    MhsdDatasetDefinition,
)


def parse_mhod_payload[RootH: ChunkHeader](
    data: bytes | bytearray,
    *,
    chunk_offset: int,
    header_end: int,
    chunk_end: int,
    header: MhodChunkHeader,
    ancestors: tuple[ChunkAncestor, ...],
    parser_definition: DatabaseParserDefinition[RootH],
) -> ParsedMhodPayload:
    try:
        return _parse_mhod_payload(
            data,
            chunk_offset=chunk_offset,
            header_end=header_end,
            chunk_end=chunk_end,
            header=header,
            ancestors=ancestors,
            parser_definition=parser_definition,
        )
    except UnknownMhodLayoutError as error:
        report_unknown_data(
            f"MHOD {header.mhod_type} unknown layout ({error})",
            header_end,
            chunk_end - header_end,
        )
        return ParsedMhodPayload(
            None,
            UnknownMhodPayload(
                bytes(data[header_end:chunk_end]),
                header.mhod_type,
                ancestors[-1].generic_header.header_marker if ancestors else None,
            ),
        )


def _parse_mhod_payload[RootH: ChunkHeader](
    data: bytes | bytearray,
    *,
    chunk_offset: int,
    header_end: int,
    chunk_end: int,
    header: MhodChunkHeader,
    ancestors: tuple[ChunkAncestor, ...],
    parser_definition: DatabaseParserDefinition[RootH],
) -> ParsedMhodPayload:
    """
    Resolve and parse the payload belonging to an MHOD chunk.

    This function is the intentional runtime type-erasure boundary.

    Registration-time helpers guarantee prefix/parser compatibility.
    At runtime, the MHOD type determines which heterogeneous
    specification is selected.
    """

    mhod_type = MHODTypeID(header.mhod_type)

    mhod_spec = parser_definition.mhod_spec(mhod_type)

    selected_spec = mhod_spec.payload_spec

    if isinstance(selected_spec, ContextualMhodPayloadSpec):
        payload_spec = selected_spec.resolver(
            MhodPayloadSpecSelectionContext(
                data=data,
                mhod_type=mhod_type,
                chunk_offset=chunk_offset,
                header_end=header_end,
                chunk_end=chunk_end,
                ancestors=ancestors,
            )
        )
    else:
        payload_spec = selected_spec

    prefix_type = payload_spec.prefix_type

    prefix: MhodPayloadPrefix | None

    if prefix_type is None:
        prefix = None
        payload_offset = header_end

    else:
        prefix_base = (
            header_end if payload_spec.prefix_origin == "payload" else chunk_offset
        )
        prefix = parse_binary_struct(
            data,
            prefix_base,
            prefix_type,
            limit=chunk_end,
        )

        prefix_extent = binary_struct_extent(prefix_type)

        payload_offset = prefix_base + prefix_extent

        if payload_offset < header_end:
            raise UnknownMhodLayoutError(
                f"MHOD type {int(mhod_type)} "
                f"prefix ends at "
                f"{payload_offset:#x}, "
                f"before chunk header end "
                f"{header_end:#x}"
            )

    if payload_offset > chunk_end:
        raise ValueError(
            f"MHOD type {int(mhod_type)} "
            f"payload begins at "
            f"{payload_offset:#x}, "
            f"past chunk end "
            f"{chunk_end:#x}"
        )

    context = MhodPayloadParseContext[Any](
        data=data,
        mhod_type=mhod_type,
        chunk_offset=chunk_offset,
        payload_offset=payload_offset,
        payload_end=chunk_end,
        prefix=prefix,
        ancestors=ancestors,
    )

    payload: MhodPayload = payload_spec.parser(
        context,
    )

    return ParsedMhodPayload(
        prefix=prefix,
        payload=payload,
    )


def parse_chunk[RootH: ChunkHeader](
    data: bytes | bytearray,
    offset: int,
    *,
    parser_definition: DatabaseParserDefinition[RootH],
) -> tuple[ParsedChunk[ChunkHeader], int]:
    return _parse_chunk(
        data,
        offset,
        parser_definition=parser_definition,
        ancestors=(),
    )


def _parse_chunk[RootH: ChunkHeader](
    data: bytes | bytearray,
    offset: int,
    *,
    parser_definition: DatabaseParserDefinition[RootH],
    ancestors: tuple[ChunkAncestor, ...],
) -> tuple[ParsedChunk[ChunkHeader], int]:
    generic_header_size = binary_struct_extent(GenericHeader)
    if offset < 0 or offset + generic_header_size > len(data):
        raise TruncatedChunkError(
            f"truncated generic Chunk header at offset {offset:#x}"
        )

    generic_header = parse_binary_struct(data, offset, GenericHeader)

    marker = generic_header.header_marker
    if generic_header.header_length < generic_header_size:
        raise InvalidChunkLengthError(
            f"{marker!r} header length {generic_header.header_length} "
            f"is smaller than {generic_header_size} at offset {offset:#x}"
        )

    definition = parser_definition.database.chunk_definition(marker)
    minimum_header_size = (
        generic_header_size if definition is None else definition.minimum_header_size
    )
    if generic_header.header_length < minimum_header_size:
        raise InvalidChunkLengthError(
            f"{marker!r} header length {generic_header.header_length} is smaller "
            f"than its minimum {minimum_header_size} "
            f"at offset {offset:#x}"
        )

    header_end = offset + generic_header.header_length

    if header_end > len(data):
        raise TruncatedChunkError(
            f"{marker!r} header extends past end of data "
            f"at offset {offset:#x}. "
            f"header_end: {header_end:#x}. "
            f"len: {len(data):#x}"
        )

    if definition is None:
        report_unknown_data(
            f"unknown Chunk {marker!r}", offset, generic_header.length_or_child_count
        )
        header: ChunkHeader = UnknownChunkHeader()
        extent_type = "length"
        body_kind = "opaque"
        child_marker_groups: tuple[frozenset[bytes], ...] = ()
    else:
        if generic_header.header_length > max(definition.header_sizes):
            known_end = offset + max(definition.header_sizes)
            report_unknown_data(
                f"{marker!r} extended header", known_end, header_end - known_end
            )
        header = parse_binary_struct(
            data,
            offset,
            definition.header_type,
            limit=header_end,
        )
        extent_type = definition.extent_type
        body_kind = definition.body_kind
        child_marker_groups = definition.child_marker_groups

    is_list_chunk = extent_type == "child_count"

    dataset_definition = None
    if body_kind == "children" and is_list_chunk:
        child_count = generic_header.length_or_child_count

        if child_count < 0:
            raise ValueError(f"{marker!r} has negative child count {child_count}")
        child_counts: tuple[int, ...] = (child_count,)

    elif body_kind == "children":
        child_counts = read_child_counts(header)

    elif body_kind == "dataset":
        if not isinstance(header, MhsdChunkHeader):
            raise TypeError(f"{marker!r} dataset definition has the wrong header type")
        dataset_definition = parser_definition.database.dataset_definition(
            header.dataset_type
        )
        if isinstance(dataset_definition, MhsdDatasetDefinition):
            child_counts = (1,)
        else:
            child_counts = ()

    else:
        child_counts = ()

    if is_list_chunk:
        chunk_end: int = -1

    else:
        chunk_end = offset + generic_header.length_or_child_count

        if chunk_end > len(data):
            raise TruncatedChunkError(
                f"{marker!r} extends past end of data: {chunk_end:#x} > {len(data):#x}"
            )

        if chunk_end < header_end:
            raise InvalidChunkLengthError(
                f"{marker!r} length is smaller than its header at offset {offset:#x}"
            )

    prefix: MhodPayloadPrefix | None = None
    payload: ChunkPayload | None = None

    if body_kind == "mhod":
        if not isinstance(header, MhodChunkHeader):
            raise TypeError(f"{marker!r} MHOD definition has the wrong header type")
        if chunk_end < 0:
            raise ValueError("MHOD Chunk cannot have an indeterminate end")

        parsed_mhod = parse_mhod_payload(
            data,
            chunk_offset=offset,
            header_end=header_end,
            chunk_end=chunk_end,
            header=header,
            ancestors=ancestors,
            parser_definition=parser_definition,
        )

        prefix = parsed_mhod.prefix
        payload = parsed_mhod.payload

    elif body_kind == "opaque" or (
        body_kind == "dataset"
        and not isinstance(dataset_definition, MhsdDatasetDefinition)
    ):
        payload = RawPayload(data=bytes(data[header_end:chunk_end]))
        if definition is not None:
            report_unknown_data(
                f"{marker!r} opaque body", header_end, chunk_end - header_end
            )

    current_ancestor = ChunkAncestor(
        offset=offset,
        generic_header=generic_header,
        header=header,
    )

    child_ancestors = (
        *ancestors,
        current_ancestor,
    )

    children: list[ParsedChunk[ChunkHeader]] = []
    child_offset = header_end

    for child_group_index, child_count in enumerate(child_counts):
        for _ in range(child_count):
            if chunk_end > 0 and child_offset >= chunk_end:
                raise ValueError(
                    f"{marker!r} expects more children, "
                    "but its declared length has been exhausted"
                )

            child, next_offset = _parse_chunk(
                data,
                child_offset,
                parser_definition=parser_definition,
                ancestors=child_ancestors,
            )

            if next_offset <= child_offset:
                raise ValueError(f"child at {child_offset:#x} did not advance parser")

            if chunk_end > 0 and next_offset > chunk_end:
                raise ValueError(
                    f"child at {child_offset:#x} extends past parent {marker!r}"
                )

            children.append(child)

            child_marker = child.generic_header.header_marker
            if isinstance(dataset_definition, MhsdDatasetDefinition):
                expected_child_marker = dataset_definition.child_definition.marker
                if child_marker != expected_child_marker and not isinstance(
                    child.header, UnknownChunkHeader
                ):
                    if not isinstance(header, MhsdChunkHeader):
                        raise TypeError(
                            f"{marker!r} dataset definition has the wrong header type"
                        )
                    raise ValueError(
                        f"dataset type {header.dataset_type} expects "
                        f"{expected_child_marker!r}, got "
                        f"{child_marker!r}"
                    )

            elif (
                definition is not None
                and child_marker not in child_marker_groups[child_group_index]
                and parser_definition.database.chunk_definition(child_marker)
                is not None
            ):
                expected_group = sorted(child_marker_groups[child_group_index])
                expected = (
                    repr(expected_group[0])
                    if len(expected_group) == 1
                    else repr(tuple(expected_group))
                )
                if len(child_marker_groups) == 1:
                    raise ValueError(
                        f"{marker!r} child must use {expected}, got {child_marker!r}"
                    )
                raise ValueError(
                    f"{marker.decode('ascii', errors='replace').upper()} child group "
                    f"{child_group_index + 1} must use {expected}, got {child_marker!r}"
                )

            child_offset = next_offset

    if chunk_end < 0:
        chunk_end = child_offset
    if child_counts and child_offset < chunk_end:
        report_unknown_data(
            f"{marker!r} trailing data", child_offset, chunk_end - child_offset
        )

    return (
        ParsedChunk(
            offset=offset,
            generic_header=generic_header,
            header=header,
            children=tuple(children),
            prefix=prefix,
            payload=payload,
            raw_header=bytes(data[offset:header_end]),
            raw_body=bytes(data[header_end:chunk_end]),
            raw_trailing_data=bytes(data[child_offset:chunk_end]),
            original_prefix=prefix,
            original_payload=payload,
        ),
        chunk_end,
    )


def parse_chunk_as[H: ChunkHeader, RootH: ChunkHeader](
    data: bytes | bytearray,
    offset: int,
    expected_definition: ChunkDefinition[H],
    *,
    parser_definition: DatabaseParserDefinition[RootH],
) -> tuple[ParsedChunk[H], int]:
    chunk, next_offset = parse_chunk(
        data,
        offset,
        parser_definition=parser_definition,
    )

    actual_marker = chunk.generic_header.header_marker
    if actual_marker != expected_definition.marker:
        raise UnexpectedHeaderMarkerError(
            f"expected {expected_definition.marker!r}, got {actual_marker!r} "
            f"at offset {offset:#x}"
        )

    return (
        chunk_as(
            chunk,
            expected_definition.header_type,
        ),
        next_offset,
    )


@log_unknown_data("database")
def parse_database[H: ChunkHeader](
    data: bytes | bytearray,
    parser_definition: DatabaseParserDefinition[H],
) -> ParsedChunk[H]:
    """Parse one complete database through its sole typed structural definition."""

    try:
        chunk, next_offset = parse_chunk_as(
            data,
            0,
            parser_definition.database.root_chunk,
            parser_definition=parser_definition,
        )
    except iPodDBParseError:
        raise
    except (ValueError, struct.error) as error:
        raise InvalidChunkDataError(str(error)) from error
    if next_offset < len(data):
        report_unknown_data("database suffix", next_offset, len(data) - next_offset)
        return replace(chunk, raw_source_suffix=bytes(data[next_offset:]))
    return chunk
