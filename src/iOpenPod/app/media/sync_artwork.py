"""Capture reviewed Host artwork through Storage and decode bounded cover pixels."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING, Any

import mutagen.id3 as id3
from PIL import Image, ImageOps

from iOpenPod.app.host_media_library import (
    HostArtworkKind,
    embedded_artwork_from_stream,
)
from iPodDB.library import ArtworkPixels, TimedArtworkFrame
from storage.host_input import LocalHostFile

if TYPE_CHECKING:
    from collections.abc import Callable

    from iOpenPod.app.host_media_library import HostMediaArtworkSource
    from storage import HostPath

_ID3: Any = id3


@dataclass(frozen=True, slots=True)
class ChapterArtworkCapture:
    frames: tuple[TimedArtworkFrame, ...] = ()
    skipped: tuple[str, ...] = ()


def capture_embedded_chapter_artwork(
    source: HostPath,
    target_px: int,
    positions: frozenset[int],
    *,
    max_bytes: int,
    checkpoint: Callable[[], None],
) -> ChapterArtworkCapture:
    """Decode bounded CHAP/APIC images from the captured original ID3 tag.

    Duplicate chapter positions retain their first decodable image in element-ID
    order. The chapter text list remains independent and keeps every chapter.
    """
    if not positions:
        return ChapterArtworkCapture()
    with LocalHostFile.observe(source).open_read(checkpoint=checkpoint) as stream:
        header = stream.read(10)
        if len(header) < 10 or header[:3] != b"ID3":
            return ChapterArtworkCapture()
        if any(value & 0x80 for value in header[6:10]):
            raise ValueError("Invalid ID3 tag size")
        size = sum(value << (7 * (3 - i)) for i, value in enumerate(header[6:10]))
        if size > 16 * 1024 * 1024:
            raise ValueError("Chapter artwork ID3 tag exceeds 16 MiB")
        payload = header + stream.read(size)
    checkpoint()
    tags = _ID3.ID3(BytesIO(payload))
    frames: dict[int, TimedArtworkFrame] = {}
    skipped: list[str] = []
    for chapter in sorted(
        tags.getall("CHAP"), key=lambda frame: (frame.start_time, frame.element_id)
    ):
        position = int(chapter.start_time)
        if position not in positions or position in frames:
            continue
        for picture in chapter.sub_frames.getall("APIC"):
            checkpoint()
            try:
                if picture.mime == "-->" or len(picture.data) > 8 * 1024 * 1024:
                    raise ValueError(
                        "Chapter artwork must be an embedded image of at most 8 MiB"
                    )
                pixels = _decode_cover(picture.data, target_px, checkpoint)
                if len(pixels.rgb888) > max_bytes:
                    raise ValueError(
                        "Chapter artwork exceeds the remaining Podcast preparation budget"
                    )
            except (OSError, ValueError, Image.DecompressionBombError) as error:
                skipped.append(str(error))
                continue
            max_bytes -= len(pixels.rgb888)
            frames[position] = TimedArtworkFrame(position, pixels)
            break
    return ChapterArtworkCapture(
        tuple(frames[key] for key in sorted(frames)), tuple(skipped)
    )


def capture_embedded_artwork(
    source: HostPath,
    target_px: int,
    *,
    checkpoint: Callable[[], None],
) -> ArtworkPixels | None:
    """Read a cover from the original Storage-owned Podcast download."""
    checkpoint()
    with LocalHostFile.observe(source).open_read(checkpoint=checkpoint) as stream:
        payload = embedded_artwork_from_stream(stream)
    checkpoint()
    return None if payload is None else _decode_cover(payload, target_px, checkpoint)


def capture_sync_artwork(
    source: HostMediaArtworkSource,
    target_px: int,
    *,
    checkpoint: Callable[[], None],
) -> ArtworkPixels:
    """Preserve the scan's exact image identity while bounding Host memory use."""

    checkpoint()
    observed = LocalHostFile.observe(source.path)
    if (observed.size_bytes, observed.modified_ns) != (
        source.size_bytes,
        source.modified_ns,
    ):
        raise ValueError(
            "The artwork source changed after scanning. Rescan before retrying."
        )
    if source.kind is HostArtworkKind.EMBEDDED:
        with observed.open_read(checkpoint=checkpoint) as stream:
            payload = embedded_artwork_from_stream(stream)
    else:
        payload = observed.read_bytes(max_bytes=64 * 1024 * 1024, checkpoint=checkpoint)
    if payload is None or hashlib.sha256(payload).hexdigest() != source.content_sha256:
        raise ValueError(
            "The artwork no longer matches its scanned image. Rescan before retrying."
        )
    return _decode_cover(payload, target_px, checkpoint)


def _decode_cover(
    payload: bytes, target_px: int, checkpoint: Callable[[], None]
) -> ArtworkPixels:
    if target_px <= 0:
        raise ValueError("Artwork target size must be positive.")
    with Image.open(BytesIO(payload)) as opened:
        if max(opened.size) > 8192 or opened.width * opened.height > 32 * 1024 * 1024:
            raise ValueError(
                "The artwork dimensions exceed safe limits. Resize the cover image and rescan."
            )
        image = ImageOps.exif_transpose(opened).convert("RGB")
        image.thumbnail((target_px, target_px), Image.Resampling.LANCZOS)
        checkpoint()
        return ArtworkPixels(image.width, image.height, image.tobytes())
