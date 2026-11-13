"""Prepare Sync comparisons from captured scan results off the GUI thread."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt, QThreadPool, Signal, Slot

from iOpenPod.app.sync_plan import prepare_sync_plan
from storage import HostPath

if TYPE_CHECKING:
    from iOpenPod.app.host_media_library import HostMediaLibrary
    from iOpenPod.app.library_sync_helper import IPodMediaLibrary
    from iOpenPod.app.models.device import ActiveIPod
    from iOpenPod.app.sync_plan import SyncPlan

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SyncComparison:
    host: HostMediaLibrary
    ipod: IPodMediaLibrary
    active: ActiveIPod
    plan: SyncPlan
    refresh_paths: frozenset[HostPath]


class SyncComparisonController(QObject):
    """Deliver only the comparison for the current Sync Workspace request."""

    finished = Signal(object)
    failed = Signal(str)
    _completed = Signal(int, object, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._generation = 0
        self.busy = False
        self._completed.connect(self._finish, Qt.ConnectionType.QueuedConnection)

    def start(
        self,
        host: HostMediaLibrary,
        ipod: IPodMediaLibrary,
        active: ActiveIPod,
        *,
        file_tag_policy: str | None,
        check_host_details: bool,
    ) -> None:
        self.cancel()
        generation = self._generation
        self.busy = True

        def compare() -> None:
            try:
                plan = prepare_sync_plan(
                    host, ipod, active.library, file_tag_policy=file_tag_policy
                )
                refresh_paths = (
                    frozenset(
                        HostPath(Path(item.host_path))
                        for item in plan.items
                        if item.metadata_changed
                        and not item.host_size_changed
                        and not item.host_modified_changed
                        and item.host_path is not None
                    )
                    if check_host_details
                    else frozenset()
                )
            except Exception as error:
                logger.exception("Sync comparison failed")
                self._completed.emit(generation, None, str(error))
            else:
                self._completed.emit(
                    generation,
                    SyncComparison(host, ipod, active, plan, refresh_paths),
                    "",
                )

        self._pool.start(compare)

    def cancel(self) -> bool:
        was_busy = self.busy
        self._generation += 1
        self.busy = False
        self._pool.clear()
        return was_busy

    def shutdown(self) -> None:
        self.cancel()
        self._pool.waitForDone()

    @Slot(int, object, str)
    def _finish(self, generation: int, value: object, error: str) -> None:
        if generation != self._generation or not self.busy:
            return
        self.busy = False
        if isinstance(value, SyncComparison):
            self.finished.emit(value)
        else:
            self.failed.emit(error)
