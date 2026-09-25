"""The Original iOpenPod application icon, retained as packaged assets."""

from pathlib import Path

from PySide6.QtGui import QIcon


def application_icon() -> QIcon:
    directory = Path(__file__).parents[2] / "assets" / "icons"
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addFile(str(directory / f"icon-{size}.png"))
    return icon
