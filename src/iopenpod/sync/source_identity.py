"""Source audio-content identity helpers.

These hashes are used for decisions where container metadata must not count as
audio replacement.  For MP4-family files we hash media data (``mdat``) payloads
and ignore metadata atoms such as ``moov``/``udta``.  Other formats fall back to
full-file SHA-256 until they get format-specific readers.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_MP4_CONTAINER_EXTS = {".m4a", ".m4b", ".mp4", ".m4v", ".mov"}


def hash_source_file(path: str | Path) -> str:
    """Return the SHA-256 hex digest of a file's full content."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65_536), b""):
            h.update(chunk)
    return h.hexdigest()


def source_content_hash(path: str | Path) -> str:
    """Return a stable hash for source audio content."""
    source_path = Path(path)
    if source_path.suffix.lower() in _MP4_CONTAINER_EXTS:
        mdat_hash = _hash_mp4_mdat_payloads(source_path)
        if mdat_hash:
            return f"mp4-mdat-sha256:{mdat_hash}"
    return f"file-sha256:{hash_source_file(source_path)}"


def source_content_identity(source_path: Path | None) -> tuple[str | None, float]:
    """Return ``(content_hash_or_None, mtime_or_0)`` for a source file."""
    if source_path is None:
        return None, 0.0
    try:
        mtime = source_path.stat().st_mtime
        return source_content_hash(source_path), mtime
    except OSError:
        return None, 0.0


def _hash_mp4_mdat_payloads(path: Path) -> str | None:
    try:
        file_size = path.stat().st_size
        h = hashlib.sha256()
        count = 0
        with open(path, "rb") as f:
            for box_type, payload_offset, payload_size in _iter_mp4_top_level_boxes(f, file_size):
                if box_type != b"mdat":
                    continue
                f.seek(payload_offset)
                _hash_range(f, payload_size, h)
                count += 1
        return h.hexdigest() if count else None
    except OSError:
        return None


def _iter_mp4_top_level_boxes(f, file_size: int):
    offset = 0
    while offset + 8 <= file_size:
        f.seek(offset)
        header = f.read(8)
        if len(header) != 8:
            return

        box_size = int.from_bytes(header[:4], "big")
        box_type = header[4:8]
        header_size = 8

        if box_size == 1:
            extended = f.read(8)
            if len(extended) != 8:
                return
            box_size = int.from_bytes(extended, "big")
            header_size = 16
        elif box_size == 0:
            box_size = file_size - offset

        if box_size < header_size:
            return

        payload_offset = offset + header_size
        payload_size = box_size - header_size
        if payload_offset + payload_size > file_size:
            return

        yield box_type, payload_offset, payload_size
        offset += box_size


def _hash_range(f, byte_count: int, h: hashlib._Hash) -> None:
    remaining = byte_count
    while remaining > 0:
        chunk = f.read(min(65_536, remaining))
        if not chunk:
            break
        h.update(chunk)
        remaining -= len(chunk)
