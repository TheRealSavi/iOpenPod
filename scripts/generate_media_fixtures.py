"""Regenerate synthetic media fixtures with locally installed FFmpeg/FFprobe.

Run with UV. No device, downloaded media, or Original iOpenPod code is involved.
Encoded bytes may differ by FFmpeg version; inspect the resulting fixture diff.
"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import cast

_CREATE_NO_WINDOW = cast("int", vars(subprocess).get("CREATE_NO_WINDOW", 0))


def main() -> None:
    executable = shutil.which("ffmpeg")
    if executable is None:
        raise RuntimeError("FFmpeg is required to regenerate media fixtures")
    destination = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "media"
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="iopenpod-media-fixtures-") as temporary:
        directory = Path(temporary)

        def encode(name: str, args: list[str]) -> None:
            result = subprocess.run(
                [executable, "-v", "error", "-nostdin", *args, str(directory / name)],
                capture_output=True,
                check=True,
                timeout=60,
                creationflags=_CREATE_NO_WINDOW,
            )
            if result.stderr:
                raise RuntimeError(result.stderr.decode("utf-8", errors="replace"))
            data = (directory / name).read_bytes()
            (destination / f"{name}.b64").write_bytes(base64.encodebytes(data))

        audio = [
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=44100:duration=0.25",
            "-ac",
            "2",
        ]
        encode("tone.wav", [*audio, "-c:a", "pcm_s16le"])
        encode("tone.aiff", [*audio, "-c:a", "pcm_s16be"])
        encode("tone.mp3", [*audio, "-c:a", "libmp3lame", "-b:a", "128k"])
        encode("tone-vbr.mp3", [*audio, "-c:a", "libmp3lame", "-q:a", "2"])
        encode(
            "tone.m4a",
            [
                *audio,
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-metadata",
                "title=Inspection tone",
                "-metadata",
                "artist=iOpenPod tests",
            ],
        )
        encode("lossless.m4a", [*audio, "-c:a", "alac"])
        encode(
            "surround.flac",
            [
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=96000:cl=5.1",
                "-t",
                "0.25",
                "-c:a",
                "flac",
                "-sample_fmt",
                "s32",
            ],
        )
        video = ["-f", "lavfi", "-i", "color=c=blue:s=320x240:r=30000/1001:d=0.25"]
        h264 = [
            "-c:v",
            "libx264",
            "-profile:v",
            "baseline",
            "-level:v",
            "3.0",
            "-pix_fmt",
            "yuv420p",
        ]
        encode("silent.mp4", [*video, *h264, "-an", "-movflags", "+faststart"])
        encode("source.mkv", [*video, "-c:v", "mpeg4", "-an"])

        (directory / "chapters.txt").write_text(
            ";FFMETADATA1\ntitle=Chapter test\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=100\ntitle=Opening\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=100\nEND=250\ntitle=Closing\n",
            encoding="utf-8",
        )
        # PPM is deliberately generated data; this is not a borrowed image fixture.
        picture = directory / "cover.ppm"
        picture.write_bytes(b"P6\n16 16\n255\n" + bytes((15, 100, 200)) * 256)
        encode(
            "chapters-cover.m4a",
            [
                "-i",
                str(directory / "tone.m4a"),
                "-i",
                str(picture),
                "-f",
                "ffmetadata",
                "-i",
                str(directory / "chapters.txt"),
                "-map",
                "0:a",
                "-map",
                "1:v",
                "-map_metadata",
                "2",
                "-map_chapters",
                "2",
                "-c:a",
                "copy",
                "-c:v",
                "png",
                "-disposition:v",
                "attached_pic",
            ],
        )
        subtitles = directory / "subtitles.srt"
        subtitles.write_text(
            "1\n00:00:00,000 --> 00:00:00,250\nTest subtitle\n", encoding="utf-8"
        )
        encode(
            "multi-track.mov",
            [
                "-i",
                str(directory / "silent.mp4"),
                "-i",
                str(directory / "tone.m4a"),
                "-i",
                str(subtitles),
                "-map",
                "0:v",
                "-map",
                "1:a",
                "-map",
                "1:a",
                "-map",
                "2:s",
                "-c:v",
                "copy",
                "-c:a",
                "copy",
                "-c:s",
                "mov_text",
                "-s:s",
                "320x240",
                "-metadata:s:a:0",
                "language=eng",
                "-metadata:s:a:1",
                "language=fra",
            ],
        )
        encode(
            "multi-track.m4v",
            [
                "-i",
                str(directory / "multi-track.mov"),
                "-map",
                "0",
                "-c",
                "copy",
                "-c:s",
                "mov_text",
                "-s:s",
                "320x240",
                "-f",
                "ipod",
            ],
        )
    version = subprocess.run(
        [executable, "-version"],
        capture_output=True,
        check=True,
        timeout=10,
        creationflags=_CREATE_NO_WINDOW,
    )
    (destination / "generator.json").write_text(
        json.dumps(
            {
                "ffmpeg": version.stdout.decode().splitlines()[0],
                "source": "Generated sine waves, solid colors, silence and text; no external media.",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
