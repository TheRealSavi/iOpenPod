"""Versioned, advisory metadata receipts for already published Phase charts."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from hashlib import sha256
from typing import TYPE_CHECKING, cast

from storage import DevicePath, FileFingerprint, FileIdentity

if TYPE_CHECKING:
    from storage import FilesystemSession

VALIDATION_PATH = DevicePath("iPod_Control/iOpenPod/phase-validation-v1.json")
CACHE_LIMIT = 8 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class PhaseCacheEntry:
    provenance: str
    audio_path: str
    audio: FileIdentity | None
    chart_path: str
    chart: FileIdentity | None


def reuse_entry(
    session: FilesystemSession,
    entry: PhaseCacheEntry,
    *,
    audio_path: DevicePath,
    chart_path: DevicePath,
    chart_size: int,
) -> PhaseCacheEntry | None:
    """Validate metadata without making retained audio a write dependency."""
    if (
        entry.audio is None
        or entry.audio_path != str(audio_path)
        or entry.chart_path != str(chart_path)
        or session.file_identity(audio_path) != entry.audio
        or not session.exists(chart_path)
    ):
        return None
    chart_identity = session.file_identity(chart_path)
    if chart_identity.size != chart_size:
        return None
    if entry.chart != chart_identity:
        # Publication assigns the final inode/time. Verify only the small chart
        # once on the next save, then retain that published identity.
        snapshot = session.read_snapshot(chart_path, max_bytes=16 * 1024 * 1024)
        if (
            len(snapshot.data) != chart_size
            or len(snapshot.data) < 90
            or snapshot.data[:4] != b"pha\x02"
            or sha256(snapshot.data).hexdigest() != entry.provenance.rsplit(":", 1)[-1]
        ):
            return None
        observed = fingerprint_identity(snapshot.fingerprint)
        assert observed is not None
        chart_identity = observed
    return PhaseCacheEntry(
        entry.provenance, str(audio_path), entry.audio, str(chart_path), chart_identity
    )


def fingerprint_identity(value: FileFingerprint | None) -> FileIdentity | None:
    if value is None:
        return None
    return FileIdentity(value.size, value.modified_ns, value.device, value.inode)


def _identity(value: object) -> FileIdentity | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Invalid Phase cache identity")
    fields = cast("dict[str, object]", value)
    numbers = tuple(
        fields.get(key) for key in ("size", "modified_ns", "device", "inode")
    )
    if any(type(number) is not int for number in numbers):
        raise ValueError("Invalid Phase cache identity fields")
    return FileIdentity(*cast("tuple[int, int, int, int]", numbers))


def decode_validation(data: bytes | None) -> dict[str, PhaseCacheEntry]:
    """Unknown or damaged advisory receipts fall back to content verification."""
    if data is None:
        return {}
    try:
        value: object = json.loads(data)
        if not isinstance(value, dict):
            return {}
        document = cast("dict[str, object]", value)
        rows = document.get("tracks")
        if document.get("version") != 1 or not isinstance(rows, dict):
            return {}
        result: dict[str, PhaseCacheEntry] = {}
        for pid, raw in cast("dict[str, object]", rows).items():
            if not isinstance(raw, dict):
                continue
            row = cast("dict[str, object]", raw)
            provenance, audio_path, chart_path = (
                row.get("provenance"),
                row.get("audio_path"),
                row.get("chart_path"),
            )
            if not all(
                isinstance(v, str) for v in (provenance, audio_path, chart_path)
            ):
                continue
            try:
                result[pid] = PhaseCacheEntry(
                    cast("str", provenance),
                    cast("str", audio_path),
                    _identity(row.get("audio")),
                    cast("str", chart_path),
                    _identity(row.get("chart")),
                )
            except ValueError:
                continue
        return result
    except (ValueError, UnicodeDecodeError):
        return {}


def encode_validation(entries: dict[str, PhaseCacheEntry]) -> bytes:
    data = (
        json.dumps(
            {
                "version": 1,
                "tracks": {pid: asdict(entry) for pid, entry in entries.items()},
            },
            sort_keys=True,
        )
        + "\n"
    ).encode()
    if len(data) > CACHE_LIMIT:
        raise ValueError("Phase validation cache exceeds its supported size.")
    return data
