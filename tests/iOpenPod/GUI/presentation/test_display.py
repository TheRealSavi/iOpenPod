"""Cross-platform and high-DPI tests for the process-wide display policy."""

import json
import os
import subprocess
import sys
from textwrap import dedent
from typing import TypedDict, cast

import pytest


class _DisplayProbe(TypedDict):
    widget_size: list[int]
    widget_dpr: float
    pixmap_size: list[int]
    pixmap_dpr: float
    independent_size: list[float]


_SCALE_PROBE = dedent(
    """
    import json

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication, QWidget

    from iOpenPod.GUI.presentation.display import configure_display

    assert QGuiApplication.instance() is None
    configure_display()
    assert (
        QGuiApplication.highDpiScaleFactorRoundingPolicy()
        is Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    application = QApplication([])
    widget = QWidget()
    widget.resize(320, 200)
    widget.show()
    application.processEvents()
    pixmap = widget.grab()
    independent_size = pixmap.deviceIndependentSize()

    print(
        json.dumps(
            {
                "widget_size": [widget.width(), widget.height()],
                "widget_dpr": widget.devicePixelRatioF(),
                "pixmap_size": [pixmap.width(), pixmap.height()],
                "pixmap_dpr": pixmap.devicePixelRatio(),
                "independent_size": [
                    independent_size.width(),
                    independent_size.height(),
                ],
            }
        )
    )
    widget.close()
    """
)


@pytest.mark.parametrize("scale_factor", [1.0, 1.5, 2.0])
def test_scale_factor_changes_backing_store_not_logical_geometry(
    scale_factor: float,
) -> None:
    # The offscreen plugin is a geometry seam; native font rendering is verified
    # separately on each Host because Windows offscreen exposes no system font DB.
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment["QT_SCALE_FACTOR"] = f"{scale_factor:g}"
    completed = subprocess.run(
        [sys.executable, "-c", _SCALE_PROBE],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert completed.returncode == 0, completed.stderr
    result = cast("_DisplayProbe", json.loads(completed.stdout))
    assert result["widget_size"] == [320, 200]
    assert result["widget_dpr"] == pytest.approx(scale_factor)
    assert result["pixmap_size"] == [
        round(320 * scale_factor),
        round(200 * scale_factor),
    ]
    assert result["pixmap_dpr"] == pytest.approx(scale_factor)
    assert result["independent_size"] == pytest.approx([320.0, 200.0])


def test_display_policy_rejects_late_configuration() -> None:
    probe = dedent(
        """
        from PySide6.QtWidgets import QApplication

        from iOpenPod.GUI.presentation.display import configure_display

        application = QApplication([])
        try:
            configure_display()
        except RuntimeError:
            raise SystemExit(0)
        raise SystemExit(1)
        """
    )
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert completed.returncode == 0, completed.stderr
