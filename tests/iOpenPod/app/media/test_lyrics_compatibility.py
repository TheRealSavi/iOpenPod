"""Authored binary cases distinguish native lyrics decoding from tag readback."""

from __future__ import annotations

import io
from typing import Literal

import pytest

from iOpenPod.app.media.lyrics_compatibility import verify_native_lyrics


def synchsafe(size: int) -> bytes:
    return bytes((size >> shift) & 0x7F for shift in (21, 14, 7, 0))


def frame(
    body: bytes, *, version: int = 3, kind: bytes = b"USLT", flags: bytes = b"\x00\x00"
) -> bytes:
    if version == 2:
        return (
            (b"ULT" if kind == b"USLT" else kind) + len(body).to_bytes(3, "big") + body
        )
    size = synchsafe(len(body)) if version == 4 else len(body).to_bytes(4, "big")
    return kind + size + flags + body


def tag(*frames: bytes, version: int = 3, flags: int = 0) -> bytes:
    data = b"".join(frames)
    return b"ID3" + bytes((version, 0, flags)) + synchsafe(len(data)) + data


def utf8_body(text: str) -> bytes:
    return b"\x03eng\x00" + text.encode("utf-8")


def atom(kind: bytes, body: bytes) -> bytes:
    return (len(body) + 8).to_bytes(4, "big") + kind + body


def mp4(*texts: bytes, extra: bytes = b"") -> bytes:
    lyric = atom(
        b"\xa9lyr", b"".join(atom(b"data", bytes(8) + text) for text in texts) + extra
    )
    return atom(b"moov", atom(b"udta", atom(b"meta", bytes(4) + atom(b"ilst", lyric))))


def verify(data: bytes, expected: str, file_name: str = "track.mp3") -> None:
    stream = io.BytesIO(data)
    stream.seek(3)
    try:
        verify_native_lyrics(stream, file_name, expected)
    finally:
        assert stream.tell() == 3
        assert stream.getvalue() == data


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (b"\x00engdescription\x00caf\xe9\x00", "café"),
        (b"\x01eng\x00\x00\xff\xfe" + "雪 🎵".encode("utf-16-le") + bytes(2), "雪 🎵"),
    ],
)
def test_unchanged_v22_ult_retains_exact_tag_and_unrelated_frames(
    body: bytes, expected: str
) -> None:
    data = (
        tag(
            frame(bytes(128), version=2, kind=b"TT2"),
            frame(body, version=2),
            frame(b"retained bytes", version=2, kind=b"XYZ"),
            version=2,
        )
        + b"unchanged encoded media"
    )
    verify(data, expected)


@pytest.mark.parametrize("size", [127, 128, 256, 10240])
def test_v22_frame_size_is_ordinary_three_byte_big_endian(size: int) -> None:
    text = "a" * (size - 5)
    body = b"\x00eng\x00" + text.encode("ascii")
    verify(tag(frame(body, version=2), version=2), text)


def test_v22_ult_uses_same_native_read_limit() -> None:
    text = "a" * 10236
    with pytest.raises(ValueError, match="10,240 bytes including"):
        verify(
            tag(frame(b"\x00eng\x00" + text.encode("ascii"), version=2), version=2),
            text,
        )


@pytest.mark.parametrize(
    "frames",
    [
        b"ULT\xff\xff\xffshort",
        b"ULT\x00\x00",
        b"ULT\x00\x00\x04\x00eng",
        b"TT2\x00\x01\x00short" + frame(b"\x00eng\x00one", version=2),
    ],
)
def test_v22_incomplete_headers_and_frame_bounds_are_rejected(frames: bytes) -> None:
    with pytest.raises(ValueError):
        verify(tag(frames, version=2), "one")


@pytest.mark.parametrize("size", [6, 127])
def test_small_v4_frame_sizes_follow_native_path(size: int) -> None:
    words = "x" * (size - 5)
    verify(tag(frame(utf8_body(words), version=4), version=4), words)


@pytest.mark.parametrize("previous", [False, True])
def test_v4_128_byte_frame_before_or_at_lyrics_is_incompatible(previous: bool) -> None:
    body = utf8_body("x" * 123)
    frames: tuple[bytes, ...] = (frame(body, version=4),)
    if previous:
        frames = (frame(bytes(128), version=4, kind=b"TIT2"), *frames)
    with pytest.raises(ValueError, match=r"frame size.*ID3v2\.3"):
        verify(tag(*frames, version=4), "x" * 123)


