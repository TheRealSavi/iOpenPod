"""Ratings stored in native file tags reach the Track as the iPod's 0-100 scale."""

from pathlib import Path
from typing import Any

import pytest
from mutagen import id3
from mutagen.mp4 import MP4FreeForm
from tests.iOpenPod.app.test_host_metadata_tags import media_file, scan_twice

FRAMES: Any = id3

# Taggers disagree on the scale: 1-5 stars, 0-100 (Vorbis/MP4 usually), 0-255 (POPM).
RATINGS = [
    ("0", 0),
    ("1", 20),
    ("3", 60),
    ("5", 100),
    ("80", 80),
    ("70", 80),
    ("100", 100),
    ("255", 100),
    ("4.5", 100),
]


@pytest.mark.parametrize(("raw", "expected"), RATINGS)
def test_vorbis_rating(tmp_path: Path, raw: str, expected: int) -> None:
    _, parsed = media_file(tmp_path / "media", "surround.flac")
    parsed.tags["RATING"] = [raw]
    parsed.save()
    assert scan_twice(tmp_path).rating == expected


@pytest.mark.parametrize(("raw", "expected"), RATINGS)
def test_mp4_freeform_rating(tmp_path: Path, raw: str, expected: int) -> None:
    _, parsed = media_file(tmp_path / "media", "lossless.m4a")
    parsed.tags["----:com.apple.iTunes:RATING"] = [MP4FreeForm(raw.encode())]  # type: ignore[no-untyped-call]
    parsed.save()
    assert scan_twice(tmp_path).rating == expected


@pytest.mark.parametrize("raw", ["", "abc", "n/a"])
def test_unreadable_rating_is_ignored(tmp_path: Path, raw: str) -> None:
    _, parsed = media_file(tmp_path / "media", "surround.flac")
    parsed.tags["RATING"] = [raw]
    parsed.save()
    assert scan_twice(tmp_path).rating == 0


def test_id3_popm_rating_is_unchanged(tmp_path: Path) -> None:
    _, parsed = media_file(tmp_path / "media", "tone.mp3")
    parsed.tags.add(FRAMES.POPM(email="user@example.test", rating=196, count=0))
    parsed.save()
    assert scan_twice(tmp_path).rating == 80
