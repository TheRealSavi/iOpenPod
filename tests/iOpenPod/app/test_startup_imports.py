"""Fresh-process checks for responsive GUI startup."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "outcome", ["ready", "close", "close_after_context", "failure"]
)
def test_launcher_paints_before_composition_and_can_close_during_startup(
    tmp_path: Path, outcome: str
) -> None:
    source = """
import sys
from PySide6 import QtWidgets
from PySide6.QtCore import QEvent, QTimer

first_paint = []
ready_windows = []
outcome = sys.argv.pop()

class Application(QtWidgets.QApplication):
    def notify(self, target, event):
        if (
            not first_paint and event.type() == QEvent.Type.Paint
            and isinstance(target, QtWidgets.QWidget)
        ):
            window = target.window()
            first_paint.append((window.objectName(), "iOpenPod.app.context" in sys.modules))
            if outcome == "close":
                QTimer.singleShot(0, window.close)
            if outcome == "close_after_context":
                progress = window.findChild(QtWidgets.QProgressBar)
                progress.valueChanged.connect(lambda value: window.close() if value == 1 else None)
        return super().notify(target, event)

QtWidgets.QApplication = Application
from iOpenPod.app.updates import bootstrap

def healthy(application, window, ready):
    ready_windows.append((type(window).__name__, window.isVisible()))
    if outcome == "failure":
        raise RuntimeError("failed to start session")
    QTimer.singleShot(0, application.quit)

bootstrap.start_health_handshake = healthy
import iopenpod_launcher
try:
    assert iopenpod_launcher.main([]) == 0
except RuntimeError as error:
    assert outcome == "failure" and str(error) == "failed to start session"
else:
    assert outcome != "failure"
assert first_paint == [("startupWindow", False)], first_paint
assert ready_windows == ([] if outcome.startswith("close") else [("MainWindow", True)]), ready_windows
"""
    completed = subprocess.run(
        [sys.executable, "-c", source, outcome],
        env=_launch_environment(tmp_path),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr


def _launch_environment(tmp_path: Path) -> dict[str, str]:
    environment = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    for name in (
        "HOME",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "TMPDIR",
        "TEMP",
        "TMP",
        "XDG_CONFIG_HOME",
        "XDG_CACHE_HOME",
        "XDG_STATE_HOME",
    ):
        environment[name] = str(tmp_path)
    return environment


def test_startup_window_stays_centered_and_visually_stable(tmp_path: Path) -> None:
    source = """
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QLabel, QScrollBar
from iOpenPod.GUI.startup_window import StartupWindow

app = QApplication([])
screen = next(display for display in app.screens() if display != app.primaryScreen())
QCursor.setPos(screen.availableGeometry().center())
window = StartupWindow()
first_paint = []
window.firstPaint.connect(lambda: first_paint.append(window.frameGeometry()))
window.show_centered()
app.processEvents()
frame = window.frameGeometry()
assert window.screen() == screen
assert first_paint == [frame]
assert (frame.center() - screen.geometry().center()).manhattanLength() <= 2, frame
window.progress.setValue(1)
original = window.grab().toImage()

from iOpenPod.app.core.settings.definitions import AppearanceMode
from iOpenPod.app.core.settings.service import SettingsService
from iOpenPod.app.core.settings.stores import DeviceSettingsStore, GlobalSettingsStore
from iOpenPod.GUI.presentation.i18n.manager import I18nManager
from iOpenPod.GUI.presentation.theme.manager import ThemeManager

settings = SettingsService(GlobalSettingsStore(), DeviceSettingsStore())
theme = ThemeManager(app, settings)
for mode in (AppearanceMode.LIGHT, AppearanceMode.DARK):
    theme.set_mode(mode)
    app.processEvents()
    assert window.grab().toImage() == original, mode
    assert window.frameGeometry() == frame
    assert not window.findChildren(QScrollBar)
window.progress.setValue(2)
assert window.grab().toImage() != original
language = I18nManager(app, settings)
for tag in ("de", "es"):
    language.set_language(tag)
    app.processEvents()
    label = next(label for label in window.findChildren(QLabel) if label.text())
    assert label.text() == window.progress.accessibleName()
    assert label.width() >= label.sizeHint().width()
    assert window.frameGeometry() == frame
theme.close()
window.close()
"""
    displays = [
        {"name": "primary", "x": 0, "width": 1200, "height": 900},
        {"name": "secondary", "x": -1600, "width": 1600, "height": 1000, "dpr": 1.5},
    ]
    (tmp_path / "displays.json").write_text(json.dumps({"screens": displays}))
    environment = _launch_environment(tmp_path)
    environment["QT_QPA_PLATFORM"] = "offscreen:configfile=displays.json"
    completed = subprocess.run(
        [sys.executable, "-c", source],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr


def test_app_composition_does_not_import_music_analysis_libraries() -> None:
    source = """
import importlib.abc
import sys

blocked_roots = frozenset({"librosa", "numba", "scipy"})

class HeavyAnalysisImportBlocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        root = fullname.partition(".")[0]
        if root in blocked_roots:
            raise AssertionError(f"GUI startup eagerly imported {root}")
        return None

sys.meta_path.insert(0, HeavyAnalysisImportBlocker())

import iOpenPod.app.context
from iOpenPod.app.synesthesia import WholeTrackMusicAnalyzer

WholeTrackMusicAnalyzer()
print("STARTUP_IMPORTS_CLEAN")
"""

    completed = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", source],
        capture_output=True,
        check=False,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "STARTUP_IMPORTS_CLEAN"
