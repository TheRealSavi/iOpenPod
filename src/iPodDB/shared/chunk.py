from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Generic, TypeVar, cast

from iPodDB.shared.chunk_field import chunk_field


class BinaryStruct:
    __slots__ = ()


class ChunkHeader(BinaryStruct):
    __slots__ = ()


class MhodChunkHeader(ChunkHeader):
    """Base class for chunk headers that select an MHOD payload specification.
    Concrete database implementations provide the actual dataclass fields."""

    __slots__ = ()
    mhod_type: int


class MhsdChunkHeader(ChunkHeader):
    """Base class for chunk headers that select an MHSD dataset behavior.

    Concrete database implementations provide the actual dataclass fields.
    """

    __slots__ = ()
    dataset_type: int


class MhodPayloadPrefix(BinaryStruct):
    """Base class for fixed binary structures appearing before an MHOD's actual payload data.
    Prefix chunk_field offsets are relative to the start of the MHOD chunk."""

    __slots__ = ()


class ChunkPayload(BinaryStruct):
    __slots__ = ()


class MhodPayload(ChunkPayload):
    __slots__ = ()


@dataclass(frozen=True, slots=True)
class UnknownMhodPayload(MhodPayload):
    """A known MHOD with an uninterpreted layout, bound to its source context."""

    data: bytes
    mhod_type: int
    parent_marker: bytes | None


@dataclass(frozen=True, slots=True)
class RawPayload(ChunkPayload):
    data: bytes


@dataclass(frozen=True, slots=True)
class EmptyChunkHeader(ChunkHeader):
    pass


@dataclass(frozen=True, slots=True)
class UnknownChunkHeader(ChunkHeader):
    """Header for a length-delimited Chunk whose marker is not yet understood."""


@dataclass(frozen=True, slots=True)
class GenericHeader(BinaryStruct):
    header_marker: bytes = chunk_field(0x00, "raw", size=4)
    header_length: int = chunk_field(0x04, "u32")
    length_or_child_count: int = chunk_field(0x08, "u32")


@dataclass(frozen=True, slots=True)
class ChunkAncestor:
    """Parent context retained for context-dependent MHOD payload layouts."""

    offset: int
    generic_header: GenericHeader
    header: ChunkHeader


@dataclass(frozen=True, slots=True)
class ChunkPath[RootH: ChunkHeader, H: ChunkHeader]:
    """Typed child indexes from one Chunk-tree root to one selected Chunk."""

    root_header_type: type[RootH]
    header_type: type[H]
    child_indexes: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ParsedMhodPayload:
    prefix: MhodPayloadPrefix | None
    payload: MhodPayload


H_co = TypeVar("H_co", bound=ChunkHeader, covariant=True)


