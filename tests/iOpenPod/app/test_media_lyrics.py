"""Focused lyrics writes preserve unrelated tags and encoded media payloads."""

import base64
import io
import struct
from pathlib import Path
from typing import Any

import mutagen.id3 as frames
import pytest
from mutagen.aiff import AIFF
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.wave import WAVE

from iOpenPod.app.media.lyrics import (
    embedded_lyrics,
    rewrite_lyrics,
    rewrite_lyrics_stream,
)

FIXTURES = Path(__file__).parents[2] / "fixtures" / "media"
FRAMES: Any = frames
MP3_READER: Any = MP3
WORDS = "First line\nDeuxième ligne — 日本語 🎵\nLast line"


def fixture(name: str) -> bytes:
    return base64.b64decode((FIXTURES / f"{name}.b64").read_bytes())


def media_payload(data: bytes, suffix: str) -> bytes:
    """Extract encoded media independently of the tag writer."""
    if suffix == ".mp3":
        if data.startswith(b"ID3"):
            size = sum(
                value << shift
                for value, shift in zip(data[6:10], (21, 14, 7, 0), strict=True)
            )
            data = data[10 + size :]
        return data[:-128] if data[-128:-125] == b"TAG" else data
    mp4 = suffix in (".m4a", ".m4v", ".mp4", ".mov")
    offset = 0 if mp4 else 12
    payload = bytearray()
    while offset + 8 <= len(data):
        if mp4:
            size, kind = struct.unpack_from(">I4s", data, offset)
            header = 8
            if size == 1:
                size = struct.unpack_from(">Q", data, offset + 8)[0]
                header = 16
            elif size == 0:
                size = len(data) - offset
            if kind == b"mdat":
                payload.extend(data[offset + header : offset + size])
            offset += size
        else:
            kind = data[offset : offset + 4]
            size = struct.unpack_from(
                "<I" if suffix == ".wav" else ">I", data, offset + 4
            )[0]
            if kind in (b"data", b"SSND"):
                payload.extend(data[offset + 8 : offset + 8 + size])
            offset += 8 + size + size % 2
    assert payload
    return bytes(payload)


@pytest.mark.parametrize(
    "name",
    [
        "tone.mp3",
        "tone.m4a",
        "lossless.m4a",
        "chapters-cover.m4a",
        "silent.mp4",
        "multi-track.m4v",
        "multi-track.mov",
        "tone.wav",
        "tone.aiff",
    ],
)
@pytest.mark.parametrize("disk_backed", [False, True])
def test_add_replace_clear_and_noop_preserve_media(
    name: str, tmp_path: Path, disk_backed: bool
) -> None:
    original = fixture(name)
    suffix = Path(name).suffix
    payload = media_payload(original, suffix)
    reader: Any = {
        ".mp3": MP3,
        ".m4a": MP4,
        ".mp4": MP4,
        ".m4v": MP4,
        ".mov": MP4,
        ".wav": WAVE,
        ".aiff": AIFF,
    }[suffix]
    before = reader(io.BytesIO(original))
    original_tags = dict(before.tags or {})
    current = original
    for lyrics in (WORDS, "Replaced\r\nSecond verse", ""):
        if disk_backed:
            path = tmp_path / name
            path.write_bytes(current)
            with path.open("r+b") as stream:
                rewrite_lyrics_stream(stream, name, lyrics)
            current = path.read_bytes()
        else:
            current = rewrite_lyrics(current, name, lyrics)
        parsed = reader(io.BytesIO(current))
        assert embedded_lyrics(parsed) == lyrics
        assert media_payload(current, suffix) == payload
        for key, value in original_tags.items():
            assert parsed.tags[key] == value
        assert rewrite_lyrics(current, name, lyrics) == current
        # Ordinary Library tags are never materialized by the lyrics path.
        assert set(parsed.tags or {}) - set(original_tags) <= {"USLT::eng", "\xa9lyr"}


