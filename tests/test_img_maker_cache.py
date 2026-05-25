from __future__ import annotations

import os

from PIL import Image

from GUI import imgMaker


def test_configure_artwork_api_reuses_cache_for_unchanged_artworkdb(
    monkeypatch,
    tmp_path,
) -> None:
    artworkdb_path = tmp_path / "ArtworkDB"
    artworkdb_path.write_bytes(b"one")
    parse_calls: list[str] = []

    def fake_parse(path: str) -> dict:
        parse_calls.append(path)
        return {"mhli": [{"img_id": len(parse_calls)}]}

    monkeypatch.setattr("ArtworkDB_Parser.parser.parse_artworkdb", fake_parse)
    imgMaker.clear_artwork_api()

    try:
        first, first_index = imgMaker.configure_artwork_api(str(artworkdb_path))
        imgMaker._image_cache_put(99, (Image.new("RGB", (1, 1)), (0, 0, 0), {}))
        second, second_index = imgMaker.configure_artwork_api(str(artworkdb_path))

        assert first is second
        assert first_index is second_index
        assert len(parse_calls) == 1
        assert imgMaker.get_artwork(99, mode="cache_only") is not None
    finally:
        imgMaker.clear_artwork_api()


def test_configure_artwork_api_reloads_when_artworkdb_file_changes(
    monkeypatch,
    tmp_path,
) -> None:
    artworkdb_path = tmp_path / "ArtworkDB"
    artworkdb_path.write_bytes(b"one")
    parse_calls: list[str] = []

    def fake_parse(path: str) -> dict:
        parse_calls.append(path)
        return {"mhli": [{"img_id": len(parse_calls)}]}

    monkeypatch.setattr("ArtworkDB_Parser.parser.parse_artworkdb", fake_parse)
    imgMaker.clear_artwork_api()

    try:
        first, first_index = imgMaker.configure_artwork_api(str(artworkdb_path))
        imgMaker._image_cache_put(99, (Image.new("RGB", (1, 1)), (0, 0, 0), {}))

        artworkdb_path.write_bytes(b"changed")
        stat = artworkdb_path.stat()
        os.utime(
            artworkdb_path,
            ns=(stat.st_atime_ns + 1_000_000, stat.st_mtime_ns + 1_000_000),
        )

        second, second_index = imgMaker.configure_artwork_api(str(artworkdb_path))

        assert first is not second
        assert first_index is not second_index
        assert len(parse_calls) == 2
        assert imgMaker.get_artwork(99, mode="cache_only") is None
    finally:
        imgMaker.clear_artwork_api()
