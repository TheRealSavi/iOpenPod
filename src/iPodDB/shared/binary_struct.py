"""Definition-driven fixed-layout binary structure parsing and writing."""

import math
import struct
from dataclasses import dataclass, fields, replace
from typing import Any, cast

from iPodDB.shared.chunk import BinaryStruct, ChunkHeader
from iPodDB.shared.chunk_field import (
    STRUCT_FORMATS_BY_ENCODING,
    ChunkFieldSchema,
)
from iPodDB.shared.errors import iPodDBWriteError


@dataclass(frozen=True, slots=True)
class BinaryField:
    """One dataclass attribute bound to its binary field definition."""

    attribute_name: str
    schema: ChunkFieldSchema


_BINARY_FIELDS_BY_TYPE: dict[type[BinaryStruct], tuple[BinaryField, ...]] = {}


def _binary_fields_for_type(
    struct_type: type[BinaryStruct],
) -> tuple[BinaryField, ...]:
    cached = _BINARY_FIELDS_BY_TYPE.get(struct_type)
    if cached is not None:
        return cached

    owner = struct_type.__name__
    result: list[BinaryField] = []
    for dataclass_field in fields(cast("Any", struct_type)):
        schema = dataclass_field.metadata.get("chunk")
        if not isinstance(schema, ChunkFieldSchema):
            raise TypeError(
                f"{owner}.{dataclass_field.name} has no valid chunk metadata"
            )
        if schema.offset < 0 or schema.size <= 0:
            raise ValueError(
                f"{owner}.{dataclass_field.name} has invalid byte range "
                f"{schema.offset}:{schema.offset + schema.size}"
            )
        result.append(BinaryField(dataclass_field.name, schema))

    occupied: list[BinaryField] = []
    for binary_field in sorted(result, key=lambda item: item.schema.offset):
        if occupied:
            previous = occupied[-1]
            if binary_field.schema.offset < (
                previous.schema.offset + previous.schema.size
            ):
                raise ValueError(
                    f"{owner}.{binary_field.attribute_name} overlaps "
                    f"{owner}.{previous.attribute_name}"
                )
        occupied.append(binary_field)
    validated = tuple(result)
    _BINARY_FIELDS_BY_TYPE[struct_type] = validated
    return validated


def binary_fields(
    value_or_type: BinaryStruct | type[BinaryStruct],
) -> tuple[BinaryField, ...]:
    """Return validated binary fields in dataclass declaration order.

    Dataclass metadata is intentionally runtime-erased. This function is the one
    place where that dynamic metadata crosses into the statically typed iPodDB
    implementation.
    """

    struct_type = (
        value_or_type if isinstance(value_or_type, type) else type(value_or_type)
    )
    return _binary_fields_for_type(struct_type)


def validate_binary_struct_definition(
    struct_type: type[BinaryStruct],
    *,
    supported_sizes: tuple[int, ...],
) -> None:
    """Validate that every field fits at least one supported binary extent.

    A field need not fit every extent: parsed short headers intentionally use the
    field default for later optional fields. New definitions must nevertheless
    provide at least one supported size capable of retaining each declared field.
    """

    for binary_field in binary_fields(struct_type):
        field_end = binary_field.schema.offset + binary_field.schema.size
        if not any(field_end <= size for size in supported_sizes):
            raise ValueError(
                f"{struct_type.__name__}.{binary_field.attribute_name} ending at "
                f"{field_end} does not fit any supported size {supported_sizes}"
            )


def binary_struct_extent(struct_type: type[BinaryStruct]) -> int:
    """Return the greatest byte offset occupied by a binary structure."""

    return max(
        (
            field.schema.offset + field.schema.size
            for field in binary_fields(struct_type)
        ),
        default=0,
    )


def parse_binary_struct[T: BinaryStruct](
    data: bytes | bytearray,
    offset: int,
    struct_type: type[T],
    *,
    limit: int | None = None,
) -> T:
    """Decode known fields, using field defaults beyond a retained short extent."""

    if limit is None:
        limit = len(data)
    if offset < 0 or limit < offset or limit > len(data):
        raise ValueError(
            f"invalid {struct_type.__name__} bounds: "
            f"offset={offset}, limit={limit}, data_length={len(data)}"
        )

    values: dict[str, Any] = {}
    for field in binary_fields(struct_type):
        schema = field.schema
        field_offset = offset + schema.offset
        field_end = field_offset + schema.size
        if field_end > limit:
            values[field.attribute_name] = schema.default
            continue

        if schema.encoding == "raw":
            values[field.attribute_name] = bytes(data[field_offset:field_end])
            continue

        struct_format = STRUCT_FORMATS_BY_ENCODING[schema.encoding]
        values[field.attribute_name] = struct.unpack_from(
            struct_format.struct_format_type,
            data,
            field_offset,
        )[0]

    return struct_type(**values)