@dataclass(frozen=True, slots=True)
# Explicit covariance is required for immutable, heterogeneous Chunk trees. Python
# 3.12's type-parameter syntax cannot declare variance when inference sees a public
# dataclass field.
class ParsedChunk(Generic[H_co]):  # noqa: UP046
    offset: int
    generic_header: GenericHeader
    header: H_co
    children: tuple["ParsedChunk[ChunkHeader]", ...]
    prefix: MhodPayloadPrefix | None
    payload: ChunkPayload | None
    raw_header: bytes = b""
    raw_body: bytes = b""
    raw_trailing_data: bytes = b""
    raw_source_suffix: bytes = b""
    original_prefix: MhodPayloadPrefix | None = None
    original_payload: ChunkPayload | None = None

    def child_as[C: ChunkHeader](
        self,
        index: int,
        expected_type: type[C],
    ) -> "ParsedChunk[C]":
        return chunk_as(
            self.children[index],
            expected_type,
        )

    def prefix_as[P: MhodPayloadPrefix](
        self,
        expected_type: type[P],
    ) -> P:
        return prefix_as(
            self.prefix,
            expected_type,
        )

    def payload_as[P: ChunkPayload](
        self,
        expected_type: type[P],
    ) -> P:
        return payload_as(
            self.payload,
            expected_type,
        )

    def edit_header[E: ChunkHeader](
        self: "ParsedChunk[E]",
        edit: Callable[[E], E],
    ) -> "ParsedChunk[E]":
        """Apply a statically typed edit to this Chunk's exact header type."""

        edited_header = edit(self.header)
        if type(edited_header) is not type(self.header):
            raise TypeError(
                f"header edit must return {type(self.header).__name__}, "
                f"got {type(edited_header).__name__}"
            )
        return replace(self, header=edited_header)

    def edit_prefix[P: MhodPayloadPrefix](
        self,
        expected_type: type[P],
        edit: Callable[[P], P],
    ) -> "ParsedChunk[H_co]":
        """Apply a statically typed edit to this Chunk's MHOD prefix."""

        prefix = self.prefix_as(expected_type)
        edited_prefix = edit(prefix)
        if type(edited_prefix) is not expected_type:
            raise TypeError(
                f"prefix edit must return {expected_type.__name__}, "
                f"got {type(edited_prefix).__name__}"
            )
        return replace(self, prefix=edited_prefix)

    def edit_payload[P: ChunkPayload](
        self,
        expected_type: type[P],
        edit: Callable[[P], P],
    ) -> "ParsedChunk[H_co]":
        """Apply a statically typed edit to this Chunk's exact payload type."""

        payload = self.payload_as(expected_type)
        edited_payload = edit(payload)
        if type(edited_payload) is not expected_type:
            raise TypeError(
                f"payload edit must return {expected_type.__name__}, "
                f"got {type(edited_payload).__name__}"
            )
        return replace(self, payload=edited_payload)

    def append_child[C: ChunkHeader](
        self,
        child: "ParsedChunk[C]",
    ) -> "ParsedChunk[H_co]":
        """Return this Chunk with one exactly typed child appended."""

        if self.payload is not None:
            raise ValueError("a payload Chunk cannot also contain children")
        return replace(
            self,
            children=(
                *self.children,
                child,
            ),
        )

    def find_chunks[RootH: ChunkHeader, C: ChunkHeader](
        self: "ParsedChunk[RootH]",
        expected_type: type[C],
    ) -> tuple["ChunkSelection[RootH, C]", ...]:
        """Find typed Chunks without exposing recursive ancestor reconstruction."""

        return _find_chunks(
            root_header_type=type(self.header),
            start_chunk=self,
            start_indexes=(),
            expected_type=expected_type,
        )

    def select_chunk[RootH: ChunkHeader, C: ChunkHeader](
        self: "ParsedChunk[RootH]",
        path: ChunkPath[RootH, C],
    ) -> "ParsedChunk[C]":
        """Resolve a typed path against this exact kind of Chunk-tree root."""

        if type(self.header) is not path.root_header_type:
            raise TypeError(
                f"path requires {path.root_header_type.__name__} root, "
                f"got {type(self.header).__name__}"
            )

        selected: ParsedChunk[ChunkHeader] = cast(
            "ParsedChunk[ChunkHeader]",
            self,
        )
        for child_index in path.child_indexes:
            try:
                selected = selected.children[child_index]
            except IndexError:
                raise IndexError(
                    f"Chunk path index {child_index} is outside "
                    f"{selected.generic_header.header_marker!r}"
                ) from None
        return chunk_as(selected, path.header_type)

    def replace_chunk[RootH: ChunkHeader, C: ChunkHeader](
        self: "ParsedChunk[RootH]",
        selection: "ChunkSelection[RootH, C]",
        replacement: "ParsedChunk[C]",
    ) -> "ParsedChunk[RootH]":
        """Return this root with one selected Chunk immutably replaced.

        A selection belongs to the tree state from which it was obtained. It remains
        valid across edits to other branches while persistent object identity is
        retained, and fails explicitly once its own path becomes stale.
        """

        current = self.select_chunk(selection.path)
        if current is not selection.chunk:
            raise ValueError("Chunk selection is stale for this tree state")
        if type(replacement.header) is not selection.path.header_type:
            raise TypeError(
                f"replacement requires {selection.path.header_type.__name__}, "
                f"got {type(replacement.header).__name__}"
            )
        expected_marker = current.generic_header.header_marker
        replacement_marker = replacement.generic_header.header_marker
        if replacement_marker != expected_marker:
            raise ValueError(
                f"replacement must retain Header Marker {expected_marker!r}, "
                f"got {replacement_marker!r}"
            )

        replaced = _replace_chunk_at_indexes(
            self,
            selection.path.child_indexes,
            replacement,
        )
        return chunk_as(replaced, type(self.header))


