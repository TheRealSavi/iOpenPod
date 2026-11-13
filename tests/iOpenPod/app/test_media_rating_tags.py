"""Ratings stored in native file tags reach the Track as the iPod's 0-100 scale."""

import shutil
import subprocess
from pathlib import Path
from typing import Any

import mutagen
import pytest
from mutagen import id3
from mutagen.apev2 import APEv2
from mutagen.asf import (  # type: ignore[attr-defined]
    ASFDWordAttribute,
    ASFUnicodeAttribute,
)
from mutagen.mp4 import MP4FreeForm
from mutagen.oggopus import OggOpusVComment
from mutagen.oggvorbis import OggVCommentDict
from tests.iOpenPod.app.test_host_metadata_tags import media_file, scan_twice

from iOpenPod.app.media.tags import read_tag_values
from iPodDB.library import ContentAdvisory

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


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("-2", "0"),
        ("2.5", "60"),
        ("5.1", "20"),
        ("30", "40"),
        ("70", "80"),
        ("31", "40"),
        ("32", "40"),
        ("95", "100"),
        ("96", "100"),
        ("100.1", "60"),
        ("159", "60"),
        ("160", "80"),
        ("223", "80"),
        ("224", "100"),
        ("196", "80"),
        ("999", "100"),
    ],
)
def test_rating_scale_boundaries(raw: str, expected: str) -> None:
    assert {tag.name: tag.value for tag in read_tag_values({"RATING": [raw]})}[
        "rating"
    ] == expected


@pytest.mark.parametrize("raw", ["NaN", "-NaN", "inf", "-inf", "Infinity", "abc"])
def test_invalid_rating_values_do_not_cross_tag_boundary(raw: str) -> None:
    assert "rating" not in {tag.name for tag in read_tag_values({"RATING": [raw]})}


@pytest.mark.parametrize(
    ("suffix", "codec", "wrapper", "raw", "expected"),
    [
        ("ogg", "libvorbis", OggVCommentDict, "4.5", 100),
        ("opus", "libopus", OggOpusVComment, "196", 80),
    ],
)
def test_ogg_and_opus_native_rating_roundtrip(
    tmp_path: Path,
    suffix: str,
    codec: str,
    wrapper: type[OggVCommentDict] | type[OggOpusVComment],
    raw: str,
    expected: int,
) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("FFmpeg is unavailable")
    media = tmp_path / "media"
    media.mkdir()
    path = media / f"rated.{suffix}"
    result = subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=mono",
            "-t",
            "0.1",
            "-c:a",
            codec,
            str(path),
        ],
        capture_output=True,
        check=False,
    )
    if result.returncode:
        pytest.skip(f"FFmpeg {codec} encoder is unavailable")
    parsed: Any = mutagen.File(path)
    assert parsed is not None and isinstance(parsed.tags, wrapper)
    parsed.tags["RATING"] = [raw]
    parsed.save()
    reopened: Any = mutagen.File(path)
    assert reopened is not None and isinstance(reopened.tags, wrapper)
    assert ("rating", str(expected)) in {
        (tag.name, tag.value) for tag in read_tag_values(reopened.tags)
    }
    assert scan_twice(tmp_path).rating == expected


def test_ape_and_asf_native_rating_wrappers() -> None:
    ape: Any = APEv2()  # type: ignore[no-untyped-call]
    ape["Rating"] = "196"
    assert ("rating", "80") in {(tag.name, tag.value) for tag in read_tag_values(ape)}
    asf_unicode: Any = ASFUnicodeAttribute
    asf_dword: Any = ASFDWordAttribute
    for attribute in (asf_unicode("196"), asf_dword(196)):
        assert ("rating", "80") in {
            (tag.name, tag.value)
            for tag in read_tag_values({"WM/SharedUserRating": [attribute]})
        }


def test_popm_precedes_named_rating_and_selects_stable_email() -> None:
    tags: Any = id3.ID3()  # type: ignore[no-untyped-call]
    tags.add(FRAMES.TXXX(encoding=3, desc="RATING", text=["5"]))
    tags.add(FRAMES.POPM(email="z@example.test", rating=255, count=8))
    tags.add(FRAMES.POPM(email="a@example.test", rating=196, count=9))
    assert ("rating", "80") in {(tag.name, tag.value) for tag in read_tag_values(tags)}


def test_mp4_advisory_does_not_become_star_rating(tmp_path: Path) -> None:
    _, parsed = media_file(tmp_path / "media", "lossless.m4a")
    parsed.tags["rtng"] = [4]
    parsed.tags["----:com.apple.iTunes:RATING"] = [MP4FreeForm(b"3")]  # type: ignore[no-untyped-call]
    parsed.save()
    track = scan_twice(tmp_path)
    assert track.rating == 60
    assert track.metadata.content_advisory is ContentAdvisory.EXPLICIT


def test_cached_zero_rating_remains_explicit(tmp_path: Path) -> None:
    _, parsed = media_file(tmp_path / "media", "surround.flac")
    parsed.tags["RATING"] = ["0"]
    parsed.save()
    assert scan_twice(tmp_path).rating == 0
    assert ("rating", "0") in {
        (tag.name, tag.value) for tag in read_tag_values(parsed.tags)
    }
