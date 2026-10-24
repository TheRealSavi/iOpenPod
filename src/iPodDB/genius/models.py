"""Immutable Genius payloads; identities here are Genius IDs, not Track IDs."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal


class GeniusPayloadKind(StrEnum):
    CONFIG = "config"
    METADATA = "metadata"
    SIMILARITIES = "similarities"


@dataclass(frozen=True, slots=True)
class OpaqueGeniusPayload:
    """A bounded, unsupported payload retained without interpreting its bytes."""

    kind: GeniusPayloadKind
    version: int | None
    data: bytes
    reason: str


@dataclass(frozen=True, slots=True)
class GeniusSimilarities:
    """Ordered candidate Genius IDs with independently retained framing suffixes.

    ``payload_tail`` is inside the declared payload length; ``trailing_data`` is
    outside it. Neither region is discarded when the candidate list is edited.
    Repeated IDs and zero are representable: relationship validity belongs to the
    caller's complete graph, not the binary codec.
    """

    candidates: tuple[int, ...]
    payload_tail: bytes = b""
    trailing_data: bytes = b""
    version: int | None = field(default=2, kw_only=True)


@dataclass(frozen=True, slots=True)
class GeniusMetadata:
    """Variable-length constraint keys, not candidate edges or Track identities."""

    keys: tuple[int, ...]
    trailing_data: bytes = b""
    version: int | None = field(default=2, kw_only=True)


@dataclass(frozen=True, slots=True)
class GeniusSpacingRule:
    field_index: int
    floor: int
    distance: int
    jitter: int
    opcode: Literal[1, 3] = field(default=3, kw_only=True)


@dataclass(frozen=True, slots=True)
class GeniusCluster:
    cluster_id: int
    compatible_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class GeniusClusterRule:
    field_index: int
    clusters: tuple[GeniusCluster, ...]


@dataclass(frozen=True, slots=True)
class GeniusSkipRule:
    minimum_skips: int
    window_seconds: int
    play_gap_seconds: int
    skip_percentage: int


@dataclass(frozen=True, slots=True)
class GeniusRandomRule:
    initial_threshold: int
    later_threshold: int


@dataclass(frozen=True, slots=True)
class GeniusNoOpRule:
    pass


type GeniusConfigEntry = (
    GeniusSpacingRule
    | GeniusClusterRule
    | GeniusSkipRule
    | GeniusRandomRule
    | GeniusNoOpRule
)


@dataclass(frozen=True, slots=True)
class GeniusConfig:
    """Ordered constraint bytecode and its exact optional control suffix.

    The suffix is retained as bytes because its complete semantics are not known.
    It is not part of the entry stream. Playlist result thresholds are separate
    SQLite columns and are deliberately absent from this payload representation.
    """

    entries: tuple[GeniusConfigEntry, ...]
    control_tail: bytes = b""
    version: int | None = field(default=2, kw_only=True)


type GeniusSimilaritiesPayload = GeniusSimilarities | OpaqueGeniusPayload
type GeniusMetadataPayload = GeniusMetadata | OpaqueGeniusPayload
type GeniusConfigPayload = GeniusConfig | OpaqueGeniusPayload
