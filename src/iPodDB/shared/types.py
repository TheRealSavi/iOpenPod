from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import (
    Any,
    Literal,
    NamedTuple,
    NewType,
    Protocol,
    cast,
)

from iPodDB.shared.binary_struct import (
    binary_fields,
    validate_binary_struct_definition,
)
from iPodDB.shared.chunk import (
    ChunkAncestor,
    ChunkHeader,
    EmptyChunkHeader,
    MhodChunkHeader,
    MhodPayload,
    MhodPayloadPrefix,
    MhsdChunkHeader,
)

MHODTypeID = NewType("MHODTypeID", int)


@dataclass(frozen=True, slots=True)
class ChunkDefinition[HeaderT: ChunkHeader]:
    """Format facts shared by a database parser and writer."""

    marker: bytes
    purpose: str
    header_type: type[HeaderT]
    minimum_header_size: int
    header_sizes: tuple[int, ...]
    extent_type: Literal["length", "child_count"]
    body_kind: Literal["children", "dataset", "mhod", "opaque"]
    child_marker_groups: tuple[frozenset[bytes], ...]

    def __post_init__(self) -> None:
        if len(self.marker) != 4:
            raise ValueError("Chunk Header Markers must contain exactly four bytes")
        if self.minimum_header_size < 12:
            raise ValueError("Chunk minimum header sizes cannot be smaller than 12")
        if not self.header_sizes:
            raise ValueError("Chunk definitions require a writable header size")
        if any(size < self.minimum_header_size for size in self.header_sizes):
            raise ValueError("known header sizes cannot be below the minimum")
        validate_binary_struct_definition(
            self.header_type,
            supported_sizes=self.header_sizes,
        )
        if self.extent_type == "child_count":
            if self.header_type is not EmptyChunkHeader:
                raise ValueError("child-count Chunks must use EmptyChunkHeader")
            if self.body_kind != "children":
                raise ValueError("child-count Chunks must contain children")

        child_count_fields = 0
        for binary_field in binary_fields(self.header_type):
            child_count_fields += binary_field.schema.counts_children

        expected_groups = 1 if self.extent_type == "child_count" else child_count_fields
        if self.body_kind == "children":
            if len(self.child_marker_groups) != expected_groups:
                raise ValueError(
                    f"{self.marker!r} defines {expected_groups} child counts but "
                    f"{len(self.child_marker_groups)} child marker groups"
                )
        else:
            if expected_groups:
                raise ValueError(
                    f"{self.body_kind} Chunks cannot declare child-count fields"
                )
            if self.child_marker_groups:
                raise ValueError(
                    f"{self.body_kind} Chunks cannot declare structured child groups"
                )

        if self.body_kind == "mhod" and not issubclass(
            self.header_type,
            MhodChunkHeader,
        ):
            raise ValueError("MHOD bodies require an MhodChunkHeader")
        if self.body_kind == "dataset" and not issubclass(
            self.header_type,
            MhsdChunkHeader,
        ):
            raise ValueError("dataset bodies require an MhsdChunkHeader")

    @property
    def default_header_size(self) -> int:
        """Return the header size emitted for a newly constructed Chunk."""
        return self.header_sizes[-1]

    @property
    def known_child_markers(self) -> frozenset[bytes]:
        """Return every known Header Marker allowed in the child groups."""
        return frozenset[bytes]().union(*self.child_marker_groups)

    def require_header(self, header: ChunkHeader) -> HeaderT:
        """Return a header only when it has this definition's declared type."""

        if type(header) is not self.header_type:
            raise TypeError(
                f"{self.marker!r} requires {self.header_type.__name__}, "
                f"got {type(header).__name__}"
            )
        return header


type ErasedChunkDefinition = ChunkDefinition[ChunkHeader]


@dataclass(frozen=True, slots=True)
class MhsdDatasetDefinition:
    """Known structure belonging to one MHSD dataset type."""

    dataset_type: int
    purpose: str
    child_definition: ChunkDefinition[EmptyChunkHeader]


@dataclass(frozen=True, slots=True)
class OpaqueMhsdDatasetDefinition:
    """Known MHSD dataset whose body has no Chunk structure."""

    dataset_type: int
    purpose: str


type MhsdDatasetSpec = MhsdDatasetDefinition | OpaqueMhsdDatasetDefinition


