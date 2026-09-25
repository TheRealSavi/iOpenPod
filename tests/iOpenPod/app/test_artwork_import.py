"""Selected artwork is captured by Storage before bounded image decoding."""

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
from storage import HostPath


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
