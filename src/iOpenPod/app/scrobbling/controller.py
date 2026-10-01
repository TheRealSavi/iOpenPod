"""Run authorization and manual scrobbling outside the Qt GUI thread."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal

from storage import Storage

from .clients import LastFmClient, ListenBrainzClient
from .credentials import SystemCredentialStore
from .models import ScrobbleError, ScrobbleResult, Service
from .queue import ScrobbleQueue
from .service import ScrobbleService
from .settings import account_setting, configured_accounts

if TYPE_CHECKING:
    from collections.abc import Callable

    from iOpenPod.app.core.settings.service import SettingsService
    from iOpenPod.app.device_controller import DeviceController
    from iOpenPod.app.services.device_coordinator import DeviceCoordinator

    from .credentials import CredentialStore


@dataclass(frozen=True, slots=True)
class _Authorization:
    token: str = field(repr=False)
    api_key: str = field(repr=False)
    secret: str = field(repr=False)
    url: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class _AccountChange:
    service: Service
    username: str


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
        except ScrobbleError as error:
            self.signals.completed.emit(None, str(error))
        except Exception:
            # Never log request objects, secrets, or untrusted response bodies.
            self.signals.completed.emit(
                None,
                "Scrobbling stopped. Check the iPod connection and Host storage, then retry; saved pending listens were retained.",
            )
        else:
            self.signals.completed.emit(result, "")


class ScrobbleController(QObject):
    changed = Signal()
    message = Signal(str)
    authorizationRequested = Signal(str)
    finished = Signal(object)

    def __init__(
        self,
        service: ScrobbleService,
        credentials: CredentialStore,
        settings: SettingsService,
        devices: DeviceController,
        parent: QObject | None = None,
        *,
        lastfm: LastFmClient | None = None,
        listenbrainz: ListenBrainzClient | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._credentials = credentials
        self._settings = settings
        self._devices = devices
        self._lastfm = lastfm or LastFmClient()
        self._listenbrainz = listenbrainz or ListenBrainzClient()
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._job: _Work | None = None
        self._authorization: _Authorization | None = None
        self._cancelled = Event()
        self._reserved = False
        self._closed = False
        self._last_result: ScrobbleResult | None = None
        devices.busyChanged.connect(self._availability_changed)
        devices.activeIPodChanged.connect(self._availability_changed)

    def _availability_changed(self) -> None:
        self.changed.emit()

    @property
    def busy(self) -> bool:
        return self._job is not None

    @property
    def last_result(self) -> ScrobbleResult | None:
        return self._last_result

    @property
    def available(self) -> bool:
        return not self._closed and not self.busy and not self._devices.busy

    @property
    def submitting(self) -> bool:
        return self.busy and self._reserved

    @property
    def awaiting_authorization(self) -> bool:
        return self._authorization is not None

    @property
    def can_scrobble(self) -> bool:
        return self.available and self._devices.active_ipod is not None

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

    def begin_lastfm(self, api_key: str, secret: str) -> None:
        if not self.available:
            return
        if not api_key.strip() or not secret.strip():
            self.message.emit(
                self.tr("Enter your Last.fm application API key and shared secret.")
            )
            return
        self._authorization = None
        key, shared = api_key.strip(), secret.strip()

        def authorize() -> _Authorization:
            token, url = self._lastfm.begin_auth(key, shared)
            return _Authorization(token, key, shared, url)

        self._start(authorize)

    def finish_lastfm(self) -> None:
        pending = self._authorization
        if not self.available or pending is None:
            return

        def finish() -> _AccountChange:
            credentials = self._lastfm.finish_auth(
                pending.api_key, pending.secret, pending.token
            )
            self._credentials.save(Service.LASTFM, credentials)
            return _AccountChange(Service.LASTFM, credentials.username)

        self._start(finish)

    def connect_listenbrainz(self, token: str) -> None:
        if not self.available:
            return
        value = token.strip()
        if not value or any(character.isspace() for character in value):
            self.message.emit(self.tr("Enter your ListenBrainz user token."))
            return

        def connect() -> _AccountChange:
            credentials = self._listenbrainz.validate_token(value)
            self._credentials.save(Service.LISTENBRAINZ, credentials)
            return _AccountChange(Service.LISTENBRAINZ, credentials.username)

        self._start(connect)

    def disconnect_service(self, service: Service) -> None:
        if not self.available:
            return

        def disconnect() -> _AccountChange:
            self._credentials.remove(service)
            return _AccountChange(service, "")

        self._start(disconnect)

    def scrobble_now(self) -> bool:
        active = self._devices.active_ipod
        if not self.can_scrobble or active is None:
            return False
        accounts = configured_accounts(self._settings)
        if not accounts:
            self.message.emit(
                self.tr(
                    "Connect Last.fm or ListenBrainz in Settings → Sync to scrobble."
                )
            )
            return False
        if not self._devices.begin_read_only_operation():
            return False
        self._reserved = True
        self._cancelled.clear()

        def submit() -> ScrobbleResult:
            assert self._job is not None
            return self._service.run(
                active, accounts, self._cancelled, self._job.signals.progress.emit
            )

        self._start(submit)
        return True

    def cancel(self) -> None:
        self._cancelled.set()

    def _completed(self, result: object, error: str) -> None:
        self._job = None
        if self._reserved:
            self._reserved = False
            self._devices.finish_read_only_operation()
        if self._closed:
            return
        if error:
            self.message.emit(error)
        elif isinstance(result, _Authorization):
            self._authorization = result
            self.message.emit(
                self.tr(
                    "Authorize iOpenPod in your browser, then click Finish signing in."
                )
            )
            self.authorizationRequested.emit(result.url)
        elif isinstance(result, _AccountChange):
            try:
                self._settings.set_global(
                    account_setting(result.service), result.username
                )
            except Exception:
                self.message.emit(
                    self.tr(
                        "Could not save the account preference. Check Host storage and reconnect the service."
                    )
                )
            else:
                if result.service is Service.LASTFM:
                    self._authorization = None
                self.message.emit(
                    self.tr("Connected to {service} as {username}.").format(
                        service=result.service.label, username=result.username
                    )
                    if result.username
                    else self.tr("Disconnected from {service}.").format(
                        service=result.service.label
                    )
                )
        elif isinstance(result, ScrobbleResult):
            self._last_result = result
            notices = (
                (self.tr("Scrobbling cancelled. Pending listens are saved."),)
                if result.cancelled
                else ()
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
            self._devices.finish_read_only_operation()
        self._authorization = None
        self._job = None


def create_scrobbling(
    coordinator: DeviceCoordinator,
    settings: SettingsService,
    devices: DeviceController,
    parent: QObject | None = None,
) -> tuple[ScrobbleService, ScrobbleController]:
    """Compose production Host persistence and vault access in the Application Layer."""
    credentials = SystemCredentialStore()
    service = ScrobbleService(
        coordinator,
        ScrobbleQueue(Storage().host_config_file("iOpenPod", "scrobbles-v2.json")),
        credentials,
    )
    return service, ScrobbleController(service, credentials, settings, devices, parent)
