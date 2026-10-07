"""Disposable Host-side iPod analysis, separate from committed Sync provenance."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from iOpenPod.app.media.fingerprint_codec import decode_fingerprint, encode_fingerprint
from storage import DevicePath

if TYPE_CHECKING:
    from storage import AtomicHostFile, FilesystemSession


_MAX_BYTES = 64 * 1024 * 1024
_MAX_RECORDS = 250_000
_MAX_DECODED_ACOUSTIC_BYTES = 256 * 1024 * 1024
_CHECKPOINT_SECONDS = 30.0


@dataclass(frozen=True, slots=True)
class IPodAnalysisRecord:
    """Analysis only; a Host cache can never supply committed Sync Details."""

    kind: str
    identity: int
    path: DevicePath
    size_bytes: int
    modified_ns: int
    fingerprint: str

    @property
    def key(self) -> tuple[str, int, DevicePath]:
        return self.kind, self.identity, self.path


def ipod_analysis_cache_identity(session: FilesystemSession) -> str:
    """Keep reconnects reusable without sharing evidence between Volumes/devices."""
    mounted = session.mounted_volume
    identity = [mounted.physical_device.id.value, mounted.volume.id.value]
    return hashlib.sha256(_json(identity)).hexdigest()


class IPodAnalysisCache:
    """One bounded, checksummed, atomically published per-device Host cache."""

    def __init__(self, file: AtomicHostFile, identity: str) -> None:
        self._file = file
        self._identity = identity
        self._records: dict[tuple[str, int, DevicePath], IPodAnalysisRecord] = {}
        self._decoded_acoustic_bytes = 0
        self._dirty = False
        self._last_save = time.monotonic()
        self._loaded = False
        self._revision: tuple[int, int, int, int] | None = None

    def load(self) -> None:
        try:
            revision = self._file.revision()
        except (OSError, ValueError):
            self._clear()
            raise
        if self._loaded and revision == self._revision:
            return
        # An external replacement/deletion retires every previous in-memory entry.
        self._clear()
        payload = self._file.read_bytes(max_bytes=_MAX_BYTES)
        if self._file.revision() != revision:
            raise ValueError("The iPod analysis cache changed while it was read")
        if payload is None:
            self._loaded = True
            self._revision = revision
            return
        if len(payload) > _MAX_BYTES:
            raise ValueError("The iPod analysis cache exceeds 64 MiB")
        try:
            raw_document: object = json.loads(payload, object_pairs_hook=_pairs)
        except RecursionError as error:
            raise ValueError("The iPod analysis cache is nested too deeply") from error
        if not isinstance(raw_document, dict):
            raise ValueError("The iPod analysis cache must be an object")
        document = cast("dict[str, object]", raw_document)
        if set(document) != {"version", "identity", "records", "sha256"}:
            raise ValueError("The iPod analysis cache fields are invalid")
        version = document["version"]
        if isinstance(version, bool) or version != 1:
            raise ValueError("The iPod analysis cache version is unsupported")
        if document["identity"] != self._identity:
            raise ValueError("The iPod analysis cache belongs to a different device")
        raw_rows = document["records"]
        if not isinstance(raw_rows, list):
            raise ValueError("The iPod analysis cache records are invalid")
        rows = cast("list[object]", raw_rows)
        if len(rows) > _MAX_RECORDS:
            raise ValueError("The iPod analysis cache records are invalid")
        if hashlib.sha256(_json(rows)).hexdigest() != document["sha256"]:
            raise ValueError("The iPod analysis cache checksum does not match")
        records: list[IPodAnalysisRecord] = []
        decoded_bytes = 0
        for row in rows:
            record = _decode(row)
            if record.kind != "image":
                decoded_bytes += len(record.fingerprint)
                if decoded_bytes > _MAX_DECODED_ACOUSTIC_BYTES:
                    raise ValueError(
                        "The iPod analysis decoded acoustic data exceeds 256 MiB"
                    )
            records.append(record)
        indexed = {record.key: record for record in records}
        if len(indexed) != len(records):
            raise ValueError("The iPod analysis cache contains duplicate identities")
        self._records = indexed
        self._decoded_acoustic_bytes = decoded_bytes
        self._loaded = True
        self._revision = revision

    def _clear(self) -> None:
        self._records.clear()
        self._decoded_acoustic_bytes = 0
        self._dirty = False
        self._loaded = False

    def get(
        self, kind: str, identity: int, path: DevicePath
    ) -> IPodAnalysisRecord | None:
        return self._records.get((kind, identity, path))

    def remember(self, record: IPodAnalysisRecord) -> None:
        if self._records.get(record.key) == record:
            return
        size = _acoustic_size(record)
        if size > _MAX_DECODED_ACOUSTIC_BYTES:
            return
        previous = self._records.pop(record.key, None)
        if previous is not None:
            self._decoded_acoustic_bytes -= _acoustic_size(previous)
        while self._records and (
            len(self._records) >= _MAX_RECORDS
            or self._decoded_acoustic_bytes + size > _MAX_DECODED_ACOUSTIC_BYTES
        ):
            self._discard_oldest()
        self._records[record.key] = record
        self._decoded_acoustic_bytes += size
        self._dirty = True

    def _discard_oldest(self) -> None:
        record = self._records.pop(next(iter(self._records)))
        self._decoded_acoustic_bytes -= _acoustic_size(record)

    def save(self, *, force: bool = False) -> None:
        if not self._dirty or (
            not force and time.monotonic() - self._last_save < _CHECKPOINT_SECONDS
        ):
            return
        rows = [_encode(record) for record in self._records.values()]
        row_sizes = [len(_json(row)) + 1 for row in rows]
        size = sum(row_sizes)
        first = 0
        while size > _MAX_BYTES - 512 and first < len(rows):
            size -= row_sizes[first]
            first += 1
            self._discard_oldest()
        records = rows[first:]
        payload = _json(
            {
                "version": 1,
                "identity": self._identity,
                "records": records,
                "sha256": hashlib.sha256(_json(records)).hexdigest(),
            }
        )
        if len(payload) > _MAX_BYTES:
            raise ValueError("The iPod analysis cache exceeds 64 MiB")
        self._file.replace_bytes(payload)
        self._revision = self._file.revision()
        self._loaded = True
        self._dirty = False
        self._last_save = time.monotonic()


def _encode(record: IPodAnalysisRecord) -> list[object]:
    return [
        record.kind,
        str(record.identity),
        str(record.path),
        record.size_bytes,
        record.modified_ns,
        encode_fingerprint(record.fingerprint)
        if record.kind != "image"
        else record.fingerprint,
    ]


def _acoustic_size(record: IPodAnalysisRecord) -> int:
    return 0 if record.kind == "image" else len(record.fingerprint)


def _decode(value: object) -> IPodAnalysisRecord:
    if not isinstance(value, list):
        raise ValueError("The iPod analysis record fields are invalid")
    values = cast("list[object]", value)
    if len(values) != 6:
        raise ValueError("The iPod analysis record fields are invalid")
    kind, identity, path, size, modified, fingerprint = values
    if not isinstance(kind, str) or kind not in ("database", "track", "image"):
        raise ValueError("The iPod analysis record kind is invalid")
    if (
        not isinstance(identity, str)
        or not identity.isascii()
        or not identity.isdigit()
        or len(identity) > 32
        or int(identity) <= 0
    ):
        raise ValueError("The iPod analysis identity is invalid")
    if not isinstance(path, str) or not isinstance(fingerprint, str):
        raise ValueError("The iPod analysis path and fingerprint must be text")
    if (
        not isinstance(size, int)
        or isinstance(size, bool)
        or size < 0
        or not isinstance(modified, int)
        or isinstance(modified, bool)
        or modified < 0
    ):
        raise ValueError("The iPod analysis file facts are invalid")
    if kind == "image":
        if len(fingerprint) != 64 or any(
            c not in "0123456789abcdef" for c in fingerprint
        ):
            raise ValueError("The iPod analysis image digest is invalid")
    else:
        fingerprint = decode_fingerprint(fingerprint)
        if not fingerprint:
            raise ValueError("The iPod analysis acoustic fingerprint is empty")
    return IPodAnalysisRecord(
        kind, int(identity), DevicePath(path), size, modified, fingerprint
    )


def _pairs(values: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in values:
        if key in result:
            raise ValueError("The iPod analysis cache has duplicate fields")
        result[key] = value
    return result


def _json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except RecursionError as error:
        raise ValueError("The iPod analysis cache is nested too deeply") from error
