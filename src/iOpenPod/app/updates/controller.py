"""One application update workflow publishes source-owned status and actions."""

from __future__ import annotations

import logging
from time import monotonic
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer, Signal

from iOpenPod.app.core.status import ApplicationStatus, StatusAction, StatusProgress

from .backend import (
    InstallChannel,
    UpdateOutcome,
    UpdateProgress,
    UpdateProvider,
    UpdateResult,
)

logger = logging.getLogger(__name__)
UPDATE_STATUS_SOURCE = "application-update"


class UpdateController(QObject):
    """Native calls and poll continuations all execute on this object's GUI thread."""

    changed = Signal()
    restartRequested = Signal(bool)
    releasePageRequested = Signal(str)

    def __init__(
        self,
        status: ApplicationStatus,
        provider: Callable[[], UpdateProvider],
        prepare_install: Callable[[], str],
        finish_install: Callable[[], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._status = status
        self._factory = provider
        self._provider: UpdateProvider | None = None
        self._channel = InstallChannel.UNKNOWN
        self._message = ""
        self._prepare = prepare_install
        self._finish = finish_install
        self._closed = False
        self._started = False
        self._busy = False
        self._install_requested = False
        self._guarded = False
        self._available = False
        self._ready = False
        self._handoff = False
        self._downloading = False
        self._release_url = ""
        self._check_started = 0.0
        self._retry_after = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._poll)
        status.actionRequested.connect(self._action)

    @property
    def channel(self) -> InstallChannel:
        return self._channel

    @property
    def busy(self) -> bool:
        return self._busy

    @property
    def message(self) -> str:
        return self._message

    @property
    def installing(self) -> bool:
        return self._guarded

    @property
    def handing_off(self) -> bool:
        return self._handoff

    @property
    def _channel_name(self) -> str:
        return (
            self._provider.display_name
            if self._provider
            else self.tr("installation source")
        )

    def start(self) -> None:
        """Make one automatic check after a native owner window exists."""
        if self._started or self._closed:
            return
        self._started = True
        self._check()

    def check_now(self) -> None:
        """A user-requested check shares startup's duplicate and retry guards."""
        if self._closed or self._busy or monotonic() < self._retry_after:
            return
        self._started = True
        self._check(manual=True)

    def _show(
        self,
        message: str,
        *,
        progress: StatusProgress | None = None,
        action: StatusAction | None = None,
        timeout_ms: int = 0,
    ) -> None:
        self._message = message
        self._status.show(
            UPDATE_STATUS_SOURCE,
            message,
            progress=progress,
            action=action,
            timeout_ms=timeout_ms,
        )
        self.changed.emit()

    def _update_action(self) -> StatusAction:
        if self._ready:
            return StatusAction("restart", self.tr("Restart to install"))
        return StatusAction("install", self.tr("Update now"))

    def _check(self, *, manual: bool = False) -> None:
        if self._closed or self._busy:
            return
        self._busy = True
        self._check_started = monotonic()
        self._show(
            self.tr("Checking for application updates…"), progress=StatusProgress()
        )
        try:
            if self._provider is None:
                self._provider = self._factory()
                self._channel = self._provider.channel
            if self._provider.backend is None:
                self._busy = False
                if manual:
                    self._show(
                        self.tr(
                            "Update checks are not available for this installation. "
                            "Use its software manager or original download source."
                        )
                    )
                else:
                    self._status.clear(UPDATE_STATUS_SOURCE)
                    self._message = ""
                    self.changed.emit()
                return
            self._provider.backend.check()
            self._show(
                self.tr("Checking %1 for updates…").replace("%1", self._channel_name),
                progress=StatusProgress(),
            )
            self._timer.start()
        except Exception as error:
            self._failed(error)

    def _action(self, source: str, key: str) -> None:
        if source != UPDATE_STATUS_SOURCE or self._closed:
            return
        if key == "cancel-download" and self._downloading:
            self._timer.stop()
            self._busy = False
            self._downloading = False
            self._available = False
            self._close_backend()
            self._show(
                self.tr("%1 update canceled").replace("%1", "GitHub"),
                action=StatusAction("retry", self.tr("Retry check")),
            )
            return
        if self._busy:
            return
        if key != "release" and monotonic() < self._retry_after:
            return
        if key == "retry":
            self.check_now()
        elif key == "release" and self._release_url:
            self.releasePageRequested.emit(self._release_url)
        elif key == "restart" and self._ready:
            try:
                self._begin_install()
            except Exception as error:
                self._failed(error)
        elif key == "install" and self._available:
            # Requery before locking the application, then validate the guard
            # against current work, not the work that existed when clicked.
            self._install_requested = True
            self._check()

    def _poll(self) -> None:
        if self._closed or self._provider is None or self._provider.backend is None:
            return
        try:
            event = self._provider.backend.poll()
            if isinstance(event, UpdateProgress):
                verb = (
                    self.tr("Installing")
                    if event.installing
                    else self.tr("Downloading / awaiting installation")
                )
                self._show(
                    self.tr("%1: %2 (current package)…")
                    .replace("%1", self._channel_name)
                    .replace("%2", verb),
                    progress=StatusProgress(
                        round(event.fraction * 100),
                        100,
                        self.tr("Package: %1").replace("%1", event.package),
                    ),
                    action=StatusAction("cancel-download", self.tr("Cancel download"))
                    if self._downloading
                    else None,
                )
            elif isinstance(event, UpdateResult):
                self._completed(event)
            elif (
                not self._guarded
                and not self._downloading
                and monotonic() - self._check_started > 60
            ):
                raise TimeoutError("Application update check timed out")
        except Exception as error:
            self._failed(error)

    def _completed(self, result: UpdateResult) -> None:
        self._timer.stop()
        self._busy = False
        if result.outcome is UpdateOutcome.READY:
            self._downloading = False
            self._ready = True
            self._show(
                self.tr("Update downloaded and verified"), action=self._update_action()
            )
            return
        if result.outcome is UpdateOutcome.HANDOFF:
            if (
                not self._guarded
                or self._provider is None
                or self._provider.backend is None
            ):
                raise RuntimeError("Installer requested an unguarded restart")
            self._handoff = True
            self._busy = True
            self._provider.backend.complete_handoff()
            self.restartRequested.emit(self._provider.native_restart)
            return
        if result.outcome is UpdateOutcome.AVAILABLE:
            self._available = True
            self._ready = False
            if self._install_requested:
                self._install_requested = False
                assert self._provider is not None and self._provider.backend is not None
                if self._provider.staged_download:
                    self._downloading = True
                    self._busy = True
                    self._show(
                        self.tr("Downloading and verifying update…"),
                        progress=StatusProgress(),
                        action=StatusAction(
                            "cancel-download", self.tr("Cancel download")
                        ),
                    )
                    self._provider.backend.download()
                    self._timer.start()
                else:
                    self._begin_install()
                return
            self._show(
                self.tr("%1 update available").replace("%1", self._channel_name),
                action=self._update_action(),
            )
            return
        self._install_requested = False
        self._downloading = False
        self._release_guard()
        if result.outcome is UpdateOutcome.MANUAL:
            self._available = False
            self._ready = False
            self._release_url = result.url
            self._show(
                result.detail,
                action=StatusAction("release", self.tr("Open download page")),
            )
        elif result.outcome is UpdateOutcome.CURRENT:
            self._available = False
            self._show(
                self.tr("%1 reports no updates (results may be cached)").replace(
                    "%1", self._channel_name
                ),
                timeout_ms=8_000,
            )
        elif result.outcome is UpdateOutcome.COMPLETED:
            self._available = False
            self._show(
                self.tr(
                    "%1 update completed. Restart iOpenPod to use the installed version."
                ).replace("%1", self._channel_name)
            )
        elif result.outcome is UpdateOutcome.CANCELED:
            self._ready = False
            self._show(
                self.tr("%1 update canceled").replace("%1", self._channel_name),
                action=self._update_action()
                if self._available
                else StatusAction("retry", self.tr("Retry check")),
            )
        else:
            self._ready = False
            self._retry_after = monotonic() + 30
            self._show(
                self.tr("%1 update failed: %2")
                .replace("%1", self._channel_name)
                .replace("%2", result.detail),
                action=self._update_action()
                if self._available
                else StatusAction("retry", self.tr("Retry check")),
            )

    def _begin_install(self) -> None:
        reason = self._prepare()
        if reason:
            self._show(reason, action=self._update_action())
            return
        self._guarded = True
        self._busy = True
        self._show(self.tr("Preparing application update…"), progress=StatusProgress())
        assert self._provider is not None and self._provider.backend is not None
        self._provider.backend.install()
        self._timer.start()

    def _release_guard(self) -> None:
        if self._guarded:
            self._guarded = False
            self._finish()

    def _failed(self, error: Exception) -> None:
        logger.exception("Application update operation failed")
        self._timer.stop()
        self._busy = False
        self._install_requested = False
        self._available = False
        self._ready = False
        self._handoff = False
        self._downloading = False
        self._close_backend()
        self._release_guard()
        self._retry_after = monotonic() + 30
        code = getattr(error, "winerror", None)
        detail = str(error)
        if isinstance(code, int):
            detail += f" (0x{code & 0xFFFFFFFF:08X})"
        self._show(
            self.tr(
                "Update check or installation unavailable: %1. Retry in 30 seconds."
            ).replace("%1", detail),
            action=StatusAction("retry", self.tr("Retry check")),
        )

    def _close_backend(self) -> None:
        provider, self._provider = self._provider, None
        if provider is not None and provider.backend is not None:
            try:
                provider.backend.close()
            except Exception:
                logger.exception("Could not close the update provider")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._timer.stop()
        self._close_backend()
        self._release_guard()
        self._status.clear(UPDATE_STATUS_SOURCE)
