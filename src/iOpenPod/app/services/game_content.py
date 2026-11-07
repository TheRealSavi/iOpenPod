"""Bounded fingerprints for the extracted Host game folders."""

from __future__ import annotations

import hashlib
import json
import stat
from dataclasses import dataclass
from typing import TYPE_CHECKING

from storage import DevicePath, FileContent, HostPath
from storage.host_installation import require_plain_path

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class GameFile:
    relative: str
    source: HostPath
    content: FileContent


@dataclass(frozen=True, slots=True)
class GameContents:
    files: tuple[GameFile, ...]
    directories: tuple[str, ...]
    sha256: str


def inspect_contents(root: Path, checkpoint: Callable[[], None]) -> GameContents:
    """Retain empty directories and reject links while capturing all file bytes."""
    require_plain_path(root)
    if not root.is_dir():
        raise ValueError("The cached game folder is missing.")
    directories: set[str] = set()
    records: list[GameFile] = []
    seen: set[str] = set()
    pending = [root]
    total = 0
    while pending:
        directory = pending.pop()
        checkpoint()
        for path in sorted(directory.iterdir()):
            checkpoint()
            require_plain_path(path)
            relative = path.relative_to(root).as_posix()
            DevicePath(relative)
            if relative.casefold() in seen or len(seen) >= 20_000:
                raise ValueError(
                    "The cached game has duplicate paths or too many entries."
                )
            seen.add(relative.casefold())
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode):
                directories.add(relative)
                pending.append(path)
            elif stat.S_ISREG(mode):
                digest = hashlib.sha256()
                size = 0
                with path.open("rb") as source:
                    while block := source.read(1024 * 1024):
                        checkpoint()
                        size += len(block)
                        total += len(block)
                        if total > 512 * 1024 * 1024:
                            raise ValueError(
                                "The cached game exceeds its supported size."
                            )
                        digest.update(block)
                records.append(
                    GameFile(
                        relative, HostPath(path), FileContent(size, digest.hexdigest())
                    )
                )
            else:
                raise ValueError("The cached game contains an unsafe filesystem entry.")
    tree = {
        "directories": sorted(directories),
        "files": sorted(
            (record.relative, record.content.size, record.content.sha256)
            for record in records
        ),
    }
    fingerprint = hashlib.sha256(
        json.dumps(tree, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()
    return GameContents(tuple(records), tuple(sorted(directories)), fingerprint)
