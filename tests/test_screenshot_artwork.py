"""Screenshot artwork is deterministic, traceable, and read without source edits."""

import hashlib
from pathlib import Path

import pytest
from PIL import Image
from scripts.capture_store_screenshots import ALBUMS, artwork_provenance, sample_images


def test_supplied_artwork_order_pixels_and_source_preservation(tmp_path: Path) -> None:
    originals: dict[str, bytes] = {}
    for index in reversed(range(len(ALBUMS) + 4)):
        name = f"{'a' if index % 2 else 'A'}{index:02}.png"
        if index == 0:
            name = name.removesuffix(".png") + ".PNG"
        path = tmp_path / name
        Image.new("RGBA", (40, 20), (index, 100, 200, 255)).save(path)
        originals[name] = path.read_bytes()
    images = sample_images(tmp_path)
    assert len(images.covers) == len(ALBUMS)
    assert len(images.photos) == 12
    for index, image in images.covers.items():
        assert image.mode == "RGB"
        assert image.width == image.height * 2
        assert image.getpixel((0, 0)) == (index - 1, 100, 200)
    assert images.photos[12].getpixel((0, 0)) == (27, 100, 200)
    provenance = artwork_provenance(tmp_path)
    assert [entry["file"] for entry in provenance] == sorted(
        originals, key=str.casefold
    )
    for entry in provenance:
        assert (tmp_path / entry["file"]).read_bytes() == originals[entry["file"]]
        assert entry["sha256"] == hashlib.sha256(originals[entry["file"]]).hexdigest()


def test_missing_artwork_fails_instead_of_silently_using_old_illustrations(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="Expected at least 24 PNG artworks"):
        sample_images(tmp_path)