def test_v4_mismatched_frame_after_selected_lyrics_is_not_traversed() -> None:
    verify(
        tag(
            frame(utf8_body("one"), version=4),
            frame(bytes(128), version=4, kind=b"TIT2"),
            version=4,
        ),
        "one",
    )


@pytest.mark.parametrize("encoding", [2, 4])
def test_unsupported_id3_text_encoding_is_not_accepted_as_displayable(
    encoding: int,
) -> None:
    with pytest.raises(ValueError, match="text encoding"):
        verify(tag(frame(bytes((encoding,)) + b"eng\x00\x00\x00a")), "a")


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (b"\x00engdescription\x00caf\xe9\x00", "café"),
        (utf8_body("雪\nline 🎵"), "雪\nline 🎵"),
        (utf8_body("\ufeffone"), "one"),
        (b"\x01eng\xff\xfe\x00\x00\xfe\xff\x00a\x00\x00", "a"),
        (b"\x01eng\xfe\xff\x00\x00\xff\xfea\x00\x00\x00", "a"),
        (b"\x01eng\xfe\xff\x00\x00a\x00\x00\x00", "a"),
    ],
)
def test_native_encodings_and_actual_text_bom(body: bytes, expected: str) -> None:
    verify(tag(frame(body)), expected)


def test_descriptor_bom_does_not_select_big_endian_for_actual_text() -> None:
    body = b"\x01eng\xfe\xff\x00\x00\x00a\x00\x00"
    with pytest.raises(ValueError, match="complete requested text"):
        verify(tag(frame(body)), "a")


@pytest.mark.parametrize(
    "body",
    [
        b"\x01eng\xff\xfe\x00\x00\xff\xfea\x00",
        b"\x01eng\x00\x00\xff\xfea",
        b"\x01eng\xff\xfea\x00",
        b"\x03engunterminated",
        b"\x03eng\x00\xe9",
        b"\x01eng\x00\x00\xff\xfe\x00\xd8\x00\x00",
    ],
)
def test_incomplete_id3_text_is_rejected(body: bytes) -> None:
    with pytest.raises(ValueError):
        verify(tag(frame(body)), "a")


def test_id3_cap_counts_language_description_and_encoded_bytes() -> None:
    text = "é" * 5117 + "a"
    body = utf8_body(text)
    assert len(body) == 10240
    verify(tag(frame(body)), text)
    with pytest.raises(ValueError, match="10,240 bytes including"):
        verify(tag(frame(utf8_body(text + "b"))), text + "b")
    with pytest.raises(ValueError, match="10,240 bytes including"):
        verify(tag(frame(b"\x03engdescription\x00" + text.encode("utf-8"))), text)


def test_utf16_native_cap_includes_bom_and_terminator() -> None:
    text = "a" * 5115
    body = b"\x01eng\x00\x00\xff\xfe" + text.encode("utf-16-le") + bytes(2)
    assert len(body) == 10240
    verify(tag(frame(body)), text)
    with pytest.raises(ValueError, match="10,240 bytes including"):
        verify(tag(frame(body[:-2] + b"a\x00\x00\x00")), text + "a")


@pytest.mark.parametrize("tag_flag", [0x80, 0x40, 0x10])
def test_transformed_or_unverified_tag_headers_are_rejected(tag_flag: int) -> None:
    with pytest.raises(ValueError, match="ID3 tag flags"):
        verify(tag(frame(utf8_body("a")), flags=tag_flag), "a")


@pytest.mark.parametrize("frame_flag", [1, 2, 4, 8, 0x20, 0x40, 0x80])
def test_transformed_frames_are_rejected(frame_flag: int) -> None:
    with pytest.raises(ValueError, match="transformed ID3 frames"):
        verify(tag(frame(utf8_body("a"), flags=bytes((0, frame_flag)))), "a")


def test_transformed_unrelated_frame_is_skipped_without_rewriting_it() -> None:
    verify(
        tag(frame(b"abc", kind=b"TIT2", flags=b"\x00\x80"), frame(utf8_body("one"))),
        "one",
    )


@pytest.mark.parametrize("suffix", [".m4a", ".M4B", ".m4p"])
def test_mp4_audio_filename_gate_and_utf8(suffix: str) -> None:
    verify(mp4("雪 🎵".encode()), "雪 🎵", "track" + suffix)


