"""Dialog allowing users to map Subsonic playlists to iPod playlists and choose sync mode."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.subsonic.models import (
    SubsonicPlaylist,
    SubsonicPlaylistMapping,
    SubsonicSyncMode,
)
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.themed_buttons import (
    ActionButtonKind,
    apply_action_button_kind,
)
from iPodDB.library import PlaylistKind

if TYPE_CHECKING:
    from iPodDB.library import Playlist


class SubsonicPlaylistMappingDialog(QDialog):
    """Two-tab dialog for mapping Subsonic playlists and configuring sync mode."""

    def __init__(
        self,
        subsonic_playlists: tuple[SubsonicPlaylist, ...],
        ipod_playlists: tuple[Playlist, ...],
        saved_mappings: dict[str, int] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Subsonic Playlist Sync"))
        self.resize(560, 420)
        self.setMinimumSize(480, 360)

        self._subsonic_playlists = subsonic_playlists
        self._ipod_playlists = tuple(
            p for p in ipod_playlists if getattr(p, "kind", None) == PlaylistKind.PLAYLIST
        )
        self._saved_mappings = saved_mappings or {}

        self._mapping_combos: dict[str, AppComboBox] = {}
        self._mode_combos: dict[str, AppComboBox] = {}

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg
        )
        layout.setSpacing(LAYOUT.space_md)

        header = QLabel(
            self.tr("Choose how to sync each selected Subsonic playlist:"), self
        )
        header.setWordWrap(True)
        layout.addWidget(header)

        tabs = QTabWidget(self)

        # Tab 1: Mapping
        mapping_scroll = QScrollArea(tabs)
        mapping_scroll.setWidgetResizable(True)
        mapping_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        mapping_content = QWidget(mapping_scroll)
        mapping_layout = QFormLayout(mapping_content)
        mapping_layout.setContentsMargins(
            LAYOUT.space_sm, LAYOUT.space_sm, LAYOUT.space_sm, LAYOUT.space_sm
        )
        mapping_layout.setSpacing(LAYOUT.space_sm)

        # Tab 2: Sync Mode
        mode_scroll = QScrollArea(tabs)
        mode_scroll.setWidgetResizable(True)
        mode_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        mode_content = QWidget(mode_scroll)
        mode_layout = QFormLayout(mode_content)
        mode_layout.setContentsMargins(
            LAYOUT.space_sm, LAYOUT.space_sm, LAYOUT.space_sm, LAYOUT.space_sm
        )
        mode_layout.setSpacing(LAYOUT.space_sm)

        for pl in self._subsonic_playlists:
            # Mapping combo
            m_combo = AppComboBox(mapping_content)
            m_combo.addItem(self.tr("New playlist (same name)"), None)
            saved_target = self._saved_mappings.get(pl.playlist_id)
            current_index = 0
            idx = 1
            for ipod_pl in self._ipod_playlists:
                m_combo.addItem(f"{ipod_pl.name} (iPod)", ipod_pl.playlist_id)
                if saved_target is not None and abs(saved_target) == ipod_pl.playlist_id:
                    current_index = idx
                idx += 1
            m_combo.setCurrentIndex(current_index)
            self._mapping_combos[pl.playlist_id] = m_combo
            mapping_layout.addRow(QLabel(f"{pl.name} (Subsonic):"), m_combo)

            # Mode combo
            mode_combo = AppComboBox(mode_content)
            mode_combo.addItem(self.tr("Add / Merge into iPod playlist"), SubsonicSyncMode.MERGE)
            mode_combo.addItem(self.tr("Overwrite iPod playlist entirely"), SubsonicSyncMode.OVERWRITE)
            if saved_target is not None and saved_target < 0:
                mode_combo.setCurrentIndex(1)
            else:
                mode_combo.setCurrentIndex(0)
            self._mode_combos[pl.playlist_id] = mode_combo
            mode_layout.addRow(QLabel(f"{pl.name}:"), mode_combo)

        mapping_scroll.setWidget(mapping_content)
        mode_scroll.setWidget(mode_content)

        tabs.addTab(mapping_scroll, self.tr("Mapping"))
        tabs.addTab(mode_scroll, self.tr("Sync Mode"))
        layout.addWidget(tabs, 1)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            Qt.Orientation.Horizontal,
            self,
        )
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setText(self.tr("Sync Playlists"))
        apply_action_button_kind(ok_btn, ActionButtonKind.PRIMARY)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_mappings(self) -> tuple[SubsonicPlaylistMapping, ...]:
        """Return the user-configured playlist mappings."""
        result: list[SubsonicPlaylistMapping] = []
        for pl in self._subsonic_playlists:
            m_combo = self._mapping_combos.get(pl.playlist_id)
            mode_combo = self._mode_combos.get(pl.playlist_id)
            target_id: int | None = m_combo.currentData() if m_combo else None
            mode: SubsonicSyncMode = (
                mode_combo.currentData() if mode_combo else SubsonicSyncMode.MERGE
            )
            result.append(
                SubsonicPlaylistMapping(
                    subsonic_id=pl.playlist_id,
                    subsonic_name=pl.name,
                    target_ipod_id=target_id,
                    mode=mode,
                )
            )
        return tuple(result)
