"""Capture reviewed Host artwork through Storage and decode bounded cover pixels."""

from __future__ import annotations

import hashlib
from io import BytesIO
from typing import TYPE_CHECKING

from PIL import Image, ImageOps

from iOpenPod.app.host_media_library import (
    HostArtworkKind,
    embedded_artwork_from_stream,
)
from iPodDB.library import ArtworkPixels
from storage.host_input import LocalHostFile

if TYPE_CHECKING:
    from collections.abc import Callable

    from iOpenPod.app.host_media_library import HostMediaArtworkSource


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
    with Image.open(BytesIO(payload)) as opened:
        if max(opened.size) > 8192 or opened.width * opened.height > 32 * 1024 * 1024:
            raise ValueError(
                "The artwork dimensions exceed safe limits. Resize the cover image and rescan."
            )
        image = ImageOps.exif_transpose(opened).convert("RGB")
        image.thumbnail((target_px, target_px), Image.Resampling.LANCZOS)
        checkpoint()
        return ArtworkPixels(image.width, image.height, image.tobytes())
