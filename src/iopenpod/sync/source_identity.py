"""Source media-content identity helpers.

These hashes are used for decisions where container metadata must not count as
media replacement. For MP4-family audio we hash all media data (``mdat``)
payloads. Videos use bounded samples, while other audio formats fall back to
full-file SHA-256 until they get format-specific readers.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from ._formats import VIDEO_EXTENSIONS

_MP4_CONTAINER_EXTS = {".m4a", ".m4b", ".mp4", ".m4v", ".mov"}
_VIDEO_SAMPLE_BYTES = 256 * 1024
_VIDEO_SAMPLE_COUNT = 8


def mp4_duration_ms(path: str | Path) -> int:
    """Read an MP4/M4V/MOV movie-header duration without decoding media."""

    source_path = Path(path)
    try:
        file_size = source_path.stat().st_size
        with open(source_path, "rb") as stream:
            for box_type, payload_offset, payload_size in _iter_mp4_top_level_boxes(
                stream,
                file_size,
            ):
                if box_type != b"moov":
                    continue
                moov_end = payload_offset + payload_size
                for child_type, child_offset, child_size in _iter_mp4_boxes(
                    stream,
                    payload_offset,
                    moov_end,
                ):
                    if child_type != b"mvhd":
                        continue
                    stream.seek(child_offset)
                    header = stream.read(min(child_size, 32))
                    if not header:
                        return 0
                    version = header[0]
                    if version == 0 and len(header) >= 20:
                        timescale = int.from_bytes(header[12:16], "big")
                        duration = int.from_bytes(header[16:20], "big")
                        if duration == 0xFFFFFFFF:
                            return 0
                    elif version == 1 and len(header) >= 32:
                        timescale = int.from_bytes(header[20:24], "big")
                        duration = int.from_bytes(header[24:32], "big")
                        if duration == 0xFFFFFFFFFFFFFFFF:
                            return 0
                    else:
                        return 0
                    if timescale <= 0 or duration <= 0:
                        return 0
                    return min(round(duration * 1000 / timescale), 0xFFFFFFFF)
        return 0
    except OSError:
        return 0


def hash_source_file(path: str | Path) -> str:
    """Return the SHA-256 hex digest of a file's full content."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65_536), b""):
            h.update(chunk)
    return h.hexdigest()


def source_content_hash(path: str | Path) -> str:
    """Return a stable, metadata-insensitive source-media hash."""
    source_path = Path(path)
    if source_path.suffix.lower() in VIDEO_EXTENSIONS:
        return video_content_identity(source_path)
    if source_path.suffix.lower() in _MP4_CONTAINER_EXTS:
        mdat_hash = _hash_mp4_mdat_payloads(source_path)
        if mdat_hash:
            return f"mp4-mdat-sha256:{mdat_hash}"
    return f"file-sha256:{hash_source_file(source_path)}"


def video_content_identity(path: str | Path) -> str:
    """Return a bounded, non-decoding identity for a video source.

    MP4-family identities sample only ``mdat`` payload bytes, so changing
    container metadata does not change identity. Other video containers use
    the same bounded sampling strategy over the whole file.
    """

    source_path = Path(path)
    file_size = source_path.stat().st_size
    ranges: list[tuple[int, int]] = []
    if source_path.suffix.lower() in _MP4_CONTAINER_EXTS:
        with open(source_path, "rb") as stream:
            ranges = [
                (payload_offset, payload_size)
                for box_type, payload_offset, payload_size in _iter_mp4_top_level_boxes(
                    stream,
                    file_size,
                )
                if box_type == b"mdat"
            ]
    if not ranges:
        ranges = [(0, file_size)]

    digest = _hash_sampled_ranges(source_path, ranges)
    return f"video-sample-sha256-v1:{digest}"


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


def _hash_sampled_ranges(path: Path, ranges: list[tuple[int, int]]) -> str:
    h = hashlib.sha256()
    h.update(b"iopenpod-video-sample-v1\0")
    h.update(len(ranges).to_bytes(8, "big"))
    for _offset, size in ranges:
        h.update(size.to_bytes(8, "big"))

    total_size = sum(size for _offset, size in ranges)
    if total_size <= 0:
        return h.hexdigest()

    sample_bytes = min(_VIDEO_SAMPLE_BYTES, total_size)
    max_start = total_size - sample_bytes
    if _VIDEO_SAMPLE_COUNT <= 1 or max_start == 0:
        sample_starts = [0]
    else:
        sample_starts = sorted({
            (max_start * index) // (_VIDEO_SAMPLE_COUNT - 1)
            for index in range(_VIDEO_SAMPLE_COUNT)
        })

    with open(path, "rb") as stream:
        for logical_start in sample_starts:
            h.update(logical_start.to_bytes(8, "big"))
            _hash_logical_range(
                stream,
                ranges,
                logical_start=logical_start,
                byte_count=sample_bytes,
                digest=h,
            )
    return h.hexdigest()


def _hash_logical_range(
    stream,
    ranges: list[tuple[int, int]],
    *,
    logical_start: int,
    byte_count: int,
    digest: hashlib._Hash,
) -> None:
    logical_offset = 0
    remaining = byte_count
    target_offset = logical_start
    for physical_offset, range_size in ranges:
        range_end = logical_offset + range_size
        if target_offset >= range_end:
            logical_offset = range_end
            continue

        within_range = max(0, target_offset - logical_offset)
        read_size = min(remaining, range_size - within_range)
        stream.seek(physical_offset + within_range)
        data = stream.read(read_size)
        if len(data) != read_size:
            raise OSError(f"Could not read sampled video content from {stream.name}")
        digest.update(data)
        remaining -= read_size
        if remaining == 0:
            return
        target_offset += read_size
        logical_offset = range_end

    raise OSError(f"Video sample range exceeds available content in {stream.name}")


def _iter_mp4_top_level_boxes(f, file_size: int):
    yield from _iter_mp4_boxes(f, 0, file_size)


def _iter_mp4_boxes(f, start_offset: int, end_offset: int):
    offset = start_offset
    while offset + 8 <= end_offset:
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
            box_size = end_offset - offset

        if box_size < header_size:
            return

        payload_offset = offset + header_size
        payload_size = box_size - header_size
        if payload_offset + payload_size > end_offset:
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
