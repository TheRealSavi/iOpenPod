"""Run Jellyfin sign-in and play count sync outside the Qt GUI thread."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from threading import Event
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal

from storage import Storage

from .client import JellyfinClient
from .models import JellyfinError, PlayCountResult
from .service import PlayCountService
from .settings import JELLYFIN_DEVICE_ID, JELLYFIN_SERVER_URL, JELLYFIN_USERNAME
from .state import PlayCountStore
from .token_store import SystemTokenStore

if TYPE_CHECKING:
    from collections.abc import Callable

    from iOpenPod.app.core.settings.service import SettingsService
    from iOpenPod.app.device_controller import DeviceController

    from .service import PlayCountSource
    from .token_store import TokenStore


@dataclass(frozen=True, slots=True)
class _AccountChange:
    server_url: str
    username: str
    device_id: str = ""


class _Signals(QObject):
    completed = Signal(object, str)
    progress = Signal(str)


class _Work(QRunnable):
    def __init__(self, action: Callable[[], object]) -> None:
        super().__init__()
        self.action = action
        self.signals = _Signals()

    def run(self) -> None:
        try:
            result = self.action()
        except JellyfinError as error:
            self.signals.completed.emit(None, str(error))
        except Exception:
            # Never log request objects, tokens, or untrusted response bodies.
            self.signals.completed.emit(
                None,
                "Play count sync stopped. Check the iPod connection and Host storage, then retry.",
            )
        else:
            self.signals.completed.emit(result, "")


class JellyfinController(QObject):
    changed = Signal()
    message = Signal(str)
    finished = Signal(object)

    def __init__(
        self,
        service: PlayCountService,
        tokens: TokenStore,
        settings: SettingsService,
        devices: DeviceController,
        library_dirty: Callable[[], bool],
        parent: QObject | None = None,
        *,
        client: JellyfinClient | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._tokens = tokens
        self._settings = settings
        self._devices = devices
        self._library_dirty = library_dirty
        self._client = client or JellyfinClient()
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._job: _Work | None = None
        self._cancelled = Event()
        self._reserved = False
        self._closed = False
        self._last_result: PlayCountResult | None = None
        devices.busyChanged.connect(self._availability_changed)
        devices.activeIPodChanged.connect(self._availability_changed)
        devices.deviceWritesAllowedChanged.connect(self._availability_changed)

    def _availability_changed(self) -> None:
        self.changed.emit()

    @property
    def busy(self) -> bool:
        return self._job is not None

    @property
    def syncing(self) -> bool:
        return self.busy and self._reserved

    @property
    def last_result(self) -> PlayCountResult | None:
        return self._last_result

    @property
    def connected(self) -> bool:
        return bool(self._settings.get(JELLYFIN_USERNAME))

    @property
    def available(self) -> bool:
        return not self._closed and not self.busy and not self._devices.busy

    @property
    def can_sync(self) -> bool:
        return (
            self.available
            and self.connected
            and self._devices.device_writes_allowed
            and self._devices.active_ipod is not None
        )

    def _start(self, action: Callable[[], object]) -> None:
        job = _Work(action)
        self._job = job
        job.signals.completed.connect(
            self._completed, Qt.ConnectionType.QueuedConnection
        )
        job.signals.progress.connect(
            self.message.emit, Qt.ConnectionType.QueuedConnection
        )
        self.changed.emit()
        self._pool.start(job)

    def connect_account(self, server_url: str, username: str, password: str) -> None:
        if not self.available:
            return
        if not server_url.strip() or not username.strip() or not password:
            self.message.emit(
                self.tr("Enter the Jellyfin server address, username, and password.")
            )
            return
        device_id = self._settings.get(JELLYFIN_DEVICE_ID) or uuid.uuid4().hex
        name = username.strip()

        def connect() -> _AccountChange:
            account = self._client.connect(server_url, name, password, device_id)
            self._tokens.save(account)
            return _AccountChange(account.server_url, account.username, device_id)

        self._start(connect)

    def disconnect_account(self) -> None:
        if not self.available:
            return

        def disconnect() -> _AccountChange:
            self._tokens.remove()
            return _AccountChange("", "")

        self._start(disconnect)

    def sync_now(self) -> bool:
        active = self._devices.active_ipod
        if not self.connected:
            self.message.emit(self.tr("Connect Jellyfin in Settings → Sync first."))
            return False
        if self._library_dirty():
            self.message.emit(
                self.tr(
                    "Save or discard your Library changes before syncing play counts."
                )
            )
            return False
        if not self.can_sync or active is None:
            return False
        if not self._devices.begin_library_save():
            return False
        self._reserved = True
        self._cancelled.clear()

        def sync() -> PlayCountResult:
            assert self._job is not None
            return self._service.run(
                active, self._cancelled, self._job.signals.progress.emit
            )

        self._start(sync)
        return True

    def cancel(self) -> None:
        self._cancelled.set()

    def _completed(self, result: object, error: str) -> None:
        self._job = None
        if self._reserved:
            self._reserved = False
            # Publish a saved Library before releasing the device reservation.
            self._devices.finish_library_save(
                result.active if isinstance(result, PlayCountResult) else None
            )
        if self._closed:
            return
        if error:
            self.message.emit(error)
        elif isinstance(result, _AccountChange):
            try:
                if result.device_id:
                    self._settings.set_global(JELLYFIN_DEVICE_ID, result.device_id)
                if result.server_url:
                    self._settings.set_global(JELLYFIN_SERVER_URL, result.server_url)
                self._settings.set_global(JELLYFIN_USERNAME, result.username)
            except Exception:
                self.message.emit(
                    self.tr(
                        "Could not save the Jellyfin preference. Check Host storage and reconnect."
                    )
                )
            else:
                self.message.emit(
                    self.tr("Connected to Jellyfin as {username}.").format(
                        username=result.username
                    )
                    if result.username
                    else self.tr("Disconnected from Jellyfin.")
                )
        elif isinstance(result, PlayCountResult):
            self._last_result = result
            notices = (
                (self.tr("Play count sync cancelled."),) if result.cancelled else ()
            )
            self.message.emit(" ".join((*notices, result.summary)))
            self.finished.emit(result)
        self.changed.emit()

    def shutdown(self) -> None:
        self._closed = True
        self._cancelled.set()
        self._pool.waitForDone()
        if self._reserved:
            self._reserved = False
            self._devices.finish_library_save(None)
        self._job = None


def create_jellyfin(
    coordinator: PlayCountSource,
    settings: SettingsService,
    devices: DeviceController,
    library_dirty: Callable[[], bool],
    parent: QObject | None = None,
) -> JellyfinController:
    """Compose production Host persistence and vault access in the Application Layer."""
    tokens = SystemTokenStore()
    service = PlayCountService(
        coordinator,
        tokens,
        # Earlier versions kept the memory on the Host; it seeds the iPod memory.
        legacy=PlayCountStore(
            Storage().host_config_file("iOpenPod", "jellyfin-play-counts-v1.json")
        ),
    )
    return JellyfinController(service, tokens, settings, devices, library_dirty, parent)
