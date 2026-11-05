"""Screenshot metadata must remain paired with its intended source artwork."""

import hashlib
from pathlib import Path

import pytest
from PIL import Image
from scripts.capture_store_screenshots import (
    artwork_provenance,
    sample_images,
    sample_library,
)
from scripts.screenshot_catalog import ALBUMS


def test_supplied_artwork_metadata_and_source_preservation(tmp_path: Path) -> None:
    originals: dict[str, bytes] = {}
    for index, album in reversed(tuple(enumerate(ALBUMS))):
        name = album.filename.upper() if index == 0 else album.filename
        path = tmp_path / name
        Image.new("RGBA", (40, 20), (index, 100, 200, 255)).save(path)
        originals[name] = path.read_bytes()
    # An unrelated early-sorting image must never shift the Album/cover pairing.
    Image.new("RGB", (40, 20), "red").save(tmp_path / "000 unrelated.png")
    originals["000 unrelated.png"] = (tmp_path / "000 unrelated.png").read_bytes()
    images = sample_images(tmp_path)
    library = sample_library()
    assert len(images.covers) == len(ALBUMS)
    assert len(images.photos) == 12
    for index, image in images.covers.items():
        album = ALBUMS[index - 1]
        assert image.mode == "RGB"
        assert image.width == image.height * 2
        assert image.getpixel((0, 0)) == (index - 1, 100, 200)
        tracks = [track for track in library.tracks if track.artwork_id == index]
        assert len(tracks) == 12
        assert all(
            track.album == album.title and track.artist == album.artist
            for track in tracks
        )
        assert tuple(track.title for track in tracks) == album.tracks
    provenance = artwork_provenance(tmp_path)
    assert [entry["file"] for entry in provenance] == sorted(
        originals, key=str.casefold
    )
    for entry in provenance:
        assert (tmp_path / entry["file"]).read_bytes() == originals[entry["file"]]
        assert entry["sha256"] == hashlib.sha256(originals[entry["file"]]).hexdigest()
    daylight = next(row for row in provenance if row["file"] == "daylight.png")
    assert daylight["album"] == "Daylight"
    assert daylight["artist"] == "Solar Arcade"


def test_missing_named_artwork_fails_instead_of_pairing_with_another_file(
    tmp_path: Path,
) -> None:
    for index in range(len(ALBUMS)):
        Image.new("RGB", (2, 2)).save(tmp_path / f"unrelated-{index}.png")
    with pytest.raises(
        ValueError, match=r"Missing screenshot artwork: 25 blimps back\.png"
    ):
        sample_images(tmp_path)


def test_album_metadata_has_distinct_thematic_track_lists() -> None:
    assert len({album.filename.casefold() for album in ALBUMS}) == len(ALBUMS)
    assert len({album.tracks for album in ALBUMS}) == len(ALBUMS)
    for album in ALBUMS:
        assert len(album.tracks) == len(set(album.tracks)) == 12
        assert album.tracks[0] == album.title
