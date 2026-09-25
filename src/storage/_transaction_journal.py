"""Versioned, strictly decoded transaction intent; no filesystem access."""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from typing import cast

from storage.paths import DevicePath
from storage.transactions import FileContent, TransactionState

MAX_JOURNAL_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class JournalEntry:
    path: DevicePath
    before: FileContent | None
    after: FileContent | None
    before_modified_ns: int | None = None
    after_modified_ns: int | None = None


@dataclass(frozen=True, slots=True)
class JournalDependency:
    path: DevicePath
    content: FileContent | None


@dataclass(frozen=True, slots=True)
class TransactionJournal:
    device_id: str
    volume_id: str
    state: TransactionState
    entries: tuple[JournalEntry, ...]
    dependencies: tuple[JournalDependency, ...]
    recovery_material_identity: str = ""


def validate_paths(paths: tuple[DevicePath, ...], *, case_sensitive: bool) -> None:
    keys: set[tuple[str, ...]] = set()
    for path in paths:
        if path.parts[0].casefold() in (".iopenpod-recovery", ".iopenpod-trash"):
            raise ValueError(
                "Transaction targets cannot use Storage recovery namespaces"
            )
        normalized = tuple(
            unicodedata.normalize("NFC", component) for component in path.parts
        )
        key = (
            normalized
            if case_sensitive
            else tuple(component.casefold() for component in normalized)
        )
        if key in keys:
            raise ValueError("Transaction paths contain duplicate or aliased targets")
        keys.add(key)
    if any(key[:i] in keys for key in keys for i in range(1, len(key))):
        raise ValueError("A transaction file cannot be an ancestor of another target")


def journal_root(path: DevicePath) -> DevicePath:
    if (
        len(path.parts) != 3
        or path.parts[0] != ".iopenpod-recovery"
        or path.name != "transaction.json"
    ):
        raise ValueError("Choose a Storage transaction journal")
    identity = path.parts[1]
    if len(identity) != 32 or any(c not in "0123456789abcdef" for c in identity):
        raise ValueError("Invalid transaction journal identity")
    assert path.parent is not None
    return path.parent


def _content(value: FileContent | None) -> dict[str, object] | None:
    return None if value is None else {"size": value.size, "sha256": value.sha256}


def encode(journal: TransactionJournal) -> bytes:
    version = (
        2
        if journal.recovery_material_identity
        or any(
            entry.before_modified_ns is not None or entry.after_modified_ns is not None
            for entry in journal.entries
        )
        else 1
    )
    entries: list[dict[str, object]] = [
        {
            "path": str(entry.path),
            "before": _content(entry.before),
            "after": _content(entry.after),
        }
        for entry in journal.entries
    ]
    document: dict[str, object] = {
        "version": version,
        "device_id": journal.device_id,
        "volume_id": journal.volume_id,
        "state": journal.state.value,
        "entries": entries,
        "dependencies": [
            {"path": str(entry.path), "content": _content(entry.content)}
            for entry in journal.dependencies
        ],
    }
    if version == 2:
        document["recovery_material_identity"] = journal.recovery_material_identity
        for encoded, entry in zip(entries, journal.entries, strict=True):
            encoded["before_modified_ns"] = entry.before_modified_ns
            encoded["after_modified_ns"] = entry.after_modified_ns
    data = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(data) > MAX_JOURNAL_BYTES:
        raise ValueError("Transaction journal exceeds its supported size")
    return data


def _object(value: object, keys: set[str]) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Invalid transaction journal fields")
    fields = cast("dict[object, object]", value)
    if set(fields) != keys:
        raise ValueError("Invalid transaction journal fields")
    return cast("dict[str, object]", fields)


def _text(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("Expected nonempty journal text")
    return value


def _items(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("Expected journal entries")
    return cast("list[object]", value)


def _unique_object(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in items:
        if key in result:
            raise ValueError("Duplicate transaction journal field")
        result[key] = value
    return result


def _read_content(value: object) -> FileContent | None:
    if value is None:
        return None
    fields = _object(value, {"size", "sha256"})
    size = fields["size"]
    if type(size) is not int:
        raise ValueError("Expected integer content size")
    return FileContent(size, _text(fields["sha256"]))


def _read_modified_ns(value: object) -> int | None:
    if value is None:
        return None
    if type(value) is not int or not 0 <= value < 1 << 63:
        raise ValueError("Invalid transaction modification time")
    return value


def _read_path(value: object, *, exact_parts: bool) -> DevicePath:
    text = _text(value)
    if exact_parts:
        return DevicePath.from_parts(tuple(text.split("/")))
    return DevicePath(text)


def decode(data: bytes) -> TransactionJournal:
    if len(data) > MAX_JOURNAL_BYTES:
        raise ValueError("Transaction journal exceeds its supported size")
    decoded: object = json.loads(data, object_pairs_hook=_unique_object)
    if not isinstance(decoded, dict):
        raise ValueError("Invalid transaction journal fields")
    raw_fields = cast("dict[object, object]", decoded)
    version = raw_fields.get("version")
    if type(version) is not int or version not in {1, 2}:
        raise ValueError("Unsupported transaction journal version")
    root_keys = {
        "version",
        "device_id",
        "volume_id",
        "state",
        "entries",
        "dependencies",
    }
    if version == 2:
        root_keys.add("recovery_material_identity")
    fields = _object(raw_fields, root_keys)
    entries: list[JournalEntry] = []
    removing = False
    for raw in _items(fields["entries"]):
        entry_keys = {"path", "before", "after"}
        if version == 2:
            entry_keys.update({"before_modified_ns", "after_modified_ns"})
        item = _object(raw, entry_keys)
        entry = JournalEntry(
            _read_path(item["path"], exact_parts=version == 2),
            _read_content(item["before"]),
            _read_content(item["after"]),
            _read_modified_ns(item["before_modified_ns"]) if version == 2 else None,
            _read_modified_ns(item["after_modified_ns"]) if version == 2 else None,
        )
        if entry.before is None and entry.after is None:
            raise ValueError("An operation must have original or resulting content")
        if entry.after is None:
            removing = True
        elif removing:
            raise ValueError("Transaction writes must precede removals")
        entries.append(entry)
    if not entries:
        raise ValueError("A transaction journal needs at least one file change")
    dependencies: list[JournalDependency] = []
    for raw in _items(fields["dependencies"]):
        item = _object(raw, {"path", "content"})
        dependencies.append(
            JournalDependency(
                _read_path(item["path"], exact_parts=version == 2),
                _read_content(item["content"]),
            )
        )
    return TransactionJournal(
        _text(fields["device_id"]),
        _text(fields["volume_id"]),
        TransactionState(_text(fields["state"])),
        tuple(entries),
        tuple(dependencies),
        _text(fields["recovery_material_identity"])
        if version == 2 and fields["recovery_material_identity"]
        else "",
    )
