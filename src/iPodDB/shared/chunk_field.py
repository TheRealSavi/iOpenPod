from collections.abc import Mapping
from dataclasses import field
from types import MappingProxyType
from typing import Any, Literal, NamedTuple, overload

ChunkFieldInt = Literal[
    "u64",
    "u32",
    "i32",
    "u16",
    "i16",
    "u8",
    "be_u64",
    "be_i64",
    "be_u32",
    "be_u16",
]
ChunkFieldFloat = Literal["f32"]
ChunkFieldRaw = Literal["raw"]
ChunkFieldEncodingFixed = ChunkFieldInt | ChunkFieldFloat
ChunkFieldEncoding = ChunkFieldEncodingFixed | ChunkFieldRaw
StructFormatType = Literal[
    "<Q",
    "<I",
    "<i",
    "<f",
    "<H",
    "<h",
    "B",
    ">Q",
    ">q",
    ">I",
    ">H",
]


class StructFormat(NamedTuple):
    size: int
    struct_format_type: StructFormatType


STRUCT_FORMATS_BY_ENCODING: Mapping[ChunkFieldEncodingFixed, StructFormat] = (
    MappingProxyType(
        {
            "u64": StructFormat(8, "<Q"),
            "u32": StructFormat(4, "<I"),
            "i32": StructFormat(4, "<i"),
            "f32": StructFormat(4, "<f"),
            "u16": StructFormat(2, "<H"),
            "i16": StructFormat(2, "<h"),
            "u8": StructFormat(1, "B"),
            "be_u64": StructFormat(8, ">Q"),
            "be_i64": StructFormat(8, ">q"),
            "be_u32": StructFormat(4, ">I"),
            "be_u16": StructFormat(2, ">H"),
        }
    )
)


type ChunkFieldValue = int | float | bytes


class ChunkFieldSchema(NamedTuple):
    offset: int
    size: int
    encoding: ChunkFieldEncoding
    default: ChunkFieldValue
    counts_children: bool


@overload
def chunk_field(
    offset: int,
    encoding: ChunkFieldInt,
    *,
    default: int = 0,
    counts_children: bool = False,
) -> int: ...


@overload
def chunk_field(
    offset: int,
    encoding: ChunkFieldFloat,
    *,
    default: float = 0.0,
) -> float: ...


@overload
def chunk_field(
    offset: int,
    encoding: ChunkFieldRaw,
    *,
    size: int,
    default: bytes | None = None,
) -> bytes: ...


def chunk_field(
    offset: int,
    encoding: ChunkFieldEncoding,
    *,
    size: int | None = None,
    default: object | None = None,
    counts_children: bool = False,
) -> Any:
    if encoding == "raw":
        if counts_children:
            raise TypeError("raw field cannot count children")
        if size is None:
            raise ValueError("raw fields require size")

        if default is None:
            raw_default = bytes(size)
        elif isinstance(default, bytes):
            raw_default = default
        else:
            raise TypeError("raw field default must be bytes")

        raw_schema = ChunkFieldSchema(
            offset=offset,
            size=size,
            encoding="raw",
            default=raw_default,
            counts_children=False,
        )

        return field(
            default=raw_default,
            metadata={"chunk": raw_schema},
        )

    format_info = STRUCT_FORMATS_BY_ENCODING[encoding]

    if encoding == "f32":
        if counts_children:
            raise TypeError("float field cannot count children")
        if default is None:
            float_default = 0.0
        elif isinstance(default, int | float):
            float_default = float(default)
        else:
            raise TypeError("f32 field default must be numeric")

        float_schema = ChunkFieldSchema(
            offset=offset,
            size=format_info.size,
            encoding="f32",
            default=float_default,
            counts_children=False,
        )

        return field(
            default=float_default,
            metadata={"chunk": float_schema},
        )

    if default is None:
        int_default = 0
    elif isinstance(default, int):
        int_default = default
    else:
        raise TypeError("integer field default must be int")

    int_schema = ChunkFieldSchema(
        offset=offset,
        size=format_info.size,
        encoding=encoding,
        default=int_default,
        counts_children=counts_children,
    )

    return field(
        default=int_default,
        metadata={"chunk": int_schema},
    )
