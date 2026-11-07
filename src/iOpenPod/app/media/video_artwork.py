"""Capture a small, optional cover from a pinned Host video."""

from __future__ import annotations

import math
from io import BytesIO
from typing import TYPE_CHECKING

from PIL import Image

from iPodDB.library import ArtworkPixels
from storage.media_processing import MediaToolError, find_media_tool, run_media_tool

if TYPE_CHECKING:
    from collections.abc import Callable

    from storage import HostPath
    from storage.media_processing import MediaToolFinder


def capture_video_frame(
    source: HostPath,
    target_px: int,
    *,
    checkpoint: Callable[[], None],
    find_tool: MediaToolFinder | None = None,
    duration_seconds: float | None = None,
) -> ArtworkPixels:
    """Use a frame near the start, retrying at zero for short videos.

    FFmpeg seeks directly in Storage's pinned input; this does not copy or encode
    the whole video. Attached pictures are excluded, and square pixels preserve
    the video's displayed proportions in the resulting artwork.
    """
    if not 0 < target_px <= 2048:
        raise ValueError("Video artwork size must be between 1 and 2048 pixels.")
    checkpoint()
    executable = (find_tool or find_media_tool)("ffmpeg")
    if executable is None:
        raise MediaToolError(
            "media.tool_unavailable",
            "FFmpeg is required to use a video frame as artwork.",
        )
    seek = (
        min(30.0, duration_seconds * 0.1)
        if duration_seconds is not None
        and math.isfinite(duration_seconds)
        and duration_seconds > 0
        else 10.0
    )
    scale = (
        f"scale=w='max(1,round(min({target_px},{target_px}*dar)))'"
        f":h='max(1,round(min({target_px},{target_px}/dar)))',setsar=1"
    )
    for position in (seek, 0.0):
        checkpoint()
        result = run_media_tool(
            executable,
            ("-v", "error", "-nostdin", "-ss", f"{position:.6f}", "-i"),
            input_file=source,
            arguments_after_input=(
                "-map",
                "0:V:0",
                "-frames:v",
                "1",
                "-an",
                "-sn",
                "-vf",
                scale,
                "-c:v",
                "png",
                "-pix_fmt",
                "rgb24",
                "-threads",
                "1",
                "-f",
                "image2pipe",
                "pipe:1",
            ),
            checkpoint=checkpoint,
            timeout_seconds=30,
            max_output_bytes=target_px * target_px * 4 + 65536,
            max_stderr_bytes=65536,
            low_priority=True,
        )
        if not result.stdout:
            continue
        with Image.open(BytesIO(result.stdout)) as frame:
            if frame.format != "PNG" or max(frame.size) > target_px:
                raise ValueError("The extracted video artwork has invalid dimensions.")
            rgb = frame.convert("RGB")
            checkpoint()
            return ArtworkPixels(rgb.width, rgb.height, rgb.tobytes())
    raise ValueError("The video did not contain a readable frame for artwork.")
