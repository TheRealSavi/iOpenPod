"""Read attached cover images without copying or decoding an entire video."""

from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING

from PIL import Image

from iOpenPod.app.media.inspection import MediaInspector
from iOpenPod.app.media.models import StreamKind
from storage.media_processing import MediaToolError, find_media_tool, run_media_tool

if TYPE_CHECKING:
    from collections.abc import Callable

    from iOpenPod.app.media.models import MediaScanMetadata
    from storage.host_input import LocalHostFile

_MAX_IMAGE_BYTES = 64 * 1024 * 1024


def container_artwork(
    source: LocalHostFile,
    *,
    checkpoint: Callable[[], None],
    metadata: MediaScanMetadata | None = None,
) -> bytes | None:
    """Return the original attached image bytes, or confirmed absence.

    Native tags are inspected first by the caller. Matroska JPEG/PNG attachments
    appear as attached-picture streams in FFprobe; fonts are never cover images.
    Failed or unsupported image observations raise instead of claiming absence.
    """
    checkpoint()
    observed = metadata or MediaInspector().scan_metadata(
        source.path, checkpoint=checkpoint
    )
    pictures = tuple(
        stream for stream in observed.streams if stream.attached_picture is True
    )
    unsupported_image = any(
        stream.kind is StreamKind.ATTACHMENT
        and any(
            tag.name.casefold() == "mimetype"
            and tag.value.casefold().startswith("image/")
            for tag in stream.tags
        )
        for stream in observed.streams
    )
    if not pictures:
        source.validate()
        if unsupported_image:
            raise ValueError("The embedded image attachment could not be read.")
        return None
    executable = find_media_tool("ffmpeg")
    if executable is None:
        raise MediaToolError(
            "media.tool_unavailable",
            "FFmpeg is required to read the video's embedded artwork.",
        )
    failure: Exception | None = None
    for picture in pictures:
        checkpoint()
        try:
            # Holding the original observation also checks that metadata and image
            # bytes came from the same source, across the separate tool reads.
            with source.open_read(checkpoint=checkpoint):
                result = run_media_tool(
                    executable,
                    ("-v", "error", "-nostdin", "-i"),
                    input_file=source.path,
                    arguments_after_input=(
                        "-map",
                        f"0:{picture.index}",
                        "-frames:v",
                        "1",
                        "-c:v",
                        "copy",
                        "-f",
                        "image2pipe",
                        "pipe:1",
                    ),
                    checkpoint=checkpoint,
                    timeout_seconds=30,
                    max_output_bytes=_MAX_IMAGE_BYTES,
                    max_stderr_bytes=65536,
                    low_priority=True,
                )
            with Image.open(BytesIO(result.stdout)) as image:
                if (
                    max(image.size) > 8192
                    or image.width * image.height > 32 * 1024 * 1024
                ):
                    raise ValueError(
                        "The embedded artwork dimensions exceed safe limits."
                    )
                image.verify()
            return result.stdout
        except InterruptedError:
            raise
        except (MediaToolError, OSError, SyntaxError, ValueError) as error:
            failure = error
    raise ValueError(f"The embedded artwork could not be read: {failure}") from failure
