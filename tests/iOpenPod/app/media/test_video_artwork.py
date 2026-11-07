"""Real frame extraction keeps video covers bounded and correctly proportioned."""

from __future__ import annotations

import hashlib
import random
import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from iOpenPod.app.media.video_artwork import capture_video_frame
from storage import HostPath
from storage.media_processing import MediaToolError

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def video(tmp_path: Path) -> Path:
    executable = shutil.which("ffmpeg")
    if executable is None:
        pytest.skip("FFmpeg is not available")
    path = tmp_path / "short anamorphic video.mp4"
    subprocess.run(
        [
            executable,
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=160x120:r=10:d=0.5",
            "-vf",
            "setsar=2",
            "-c:v",
            "mpeg4",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


@pytest.mark.parametrize("duration", [None, 0.5])
def test_frame_uses_display_aspect_and_retries_past_short_video(
    video: Path, duration: float | None
) -> None:
    before = hashlib.sha256(video.read_bytes()).hexdigest()
    pixels = capture_video_frame(
        HostPath(video),
        160,
        duration_seconds=duration,
        checkpoint=lambda: None,
    )
    assert (pixels.width, pixels.height) == (160, 60)
    assert pixels.rgb888[0] > 240
    assert max(pixels.rgb888[1:3]) < 10
    assert hashlib.sha256(video.read_bytes()).hexdigest() == before


def test_missing_tool_reports_optional_artwork_failure(video: Path) -> None:
    with pytest.raises(MediaToolError, match="FFmpeg is required"):
        capture_video_frame(
            HostPath(video), 160, checkpoint=lambda: None, find_tool=lambda _: None
        )


def test_cancellation_does_not_become_missing_artwork(video: Path) -> None:
    def cancel() -> None:
        raise InterruptedError("cancelled")

    with pytest.raises(InterruptedError, match="cancelled"):
        capture_video_frame(HostPath(video), 160, checkpoint=cancel)


def test_high_bit_depth_frame_fits_the_rgb_artwork_budget(tmp_path: Path) -> None:
    executable = shutil.which("ffmpeg")
    if executable is None:
        pytest.skip("FFmpeg is not available")
    path = tmp_path / "high-depth.mkv"
    subprocess.run(
        [
            executable,
            "-v",
            "error",
            "-f",
            "rawvideo",
            "-pixel_format",
            "rgb48le",
            "-video_size",
            "512x512",
            "-i",
            "pipe:0",
            "-frames:v",
            "1",
            "-c:v",
            "ffv1",
            "-pix_fmt",
            "gbrp16le",
            str(path),
        ],
        input=random.Random(0).randbytes(512 * 512 * 6),
        check=True,
        capture_output=True,
    )
    pixels = capture_video_frame(HostPath(path), 512, checkpoint=lambda: None)
    assert (pixels.width, pixels.height) == (512, 512)
    assert len(pixels.rgb888) == 512 * 512 * 3
