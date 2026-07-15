from __future__ import annotations

import os
from typing import cast

import numpy as np
from PIL import Image

from iopenpod.artworkdb_writer.ithmb_codecs import encode_image_for_format
from iopenpod.device.artwork import resolve_cover_art_format_definitions
from iopenpod.gui import imgMaker


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

    monkeypatch.setattr("iopenpod.artworkdb_parser.parser.parse_artworkdb", fake_parse)
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

    monkeypatch.setattr("iopenpod.artworkdb_parser.parser.parse_artworkdb", fake_parse)
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


def test_image_only_artwork_reuses_full_result_cache(monkeypatch) -> None:
    decode_calls = []
    cached_image = Image.new("RGB", (2, 2), (12, 34, 56))

    def fake_decode(*_args, **_kwargs):
        decode_calls.append(True)
        return None

    monkeypatch.setattr(imgMaker, "_decode_image_from_db", fake_decode)
    imgMaker.clear_artwork_api()

    try:
        imgMaker._image_cache_put(99, (cached_image, (0, 0, 0), {}))

        result = imgMaker.get_artwork(99, mode="image_only")

        assert result is not None
        assert result is not cached_image
        assert result.size == cached_image.size
        assert decode_calls == []
    finally:
        imgMaker.clear_artwork_api()


def test_generate_image_crops_rgb565_stride_padding(tmp_path) -> None:
    fmt = resolve_cover_art_format_definitions("iPod Nano", "7th Gen")[1016]
    source = Image.new("RGB", (fmt.width, fmt.height), (240, 16, 32))
    encoded = encode_image_for_format(
        source,
        fmt.format_id,
        fmt.width,
        fmt.height,
        fmt_override=fmt,
    )
    ithmb_path = tmp_path / "F1016_1.ithmb"
    ithmb_path.write_bytes(encoded.data)

    decoded = imgMaker.generate_image(
        str(ithmb_path),
        {
            "correlationID": fmt.format_id,
            "ithmbOffset": 0,
            "imgSize": encoded.size,
            "imageWidth": fmt.width,
            "imageHeight": fmt.height,
            "horizontalPadding": encoded.stride_pixels - fmt.width,
            "verticalPadding": 0,
            "estimatedPixmapWidth": encoded.stride_pixels,
            "estimatedPixmapHeight": fmt.height,
            "image_format": {
                "format_id": fmt.format_id,
                "width": fmt.width,
                "height": fmt.height,
                "format": fmt.pixel_format,
                "description": fmt.description,
            },
            "3": {"File Name": ":F1016_1.ithmb"},
        },
    )

    assert decoded is not None
    assert decoded.size == (fmt.width, fmt.height)
    right_edge = np.asarray(decoded.convert("RGB"), dtype=np.uint8)[:, -1, :]
    assert int(right_edge[:, 0].min()) > 200
    assert int(right_edge[:, 1].max()) < 40
    assert int(right_edge[:, 2].max()) < 60


def test_artwork_decode_uses_integer_mhod_file_metadata_key(tmp_path) -> None:
    fmt = resolve_cover_art_format_definitions("iPod Classic", "6th Gen")[1061]
    red = encode_image_for_format(
        Image.new("RGB", (fmt.width, fmt.height), (240, 16, 32)),
        fmt.format_id,
        fmt.width,
        fmt.height,
        fmt_override=fmt,
    )
    blue = encode_image_for_format(
        Image.new("RGB", (fmt.width, fmt.height), (16, 32, 240)),
        fmt.format_id,
        fmt.width,
        fmt.height,
        fmt_override=fmt,
    )
    (tmp_path / f"F{fmt.format_id}_1.ithmb").write_bytes(red.data)
    (tmp_path / f"F{fmt.format_id}_2.ithmb").write_bytes(blue.data)

    image_result = {
        "correlationID": fmt.format_id,
        "ithmbOffset": 0,
        "imgSize": blue.size,
        "imageWidth": fmt.width,
        "imageHeight": fmt.height,
        "horizontalPadding": 0,
        "verticalPadding": 0,
        "estimatedPixmapWidth": fmt.width,
        "estimatedPixmapHeight": fmt.height,
        "image_format": {
            "format_id": fmt.format_id,
            "width": fmt.width,
            "height": fmt.height,
            "format": fmt.pixel_format,
            "description": fmt.description,
        },
        3: {"mhodType": 3, "File Name": f":F{fmt.format_id}_2.ithmb"},
    }
    entry = {
        "img_id": 42,
        "songId": 99,
        "_image_containers": [
            {
                "mhodType": 2,
                "Thumbnail Image": {"result": image_result},
            }
        ],
    }
    artworkdb = {"mhli": [entry]}

    decoded = imgMaker.get_artwork(
        42,
        mode="image_only",
        artworkdb_data=artworkdb,
        artwork_folder_path=str(tmp_path),
        img_id_index={42: entry},
    )
    assert decoded is not None
    pixel = cast(tuple[int, int, int], decoded.convert("RGB").getpixel((0, 0)))
    assert pixel[2] > 200
    assert pixel[0] < 40

    previews = imgMaker.get_track_artwork_previews(
        {"db_track_id": 99, "artwork_id_ref": 42},
        artworkdb_data=artworkdb,
        artwork_folder_path=str(tmp_path),
        img_id_index={42: entry},
    )
    assert len(previews) == 1
    preview_pixel = cast(
        tuple[int, int, int],
        previews[0].variants[0].image.convert("RGB").getpixel((0, 0)),
    )
    assert preview_pixel[2] > 200
    assert preview_pixel[0] < 40
