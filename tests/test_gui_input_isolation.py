"""GUI tests release Qt input state independently of test execution order."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("leak_first", [True, False])
@pytest.mark.parametrize(
    "input_kind", ["control", "shift", "alt_meta", "buttons", "cursor"]
)
def test_gui_tests_release_input_between_cases(
    tmp_path: Path, leak_first: bool, input_kind: str
) -> None:
    shutil.copyfile(ROOT / "tests/iOpenPod/GUI/conftest.py", tmp_path / "conftest.py")
    (tmp_path / "gui_support.py").write_text(
        "from PySide6.QtWidgets import QApplication\nAPPLICATION = QApplication([])\n",
        encoding="utf-8",
    )
    (tmp_path / "test_leak.py").write_text(
        f"INPUT_KIND = {input_kind!r}\n"
        + """from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget
from gui_support import APPLICATION

def test_leave_input_active():
    assert APPLICATION.keyboardModifiers() == Qt.KeyboardModifier.NoModifier
    assert APPLICATION.mouseButtons() == Qt.MouseButton.NoButton
    widget = QWidget()
    widget.resize(180, 40)
    widget.show()
    APPLICATION.processEvents()
    modifiers = {
        "control": Qt.KeyboardModifier.ControlModifier,
        "shift": Qt.KeyboardModifier.ShiftModifier,
        "alt_meta": Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier,
    }.get(INPUT_KIND, Qt.KeyboardModifier.NoModifier)
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, modifiers)
    assert APPLICATION.keyboardModifiers() == modifiers
    if INPUT_KIND == "buttons":
        widget.grabMouse()
        widget.grabKeyboard()
        QTest.mousePress(widget, Qt.MouseButton.LeftButton)
        QTest.mousePress(widget, Qt.MouseButton.RightButton)
        assert APPLICATION.mouseButtons() == (
            Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton
        )
        APPLICATION.setOverrideCursor(Qt.CursorShape.WaitCursor)
    QCursor.setPos(widget.mapToGlobal(widget.rect().center()))
    # Keep the widget and its pressed input alive for the shared teardown.
    APPLICATION.leaked_widget = widget
""",
        encoding="utf-8",
    )
    (tmp_path / "test_probe.py").write_text(
        """from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget
from gui_support import APPLICATION
from iOpenPod.GUI.widgets.star_rating import StarRating

def test_next_widget_starts_with_neutral_input():
    assert APPLICATION.keyboardModifiers() == Qt.KeyboardModifier.NoModifier
    assert APPLICATION.mouseButtons() == Qt.MouseButton.NoButton
    assert QWidget.mouseGrabber() is None
    assert QWidget.keyboardGrabber() is None
    assert APPLICATION.overrideCursor() is None
    rating = StarRating()
    rating.resize(180, 40)
    rating.show()
    APPLICATION.processEvents()
    assert rating.property("ratingHover") is False
    QTest.mouseMove(rating, rating.rect().center())
    APPLICATION.processEvents()
    assert rating.property("ratingHover") is True
""",
        encoding="utf-8",
    )
    paths = ["test_leak.py", "test_probe.py"]
    if not leak_first:
        paths.reverse()
    environment = dict(os.environ)
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment.pop("PYTEST_ADDOPTS", None)
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *paths],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
