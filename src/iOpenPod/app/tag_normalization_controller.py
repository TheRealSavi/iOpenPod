"""Cancellable normalization scans bound to one unchanged workspace revision."""

import logging
from threading import Event

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QTimer, Signal, Slot

from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.tag_normalizer import TagProfile, TagSuggestion, normalize_tags
from iPodDB.library import Track

logger = logging.getLogger(__name__)


class _ScanCancelledError(Exception):
    pass


class _Signals(QObject):
    completed = Signal(int, object, str)


class _Scan(QRunnable):
    def __init__(
        self, token: int, tracks: tuple[Track, ...], profile: TagProfile
    ) -> None:
        super().__init__()
        self.token, self.tracks, self.profile = token, tracks, profile
        self.cancelled = Event()
        self.signals = _Signals()

    def run(self) -> None:
        def checkpoint() -> None:
            if self.cancelled.is_set():
                raise _ScanCancelledError

        try:
            result = normalize_tags(self.tracks, self.profile, checkpoint=checkpoint)
        except _ScanCancelledError:
            self.signals.completed.emit(self.token, None, "")
        except Exception:
            logger.exception("Unexpected tag normalization failure")
            self.signals.completed.emit(
                self.token,
                None,
                "Scanning failed unexpectedly. Details are in the application log.",
            )
        else:
            self.signals.completed.emit(self.token, result, "")


class TagNormalizationController(QObject):
    changed = Signal()

    def __init__(
        self, workspace: LibraryWorkspace, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self.workspace = workspace
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._jobs: dict[int, _Scan] = {}
        self._token = 0
        self._revision = workspace.edit_revision
        self._closed = False
        self._profile: TagProfile | None = None
        self._monitor_profile: TagProfile | None = None
        self._rescan_timer = QTimer(self)
        self._rescan_timer.setSingleShot(True)
        self._rescan_timer.setInterval(250)
        self._rescan_timer.timeout.connect(self._rescan)
        self.scanning = False
        self.failed = False
        self.suggestion: TagSuggestion | None = None
        self.tracks: tuple[Track, ...] = ()
        self.message = ""
        workspace.changed.connect(self._invalidate)

    @property
    def monitoring(self) -> bool:
        return self._monitor_profile is not None

    @property
    def pending_count(self) -> int:
        """Count proposed field edits, never Tracks or already-applied edits."""
        return self.suggestion.field_count if self.suggestion is not None else 0

    def monitor(self, profile: TagProfile | None) -> None:
        """Keep one shared preview current for the Active iPod and its Sidebar."""
        if self._monitor_profile == profile:
            return
        self._monitor_profile = profile
        self.cancel()
        self._schedule_rescan()

    def ensure_scan(self, profile: TagProfile) -> None:
        """Reuse the background result when opening an unchanged preview."""
        if (
            self._profile == profile
            and self._revision == self.workspace.edit_revision
            and not self.workspace.locked
            and (self.scanning or self.suggestion is not None)
        ):
            return
        self.start(profile)

    def start(self, profile: TagProfile) -> None:
        if self._closed:
            return
        self.cancel()
        self.workspace.require_revision(self.workspace.edit_revision)
        self._revision = self.workspace.edit_revision
        self._profile = profile
        self.tracks = self.workspace.tracks
        self.scanning = True
        self.failed = False
        self.message = "Scanning the Library…"
        job = _Scan(self._token, self.tracks, profile)
        self._jobs[self._token] = job
        job.signals.completed.connect(
            self._completed, Qt.ConnectionType.QueuedConnection
        )
        self._pool.start(job)
        self.changed.emit()

    def cancel(self) -> None:
        self._rescan_timer.stop()
        self._token += 1
        for job in self._jobs.values():
            job.cancelled.set()
        self.suggestion = None
        self.scanning = False
        self.failed = False
        self.message = "Scan cancelled."
        self.changed.emit()

    def _invalidate(self) -> None:
        if self._revision != self.workspace.edit_revision or self.workspace.locked:
            self.cancel()
            self.message = (
                "The Library changed. Scan again before applying suggestions."
            )
            self.changed.emit()
        self._schedule_rescan()

    def _schedule_rescan(self) -> None:
        if (
            not self._closed
            and self.monitoring
            and self.workspace.snapshot is not None
            and not self.workspace.locked
            and not self.scanning
            and self.suggestion is None
        ):
            self._rescan_timer.start()

    def _rescan(self) -> None:
        profile = self._monitor_profile
        if (
            profile is not None
            and self.workspace.snapshot is not None
            and not self.workspace.locked
        ):
            self.start(profile)

    @Slot(int, object, str)
    def _completed(self, token: int, value: object, error: str) -> None:
        self._jobs.pop(token, None)
        if (
            token != self._token
            or self._closed
            or self._revision != self.workspace.edit_revision
        ):
            return
        self.scanning = False
        self.failed = bool(error)
        self.suggestion = value if isinstance(value, TagSuggestion) else None
        self.message = error or (
            "No tag changes are needed."
            if self.suggestion is not None and not self.suggestion.updates
            else "Review the suggested changes before applying them."
        )
        self.changed.emit()

    def apply(self) -> None:
        suggestion = self.suggestion
        if suggestion is None:
            raise ValueError("Scan the Library before applying suggestions.")
        self.workspace.apply_track_edits(suggestion.updates, self._revision)
        self.suggestion = None
        self.message = "Normalization applied."
        self.changed.emit()

    def shutdown(self) -> None:
        self._closed = True
        self.cancel()
        self._pool.waitForDone()