@pytest.mark.parametrize("suffix", [".mp4", ".M4V", ".mov"])
def test_mp4_video_filename_does_not_select_direct_utf8(suffix: str) -> None:
    with pytest.raises(ValueError, match=r"filename.*native MP4 audio"):
        verify(mp4(b"one"), "one", "track" + suffix)


def test_mp4_direct_utf8_does_not_strip_bom_like_id3() -> None:
    verify(mp4("\ufeffone".encode()), "\ufeffone", "track.m4a")
    with pytest.raises(ValueError, match="complete requested text"):
        verify(mp4("\ufeffone".encode()), "one", "track.m4a")


def test_mp4_payload_cap_is_byte_count_excluding_data_header() -> None:
    text = "é" * 5120
    verify(mp4(text.encode()), text, "track.m4a")
    with pytest.raises(ValueError, match="10,240-byte"):
        verify(mp4((text + "a").encode()), text + "a", "track.m4a")


@pytest.mark.parametrize(
    "data", [mp4(b"one", b"two"), mp4(b"one", extra=atom(b"free", b""))]
)
def test_mp4_single_data_child_must_fill_lyrics_atom(data: bytes) -> None:
    with pytest.raises(ValueError, match="one data child"):
        verify(data, "one", "track.m4a")


@pytest.mark.parametrize("suffix", [".wav", ".wave", ".aif", ".aiff", ".aifc"])
def test_embedded_id3_chunks_are_located_without_reading_media(suffix: str) -> None:
    payload = tag(frame(utf8_body("one")))
    wave = suffix in (".wav", ".wave")
    order: Literal["little", "big"] = "little" if wave else "big"
    media = b"JUNK" + (3).to_bytes(4, order) + b"abc\x00"
    media += b"id3 " + len(payload).to_bytes(4, order) + payload
    if len(payload) % 2:
        media += b"\x00"
    data = (b"RIFF" if wave else b"FORM") + (len(media) + 4).to_bytes(4, order)
    data += (b"WAVE" if wave else b"AIFF") + media
    verify(data, "one", "track" + suffix)


@pytest.mark.parametrize("file_name", ["track.mp3", "track.m4a", "track.bin"])
def test_empty_expected_permits_removal_without_container_constraints(
    file_name: str,
) -> None:
    verify(b"not metadata", "", file_name)


@pytest.mark.parametrize("file_name", ["track.mp3", "track.m4a"])
def test_embedded_nul_cannot_be_claimed_as_complete_text(file_name: str) -> None:
    text = "one\x00two"
    data = (
        tag(frame(utf8_body(text))) if file_name.endswith("mp3") else mp4(text.encode())
    )
    with pytest.raises(ValueError, match="NUL"):
        verify(data, text, file_name)
    with pytest.raises(ValueError, match=r"complete requested text|NUL"):
        verify(data, "onetwo", file_name)


def test_mp4_nul_payload_is_rejected_even_when_prefix_matches_expected() -> None:
    with pytest.raises(ValueError, match="NUL"):
        verify(mp4(b"one\x00two"), "one", "track.m4a")


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"ID3",
        tag(frame(utf8_body("one")))[:-1],
        b"ID3\x03\x00\x00\x80\x00\x00\x00",
    ],
)
def test_truncated_or_invalid_id3_does_not_read_outside_container(data: bytes) -> None:
    with pytest.raises(ValueError):
        verify(data, "one")


def test_large_media_payload_is_skipped_with_bounded_reads() -> None:
    class BoundedStream(io.BytesIO):
        def read(self, size: int | None = -1) -> bytes:
            assert size is not None and 0 <= size <= 10240
            return super().read(size)

    data = atom(b"mdat", bytes(1_000_000)) + mp4(b"one")
    stream = BoundedStream(data)
    stream.seek(5)
    verify_native_lyrics(stream, "track.m4a", "one")
    assert stream.tell() == 5


@pytest.mark.parametrize(
    "data",
    [
        b"\x00\x00\x00\x07moov",
        b"\x00\x00\x00\x10moov",
        atom(b"moov", atom(b"udta", b"x")),
    ],
)
def test_malformed_mp4_atom_bounds_are_rejected(data: bytes) -> None:
    with pytest.raises(ValueError):
        verify(data, "one", "track.m4a")
