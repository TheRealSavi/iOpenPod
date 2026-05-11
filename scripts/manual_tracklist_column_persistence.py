from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from PyQt6.QtCore import QEvent, Qt, QTimer
from PyQt6.QtGui import QFont, QMouseEvent
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app_core.context import RuntimeSettingsService
from app_core.services import (
    DeviceCapabilitySnapshot,
    DeviceIdentitySnapshot,
    DeviceManagerLike,
    DeviceSession,
)
from GUI.styles import FONT_FAMILY, Metrics
from GUI.widgets.browserChrome import chrome_action_btn_css
from GUI.widgets.formatters import format_duration_mmss
from GUI.widgets.MBListView import MusicBrowserList
from infrastructure.settings_paths import get_settings_path
from infrastructure.settings_runtime import SettingsRuntime

_HARNESS_BG = "#f4f1ea"
_HARNESS_PANEL = "#fffaf0"
_HARNESS_TEXT = "#1f1a14"
_HARNESS_TEXT_MUTED = "#5c5146"
_HARNESS_BORDER = "#cdbfae"


@dataclass
class _CancellationToken:
    def is_cancelled(self) -> bool:
        return False


class _DeviceManager:
    device_changed = None
    device_settings_loaded = None
    device_settings_failed = None

    def __init__(self) -> None:
        self.cancellation_token = _CancellationToken()
        self._device_path: str | None = None
        self._discovered_ipod: object | None = None
        self._device_settings_loading = False
        self._itunesdb_path: str | None = None
        self._artworkdb_path: str | None = None
        self._artwork_folder_path: str | None = None

    @property
    def device_path(self) -> str | None:
        return self._device_path

    @device_path.setter
    def device_path(self, path: str | None) -> None:
        self._device_path = path

    @property
    def discovered_ipod(self) -> object | None:
        return self._discovered_ipod

    @discovered_ipod.setter
    def discovered_ipod(self, ipod: object | None) -> None:
        self._discovered_ipod = ipod

    @property
    def device_settings_loading(self) -> bool:
        return self._device_settings_loading

    @property
    def itunesdb_path(self) -> str | None:
        return self._itunesdb_path

    @property
    def artworkdb_path(self) -> str | None:
        return self._artworkdb_path

    @property
    def artwork_folder_path(self) -> str | None:
        return self._artwork_folder_path

    def is_valid_ipod_root(self, path: str) -> bool:
        return True

    def cancel_all_operations(self) -> None:
        return None


@dataclass
class _Session:
    device_path: str | None = None
    itunesdb_path: str | None = None
    artworkdb_path: str | None = None
    artwork_folder_path: str | None = None
    device_settings_loading: bool = False
    discovered_ipod: object | None = None
    identity: DeviceIdentitySnapshot | None = None
    capabilities: DeviceCapabilitySnapshot | None = None

    @property
    def has_device(self) -> bool:
        return bool(self.device_path)


class _DeviceSessions:
    def __init__(self) -> None:
        self._manager = _DeviceManager()

    def current_session(self) -> DeviceSession:
        return cast(DeviceSession, _Session())

    def manager(self) -> DeviceManagerLike:
        return cast(DeviceManagerLike, self._manager)


def _sample_tracks() -> list[dict[str, object]]:
    tracks: list[dict[str, object]] = []
    for index in range(1, 16):
        minutes = 3 + (index % 4)
        seconds = (index * 11) % 60
        tracks.append(
            {
                "Title": f"Track {index:02d}",
                "Artist": f"Artist {((index - 1) % 4) + 1}",
                "Album": f"Album {((index - 1) % 3) + 1}",
                "Genre": ("Rock", "Jazz", "Pop")[index % 3],
                "year": 2000 + (index % 8),
                "track_number": index,
                "length": ((minutes * 60) + seconds) * 1000,
                "rating": ((index % 5) + 1) * 20,
                "play_count_1": index * 3,
                "date_added": 1710000000 + (index * 12345),
            }
        )
    return tracks