type DatabaseDocument[H: ChunkHeader] = ParsedChunk[H]


@dataclass(frozen=True, slots=True)
class ChunkSelection[RootH: ChunkHeader, H: ChunkHeader]:
    """One typed Chunk and its immutable location in a root Chunk tree."""

    path: ChunkPath[RootH, H]
    chunk: ParsedChunk[H]

    def find_chunks[C: ChunkHeader](
        self,
        expected_type: type[C],
    ) -> tuple["ChunkSelection[RootH, C]", ...]:
        """Find typed Chunks within this selection, retaining the root path."""

        return _find_chunks(
            root_header_type=self.path.root_header_type,
            start_chunk=self.chunk,
            start_indexes=self.path.child_indexes,
            expected_type=expected_type,
        )


def _find_chunks[RootH: ChunkHeader, H: ChunkHeader](
    *,
    root_header_type: type[RootH],
    start_chunk: ParsedChunk[ChunkHeader],
    start_indexes: tuple[int, ...],
    expected_type: type[H],
) -> tuple[ChunkSelection[RootH, H], ...]:
    selections: list[ChunkSelection[RootH, H]] = []

    def visit(
        chunk: ParsedChunk[ChunkHeader],
        child_indexes: tuple[int, ...],
    ) -> None:
        if type(chunk.header) is expected_type:
            selections.append(
                ChunkSelection(
                    path=ChunkPath(
                        root_header_type=root_header_type,
                        header_type=expected_type,
                        child_indexes=child_indexes,
                    ),
                    chunk=cast("ParsedChunk[H]", chunk),
                )
            )
        for child_index, child in enumerate(chunk.children):
            visit(child, (*child_indexes, child_index))

    visit(start_chunk, start_indexes)
    return tuple(selections)


def _replace_chunk_at_indexes(
    chunk: ParsedChunk[ChunkHeader],
    child_indexes: tuple[int, ...],
    replacement: ParsedChunk[ChunkHeader],
) -> ParsedChunk[ChunkHeader]:
    if not child_indexes:
        return replacement

    child_index = child_indexes[0]
    try:
        child = chunk.children[child_index]
    except IndexError:
        raise IndexError(
            f"Chunk path index {child_index} is outside "
            f"{chunk.generic_header.header_marker!r}"
        ) from None

    children = list(chunk.children)
    children[child_index] = _replace_chunk_at_indexes(
        child,
        child_indexes[1:],
        replacement,
    )
    return replace(chunk, children=tuple(children))


def chunk_as[H: ChunkHeader](
    chunk: ParsedChunk[ChunkHeader],
    expected_type: type[H],
) -> ParsedChunk[H]:
    if type(chunk.header) is not expected_type:
        raise TypeError(
            f"expected {expected_type.__name__}, "
            f"got {type(chunk.header).__name__} "
            f"at offset {chunk.offset:#x}"
        )

    return cast(
        "ParsedChunk[H]",
        chunk,
    )


def prefix_as[P: MhodPayloadPrefix](
    prefix: MhodPayloadPrefix | None,
    expected_type: type[P],
) -> P:
    if prefix is None:
        raise TypeError(
            f"expected {expected_type.__name__}, but chunk has no payload prefix"
        )

    if type(prefix) is not expected_type:
        raise TypeError(
            f"expected {expected_type.__name__}, got {type(prefix).__name__}"
        )

    return prefix


def payload_as[P: ChunkPayload](
    payload: ChunkPayload | None,
    expected_type: type[P],
) -> P:
    if payload is None:
        raise TypeError(f"expected {expected_type.__name__}, but chunk has no payload")

    if type(payload) is not expected_type:
        raise TypeError(
            f"expected {expected_type.__name__}, got {type(payload).__name__}"
        )

    return payload
