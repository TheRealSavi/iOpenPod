"""Process-wide Qt display policy for cross-platform, high-DPI rendering."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication


def configure_display() -> None:
    """Configure display scaling before the application object is created.

    Qt 6 enables high-DPI scaling automatically. Pass-through rounding preserves
    native fractional scale factors such as Windows 150% while remaining a no-op
    for integer Retina scale factors on macOS.
    """

    if QGuiApplication.instance() is not None:
        raise RuntimeError("Display policy must be configured before QApplication")

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
