import struct
from dataclasses import replace
from typing import Protocol, cast

from iPodDB.shared.binary_struct import (
    parse_binary_struct,
    read_child_counts,
    replace_child_counts,
    write_binary_struct_into,
)
from iPodDB.shared.chunk import (
    ChunkHeader,
    MhodChunkHeader,
    MhsdChunkHeader,
    ParsedChunk,
    RawPayload,
    UnknownChunkHeader,
    UnknownMhodPayload,
)
from iPodDB.shared.errors import iPodDBWriteError
from iPodDB.shared.types import (
    ChunkDefinition,
    DatabaseDefinition,
    MhsdDatasetDefinition,
    MhsdDatasetSpec,
)


class NestedChunkSerializer(Protocol):
    """Serialize any exactly typed child through the shared recursive writer."""

    def __call__[H: ChunkHeader](
        self,
        chunk: ParsedChunk[H],
        parent_marker: bytes,
        /,
    ) -> bytes: ...


class MhodBodySerializer(Protocol):
    """Encode one format-specific MHOD body through the shared writer seam."""

    def __call__(
        self,
        chunk: ParsedChunk[ChunkHeader],
        parent_marker: bytes | None,
        serialize_child: NestedChunkSerializer,
        /,
    ) -> tuple[bytes, ChunkHeader]: ...


def _expected_markers_text(markers: frozenset[bytes]) -> str:
    expected_markers = sorted(markers)
    if len(expected_markers) == 1:
        return repr(expected_markers[0])
    return repr(tuple(expected_markers))


def _with_child_counts(
    header: ChunkHeader,
    children: tuple[ParsedChunk[ChunkHeader], ...],
    definition: ChunkDefinition[ChunkHeader] | None,
) -> ChunkHeader:
    declared_counts = read_child_counts(header)
    if not declared_counts:
        return header
    if len(declared_counts) == 1:
        return replace_child_counts(header, (len(children),))
    if definition is None:
        raise ValueError("an Unknown Chunk cannot declare typed child counts")

    child_marker_groups = definition.child_marker_groups
    group_counts = tuple(
        sum(child.generic_header.header_marker in group_markers for child in children)
        for group_markers in child_marker_groups
    )
    if sum(group_counts) == len(children):
        return replace_child_counts(header, group_counts)
    if sum(declared_counts) == len(children):
        child_offset = 0
        for group_index, (group_count, group_markers) in enumerate(
            zip(declared_counts, child_marker_groups, strict=True),
            start=1,
        ):
            for child in children[child_offset : child_offset + group_count]:
                child_marker = child.generic_header.header_marker
                if (
                    child_marker in definition.known_child_markers
                    and child_marker not in group_markers
                ):
                    raise ValueError(
                        f"{definition.marker!r} declared child group {group_index} "
                        f"cannot contain {child_marker!r}"
                    )
            child_offset += group_count
        return header
    raise ValueError(
        f"cannot infer {definition.marker!r} child groups after a structural edit "
        "that contains Unknown Chunks"
    )


def _validate_known_children(
    chunk: ParsedChunk[ChunkHeader],
    definition: ChunkDefinition[ChunkHeader],
    database_definition: DatabaseDefinition[ChunkHeader],
) -> None:
    if definition.body_kind != "children":
        return

    allowed_child_markers = definition.known_child_markers
    for child in chunk.children:
        child_marker = child.generic_header.header_marker
        if (
            child_marker not in allowed_child_markers
            and database_definition.chunk_definition(child_marker) is not None
        ):
            expected = _expected_markers_text(allowed_child_markers)
            raise ValueError(
                f"{definition.marker!r} child must use {expected}, got {child_marker!r}"
            )

    child_marker_groups = definition.child_marker_groups
    if len(child_marker_groups) <= 1:
        return

    previous_group = -1
    for child in chunk.children:
        child_marker = child.generic_header.header_marker
        matching_groups = [
            index
            for index, group_markers in enumerate(child_marker_groups)
            if child_marker in group_markers
        ]
        if not matching_groups:
            continue
        current_group = matching_groups[0]
        if current_group < previous_group:
            raise ValueError(f"{definition.marker!r} child groups are out of order")
        previous_group = current_group


