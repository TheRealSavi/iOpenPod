"""Run game authorization, installation and removal outside the GUI thread."""

from __future__ import annotations

import logging
import threading
from time import monotonic
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot

from iOpenPod.app.core.status import StatusProgress
from iOpenPod.app.services.device_coordinator import SyncRecoveryRequiredError
from iOpenPod.app.services.game_catalog import catalog_games
from iOpenPod.app.services.game_installation import (
    GameInstallationPhase,
    GameInstallationProgress,
)
from iOpenPod.app.services.game_library import GameCatalog
from iOpenPod.app.services.game_uninstallation import (
    GameRemovalPhase,
    GameRemovalProgress,
)
from iOpenPod.app.services.games import GamesResult

if TYPE_CHECKING:
    from iOpenPod.app.core.status import ApplicationStatus
    from iOpenPod.app.device_controller import DeviceController
    from iOpenPod.app.models.device import ActiveIPod
    from iOpenPod.app.services.device_coordinator import DeviceCoordinator
    from iOpenPod.app.services.game_library import InstalledGame

_LOGGER = logging.getLogger(__name__)
_REMOVAL_STATUS = "games.uninstall"
_INSTALLATION_STATUS = "games.install"


class _Signals(QObject):
    completed = Signal(object)
    failed = Signal(object)
    finished = Signal()
    progress = Signal(object, object)


class _Work(QRunnable):
    def __init__(
        self,
        coordinator: DeviceCoordinator,
        active: ActiveIPod,
        identifiers: tuple[str, ...] = (),
        *,
        uninstall_game: InstalledGame | None = None,
    ) -> None:
        super().__init__()
        self.coordinator = coordinator
        self.active = active
        self.identifiers = identifiers
        self.uninstall_game = uninstall_game
        self.preparing_files = False
        self.cancelled = threading.Event()
        self.signals = _Signals()
        self._last_progress_stage: (
            tuple[type[GameRemovalProgress] | type[GameInstallationProgress], str, str]
            | None
        ) = None
        self._last_progress_time = 0.0

    def _operation_progress(
        self, value: GameRemovalProgress | GameInstallationProgress
    ) -> None:
        now = monotonic()
        stage = (
            type(value),
            value.phase.value,
            value.title if isinstance(value, GameInstallationProgress) else "",
        )
        if (
            stage != self._last_progress_stage
            or now - self._last_progress_time >= 0.1
            or (value.total > 0 and value.current >= value.total)
        ):
            self._last_progress_stage = stage
            self._last_progress_time = now
            self.signals.progress.emit(self, value)

    def run(self) -> None:
        try:
            result: GameCatalog | GamesResult
            if self.uninstall_game is not None:
                result = self.coordinator.uninstall_game(
                    self.active,
                    self.uninstall_game,
                    self.cancelled,
                    progress=self._operation_progress,
                )
            elif self.identifiers:
                result = self.coordinator.install_games(
                    self.active,
                    self.identifiers,
                    self.cancelled,
                    progress=self._operation_progress,
                )
            else:
                self.preparing_files = True
                self.coordinator.prepare_game_files(
                    self.active, self.cancelled, progress=self._operation_progress
                )
                self.preparing_files = False
                result = self.coordinator.install_game_authorizations(
                    self.active, self.cancelled
                )
        except Exception as error:
            self.signals.failed.emit(error)
        else:
            self.signals.completed.emit(result)
        finally:
            self.signals.finished.emit()


class _ScanSignals(QObject):
    completed = Signal(object, object)


class _ScanWork(QRunnable):
    def __init__(self, coordinator: DeviceCoordinator, active: ActiveIPod) -> None:
        super().__init__()
        self.coordinator = coordinator
        self.active = active
        self.cancelled = threading.Event()
        self.signals = _ScanSignals()

    def run(self) -> None:
        outcome: GameCatalog | Exception
        try:
            outcome = self.coordinator.load_installed_games(self.active, self.cancelled)
        except Exception as error:
            outcome = error
        self.signals.completed.emit(self, outcome)


