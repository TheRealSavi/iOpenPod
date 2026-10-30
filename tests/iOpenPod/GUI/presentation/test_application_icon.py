"""Application icon colors through native Wayland buffers and Qt painting."""

from pathlib import Path

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from iOpenPod.GUI.presentation import application_icon as icon_module


def _application() -> QApplication:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    return QApplication([])


APPLICATION = _application()
SIZES = (16, 24, 32, 48, 64, 128, 256)
ICONS = Path(icon_module.__file__).parents[2] / "assets" / "icons"


def _original_icon() -> QIcon:
    icon = QIcon()
    for size in SIZES:
        icon.addFile(str(ICONS / f"icon-{size}.png"))
    return icon


def _runtime(monkeypatch: pytest.MonkeyPatch, platform: str, version: str) -> None:
    monkeypatch.setattr(QGuiApplication, "platformName", staticmethod(lambda: platform))
    monkeypatch.setattr(icon_module, "qVersion", lambda: version)


def _wayland_buffer(pixmap: QPixmap) -> QImage:
    # Qt 6.11.2/6.12.0's xdg-toplevel-icon path paints into straight ARGB32,
    # but wl_shm ARGB8888 is read as premultiplied ARGB32 by KWin.
    stride = ((pixmap.width() * 4 + 255) // 256) * 256
    storage = bytearray(stride * pixmap.height())
    buffer = QImage(
        storage,
        pixmap.width(),
        pixmap.height(),
        stride,
        QImage.Format.Format_ARGB32,
    )
    buffer.fill(Qt.GlobalColor.transparent)
    painter = QPainter(buffer)
    try:
        painter.drawPixmap(buffer.rect(), pixmap, pixmap.rect())
    finally:
        painter.end()
    assert buffer.reinterpretAsFormat(QImage.Format.Format_ARGB32_Premultiplied)
    return buffer.copy()  # KWin copies the imported image before retaining it.


@pytest.mark.parametrize("platform", ["wayland", "wayland-egl"])
@pytest.mark.parametrize("version", ["6.11.2", "6.12.0"])
@pytest.mark.parametrize("size", SIZES)
def test_wayland_window_icon_preserves_original_premultiplied_pixels(
    monkeypatch: pytest.MonkeyPatch, platform: str, version: str, size: int
) -> None:
    _runtime(monkeypatch, platform, version)
    icon = icon_module.application_icon()
    assert icon.availableSizes() == [QSize(value, value) for value in SIZES]
    expected = _original_icon().pixmap(QSize(size, size), 1.0).toImage()
    expected = expected.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)

    actual = _wayland_buffer(icon.pixmap(QSize(size, size), 1.0))

    assert bytes(actual.constBits()) == bytes(expected.constBits())


@pytest.mark.parametrize("dpr", [1.0, 1.5, 2.0])
def test_wayland_icon_keeps_scaled_pixel_data_after_copy(
    monkeypatch: pytest.MonkeyPatch, dpr: float
) -> None:
    _runtime(monkeypatch, "wayland", "6.11.2")
    original = icon_module.application_icon()
    icon = QIcon(original)
    icon.setIsMask(False)  # Detach the shared engine, exercising its Qt clone hook.
    pixmap = icon.pixmap(QSize(16, 16), dpr)
    expected = _original_icon().pixmap(QSize(16, 16), dpr)

    assert pixmap.size() == expected.size()
    assert pixmap.devicePixelRatio() == expected.devicePixelRatio()
    assert bytes(_wayland_buffer(pixmap).constBits()) == bytes(
        expected.toImage().constBits()
    )


def test_new_windows_inherit_the_wayland_icon_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _runtime(monkeypatch, "wayland", "6.11.2")
    previous = QApplication.windowIcon()
    window = QWidget()
    try:
        QApplication.setWindowIcon(icon_module.application_icon())
        window.show()
        handle = window.windowHandle()
        actual = _wayland_buffer(handle.icon().pixmap(QSize(16, 16), 1.0))
        expected = _original_icon().pixmap(QSize(16, 16), 1.0).toImage()
        assert bytes(actual.constBits()) == bytes(expected.constBits())
    finally:
        window.close()
        QApplication.setWindowIcon(previous)


@pytest.mark.parametrize("platform", ["windows", "cocoa", "xcb", "offscreen"])
def test_non_wayland_icons_keep_original_pixels(
    monkeypatch: pytest.MonkeyPatch, platform: str
) -> None:
    monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
    _runtime(monkeypatch, platform, "6.11.2")
    icon = icon_module.application_icon()
    original = _original_icon()

    for size in SIZES:
        assert (
            icon.pixmap(size, size).toImage() == original.pixmap(size, size).toImage()
        )


@pytest.mark.parametrize("version", ["6.11.1", "6.11.3", "6.12.1", "6.13.0"])
def test_uninspected_qt_versions_keep_original_pixels(
    monkeypatch: pytest.MonkeyPatch, version: str
) -> None:
    _runtime(monkeypatch, "wayland", version)
    assert icon_module.application_icon().pixmap(16, 16).toImage() == (
        _original_icon().pixmap(16, 16).toImage()
    )


@pytest.mark.parametrize("dpr", [1.0, 1.5, 2.0])
def test_wayland_client_decoration_paints_original_colors(
    monkeypatch: pytest.MonkeyPatch, dpr: float
) -> None:
    _runtime(monkeypatch, "wayland", "6.11.2")
    images: list[QImage] = []
    for icon in (icon_module.application_icon(), _original_icon()):
        image = QImage(
            round(22 * dpr), round(22 * dpr), QImage.Format.Format_ARGB32_Premultiplied
        )
        image.setDevicePixelRatio(dpr)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        try:
            icon.paint(painter, 0, 0, 22, 22)
        finally:
            painter.end()
        images.append(image)

    assert images[0] == images[1]
