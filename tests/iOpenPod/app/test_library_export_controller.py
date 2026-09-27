"""Background export failures retain display templates across queued Qt signals."""

from pathlib import Path

import pytest
from PySide6.QtCore import Qt, QThreadPool
from tests.iOpenPod.GUI.application_shell_test_support import APPLICATION, build_context

from iOpenPod.app.display_text import SourceText, source_text
from iOpenPod.app.library_export import LibraryExporter, PhotoExporter
from iOpenPod.app.library_export_controller import (
    LibraryExportController,
    _ExportWork,  # pyright: ignore[reportPrivateUsage]
)
from iOpenPod.app.services.device_coordinator import DeviceTrackExportError
from storage import HostPath


@pytest.mark.parametrize(
    "detail",
    (
        source_text(
            "The selected Track could not be exported: {error}",
            error="native error with {braces}",
        ),
        "native error with {braces}",
    ),
)
def test_export_failure_keeps_source_text_through_worker_and_controller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, detail: str
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise DeviceTrackExportError(detail)

    monkeypatch.setattr(LibraryExporter, "export_tracks", fail)
    context = build_context()
    controller = LibraryExportController(
        context.device_coordinator, context.device_controller
    )
    work = _ExportWork(
        0,
        LibraryExporter(context.device_coordinator),
        PhotoExporter(context.device_coordinator),
        HostPath(tmp_path),
        (),
    )
    received: list[object] = []
    controller.failed.connect(received.append)
    # Exercise the worker's queued completion path without a device export.
    work.signals.completed.connect(
        controller._completed,  # pyright: ignore[reportPrivateUsage]
        Qt.ConnectionType.QueuedConnection,
    )
    pool = QThreadPool()
    try:
        pool.start(work)
        assert pool.waitForDone(5000)
        APPLICATION.processEvents()

        assert len(received) == 1
        assert received[0] == detail
        if isinstance(detail, SourceText):
            assert received[0] is detail
        else:
            assert type(received[0]) is str
    finally:
        pool.waitForDone()
        controller.shutdown()
        context.shutdown()
