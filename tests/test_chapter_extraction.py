from __future__ import annotations

from iopenpod.podcasts.downloader import _read_nero_chapters


def _atom(kind: bytes, body: bytes) -> bytes:
    return (len(body) + 8).to_bytes(4, "big") + kind + body


def _chpl_body(chapters: list[tuple[int, str]]) -> bytes:
    body = bytearray(b"\x00\x00\x00\x00")  # version/flags
    body.append(0)  # Nero unknown byte
    body.append(len(chapters))  # version 0 chapter count
    for start_ms, title in chapters:
        encoded = title.encode("utf-8")
        body.extend((start_ms * 10_000).to_bytes(8, "big"))
        body.append(len(encoded))
        body.extend(encoded)
    return bytes(body)


def _mp4_with_chpl(chapters: list[tuple[int, str]]) -> bytes:
    return (
        _atom(b"ftyp", b"isom\x00\x00\x00\x01")
        + _atom(b"moov", _atom(b"udta", _atom(b"chpl", _chpl_body(chapters))))
    )


def test_nero_chapter_reader_reads_moov_udta_chpl_atom(tmp_path) -> None:
    path = tmp_path / "chaptered.m4a"
    path.write_bytes(_mp4_with_chpl([(0, "Intro"), (65_000, "Part One")]))

    assert _read_nero_chapters(str(path)) == [
        {"startpos": 0, "title": "Intro"},
        {"startpos": 65_000, "title": "Part One"},
    ]


def test_nero_chapter_reader_ignores_raw_chpl_bytes_outside_atom_tree(tmp_path) -> None:
    path = tmp_path / "song.m4a"
    path.write_bytes(b"audio payload chpl" + _chpl_body([(0, "Not a real atom")]))

    assert _read_nero_chapters(str(path)) is None


def test_nero_chapter_reader_rejects_implausible_timeline(tmp_path) -> None:
    path = tmp_path / "bad-chapters.m4a"
    path.write_bytes(_mp4_with_chpl([(0x1_0000_0000, "Too late")]))

    assert _read_nero_chapters(str(path)) is None
