from pathlib import Path

from PIL import Image

import SyncEngine.photos as photos
from ArtworkDB_Writer.artwork_types import EncodedFormatPayload
from ipod_device.artwork_presets import ArtworkFormat
from SyncEngine.photos import (
    PhotoEntry,
    PhotoThumbRef,
    _decode_photo_format,
    _encode_photo_for_formats,
)


def test_photo_encoder_accepts_typed_codec_payload():
    img = Image.new("RGB", (80, 40), (200, 40, 20))
    fmt = ArtworkFormat(
        1017,
        56,
        56,
        112,
        "RGB565_LE",
        "photo_thumb",
        "test photo thumbnail",
    )

    encoded = _encode_photo_for_formats(
        img,
        {1017: fmt},
        fit_thumbnails=True,
    )

    info = encoded[1017]
    assert isinstance(info["data"], bytes)
    assert info["size"] == len(info["data"])
    assert info["width"] > 0
    assert info["height"] > 0
    assert info["filename"] == "F1017_1.ithmb"


def test_photo_encoder_passes_format_override(monkeypatch):
    img = Image.new("RGB", (80, 40), (200, 40, 20))
    fmt = ArtworkFormat(
        9998,
        12,
        10,
        24,
        "RGB565_LE",
        "photo_thumb",
        "test override thumbnail",
    )
    seen = {}

    def fake_encode(source_img, format_id, width, height, fmt_override=None):
        seen["format_id"] = format_id
        seen["fmt_override"] = fmt_override
        return EncodedFormatPayload(
            data=b"\x00" * (width * height * 2),
            width=width,
            height=height,
            size=width * height * 2,
            stride_pixels=width,
            pixel_format="RGB565_LE",
        )

    monkeypatch.setattr(photos, "encode_image_for_format", fake_encode)

    encoded = _encode_photo_for_formats(img, {9998: fmt})

    assert encoded[9998]["size"] == 240
    assert seen == {"format_id": 9998, "fmt_override": fmt}


def test_photo_decoder_passes_current_device_format_override(tmp_path, monkeypatch):
    fmt = ArtworkFormat(
        9999,
        2,
        2,
        4,
        "RGB565_LE",
        "photo_thumb",
        "test decode thumbnail",
    )
    thumbs_dir = tmp_path / "Photos" / "Thumbs"
    thumbs_dir.mkdir(parents=True)
    (thumbs_dir / "F9999_1.ithmb").write_bytes(b"\x00" * 8)
    entry = PhotoEntry(image_id=100)
    entry.thumbs[9999] = PhotoThumbRef(
        format_id=9999,
        offset=0,
        size=8,
        width=2,
        height=2,
        filename="F9999_1.ithmb",
    )
    seen = {}

    def fake_formats(_ipod_path):
        return {9999: fmt}

    def fake_decode(format_id, payload, width, height, hpad=0, vpad=0, fmt_override=None):
        seen["format_id"] = format_id
        seen["payload"] = payload
        seen["fmt_override"] = fmt_override
        return Image.new("RGB", (width, height))

    monkeypatch.setattr(photos, "_photo_formats_for_current_device", fake_formats)
    monkeypatch.setattr(photos, "decode_pixels_for_format", fake_decode)

    decoded = _decode_photo_format(entry, tmp_path, 9999)

    assert decoded is not None
    assert seen == {
        "format_id": 9999,
        "payload": b"\x00" * 8,
        "fmt_override": fmt,
    }


def test_scan_pc_photos_records_decompression_bomb_with_source_path(
    monkeypatch,
    tmp_path: Path,
) -> None:
    bomb = Image.DecompressionBombError(
        "Image size (200000000 pixels) exceeds limit of 178956970 pixels, could be decompression bomb DOS attack.",
    )
    image_path = tmp_path / "Booklet Scan.tif"
    image_path.write_bytes(b"fake")

    def fake_load(_path):
        raise bomb

    monkeypatch.setattr(photos, "_load_pil_still_image", fake_load)

    library = photos.scan_pc_photos(tmp_path)

    assert library.skipped == [(
        str(image_path),
        (
            "Image size (200000000 pixels) exceeds limit of 178956970 pixels, "
            "could be decompression bomb DOS attack. "
            f"Offending image: {image_path}"
        ),
    )]


def test_scan_pc_photos_respects_folder_entry_options(monkeypatch, tmp_path: Path) -> None:
    nested = tmp_path / "Nested"
    nested.mkdir()
    top = tmp_path / "top.jpg"
    deep = nested / "deep.jpg"
    top.write_bytes(b"fake")
    deep.write_bytes(b"fake")

    def fake_load(path):
        shade = 20 if Path(path).name == "top.jpg" else 40
        return Image.new("RGB", (2, 2), (shade, 0, 0))

    monkeypatch.setattr(photos, "_load_pil_still_image", fake_load)

    library = photos.scan_pc_photos([{
        "directory": str(tmp_path),
        "recurse": False,
        "media_types": ["photo"],
    }])

    assert [photo.display_name for photo in library.photos.values()] == ["top.jpg"]

    disabled = photos.scan_pc_photos([{
        "directory": str(tmp_path),
        "recurse": True,
        "media_types": ["music"],
    }])

    assert disabled.photos == {}
