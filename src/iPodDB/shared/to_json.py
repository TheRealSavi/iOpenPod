import json
from collections.abc import Mapping
from dataclasses import fields
from enum import Enum
from typing import Any, cast

from .chunk import (
    BinaryStruct,
    ChunkHeader,
    ParsedChunk,
)


def json_value(value: object) -> object:
    """
    Convert parser-domain values into JSON-serializable values.
    """

    if isinstance(value, BinaryStruct):
        return struct_to_dict(value)

    if isinstance(value, bytes):
        try:
            text = value.decode("ascii")

            if text.isprintable():
                return text

        except UnicodeDecodeError:
            pass

        return value.hex()

    if isinstance(value, Enum):
        return cast("object", value.value)

    if isinstance(value, Mapping):
        mapping = cast("Mapping[object, object]", value)
        return {str(key): json_value(item) for key, item in mapping.items()}

    if isinstance(value, tuple):
        tuple_items = cast("tuple[object, ...]", value)
        return [json_value(item) for item in tuple_items]

    if isinstance(value, list):
        list_items = cast("list[object]", value)
        return [json_value(item) for item in list_items]

    return value


def struct_to_dict(
    value: BinaryStruct,
) -> dict[str, Any]:
    return {
        field.name: json_value(
            cast(
                "object",
                getattr(
                    value,
                    field.name,
                ),
            )
        )
        for field in fields(cast("Any", value))
    }


def chunk_to_dict[H: ChunkHeader](
    chunk: ParsedChunk[H],
) -> dict[str, Any]:
    return {
        "offset": chunk.offset,
        "generic_header": struct_to_dict(chunk.generic_header),
        "header": struct_to_dict(chunk.header),
        "payload": (
            struct_to_dict(chunk.payload) if chunk.payload is not None else None
        ),
        "children": [chunk_to_dict(child) for child in chunk.children],
    }


def chunk_to_json[H: ChunkHeader](
    chunk: ParsedChunk[H],
    *,
    indent: int = 2,
) -> str:
    return json.dumps(
        chunk_to_dict(chunk),
        indent=indent,
    )
