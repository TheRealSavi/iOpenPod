"""Application controllers that coordinate runtime services for the UI shell."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal, pyqtSlot

from .jobs import AutoRestoreDeviceWorker, QuickWriteWorker
from .services import (
    DeviceManagerLike,
    DeviceStorageSnapshot,
    LibraryCacheLike,
    is_device_info_like,
)

logger = logging.getLogger(__name__)


class StartupDeviceRestoreController(QObject):
    """Own the remembered-device restore lifecycle for the main window."""

    identification_rejected = pyqtSignal(str, object)

    def __init__(
        self,
        device_manager: DeviceManagerLike,
        remembered_path: str,
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._device_manager = device_manager
        self._remembered_path = remembered_path
        self._worker: AutoRestoreDeviceWorker | None = None
        self._cancelled = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.start)

    def start_later(self, delay_ms: int = 100) -> None:
        self._timer.start(delay_ms)

    def start(self) -> None:
        """Restore the remembered iPod after first paint without blocking startup."""

        if not self._remembered_path or self._device_manager.device_path:
            return

        self._cancelled = False
        worker = AutoRestoreDeviceWorker(self._remembered_path)
        self._worker = worker
        worker.found.connect(self._on_found)
        worker.not_found.connect(self._on_not_found)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(self._on_finished)
        worker.start()

    def cancel(self) -> None:
        """Supersede fast resume when the user explicitly opens the picker."""

        self._cancelled = True
        self._timer.stop()
        worker = self._worker
        if worker and worker.isRunning():
            worker.requestInterruption()

    def stop(self, timeout_ms: int = 3000) -> None:
        """Request shutdown and wait briefly for the restore worker to exit."""

        self.cancel()
        worker = self._worker
        if worker and worker.isRunning():
            worker.wait(timeout_ms)

    @pyqtSlot(str, object)
    def _on_found(self, path: str, ipod: object) -> None:
        if self._cancelled or self._device_manager.device_path:
            return
        if not is_device_info_like(ipod):
            logger.warning(
                "Fast resume identification returned an unexpected device payload for '%s'",
                path,
            )
            return
        from iopenpod.device import has_exact_model_number

        if not has_exact_model_number(ipod):
            logger.warning(
                "Fast resume rejected unidentified iPod at '%s': no model number",
                path,
            )
            self.identification_rejected.emit(path, ipod)
            return
        self._device_manager.discovered_ipod = ipod
        self._device_manager.device_path = path

    @pyqtSlot(str)
    def _on_not_found(self, path: str) -> None:
        if not self._cancelled:
            logger.info(
                "Fast resume skipped: remembered device is unavailable (%s)",
                path,
            )

    @pyqtSlot(str, str)
    def _on_failed(self, path: str, error: str) -> None:
        if not self._cancelled:
            logger.warning(
                "Fast resume identification failed for '%s': %s",
                path,
                error,
            )

    @pyqtSlot()
    def _on_finished(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
        self._worker = None


class StartupUpdateController(QObject):
    """Own the silent startup update-check lifecycle."""

    update_available = pyqtSignal(object)

    def __init__(
        self,
        checker_factory: Callable[[QObject | None], Any],
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._checker_factory = checker_factory
        self._checker: Any | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.start)

    def start_later(self, delay_ms: int = 2000) -> None:
        self._timer.start(delay_ms)

    def start(self) -> None:
        if self._checker is not None:
            return

        checker = self._checker_factory(self)
        self._checker = checker
        checker.result_ready.connect(self._on_result)
        checker.finished.connect(self._on_finished)
        checker.start()

    def stop(self, timeout_ms: int = 3000) -> None:
        self._timer.stop()
        checker = self._checker
        if checker is not None and checker.isRunning():
            checker.requestInterruption()
            checker.wait(timeout_ms)

    @pyqtSlot(object)
    def _on_result(self, result: object) -> None:
        error = getattr(result, "error", "")
        available = bool(getattr(result, "update_available", False))
        if error or not available:
            return
        self.update_available.emit(result)

    @pyqtSlot()
    def _on_finished(self) -> None:
        if self._checker is not None:
            self._checker.deleteLater()
        self._checker = None


class QuickWriteController(QObject):
    """Own quick metadata and playlist writes that run outside full sync."""

    save_status_changed = pyqtSignal(str)
    metadata_failed = pyqtSignal(str)
    playlist_failed = pyqtSignal(str)

    def __init__(
        self,
        device_manager: DeviceManagerLike,
        library_cache: LibraryCacheLike,
        is_sync_running: Callable[[], bool],
        parent: QObject | None = None,
    ):
        super().__init__(parent)
        self._device_manager = device_manager
        self._library_cache = library_cache
        self._is_sync_running = is_sync_running
        self._quick_worker: QThread | None = None
        self._active_write_has_track_edits = False
        self._active_write_has_playlists = False
        self._force_snapshot_write = False

        self._metadata_timer = QTimer(self)
        self._metadata_timer.setSingleShot(True)
        self._metadata_timer.setInterval(1500)
        self._metadata_timer.timeout.connect(self.start_quick_write)

        self._playlist_timer = QTimer(self)
        self._playlist_timer.setSingleShot(True)
        self._playlist_timer.setInterval(1500)
        self._playlist_timer.timeout.connect(self.start_quick_write)

    def schedule_metadata_write(self) -> None:
        if self._is_sync_running() or not self._device_manager.device_path:
            return
        self._metadata_timer.start()

    def start_metadata_write(self) -> None:
        self.start_quick_write()

    def schedule_playlist_sync(self) -> None:
        if self._is_sync_running() or not self._device_manager.device_path:
            return
        self._playlist_timer.start()

    def start_playlist_sync(self) -> None:
        self.start_quick_write()

    def start_quick_write(self) -> None:
        if self._is_sync_running():
            return
        if self._quick_worker is not None and self._quick_worker.isRunning():
            self._metadata_timer.start()
            return

        has_track_edits = self._library_cache.has_pending_track_edits()
        has_playlists = self._library_cache.has_pending_playlists()
        if not has_track_edits and not has_playlists and not self._force_snapshot_write:
            return

        ipod_path = self._device_manager.device_path
        if not ipod_path:
            return

        edits = self._library_cache.get_track_edits()
        artwork_edits = self._library_cache.get_track_artwork_edits()
        user_playlists = self._library_cache.get_user_playlists()
        if (
            not edits
            and not artwork_edits
            and not user_playlists
            and not self._force_snapshot_write
        ):
            return

        logger.info(
            "Quick write: %d track edit(s), %d artwork edit(s), %d playlist edit(s)",
            len(edits),
            len(artwork_edits),
            len(user_playlists),
        )
        self.save_status_changed.emit("saving")
        self._active_write_has_track_edits = bool(edits or artwork_edits)
        self._active_write_has_playlists = bool(user_playlists)

        device_storage = DeviceStorageSnapshot.from_device_info(
            getattr(self._device_manager, "discovered_ipod", None)
        )
        if device_storage is None:
            worker = QuickWriteWorker(
                ipod_path=ipod_path,
                cache=self._library_cache,
            )
        else:
            worker = QuickWriteWorker(
                ipod_path=ipod_path,
                cache=self._library_cache,
                device_storage=device_storage,
            )
        self._force_snapshot_write = False
        self._quick_worker = worker
        worker.completed.connect(self._on_quick_write_done)
        worker.error.connect(self._on_quick_write_error)
        worker.start()

    def prepare_for_full_sync(self, timeout_ms: int = 30000) -> tuple[bool, str | None]:
        """Finish queued quick writes before a full sync starts."""

        return self.flush_before_eject(timeout_ms)

    def flush_before_eject(self, timeout_ms: int = 30000) -> tuple[bool, str | None]:
        """Finish queued quick writes before ejecting the device."""

        self._metadata_timer.stop()
        self._playlist_timer.stop()

        had_worker = (
            self._quick_worker is not None and self._quick_worker.isRunning()
        )
        if not self._wait_for_worker(self._quick_worker, timeout_ms):
            return False, "quick changes"
        if had_worker:
            return True, None

        if (
            self._library_cache.has_pending_track_edits()
            or self._library_cache.has_pending_playlists()
        ):
            self.start_quick_write()
            if not self._wait_for_worker(self._quick_worker, timeout_ms):
                return False, "quick changes"

        return True, None

    def shutdown(self, timeout_ms: int = 3000) -> None:
        self._metadata_timer.stop()
        self._playlist_timer.stop()
        self._wait_for_worker(self._quick_worker, timeout_ms)

    @staticmethod
    def _wait_for_worker(worker: QThread | None, timeout_ms: int) -> bool:
        if worker is None or not worker.isRunning():
            return True
        return bool(worker.wait(timeout_ms))

    @pyqtSlot(object)
    def _on_quick_write_done(self, result) -> None:
        had_track_edits = self._active_write_has_track_edits
        had_playlists = self._active_write_has_playlists
        self._clear_active_write_flags()
        if self._quick_worker is not None:
            self._quick_worker.wait()
            self._quick_worker.deleteLater()
            self._quick_worker = None
        if result.success:
            logger.info("Quick write completed successfully")
            if getattr(result, "newer_changes_pending", False):
                self._force_snapshot_write = True
                self.save_status_changed.emit("saving")
                self._metadata_timer.start(0)
            else:
                self.save_status_changed.emit("saved")
        else:
            errors = "; ".join(msg for _, msg in getattr(result, "errors", []))
            if not errors:
                errors = getattr(result, "error", "") or "Database write failed"
            logger.error("Quick write failed: %s", errors)
            self.save_status_changed.emit("error")
            if had_playlists and not had_track_edits:
                self.playlist_failed.emit(errors)
            else:
                self.metadata_failed.emit(errors)

    @pyqtSlot(str)
    def _on_quick_write_error(
        self,
        error_msg: str,
    ) -> None:
        had_track_edits = self._active_write_has_track_edits
        had_playlists = self._active_write_has_playlists
        self._clear_active_write_flags()
        if self._quick_worker is not None:
            self._quick_worker.wait()
            self._quick_worker.deleteLater()
            self._quick_worker = None
        logger.error("Quick write error: %s", error_msg)
        self.save_status_changed.emit("error")
        if had_playlists and not had_track_edits:
            self.playlist_failed.emit(error_msg)
        else:
            self.metadata_failed.emit(error_msg)

    def _clear_active_write_flags(self) -> None:
        self._active_write_has_track_edits = False
        self._active_write_has_playlists = False
