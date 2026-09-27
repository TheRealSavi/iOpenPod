"""Exported media receives current semantic tags and embedded cover artwork."""

import base64
import io
from pathlib import Path
from typing import Protocol, cast

import pytest
from mutagen.id3 import ID3
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4

from iOpenPod.app.export_tagging import ExportMediaTagger
from iOpenPod.app.models.artwork import ArtworkImage
from iPodDB.library import ContentAdvisory, Track, TrackMetadata
from storage import HostPath

_FIXTURES = Path(__file__).parents[2] / "fixtures" / "media"


class _ArtworkFrame(Protocol):
    mime: str
    data: bytes


class _ID3TagView(Protocol):
    def __getitem__(self, key: str) -> object: ...

    def getall(self, key: str) -> list[_ArtworkFrame]: ...


class _MP4TagView(Protocol):
    def __getitem__(self, key: str) -> object: ...


def _fixture(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.write_bytes(base64.b64decode((_FIXTURES / f"{name}.b64").read_bytes()))
    return path


def _track() -> Track:
    return Track(
        1,
        "Exported title",
        "Exported artist",
        "Exported album",
        1_000,
        genre="Jazz",
        year=2026,
        track_number=2,
        album_artist="Album artist",
        metadata=TrackMetadata(
            total_tracks=9,
            disc_number=1,
            total_discs=2,
            compilation=True,
            bpm=120,
            composer="Composer",
            grouping="Movement",
            comment="From the iPod Library",
            lyrics="Synthetic lyrics",
            content_advisory=ContentAdvisory.EXPLICIT,
            sort_title="Title, Exported",
        ),
    )


def _artwork() -> ArtworkImage:
    return ArtworkImage("export-cover", 1, 1, 2, 2, bytes((30, 80, 140)) * 4)


def test_mp3_export_receives_id3_metadata_and_front_cover(tmp_path: Path) -> None:
    path = _fixture(tmp_path, "tone.mp3")

    ExportMediaTagger().prepare(HostPath(path), _track(), _artwork())

    tags = MP3(path).tags  # type: ignore[no-untyped-call]
    assert isinstance(tags, ID3)
    typed_tags = cast("_ID3TagView", tags)
    assert str(typed_tags["TIT2"]) == "Exported title"
    assert str(typed_tags["TPE1"]) == "Exported artist"
    assert str(typed_tags["TRCK"]) == "2/9"
    assert str(typed_tags["TPOS"]) == "1/2"
    assert typed_tags.getall("APIC")[0].mime == "image/jpeg"
    assert typed_tags.getall("APIC")[0].data.startswith(b"\xff\xd8")


def test_m4a_export_receives_itunes_metadata_and_cover_atom(tmp_path: Path) -> None:
    path = _fixture(tmp_path, "tone.m4a")

    ExportMediaTagger().prepare(HostPath(path), _track(), _artwork())

    tags = MP4(path).tags  # type: ignore[no-untyped-call]
    assert tags is not None
    typed_tags = cast("_MP4TagView", tags)
    assert typed_tags["\xa9nam"] == ["Exported title"]
    assert typed_tags["\xa9ART"] == ["Exported artist"]
    assert typed_tags["trkn"] == [(2, 9)]
    assert typed_tags["disk"] == [(1, 2)]
    covers = cast("list[bytes]", typed_tags["covr"])
    assert bytes(covers[0]).startswith(b"\xff\xd8")


def test_unsupported_export_format_is_rejected_before_tagging(tmp_path: Path) -> None:
    path = tmp_path / "track.aac"
    path.write_bytes(b"raw aac")

    try:
        ExportMediaTagger().prepare(HostPath(path), _track(), None)
    except ValueError as error:
        assert ".aac" in str(error)
    else:
        raise AssertionError("Raw AAC should not claim embedded-tag support")


@pytest.mark.parametrize("name", ("tone.mp3", "tone.m4a", "tone.wav", "tone.aiff"))
def test_rockbox_metadata_is_verified_on_private_bytes(name: str) -> None:
    data = base64.b64decode((_FIXTURES / f"{name}.b64").read_bytes())
    output = ExportMediaTagger().prepare_bytes(data, name, _track(), _artwork())
    assert output != data
    if name.endswith(".mp3"):
        tags = MP3(io.BytesIO(output)).tags  # type: ignore[no-untyped-call]
        assert tags is not None
        assert str(cast("_ID3TagView", tags)["TIT2"]) == _track().title
    elif name.endswith(".m4a"):
        tags = MP4(io.BytesIO(output)).tags  # type: ignore[no-untyped-call]
        assert tags is not None
        assert cast("_MP4TagView", tags)["\xa9lyr"] == [_track().metadata.lyrics]


def test_rockbox_mp4_non_compilation_survives_read_back() -> None:
    data = base64.b64decode((_FIXTURES / "tone.m4a.b64").read_bytes())
    track = Track(1, "Reviewed title", "Reviewed artist", "Reviewed album", 1_000)

    output = ExportMediaTagger().prepare_bytes(data, "media.m4a", track)

    tags = MP4(io.BytesIO(output)).tags  # type: ignore[no-untyped-call]
    assert tags is not None
    assert tags["cpil"] is False
