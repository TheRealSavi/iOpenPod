"""Qt object-lifecycle isolation for GUI tests."""

from collections.abc import Iterator

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication


@pytest.fixture(autouse=True)
def _release_top_level_widgets() -> Iterator[None]:
    """Do not carry closed widget trees into the next application-style test."""

    yield
    application = QApplication.instance()
    if not isinstance(application, QApplication):
        return
    for widget in application.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()