@pytest.mark.parametrize("version", [3, 4])
def test_id3_version_custom_frames_and_all_lyrics_variants(version: int) -> None:
    buffer = io.BytesIO(fixture("tone.mp3"))
    audio = MP3_READER(buffer)
    if audio.tags is None:
        audio.add_tags()
    assert audio.tags is not None
    audio.tags.add(FRAMES.TXXX(encoding=1, desc="private", text="keep me"))
    audio.tags.add(FRAMES.USLT(encoding=1, lang="eng", desc="", text="old"))
    audio.tags.add(FRAMES.USLT(encoding=1, lang="deu", desc="translation", text="alt"))
    audio.tags.add(
        FRAMES.APIC(encoding=1, mime="image/jpeg", type=3, desc="", data=b"picture")
    )
    buffer.seek(0)
    audio.save(buffer, v2_version=version)
    before = buffer.getvalue()
    for lyrics in (WORDS, ""):
        output = rewrite_lyrics(before, "track.mp3", lyrics)
        parsed = MP3_READER(io.BytesIO(output))
        assert parsed.tags.version == (2, version, 0)
        assert str(parsed.tags["TXXX:private"]) == "keep me"
        assert parsed.tags.getall("APIC")[0].data == b"picture"
        assert media_payload(output, ".mp3") == media_payload(before, ".mp3")
        assert len(parsed.tags.getall("USLT")) == bool(lyrics)
        assert embedded_lyrics(parsed) == lyrics
        if lyrics:
            assert parsed.tags.getall("USLT")[0].encoding == (1 if version == 3 else 3)


def test_new_mp3_tag_uses_baseline_v23_policy() -> None:
    original = media_payload(fixture("tone.mp3"), ".mp3")
    output = rewrite_lyrics(original, "track.mp3", WORDS)
    parsed = MP3_READER(io.BytesIO(output))
    assert parsed.tags.version == (2, 3, 0)
    assert parsed.tags.getall("USLT")[0].encoding == 1
    assert media_payload(output, ".mp3") == original


def test_v24_only_and_opaque_frames_survive_a_focused_edit() -> None:
    buffer = io.BytesIO(fixture("tone.mp3"))
    audio = MP3_READER(buffer)
    if audio.tags is None:
        audio.add_tags()
    assert audio.tags is not None
    audio.tags.add(FRAMES.TPE1(encoding=3, text=["First artist", "Second artist"]))
    audio.tags.add(FRAMES.TDOR(encoding=3, text="2001-02-03"))
    opaque = b"ZZZZ\x00\x00\x00\x07\x00\x00private"
    audio.tags.unknown_frames.append(opaque)
    buffer.seek(0)
    audio.save(buffer, v2_version=4)
    output = rewrite_lyrics(buffer.getvalue(), "track.mp3", WORDS)
    parsed = MP3_READER(io.BytesIO(output))
    assert parsed.tags["TPE1"].text == ["First artist", "Second artist"]
    assert str(parsed.tags["TDOR"]) == "2001-02-03"
    assert opaque in parsed.tags.unknown_frames


def test_tag_write_that_does_not_persist_text_fails_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def discard_save(*_args: object, **_kwargs: object) -> None:
        pass

    monkeypatch.setattr(MP4, "save", discard_save)
    with pytest.raises(ValueError, match="read-back verification"):
        rewrite_lyrics(fixture("tone.m4a"), "track.m4a", WORDS)


def test_legacy_id3v22_is_not_implicitly_migrated() -> None:
    text = b"\x00Old title"
    frames = b"TT2" + len(text).to_bytes(3, "big") + text
    data = (
        b"ID3\x02\x00\x00\x00\x00\x00"
        + bytes((len(frames),))
        + frames
        + media_payload(fixture("tone.mp3"), ".mp3")
    )
    assert MP3_READER(io.BytesIO(data)).tags.version == (2, 2, 0)
    with pytest.raises(ValueError, match=r"ID3v2\.2"):
        rewrite_lyrics(data, "track.mp3", WORDS)
    assert rewrite_lyrics(data, "track.mp3", "") == data


@pytest.mark.parametrize("name", ["track.mp3", "track.m4a", "track.aac"])
def test_invalid_or_unsupported_media_cannot_claim_lyrics(name: str) -> None:
    with pytest.raises(ValueError):
        rewrite_lyrics(b"not a media file", name, WORDS)
