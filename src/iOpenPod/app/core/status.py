"""Application-wide status messages independent of their GUI presentation."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal

_ROTATION_INTERVAL_MS = 4_000


@dataclass(frozen=True, slots=True)
class StatusMessage:
    """One active source-owned status, without presentation or timer details."""

    source: str
    message: str
    progress: StatusProgress | None = None
    action: StatusAction | None = None


@dataclass(frozen=True, slots=True)
class StatusProgress:
    """Completed work out of a total; zero total means indeterminate progress."""

    current: int = 0
    total: int = 0
    detail: str = ""

    def __post_init__(self) -> None:
        if self.current < 0 or self.total < 0:
            raise ValueError("Status progress values must not be negative")


@dataclass(frozen=True, slots=True)
class StatusAction:
    """A source-scoped action requested through ApplicationStatus."""

    key: str
    label: str

    def __post_init__(self) -> None:
        if not self.key.strip() or not self.label.strip():
            raise ValueError("A status action needs a key and label")


@dataclass(frozen=True, slots=True)
class _StatusEntry:
    message: str
    revision: int
    progress: StatusProgress | None = None
    action: StatusAction | None = None


class ApplicationStatus(QObject):
    """Retain source-owned messages and rotate the text shown in the status bar."""

    messageChanged = Signal(str)
    currentStatusChanged = Signal()
    activeMessagesChanged = Signal()
    actionRequested = Signal(str, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._default_message = ""
        self._entries: dict[str, _StatusEntry] = {}
        self._current_source: str | None = None
        self._revision = 0
        self._rotation_timer = QTimer(self)
        self._rotation_timer.setInterval(_ROTATION_INTERVAL_MS)
        self._rotation_timer.timeout.connect(self._rotate)

    @property
    def active_messages(self) -> tuple[StatusMessage, ...]:
        """Return active messages in stable arrival order, excluding the default."""

        return tuple(
            StatusMessage(source, entry.message, entry.progress, entry.action)
            for source, entry in self._entries.items()
        )

    @property
    def current_status(self) -> StatusMessage | None:
        source = self._current_source
        if source is None:
            return None
        entry = self._entries[source]
        return StatusMessage(source, entry.message, entry.progress, entry.action)

    @property
    def current_message(self) -> str:
        if self._current_source is None:
            return self._default_message
        return self._entries[self._current_source].message

    def set_default(self, message: str) -> None:
        """Set the message shown whenever no source has an active message."""

        previous = self.current_message
        previous_status = self.current_status
        self._default_message = message
        self._emit_if_changed(previous, previous_status)

    def show(
        self,
        source: str,
        message: str,
        *,
        progress: StatusProgress | None = None,
        action: StatusAction | None = None,
        timeout_ms: int = 0,
    ) -> None:
        """Add or update a source, optionally until its own timeout expires.

        New sources appear immediately. Updating an existing source preserves the
        rotation position and cadence so frequent progress cannot starve peers.
        """

        if not source.strip():
            raise ValueError("A status source must not be empty")
        if not message:
            raise ValueError("A status message must not be empty")
        if timeout_ms < 0:
            raise ValueError("A status timeout must not be negative")
        previous = self.current_message
        previous_status = self.current_status
        existing = self._entries.get(source)
        self._revision += 1
        revision = self._revision
        self._entries[source] = _StatusEntry(message, revision, progress, action)
        if existing is None:
            self._current_source = source
        self._sync_rotation()
        self._emit_if_changed(previous, previous_status)
        if (
            existing is None
            or existing.message != message
            or existing.progress != progress
            or existing.action != action
        ):
            self.activeMessagesChanged.emit()
        if timeout_ms:
            QTimer.singleShot(
                timeout_ms,
                self,
                lambda: self._clear_revision(source, revision),
            )

    def clear(self, source: str) -> None:
        """Clear one source, advancing if it was visible, or restore the default."""

        if source not in self._entries:
            return
        previous = self.current_message
        previous_status = self.current_status
        sources = tuple(self._entries)
        index = sources.index(source)
        del self._entries[source]
        if source == self._current_source:
            remaining = tuple(self._entries)
            self._current_source = (
                remaining[index % len(remaining)] if remaining else None
            )
        self._sync_rotation()
        self._emit_if_changed(previous, previous_status)
        self.activeMessagesChanged.emit()

    def request_action(self, source: str, key: str) -> None:
        """Request an action only while that source still offers it."""
        entry = self._entries.get(source)
        if entry is not None and entry.action is not None and entry.action.key == key:
            self.actionRequested.emit(source, key)

    def _sync_rotation(self) -> None:
        if len(self._entries) < 2:
            self._rotation_timer.stop()
        elif not self._rotation_timer.isActive():
            self._rotation_timer.start()

    def _rotate(self) -> None:
        sources = tuple(self._entries)
        if len(sources) < 2 or self._current_source is None:
            return
        previous = self.current_message
        previous_status = self.current_status
        index = sources.index(self._current_source)
        self._current_source = sources[(index + 1) % len(sources)]
        self._emit_if_changed(previous, previous_status)

    def _clear_revision(self, source: str, revision: int) -> None:
        entry = self._entries.get(source)
        if entry is not None and entry.revision == revision:
            self.clear(source)

    def _emit_if_changed(
        self, previous: str, previous_status: StatusMessage | None
    ) -> None:
        current = self.current_message
        if current != previous:
            self.messageChanged.emit(current)
        if self.current_status != previous_status:
            self.currentStatusChanged.emit()


__all__ = ["ApplicationStatus", "StatusAction", "StatusMessage", "StatusProgress"]
