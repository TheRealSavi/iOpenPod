"""Selected artwork is captured by Storage before bounded image decoding."""

import weakref
from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtTest import QSignalSpy
from tests.iOpenPod.app.test_library_write_controller import wait_for

from iOpenPod.app.artwork_import import (
    ArtworkImportController,
    ArtworkImportError,
    import_artwork,
)
from iOpenPod.app.media.photo_image import photo_viewing_image
from storage import HostPath


@pytest.mark.filterwarnings("error:Palette images with Transparency:UserWarning")
def test_palette_transparency_decodes_for_artwork_and_photos(tmp_path: Path) -> None:
    path = tmp_path / "palette.png"
    source = Image.new("P", (3, 1))
    source.putpalette([255, 0, 0, 0, 255, 0, 0, 0, 255])
    source.putdata([0, 1, 2])
    source.save(path, transparency=bytes([0, 128, 255]))
    expected = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255])

    pixels = import_artwork(HostPath(path), checkpoint=lambda: None)
    assert pixels.rgb888 == expected
    with path.open("rb") as stream, photo_viewing_image(stream, (3, 1)) as photo:
        assert photo.mode == "RGB"
        assert photo.tobytes() == expected


def test_import_applies_exif_orientation_and_returns_owned_rgb(tmp_path: Path) -> None:
    path = tmp_path / "rotated.jpg"
    source = Image.new("RGB", (2, 3), (12, 34, 56))
    exif = Image.Exif()
    exif[274] = 6
    source.save(path, exif=exif)

    pixels = import_artwork(HostPath(path), checkpoint=lambda: None)

    assert (pixels.width, pixels.height) == (3, 2)
    assert len(pixels.rgb888) == 3 * 2 * 3


def test_import_rejects_dimensions_before_loading_pixels(tmp_path: Path) -> None:
    path = tmp_path / "too-wide.png"
    Image.new("1", (8193, 1)).save(path)

    with pytest.raises(ArtworkImportError, match="8192"):
        import_artwork(HostPath(path), checkpoint=lambda: None)


def test_controller_decodes_without_blocking_the_calling_thread(tmp_path: Path) -> None:
    path = tmp_path / "cover.png"
    Image.new("RGB", (20, 10), (12, 34, 56)).save(path)
    controller = ArtworkImportController()
    finished = QSignalSpy(controller.finished)
    failed = QSignalSpy(controller.failed)
    try:
        controller.start(HostPath(path))
        assert controller.busy
        wait_for(lambda: not controller.busy)
        assert finished.count() == 1
        assert failed.count() == 0
    finally:
        controller.shutdown()


def test_repeated_artwork_imports_release_completed_jobs(tmp_path: Path) -> None:
    path = tmp_path / "cover.png"
    Image.new("RGB", (20, 10), (12, 34, 56)).save(path)
    controller = ArtworkImportController()
    references: list[weakref.ReferenceType[object]] = []
    try:
        for _ in range(12):
            controller.start(HostPath(path))
            references.extend(
                weakref.ref(job)
                for job in controller._jobs.values()  # pyright: ignore[reportPrivateUsage]
            )
            wait_for(lambda: not controller.busy)
        wait_for(lambda: all(reference() is None for reference in references))
    finally:
        controller.shutdown()