def write_binary_struct_into(
    data: bytearray,
    value: BinaryStruct,
    *,
    offset: int = 0,
    limit: int | None = None,
) -> None:
    """Encode known fields while leaving all other retained bytes untouched."""

    if limit is None:
        limit = len(data)
    if offset < 0 or limit < offset or limit > len(data):
        raise ValueError(
            f"invalid {type(value).__name__} bounds: "
            f"offset={offset}, limit={limit}, data_length={len(data)}"
        )

    for field in binary_fields(value):
        schema = field.schema
        field_offset = offset + schema.offset
        field_end = field_offset + schema.size
        field_value = getattr(value, field.attribute_name)

        if field_end > limit:
            if field_value != schema.default:
                retained_size = limit - offset
                raise iPodDBWriteError(
                    f"{type(value).__name__}.{field.attribute_name} cannot fit "
                    f"the retained {retained_size}-byte header",
                    code="binary.short_header",
                    field=field.attribute_name,
                )
            continue

        if schema.encoding == "raw":
            if not isinstance(field_value, bytes) or len(field_value) != schema.size:
                raise iPodDBWriteError(
                    f"{type(value).__name__}.{field.attribute_name} must contain "
                    f"exactly {schema.size} bytes",
                    code="binary.field_size",
                    field=field.attribute_name,
                )
            if bytes(data[field_offset:field_end]) != field_value:
                data[field_offset:field_end] = field_value
            continue

        struct_format = STRUCT_FORMATS_BY_ENCODING[schema.encoding].struct_format_type
        if schema.encoding == "f32":
            if not isinstance(field_value, float):
                raise TypeError(
                    f"{type(value).__name__}.{field.attribute_name} must be a float"
                )
            retained_value = struct.unpack_from(struct_format, data, field_offset)[0]
            # Python does not retain a decoded NaN's payload/signaling bits.
            # Preserve the source encoding while the typed field remains NaN.
            if math.isnan(field_value) and math.isnan(retained_value):
                continue

        try:
            encoded_value = struct.pack(struct_format, field_value)
        except (struct.error, OverflowError) as error:
            raise iPodDBWriteError(
                f"{type(value).__name__}.{field.attribute_name}: {error}",
                code="binary.field_range",
                field=field.attribute_name,
            ) from error
        if bytes(data[field_offset:field_end]) != encoded_value:
            data[field_offset:field_end] = encoded_value


def read_child_counts(header: ChunkHeader) -> tuple[int, ...]:
    """Return definition-marked child counts in declaration order."""

    counts: list[int] = []
    for field in binary_fields(header):
        if not field.schema.counts_children:
            continue

        value = getattr(header, field.attribute_name)
        if not isinstance(value, int):
            raise TypeError(
                f"{type(header).__name__}.{field.attribute_name} is marked "
                "counts_children=True but is not an int"
            )
        if value < 0:
            raise ValueError(
                f"{type(header).__name__}.{field.attribute_name} "
                f"has negative child count {value}"
            )
        counts.append(value)
    return tuple(counts)


def replace_child_counts[H: ChunkHeader](
    header: H,
    child_counts: tuple[int, ...],
) -> H:
    """Replace every definition-marked child count in declaration order."""

    field_names = tuple(
        field.attribute_name
        for field in binary_fields(header)
        if field.schema.counts_children
    )
    if len(field_names) != len(child_counts):
        raise ValueError(
            f"{type(header).__name__} defines {len(field_names)} child-count fields, "
            f"but {len(child_counts)} values were supplied"
        )

    updated = replace(
        cast("Any", header),
        **dict(zip(field_names, child_counts, strict=True)),
    )
    if not isinstance(updated, type(header)):
        raise TypeError("replacing a ChunkHeader returned an invalid value")
    return updated
