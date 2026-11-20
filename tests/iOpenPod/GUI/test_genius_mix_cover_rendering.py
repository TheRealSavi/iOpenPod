"""On-demand covers match Add Mixes and render safely without a GUI event loop."""

import subprocess
import sys

import pytest
from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage, QPainter
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION

from iOpenPod.app.genius_mixes import MIX_CATALOG
from iOpenPod.GUI.presentation.genius_mix_artwork import (
    paint_mix_artwork,
    render_mix_cover,
)
from iOpenPod.GUI.presentation.theme.tokens import DARK_TOKENS


@pytest.mark.parametrize("size", (142, 240))
def test_runtime_covers_match_shared_ui_painter(size: int) -> None:
    APPLICATION.processEvents()
    for definition in MIX_CATALOG:
        image = QImage(size, size, QImage.Format.Format_RGB32)
        painter = QPainter(image)
        paint_mix_artwork(
            painter, QRectF(0, 0, size, size), definition.key, DARK_TOKENS
        )
        painter.end()
        rgb = image.convertToFormat(QImage.Format.Format_RGB888)
        data = bytes(rgb.constBits())
        pixels = b"".join(
            data[row * rgb.bytesPerLine() : row * rgb.bytesPerLine() + size * 3]
            for row in range(size)
        )
        cover = render_mix_cover(definition.key, size)
        assert (cover.width, cover.height) == (size, size)
        assert pixels == cover.rgb888, definition.key


def test_covers_render_on_workers_without_a_gui_application() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import QCoreApplication
from iOpenPod.app.genius_mixes import MIX_CATALOG
from iOpenPod.GUI.presentation.genius_mix_artwork import render_mix_cover

assert QCoreApplication.instance() is None
jobs = [(d.key, size) for d in MIX_CATALOG for size in (142, 240)]
with ThreadPoolExecutor(max_workers=4) as pool:
    futures = [pool.submit(render_mix_cover, *job) for job in jobs]
    covers = [future.result() for future in futures]
assert len({cover.rgb888 for cover in covers}) == len(jobs)
for (key, size), cover in zip(jobs, covers, strict=True):
    assert len(cover.rgb888) == size * size * 3
    assert cover == render_mix_cover(key, size)
assert QCoreApplication.instance() is None
""",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert not result.stderr, result.stderr


@pytest.mark.parametrize(
    ("key", "size"), [("unknown", 142), ("rock", 0), ("rock", 512)]
)
def test_rendering_rejects_unknown_artwork_and_unbounded_sizes(
    key: str, size: int
) -> None:
    with pytest.raises(ValueError):
        render_mix_cover(key, size)