def _validate_dataset(
    chunk: ParsedChunk[ChunkHeader],
    database_definition: DatabaseDefinition[ChunkHeader],
) -> MhsdDatasetSpec | None:
    if not isinstance(chunk.header, MhsdChunkHeader):
        raise TypeError("a dataset Chunk must use an MhsdChunkHeader")

    dataset_definition = database_definition.dataset_definition(
        chunk.header.dataset_type
    )
    if isinstance(dataset_definition, MhsdDatasetDefinition):
        if len(chunk.children) != 1 or (
            chunk.children[0].generic_header.header_marker
            != dataset_definition.child_definition.marker
            and not isinstance(chunk.children[0].header, UnknownChunkHeader)
        ):
            raise ValueError(
                f"dataset type {chunk.header.dataset_type} expects exactly one "
                f"{dataset_definition.child_definition.marker!r} child"
            )
        if chunk.payload is not None:
            raise ValueError("a structured dataset cannot also contain a payload")
    else:
        if chunk.children:
            raise ValueError(f"dataset type {chunk.header.dataset_type} must be opaque")
        if not isinstance(chunk.payload, RawPayload):
            raise ValueError("an opaque dataset requires a RawPayload")
    return dataset_definition


def _serialize_chunk_body(
    chunk: ParsedChunk[ChunkHeader],
    *,
    database_definition: DatabaseDefinition[ChunkHeader],
    serialize_mhod_body: MhodBodySerializer,
    parent_marker: bytes | None = None,
) -> bytes:
    """Serialize one definition-driven Chunk tree without normalizing Unknown Data."""
    marker = chunk.generic_header.header_marker
    definition = database_definition.chunk_definition(marker)

    if chunk.raw_header:
        header = bytearray(chunk.raw_header)
    elif definition is not None:
        header = bytearray(definition.default_header_size)
    else:
        raise ValueError(
            f"new Unknown Chunk {marker!r} requires retained raw header bytes"
        )

    if definition is None:
        if not isinstance(chunk.header, UnknownChunkHeader):
            raise TypeError(
                f"unknown marker {marker!r} requires UnknownChunkHeader, "
                f"got {type(chunk.header).__name__}"
            )
        if chunk.children or not isinstance(chunk.payload, RawPayload):
            raise ValueError("an Unknown Chunk must contain one opaque RawPayload")
        if chunk.prefix is not None:
            raise ValueError("an Unknown Chunk cannot contain an MHOD prefix")
    else:
        definition.require_header(chunk.header)

    if definition is not None:
        _validate_known_children(chunk, definition, database_definition)
        if definition.body_kind == "children" and chunk.payload is not None:
            raise ValueError("a children Chunk cannot contain a payload")
        if definition.body_kind in {"mhod", "opaque"} and chunk.children:
            raise ValueError(f"a {definition.body_kind} Chunk cannot contain children")
        if definition.body_kind != "mhod" and chunk.prefix is not None:
            raise ValueError(
                f"a {definition.body_kind} Chunk cannot contain an MHOD prefix"
            )

    dataset_definition: MhsdDatasetSpec | None = None
    if definition is not None and definition.body_kind == "dataset":
        dataset_definition = _validate_dataset(chunk, database_definition)

    child_indexes = {id(child): index for index, child in enumerate(chunk.children)}

    def serialize_child[H: ChunkHeader](
        child: ParsedChunk[H],
        parent: bytes,
    ) -> bytes:
        try:
            return _serialize_chunk(
                cast("ParsedChunk[ChunkHeader]", child),
                database_definition=database_definition,
                serialize_mhod_body=serialize_mhod_body,
                parent_marker=parent,
            )
        except iPodDBWriteError as error:
            index = child_indexes.get(id(child))
            if index is not None:
                error.chunk_path = (index, *error.chunk_path)
            raise

    header_value = chunk.header
    if definition is not None and definition.body_kind == "mhod":
        if isinstance(chunk.payload, UnknownMhodPayload):
            payload = chunk.payload
            original_header = parse_binary_struct(
                chunk.raw_header,
                0,
                definition.header_type,
                limit=len(chunk.raw_header),
            )
            if (
                not chunk.raw_header
                or not isinstance(header_value, MhodChunkHeader)
                or not isinstance(original_header, MhodChunkHeader)
                or payload.mhod_type != header_value.mhod_type
                or payload.mhod_type != original_header.mhod_type
                or payload.parent_marker != parent_marker
                or chunk.prefix is not None
                or chunk.original_prefix is not None
                or payload != chunk.original_payload
                or payload.data != chunk.raw_body
            ):
                raise ValueError(
                    "An unknown MHOD layout must retain its bytes, type, and parent context."
                )
            body = payload.data
        else:
            body, header_value = serialize_mhod_body(
                chunk,
                parent_marker,
                serialize_child,
            )
    elif definition is None or (
        definition.body_kind == "opaque"
        or (
            definition.body_kind == "dataset"
            and not isinstance(dataset_definition, MhsdDatasetDefinition)
        )
    ):
        if not isinstance(chunk.payload, RawPayload):
            raise ValueError(f"{marker!r} requires a RawPayload")
        body = chunk.payload.data
    else:
        body = b"".join(serialize_child(child, marker) for child in chunk.children)
        body += chunk.raw_trailing_data

    header_value = _with_child_counts(header_value, chunk.children, definition)
    if definition is not None and definition.extent_type == "child_count":
        length_or_child_count = len(chunk.children)
    else:
        length_or_child_count = len(header) + len(body)

    generic_header = replace(
        chunk.generic_header,
        header_length=len(header),
        length_or_child_count=length_or_child_count,
    )
    write_binary_struct_into(header, generic_header)
    write_binary_struct_into(header, header_value)
    return bytes(header) + body