class ManualTracklistPersistenceHarness(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._settings_service = RuntimeSettingsService(runtime=SettingsRuntime())
        self._device_sessions = _DeviceSessions()
        self._settings_path = Path(get_settings_path())
        self._last_settings_mtime_ns: int | None = None
        self._last_preview_text = ""
        self._last_flushed_header_signature: tuple[tuple[str, ...], tuple[tuple[str, int], ...]] | None = None
        self._pending_auto_flush_reason = ""
        self._auto_flush_count = 0
        self._header_events: list[str] = []

        self.setWindowTitle("Tracklist Column Persistence Harness")
        self.resize(1320, 900)
        self.setStyleSheet(
            f"""
            QWidget {{
                background: {_HARNESS_BG};
                color: {_HARNESS_TEXT};
            }}
            QLabel {{
                background: transparent;
                color: {_HARNESS_TEXT};
            }}
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        intro = QLabel(
            "Move or resize columns in the track list below. "
            "The panel at the bottom watches the live settings file from disk and "
            "rerenders the saved `track_list_columns_by_content.music` payload automatically. "
            "The flush button is only there as a manual fallback."
        )
        intro.setWordWrap(True)
        intro.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
        intro.setStyleSheet(f"color: {_HARNESS_TEXT};")
        layout.addWidget(intro)

        path_label = QLabel(f"Settings file: {self._settings_path}")
        path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        path_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        path_label.setStyleSheet(f"color: {_HARNESS_TEXT_MUTED};")
        layout.addWidget(path_label)

        button_row = QHBoxLayout()
        button_row.setSpacing(10)

        self._done_btn = QPushButton("Force Flush")
        self._done_btn.setStyleSheet(chrome_action_btn_css())
        self._done_btn.clicked.connect(self._flush_and_refresh)
        button_row.addWidget(self._done_btn)

        self._reload_btn = QPushButton("Reload File")
        self._reload_btn.setStyleSheet(chrome_action_btn_css())
        self._reload_btn.clicked.connect(self._refresh_file_preview)
        button_row.addWidget(self._reload_btn)

        self._reset_btn = QPushButton("Reset Stored Music Layout")
        self._reset_btn.setStyleSheet(chrome_action_btn_css())
        self._reset_btn.clicked.connect(self._reset_music_layout)
        button_row.addWidget(self._reset_btn)

        self._close_btn = QPushButton("Close")
        self._close_btn.setStyleSheet(chrome_action_btn_css())
        self._close_btn.clicked.connect(self.close)
        button_row.addWidget(self._close_btn)

        button_row.addStretch(1)
        layout.addLayout(button_row)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setFont(QFont(FONT_FAMILY, Metrics.FONT_SM))
        self._status.setStyleSheet(f"color: {_HARNESS_TEXT_MUTED};")
        layout.addWidget(self._status)

        self._list = MusicBrowserList(
            settings_service=self._settings_service,
            device_sessions=self._device_sessions,
            show_art_override=False,
        )
        self._list.setFrameShape(QFrame.Shape.NoFrame)
        layout.addWidget(self._list, 1)

        preview_label = QLabel("Saved Layout Preview")
        preview_label.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD, QFont.Weight.Bold))
        preview_label.setStyleSheet(f"color: {_HARNESS_TEXT};")
        layout.addWidget(preview_label)

        self._preview = QTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setFont(QFont("Menlo", max(11, Metrics.FONT_SM)))
        self._preview.setMinimumHeight(220)
        self._preview.setStyleSheet(
            f"""
            QTextEdit {{
                background: {_HARNESS_PANEL};
                color: {_HARNESS_TEXT};
                border: 1px solid {_HARNESS_BORDER};
                border-radius: 10px;
                padding: 8px;
                selection-background-color: #d7b98e;
                selection-color: {_HARNESS_TEXT};
            }}
            """
        )
        layout.addWidget(self._preview)

        self._load_tracks()
        self._install_header_observer()
        self._last_flushed_header_signature = self._current_header_signature()
        self._refresh_file_preview()
        self._preview_timer = QTimer(self)
        self._preview_timer.setInterval(250)
        self._preview_timer.timeout.connect(self._refresh_file_preview_if_changed)
        self._preview_timer.start()

        self._auto_flush_timer = QTimer(self)
        self._auto_flush_timer.setSingleShot(True)
        self._auto_flush_timer.timeout.connect(self._auto_flush_if_header_changed)

    def _load_tracks(self) -> None:
        tracks = _sample_tracks()
        self._list.clearTable()
        self._list._all_tracks = tracks
        self._list._tracks = tracks
        self._list._media_type_filter = 0x01
        self._list._is_playlist_mode = False
        self._list._setup_columns()
        self._list._populate_table()
        self._install_header_observer()

    def _current_visible_order(self) -> list[str]:
        keys: list[str] = []
        for visual_index in range(self._list.table.columnCount()):
            key = self._list._col_key_at(visual_index)
            if key is not None:
                keys.append(key)
        return keys

    def _current_header_signature(self) -> tuple[tuple[str, ...], tuple[tuple[str, int], ...]]:
        header = self._list.table.horizontalHeader()
        if header is None:
            return (), ()

        widths: dict[str, int] = {}
        for logical_index in range(self._list.table.columnCount()):
            key = self._list._col_key_for_logical(logical_index)
            if key is not None:
                widths[key] = header.sectionSize(logical_index)

        return tuple(self._current_visible_order()), tuple(sorted(widths.items()))

    def _install_header_observer(self) -> None:
        header = self._list.table.horizontalHeader()
        if header is None:
            return

        header.installEventFilter(self)
        viewport = header.viewport()
        if viewport is not None:
            viewport.installEventFilter(self)

        try:
            header.sectionMoved.disconnect(self._on_observed_header_moved)
        except TypeError:
            pass
        try:
            header.sectionResized.disconnect(self._on_observed_header_resized)
        except TypeError:
            pass
        header.sectionMoved.connect(self._on_observed_header_moved)
        header.sectionResized.connect(self._on_observed_header_resized)

    def _remember_header_event(self, label: str) -> None:
        self._header_events.append(label)
        self._header_events = self._header_events[-10:]

    def _schedule_auto_flush(self, reason: str) -> None:
        self._pending_auto_flush_reason = reason
        self._remember_header_event(f"queued: {reason}")
        self._auto_flush_timer.start(250)

    def _on_observed_header_moved(
        self,
        logical_index: int,
        old_visual: int,
        new_visual: int,
    ) -> None:
        self._remember_header_event(
            f"sectionMoved logical={logical_index} {old_visual}->{new_visual}"
        )
        self._schedule_auto_flush("sectionMoved settled")

    def _on_observed_header_resized(
        self,
        logical_index: int,
        old_size: int,
        new_size: int,
    ) -> None:
        self._remember_header_event(
            f"sectionResized logical={logical_index} {old_size}->{new_size}"
        )
        self._schedule_auto_flush("sectionResized settled")

    def _auto_flush_if_header_changed(self) -> None:
        current_signature = self._current_header_signature()
        if current_signature == self._last_flushed_header_signature:
            self._remember_header_event("auto flush skipped: no header delta")
            self._refresh_file_preview()
            return

        reason = self._pending_auto_flush_reason or "header changed"
        self._list.flush_pending_column_changes()
        QApplication.processEvents()
        self._last_flushed_header_signature = current_signature
        self._auto_flush_count += 1
        self._remember_header_event(f"auto flushed: {reason}")
        self._refresh_file_preview()

    def _flush_and_refresh(self) -> None:
        self._list.flush_pending_column_changes(force=True)
        QApplication.processEvents()
        self._last_flushed_header_signature = self._current_header_signature()
        self._auto_flush_count += 1
        self._remember_header_event("manual force flush")
        self._refresh_file_preview()

    def _reset_music_layout(self) -> None:
        settings = self._settings_service.get_global_settings()
        layouts = dict(settings.track_list_columns_by_content)
        layouts.pop("music", None)
        settings.track_list_columns_by_content = layouts
        self._settings_service.save_global_settings(settings)

        self._list._column_layouts.pop("music", None)
        self._list._user_col_widths.clear()
        self._list._user_col_order = None
        self._list._active_column_content_key = None
        self._load_tracks()
        self._install_header_observer()
        self._last_flushed_header_signature = self._current_header_signature()
        self._refresh_file_preview()

    def _refresh_file_preview(self) -> None:
        if not self._settings_path.exists():
            self._status.setText(f"Settings file does not exist yet: {self._settings_path}")
            self._preview.setPlainText("")
            self._last_settings_mtime_ns = None
            self._last_preview_text = ""
            return

        try:
            payload = json.loads(self._settings_path.read_text(encoding="utf-8"))
        except Exception as exc:
            self._status.setText(f"Failed to read settings file: {exc}")
            self._preview.setPlainText("")
            return

        music_layout = (
            payload.get("track_list_columns_by_content", {})
            .get("music", {})
        )
        visible_order = self._current_visible_order()
        mtime_ns = self._settings_path.stat().st_mtime_ns
        self._status.setText(
            "Visible order in widget: "
            f"{visible_order}\n"
            f"Auto flushes: {self._auto_flush_count}; "
            f"pending reason: {self._pending_auto_flush_reason or 'none'}\n"
            "Recent header activity: "
            f"{' | '.join(self._header_events[-5:]) or 'none'}\n"
            "Saved file payload read from disk. "
            f"Last file write: {mtime_ns}"
        )
        preview_text = json.dumps(
            {
                "settings_path": str(self._settings_path),
                "music_layout": music_layout,
                "sample_duration_display": format_duration_mmss(245000),
            },
            indent=2,
        )
        if preview_text != self._last_preview_text:
            self._preview.setPlainText(preview_text)
            self._last_preview_text = preview_text
        self._last_settings_mtime_ns = mtime_ns

    def _refresh_file_preview_if_changed(self) -> None:
        if not self._settings_path.exists():
            if self._last_settings_mtime_ns is not None:
                self._refresh_file_preview()
            return
        try:
            current_mtime_ns = self._settings_path.stat().st_mtime_ns
        except OSError:
            return
        if self._last_settings_mtime_ns != current_mtime_ns:
            self._refresh_file_preview()

    def eventFilter(self, obj, event):  # type: ignore[override]
        header = self._list.table.horizontalHeader()
        if header is not None and obj in {header, header.viewport()}:
            event_type = event.type()
            if event_type == QEvent.Type.MouseButtonPress:
                mouse_event: QMouseEvent = event  # type: ignore[assignment]
                if mouse_event.button() == Qt.MouseButton.LeftButton:
                    self._remember_header_event("left press")
            elif event_type == QEvent.Type.MouseMove:
                mouse_event = event  # type: ignore[assignment]
                if mouse_event.buttons() & Qt.MouseButton.LeftButton:
                    self._remember_header_event("left drag")
            elif event_type == QEvent.Type.MouseButtonRelease:
                mouse_event = event  # type: ignore[assignment]
                if mouse_event.button() == Qt.MouseButton.LeftButton:
                    self._schedule_auto_flush("left mouse release")
            elif event_type in {
                QEvent.Type.FocusOut,
                QEvent.Type.Leave,
                QEvent.Type.Hide,
            }:
                self._schedule_auto_flush(event_type.name)

        return super().eventFilter(obj, event)


def main() -> int:
    app = QApplication.instance() or QApplication([])
    window = ManualTracklistPersistenceHarness()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