class GamesController(QObject):
    """Reserve the Active iPod for one requested Games operation at a time."""

    changed = Signal()
    catalogRequested = Signal()

    def __init__(
        self,
        coordinator: DeviceCoordinator,
        devices: DeviceController,
        parent: QObject | None = None,
        *,
        status: ApplicationStatus,
    ) -> None:
        super().__init__(parent)
        self._coordinator = coordinator
        self._devices = devices
        self._status = status
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._job: _Work | None = None
        self._closed = False
        self._message = ""
        self._authorization_ready = False
        self._open_catalog = False
        self._scan_pool = QThreadPool(self)
        self._scan_pool.setMaxThreadCount(1)
        self._scan_job: _ScanWork | None = None
        self._loaded_for: ActiveIPod | None = None
        self._catalog = GameCatalog()
        self._catalog_error = ""
        devices.activeIPodChanged.connect(self._device_changed)
        devices.deviceWritesAllowedChanged.connect(self._availability_changed)
        self.load_games()

    @property
    def active_ipod(self) -> ActiveIPod | None:
        return self._devices.active_ipod

    def offered_games(self) -> tuple[InstalledGame, ...]:
        active = self._devices.active_ipod
        if active is None:
            raise ValueError("No Active iPod is selected.")
        return catalog_games(active.profile)

    @property
    def catalog(self) -> GameCatalog:
        return self._catalog

    @property
    def catalog_ready(self) -> bool:
        """A successful installed-game scan for the current connection is ready."""
        return (
            self._loaded_for is not None
            and self._loaded_for is self._devices.active_ipod
            and self._scan_job is None
            and not self._catalog_error
        )

    def load_games(self, *, force: bool = False) -> None:
        active = self._devices.active_ipod
        if (
            self._closed
            or active is None
            or not active.profile.capabilities.supports_games
            or self._scan_job is not None
            or (not force and self._loaded_for is active)
        ):
            return
        job = _ScanWork(self._coordinator, active)
        self._scan_job = job
        self._catalog_error = ""
        job.signals.completed.connect(
            self._games_loaded, Qt.ConnectionType.QueuedConnection
        )
        self.changed.emit()
        self._scan_pool.start(job)

    @Slot(object, object)
    def _games_loaded(self, job: object, outcome: object) -> None:
        if self._closed or job is not self._scan_job or not isinstance(job, _ScanWork):
            return
        self._scan_job = None
        if self._devices.active_ipod is not job.active:
            return
        self._loaded_for = job.active
        if isinstance(outcome, GameCatalog):
            self._catalog = outcome
        else:
            self._catalog_error = str(outcome)
            _LOGGER.warning("Installed games could not be loaded: %s", outcome)
        self.changed.emit()

    @property
    def busy(self) -> bool:
        return self._job is not None

    @property
    def installing(self) -> bool:
        return self._job is not None and bool(self._job.identifiers)

    @property
    def can_install(self) -> bool:
        return self.available and self.catalog_ready and self._authorization_ready

    @property
    def can_uninstall(self) -> bool:
        active = self._devices.active_ipod
        return (
            not self._closed
            and not self.busy
            and self.catalog_ready
            and self._devices.device_writes_allowed
            and active is not None
            and active.profile.capabilities.supports_games
        )

    def uninstall(self, game: InstalledGame) -> bool:
        """Remove a catalog item without requiring an authorization preparation."""
        active = self._devices.active_ipod
        if active is None or not self.can_uninstall or game not in self._catalog.games:
            return False
        if not self._devices.begin_exclusive_operation():
            return False
        self._start_job(_Work(self._coordinator, active, uninstall_game=game))
        return True

    def install(self, identifiers: tuple[str, ...]) -> bool:
        """Admit checked compatible games under the existing exclusive reservation."""
        active = self._devices.active_ipod
        if active is None or not self.can_install or not identifiers:
            return False
        if not self._devices.begin_exclusive_operation():
            return False
        job = _Work(self._coordinator, active, identifiers)
        self._start_job(job)
        return True

    @property
    def available(self) -> bool:
        return not self._closed and not self.busy and not self.unavailable_reason

    @property
    def unavailable_reason(self) -> str:
        active = self._devices.active_ipod
        if active is None:
            return self.tr("Select an iPod to prepare game authorization.")
        if not self._devices.device_writes_allowed:
            return self.tr("Finish the current iPod operation or recovery first.")
        return self._coordinator.games_unavailable_reason(active)

    @property
    def message(self) -> str:
        """Expose only failures; ownership preparation is otherwise silent."""
        return self._message

    @Slot()
    def start(self) -> bool:
        active = self._devices.active_ipod
        if (
            active is None
            or not self.available
            or not self._devices.begin_exclusive_operation()
        ):
            return False
        job = _Work(self._coordinator, active)
        self._authorization_ready = False
        self._start_job(job)
        return True

    def _start_job(self, job: _Work) -> None:
        self._job = job
        self._message = ""
        self._open_catalog = False
        job.signals.progress.connect(
            self._installation_progress_changed
            if job.uninstall_game is None
            else self._removal_progress_changed,
            Qt.ConnectionType.QueuedConnection,
        )
        if job.uninstall_game is None:
            self._installation_progress_changed(
                job, GameInstallationProgress(GameInstallationPhase.PREPARING)
            )
        if job.uninstall_game is not None:
            self._removal_progress_changed(
                job, GameRemovalProgress(GameRemovalPhase.PREPARING)
            )
        job.signals.completed.connect(
            self._completed, Qt.ConnectionType.QueuedConnection
        )
        job.signals.failed.connect(self._failed, Qt.ConnectionType.QueuedConnection)
        job.signals.finished.connect(self._finished, Qt.ConnectionType.QueuedConnection)
        self.changed.emit()
        self._pool.start(job)

    @Slot(object, object)
    def _removal_progress_changed(self, job: object, value: object) -> None:
        if (
            self._closed
            or job is not self._job
            or not isinstance(job, _Work)
            or job.uninstall_game is None
            or not isinstance(value, GameRemovalProgress)
            or self._devices.active_ipod is not job.active
        ):
            return
        title = job.uninstall_game.title
        match value.phase:
            case GameRemovalPhase.PREPARING:
                message = self.tr("Preparing to uninstall {title}…")
            case GameRemovalPhase.REMOVING:
                message = self.tr("Uninstalling {title}…")
            case GameRemovalPhase.VERIFYING:
                message = self.tr("Verifying removal of {title}…")
            case GameRemovalPhase.CLEANING:
                message = self.tr("Removing folders for {title}…")
            case GameRemovalPhase.FINALIZING:
                message = self.tr("Finishing uninstall of {title}…")
        self._status.show(
            _REMOVAL_STATUS,
            message.format(title=title),
            progress=StatusProgress(
                value.current, value.total, str(value.path) if value.path else ""
            ),
        )

    @Slot(object, object)
    def _installation_progress_changed(self, job: object, value: object) -> None:
        if (
            self._closed
            or job is not self._job
            or not isinstance(job, _Work)
            or job.uninstall_game is not None
            or not isinstance(value, GameInstallationProgress)
            or self._devices.active_ipod is not job.active
        ):
            return
        match value.phase:
            case GameInstallationPhase.DOWNLOADING:
                message = self.tr("Downloading game files…")
            case GameInstallationPhase.PREPARING:
                message = self.tr("Preparing games for installation…")
            case GameInstallationPhase.EXTRACTING:
                message = (
                    self.tr("Extracting {title}…").format(title=value.title)
                    if value.title
                    else self.tr("Extracting game archives…")
                )
            case GameInstallationPhase.INSTALLING:
                message = self.tr("Installing games…")
            case GameInstallationPhase.VERIFYING:
                message = (
                    self.tr("Verifying installed games…")
                    if job.identifiers
                    else self.tr("Verifying game files…")
                )
            case GameInstallationPhase.FINALIZING:
                message = (
                    self.tr("Finishing game installation…")
                    if job.identifiers
                    else self.tr("Finishing game preparation…")
                )
        self._status.show(
            _INSTALLATION_STATUS,
            message,
            progress=StatusProgress(
                value.current, value.total, str(value.path) if value.path else ""
            ),
        )

    @Slot(object)
    def _completed(self, result: object) -> None:
        if (
            self._closed
            or self._job is None
            or self._devices.active_ipod is not self._job.active
        ):
            return
        self._message = ""
        if isinstance(result, GameCatalog) and (
            self._job.identifiers or self._job.uninstall_game is not None
        ):
            # Discard a pre-install scan that might finish after publication.
            if self._scan_job is not None:
                self._scan_job.cancelled.set()
                self._scan_job = None
            self._catalog = result
            self._loaded_for = self._job.active
            self._catalog_error = ""
            return
        if not isinstance(result, GamesResult):
            return
        self._authorization_ready = True
        self._open_catalog = True
        _LOGGER.debug(
            "Game authorization completed: changed=%s added=%s replaced=%s unchanged=%s",
            result.changed,
            result.added_keys,
            result.replaced_keys,
            result.unchanged_keys,
        )

    @Slot(object)
    def _failed(self, error: object) -> None:
        if (
            self._closed
            or self._job is None
            or self._devices.active_ipod is not self._job.active
        ):
            return
        _LOGGER.error("Games operation failed: %s", error)
        if isinstance(error, SyncRecoveryRequiredError):
            self._devices.set_recovery_required(True)
            if self._job.uninstall_game is not None:
                self._message = self.tr(
                    "Game removal was interrupted. Device recovery is required before another write."
                )
            else:
                self._message = (
                    self.tr(
                        "Game installation was interrupted. Device recovery is required before another write."
                    )
                    if self.installing
                    else self.tr(
                        "Game authorization was interrupted. Device recovery is required before another write."
                    )
                )
        else:
            if self._job.preparing_files:
                self._message = self.tr(
                    "Game files could not be prepared: {detail}"
                ).format(detail=str(error))
            elif self._job.uninstall_game is not None:
                self._message = self.tr(
                    "The game could not be uninstalled: {detail}"
                ).format(detail=str(error))
            else:
                self._message = (
                    self.tr("Games could not be installed: {detail}")
                    if self.installing
                    else self.tr("Game authorization could not be saved: {detail}")
                ).format(detail=str(error))

    @Slot()
    def _finished(self) -> None:
        if self._closed or self._job is None:
            return
        open_catalog = (
            self._open_catalog and self._devices.active_ipod is self._job.active
        )
        self._open_catalog = False
        self._job = None
        self._status.clear(_REMOVAL_STATUS)
        self._status.clear(_INSTALLATION_STATUS)
        self._devices.finish_exclusive_operation()
        self.changed.emit()
        if open_catalog:
            self.catalogRequested.emit()

    @Slot(object)
    def _device_changed(self, _active: object) -> None:
        if _active is not None and (
            _active is self._loaded_for
            or (self._scan_job is not None and _active is self._scan_job.active)
        ):
            self.changed.emit()
            return
        if self._scan_job is not None:
            self._scan_job.cancelled.set()
        self._scan_job = None
        self._loaded_for = None
        self._catalog = GameCatalog()
        self._catalog_error = ""
        self._message = ""
        self._authorization_ready = False
        self._status.clear(_REMOVAL_STATUS)
        self._status.clear(_INSTALLATION_STATUS)
        if self._job is not None:
            self._job.cancelled.set()
        self.changed.emit()
        self.load_games()

    @Slot(bool)
    def _availability_changed(self, _allowed: bool) -> None:
        self.changed.emit()

    def shutdown(self) -> None:
        """Finish an in-flight Storage operation before releasing its connection."""
        self._closed = True
        self._status.clear(_REMOVAL_STATUS)
        self._status.clear(_INSTALLATION_STATUS)
        if self._scan_job is not None:
            self._scan_job.cancelled.set()
        self._scan_pool.waitForDone()
        self._scan_job = None
        if self._job is not None:
            self._job.cancelled.set()
        self._pool.waitForDone()
        if self._job is not None:
            self._job = None
            self._devices.finish_exclusive_operation()
