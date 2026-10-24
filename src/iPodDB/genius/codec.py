"""Bounded, lossless Genius version-2 blob codecs without SQL or filesystem I/O.

Format evidence: dotm5/Genius-Mix-Research, docs/FORMAT.md at
57b7ae865a10177f725c90e946e1199c00411e53, plus the local Classic 6.5G and nano
7G experiments recorded in docs/research/genius-generation-2026-10-24.md.
Compressed similarities and unsupported versions remain explicitly opaque.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

from iPodDB.genius.models import (
    GeniusCluster,
    GeniusClusterRule,
    GeniusConfig,
    GeniusMetadata,
    GeniusNoOpRule,
    GeniusPayloadKind,
    GeniusRandomRule,
    GeniusSimilarities,
    GeniusSkipRule,
    GeniusSpacingRule,
    OpaqueGeniusPayload,
)
from iPodDB.shared.diagnostics import log_unknown_data, retain_unknown_bytes
from iPodDB.shared.errors import iPodDBParseError, iPodDBWriteError

if TYPE_CHECKING:
    from collections.abc import Iterable

    from iPodDB.genius.models import (
        GeniusConfigEntry,
        GeniusConfigPayload,
        GeniusMetadataPayload,
        GeniusSimilaritiesPayload,
    )

MAX_GENIUS_PAYLOAD_BYTES = 16 * 1024 * 1024
_WORD = struct.Struct("<I")
_KEY = struct.Struct("<Q")
_SIMILARITIES_HEADER = struct.Struct("<III")
_CLUSTER_HEADER = struct.Struct("<QI")
_SPACING_PARAMETERS = struct.Struct("<IIII")
_CLUSTER_PARAMETERS = struct.Struct("<II")
_SKIP_PARAMETERS = struct.Struct("<IIII")
_RANDOM_PARAMETERS = struct.Struct("<II")
_COMPATIBILITY_TAIL = struct.pack("<11I", 70, 100, 1, 20, 50, 10, 10, 0, 0, 10, 20)


class GeniusFormatError(iPodDBParseError):
    """A known Genius representation has malformed framing or truncated fields."""


def _capture(data: bytes, version: int | None) -> bytes:
    if type(data) is not bytes:
        raise TypeError("Genius payloads require immutable bytes.")
    if version is not None and type(version) is not int:
        raise TypeError("Genius versions require an integer or None.")
    if len(data) > MAX_GENIUS_PAYLOAD_BYTES:
        raise GeniusFormatError("Genius payload exceeds the byte limit.")
    return data


def _opaque(
    data: bytes, kind: GeniusPayloadKind, version: int | None, reason: str
) -> OpaqueGeniusPayload:
    return OpaqueGeniusPayload(
        kind, version, retain_unknown_bytes(data, 0, len(data), reason), reason
    )


def _require(data: bytes, offset: int, size: int) -> None:
    if size > len(data) - offset:
        raise GeniusFormatError("Truncated Genius payload.")


def _read_values(data: bytes, offset: int, layout: struct.Struct) -> tuple[int, ...]:
    _require(data, offset, layout.size)
    return tuple(int(value) for value in layout.unpack_from(data, offset))


def _read_keys(data: bytes, offset: int, count: int) -> tuple[int, ...]:
    _require(data, offset, count * _KEY.size)
    return tuple(
        int(_KEY.unpack_from(data, offset + index * _KEY.size)[0])
        for index in range(count)
    )


@log_unknown_data("Genius similarities")
def parse_genius_similarities(
    data: bytes, *, version: int | None = 2
) -> GeniusSimilaritiesPayload:
    source = _capture(data, version)
    if version != 2:
        return _opaque(
            source, GeniusPayloadKind.SIMILARITIES, version, "unsupported version"
        )
    flag = _read_values(source, 0, _WORD)[0]
    if flag != 0:
        # The nonzero flag selects another representation. Its undocumented
        # framing must not be validated as if it were the plaintext structure.
        return _opaque(
            source,
            GeniusPayloadKind.SIMILARITIES,
            version,
            "compressed or unsupported similarities",
        )
    _, payload_size, count = _read_values(source, 0, _SIMILARITIES_HEADER)
    payload_end = 2 * _WORD.size + payload_size
    ids_end = _SIMILARITIES_HEADER.size + count * _KEY.size
    if payload_size < _WORD.size or ids_end > payload_end:
        raise GeniusFormatError("Genius candidate count exceeds its payload length.")
    _require(source, 0, payload_end)
    return GeniusSimilarities(
        _read_keys(source, _SIMILARITIES_HEADER.size, count),
        retain_unknown_bytes(source, ids_end, payload_end, "similarities payload tail"),
        retain_unknown_bytes(source, payload_end, len(source), "similarities suffix"),
        version=version,
    )


@log_unknown_data("Genius metadata")
def parse_genius_metadata(
    data: bytes, *, version: int | None = 2
) -> GeniusMetadataPayload:
    source = _capture(data, version)
    if version != 2:
        return _opaque(
            source, GeniusPayloadKind.METADATA, version, "unsupported version"
        )
    count = len(source) // _KEY.size
    return GeniusMetadata(
        _read_keys(source, 0, count),
        retain_unknown_bytes(
            source, count * _KEY.size, len(source), "metadata partial-key suffix"
        ),
        version=version,
    )


def _read_cluster_rule(data: bytes, offset: int) -> tuple[GeniusClusterRule, int]:
    field_index, count = _read_values(data, offset, _CLUSTER_PARAMETERS)
    offset += _CLUSTER_PARAMETERS.size
    _require(data, offset, count * _CLUSTER_HEADER.size)
    clusters: list[GeniusCluster] = []
    for _ in range(count):
        cluster_id, inner_count = _read_values(data, offset, _CLUSTER_HEADER)
        offset += _CLUSTER_HEADER.size
        keys = _read_keys(data, offset, inner_count)
        offset += inner_count * _KEY.size
        clusters.append(GeniusCluster(cluster_id, keys))
    return GeniusClusterRule(field_index, tuple(clusters)), offset


@log_unknown_data("Genius config")
def parse_genius_config(data: bytes, *, version: int | None = 2) -> GeniusConfigPayload:
    source = _capture(data, version)
    if version != 2:
        return _opaque(source, GeniusPayloadKind.CONFIG, version, "unsupported version")
    count = _read_values(source, 0, _WORD)[0]
    offset = _WORD.size
    _require(source, offset, count * _WORD.size)
    entries: list[GeniusConfigEntry] = []
    for _ in range(count):
        opcode = _read_values(source, offset, _WORD)[0]
        offset += _WORD.size
        match opcode:
            case 1 | 3:
                field_index, floor, distance, jitter = _read_values(
                    source, offset, _SPACING_PARAMETERS
                )
                entries.append(
                    GeniusSpacingRule(
                        field_index, floor, distance, jitter, opcode=opcode
                    )
                )
                offset += _SPACING_PARAMETERS.size
            case 2:
                cluster_rule, offset = _read_cluster_rule(source, offset)
                entries.append(cluster_rule)
            case 4:
                minimum_skips, window, gap, percentage = _read_values(
                    source, offset, _SKIP_PARAMETERS
                )
                entries.append(GeniusSkipRule(minimum_skips, window, gap, percentage))
                offset += _SKIP_PARAMETERS.size
            case 5:
                initial, later = _read_values(source, offset, _RANDOM_PARAMETERS)
                entries.append(GeniusRandomRule(initial, later))
                offset += _RANDOM_PARAMETERS.size
            case 6:
                entries.append(GeniusNoOpRule())
            case _:
                # Unknown opcodes have no trusted length, so the remainder
                # cannot be segmented safely into entries and control bytes.
                return _opaque(
                    source,
                    GeniusPayloadKind.CONFIG,
                    version,
                    "unsupported config opcode",
                )
    return GeniusConfig(
        tuple(entries),
        retain_unknown_bytes(source, offset, len(source), "config control tail"),
        version=version,
    )


def _check_bytes(data: bytes) -> None:
    if type(data) is not bytes:
        raise iPodDBWriteError("Genius retained regions require immutable bytes.")


def _check_size(size: int) -> None:
    if size > MAX_GENIUS_PAYLOAD_BYTES:
        raise iPodDBWriteError("Genius payload exceeds the byte limit.")


def _integer(value: int, width: int) -> int:
    if type(value) is not int or not 0 <= value < 1 << width:
        raise iPodDBWriteError(f"Genius values require unsigned {width}-bit integers.")
    return value


def _pack(layout: struct.Struct, values: Iterable[int], width: int = 32) -> bytes:
    return layout.pack(*(_integer(value, width) for value in values))


def _known_version(version: int | None) -> None:
    if type(version) is not int or version != 2:
        raise iPodDBWriteError("Only Genius payload version 2 can be authored.")


def _write_opaque(payload: OpaqueGeniusPayload, kind: GeniusPayloadKind) -> bytes:
    if payload.kind is not kind:
        raise iPodDBWriteError("Opaque Genius payload belongs to another table.")
    _check_bytes(payload.data)
    _check_size(len(payload.data))
    return payload.data


def serialize_genius_similarities(payload: GeniusSimilaritiesPayload) -> bytes:
    if isinstance(payload, OpaqueGeniusPayload):
        return _write_opaque(payload, GeniusPayloadKind.SIMILARITIES)
    _known_version(payload.version)
    _check_bytes(payload.payload_tail)
    _check_bytes(payload.trailing_data)
    count = len(payload.candidates)
    size = _WORD.size + count * _KEY.size + len(payload.payload_tail)
    _check_size(2 * _WORD.size + size + len(payload.trailing_data))
    return (
        _pack(_SIMILARITIES_HEADER, (0, size, count))
        + b"".join(_pack(_KEY, (key,), 64) for key in payload.candidates)
        + payload.payload_tail
        + payload.trailing_data
    )


def serialize_genius_metadata(payload: GeniusMetadataPayload) -> bytes:
    if isinstance(payload, OpaqueGeniusPayload):
        return _write_opaque(payload, GeniusPayloadKind.METADATA)
    _known_version(payload.version)
    _check_bytes(payload.trailing_data)
    if len(payload.trailing_data) >= _KEY.size:
        raise iPodDBWriteError("Metadata suffix would be interpreted as another key.")
    _check_size(len(payload.keys) * _KEY.size + len(payload.trailing_data))
    return (
        b"".join(_pack(_KEY, (key,), 64) for key in payload.keys)
        + payload.trailing_data
    )


def _entry_size(entry: GeniusConfigEntry) -> int:
    match entry:
        case GeniusSpacingRule():
            return _WORD.size + _SPACING_PARAMETERS.size
        case GeniusClusterRule():
            return (
                _WORD.size
                + _CLUSTER_PARAMETERS.size
                + sum(
                    _CLUSTER_HEADER.size + len(cluster.compatible_ids) * _KEY.size
                    for cluster in entry.clusters
                )
            )
        case GeniusSkipRule():
            return _WORD.size + _SKIP_PARAMETERS.size
        case GeniusRandomRule():
            return _WORD.size + _RANDOM_PARAMETERS.size
        case GeniusNoOpRule():
            return _WORD.size
        case _:
            raise iPodDBWriteError("Unsupported Genius config entry.")


def _write_entry(entry: GeniusConfigEntry) -> bytes:
    match entry:
        case GeniusSpacingRule():
            if type(entry.opcode) is not int or entry.opcode not in (1, 3):
                raise iPodDBWriteError("Spacing rule opcode must be 1 or 3.")
            return _pack(_WORD, (entry.opcode,)) + _pack(
                _SPACING_PARAMETERS,
                (entry.field_index, entry.floor, entry.distance, entry.jitter),
            )
        case GeniusClusterRule():
            output = bytearray(_pack(_WORD, (2,)))
            output.extend(
                _pack(_CLUSTER_PARAMETERS, (entry.field_index, len(entry.clusters)))
            )
            for cluster in entry.clusters:
                output.extend(
                    _CLUSTER_HEADER.pack(
                        _integer(cluster.cluster_id, 64),
                        _integer(len(cluster.compatible_ids), 32),
                    )
                )
                for key in cluster.compatible_ids:
                    output.extend(_pack(_KEY, (key,), 64))
            return bytes(output)
        case GeniusSkipRule():
            return _pack(_WORD, (4,)) + _pack(
                _SKIP_PARAMETERS,
                (
                    entry.minimum_skips,
                    entry.window_seconds,
                    entry.play_gap_seconds,
                    entry.skip_percentage,
                ),
            )
        case GeniusRandomRule():
            return _pack(_WORD, (5,)) + _pack(
                _RANDOM_PARAMETERS, (entry.initial_threshold, entry.later_threshold)
            )
        case GeniusNoOpRule():
            return _pack(_WORD, (6,))
        case _:
            raise iPodDBWriteError("Unsupported Genius config entry.")


def serialize_genius_config(payload: GeniusConfigPayload) -> bytes:
    if isinstance(payload, OpaqueGeniusPayload):
        return _write_opaque(payload, GeniusPayloadKind.CONFIG)
    _known_version(payload.version)
    _check_bytes(payload.control_tail)
    _check_size(
        _WORD.size
        + sum(_entry_size(entry) for entry in payload.entries)
        + len(payload.control_tail)
    )
    return (
        _pack(_WORD, (len(payload.entries),))
        + b"".join(_write_entry(entry) for entry in payload.entries)
        + payload.control_tail
    )


def make_no_rule_genius_config() -> GeniusConfig:
    """The 48-byte compact variant accepted in the local hardware experiments.

    Its 44-byte compatibility suffix is historical, not canonical firmware
    defaults. This constructor does not promise playability for an arbitrary
    candidate graph or device; result thresholds remain separate table fields.
    """
    return GeniusConfig((), _COMPATIBILITY_TAIL)


def make_limited_genius_config() -> GeniusConfig:
    """The upstream 108-byte variant with two spacing rules and skip filtering."""
    return GeniusConfig(
        (
            GeniusSpacingRule(2, 2, 10, 6),
            GeniusSpacingRule(3, 3, 10, 6),
            GeniusSkipRule(2, 604800, 0, 50),
        ),
        _COMPATIBILITY_TAIL,
    )