@dataclass(frozen=True, slots=True)
class DatabaseDefinition[RootHeaderT: ChunkHeader]:
    """One immutable structural definition shared by parsing and writing."""

    root_chunk: ChunkDefinition[RootHeaderT]
    chunk_definitions: tuple[ErasedChunkDefinition, ...]
    mhsd_dataset_definitions: tuple[MhsdDatasetSpec, ...]
    _chunks_by_marker: Mapping[bytes, ErasedChunkDefinition] = field(
        init=False,
        repr=False,
    )
    _datasets_by_type: Mapping[int, MhsdDatasetSpec] = field(
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        chunks_by_marker: dict[bytes, ErasedChunkDefinition] = {}
        for definition in self.chunk_definitions:
            if definition.marker in chunks_by_marker:
                raise ValueError(
                    f"duplicate Chunk definition for {definition.marker!r}"
                )
            chunks_by_marker[definition.marker] = definition

        if chunks_by_marker.get(self.root_chunk.marker) is not self.root_chunk:
            raise ValueError(
                "the database root must be its registered Chunk definition"
            )

        for definition in self.chunk_definitions:
            for child_marker in definition.known_child_markers:
                if child_marker not in chunks_by_marker:
                    raise ValueError(
                        f"{definition.marker!r} references unregistered child "
                        f"{child_marker!r}"
                    )

        datasets_by_type: dict[int, MhsdDatasetSpec] = {}
        for dataset_definition in self.mhsd_dataset_definitions:
            dataset_type = dataset_definition.dataset_type
            if dataset_type in datasets_by_type:
                raise ValueError(f"duplicate MHSD dataset definition {dataset_type}")
            datasets_by_type[dataset_type] = dataset_definition
            if isinstance(dataset_definition, MhsdDatasetDefinition):
                child_definition = dataset_definition.child_definition
                if (
                    chunks_by_marker.get(child_definition.marker)
                    is not child_definition
                ):
                    raise ValueError(
                        f"dataset type {dataset_type} references unregistered child "
                        f"{child_definition.marker!r}"
                    )

        object.__setattr__(
            self,
            "_chunks_by_marker",
            MappingProxyType(chunks_by_marker),
        )
        object.__setattr__(
            self,
            "_datasets_by_type",
            MappingProxyType(datasets_by_type),
        )

    def chunk_definition(self, marker: bytes) -> ErasedChunkDefinition | None:
        """Return the registered definition for a Header Marker, if known."""

        return self._chunks_by_marker.get(marker)

    def require_registered[H: ChunkHeader](
        self,
        definition: ChunkDefinition[H],
    ) -> ChunkDefinition[H]:
        """Preserve a definition's header type after proving it is registered."""

        if self._chunks_by_marker.get(definition.marker) is not definition:
            raise ValueError(
                f"{definition.marker!r} is not a registered Chunk definition"
            )
        return definition

    def dataset_definition(self, dataset_type: int) -> MhsdDatasetSpec | None:
        """Return the registered MHSD dataset definition, if known."""

        return self._datasets_by_type.get(dataset_type)


class MhodPayloadParseContext[P](NamedTuple):
    data: bytes | bytearray

    mhod_type: MHODTypeID

    chunk_offset: int
    payload_offset: int
    payload_end: int

    prefix: P

    # Parents of this MHOD, nearest parent last.
    ancestors: tuple[ChunkAncestor, ...]


class MhodPayloadParser[
    P,
    R: MhodPayload,
](Protocol):
    def __call__(
        self,
        context: MhodPayloadParseContext[P],
        /,
    ) -> R: ...


type ErasedMhodPayloadParser = Callable[
    [MhodPayloadParseContext[Any]],
    MhodPayload,
]


class MhodPayloadSpec(NamedTuple):
    """
    Runtime-erased payload specification.

    Do not normally construct this directly.

    Use:
        prefixed_mhod_payload_spec()
        unprefixed_mhod_payload_spec()

    Those functions statically verify that the prefix type agrees with
    the parser's expected MhodPayloadParseContext prefix type.
    """

    prefix_type: type[MhodPayloadPrefix] | None
    parser: ErasedMhodPayloadParser
    prefix_origin: Literal["chunk", "payload"] = "chunk"


class MhodPayloadSpecSelectionContext(NamedTuple):
    """Chunk context available while selecting a contextual MHOD layout."""

    data: bytes | bytearray
    mhod_type: MHODTypeID
    chunk_offset: int
    header_end: int
    chunk_end: int
    ancestors: tuple[ChunkAncestor, ...]


type MhodPayloadSpecResolver = Callable[
    [MhodPayloadSpecSelectionContext],
    MhodPayloadSpec,
]


class ContextualMhodPayloadSpec(NamedTuple):
    """Resolve a concrete prefix/parser pair from the containing chunk context."""

    resolver: MhodPayloadSpecResolver


def prefixed_mhod_payload_spec[
    P: MhodPayloadPrefix,
    R: MhodPayload,
](
    prefix_type: type[P],
    parser: MhodPayloadParser[P, R],
    *,
    prefix_origin: Literal["chunk", "payload"] = "chunk",
) -> MhodPayloadSpec:
    """
    Construct an MHOD specification with a fixed payload prefix.

    Static type checkers verify that `parser` expects
    MhodPayloadParseContext[P].
    """

    return MhodPayloadSpec(
        prefix_type=prefix_type,
        parser=cast(
            "ErasedMhodPayloadParser",
            parser,
        ),
        prefix_origin=prefix_origin,
    )


def unprefixed_mhod_payload_spec[
    R: MhodPayload,
](
    parser: MhodPayloadParser[None, R],
) -> MhodPayloadSpec:
    """
    Construct an MHOD specification whose payload begins directly after
    the MHOD chunk header.
    """

    return MhodPayloadSpec(
        prefix_type=None,
        parser=cast(
            "ErasedMhodPayloadParser",
            parser,
        ),
    )


def contextual_mhod_payload_spec(
    resolver: MhodPayloadSpecResolver,
) -> ContextualMhodPayloadSpec:
    return ContextualMhodPayloadSpec(resolver=resolver)


class MhodSpec(NamedTuple):
    name: str
    payload_spec: MhodPayloadSpec | ContextualMhodPayloadSpec


@dataclass(frozen=True, slots=True)
class DatabaseParserDefinition[RootHeaderT: ChunkHeader]:
    """Complete parser definition for one iPod database format."""

    database: DatabaseDefinition[RootHeaderT]
    mhod_specs: Mapping[MHODTypeID, MhodSpec]
    unknown_mhod_spec: MhodSpec

    def __post_init__(self) -> None:
        if isinstance(self.unknown_mhod_spec.payload_spec, ContextualMhodPayloadSpec):
            raise ValueError("the unknown MHOD parser cannot depend on parent context")
        object.__setattr__(
            self,
            "mhod_specs",
            MappingProxyType(dict(self.mhod_specs)),
        )

    def mhod_spec(self, mhod_type: MHODTypeID) -> MhodSpec:
        """Return the registered MHOD parser or the mandatory opaque parser."""

        return self.mhod_specs.get(mhod_type, self.unknown_mhod_spec)