def _serialize_chunk(
    chunk: ParsedChunk[ChunkHeader],
    *,
    database_definition: DatabaseDefinition[ChunkHeader],
    serialize_mhod_body: MhodBodySerializer,
    parent_marker: bytes | None = None,
) -> bytes:
    try:
        return _serialize_chunk_body(
            chunk,
            database_definition=database_definition,
            serialize_mhod_body=serialize_mhod_body,
            parent_marker=parent_marker,
        )
    except iPodDBWriteError as error:
        if error.offset is None:
            error.offset = chunk.offset
            error.marker = chunk.generic_header.header_marker
        raise
    except (ValueError, struct.error, OverflowError) as error:
        raise iPodDBWriteError(
            str(error),
            offset=chunk.offset,
            marker=chunk.generic_header.header_marker,
        ) from error


def serialize_database[H: ChunkHeader](
    database: ParsedChunk[H],
    database_definition: DatabaseDefinition[H],
    serialize_mhod_body: MhodBodySerializer,
) -> bytes:
    """Serialize one complete database through its sole structural definition."""

    root_definition = database_definition.root_chunk
    actual_marker = database.generic_header.header_marker
    if actual_marker != root_definition.marker:
        raise iPodDBWriteError(
            f"database root must use {root_definition.marker!r}, got {actual_marker!r}"
        )
    root_definition.require_header(database.header)
    try:
        body = _serialize_chunk(
            cast("ParsedChunk[ChunkHeader]", database),
            database_definition=database_definition,
            serialize_mhod_body=serialize_mhod_body,
        )
    except iPodDBWriteError:
        raise
    except (ValueError, struct.error, OverflowError) as error:
        raise iPodDBWriteError(str(error)) from error
    return body + database.raw_source_suffix
