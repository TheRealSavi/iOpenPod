"""Dialog allowing users to map Subsonic playlists to iPod playlists and choose sync mode."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.subsonic.models import (
    SubsonicPlaylist,
    SubsonicPlaylistMapping,
    SubsonicSyncMode,
    SubsonicSyncScope,
)
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.themed_buttons import (
    ActionButton,
    ActionButtonKind,
    apply_action_button_kind,
)
from iPodDB.library import PlaylistKind

if TYPE_CHECKING:
    from iPodDB.library import Playlist


class SubsonicPlaylistMappingDialog(QDialog):
    """Dialog for selecting Subsonic playlists, mapping to iPod targets, and choosing sync scope."""

    def __init__(
        self,
        subsonic_playlists: tuple[SubsonicPlaylist, ...],
        ipod_playlists: tuple[Playlist, ...],
        saved_mappings: dict[str, int] | None = None,
        saved_selected_ids: tuple[str, ...] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("subsonicMappingDialog")
        self.setWindowTitle(self.tr("Subsonic Sync"))
        self.resize(600, 520)
        self.setMinimumSize(500, 400)

        self._subsonic_playlists = subsonic_playlists
        self._ipod_playlists = tuple(
            p
            for p in ipod_playlists
            if getattr(p, "kind", None) == PlaylistKind.PLAYLIST
        )
        self._saved_mappings = saved_mappings or {}
        self._saved_selected_ids = (
            set(saved_selected_ids)
            if saved_selected_ids
            else {p.playlist_id for p in subsonic_playlists}
        )

        self._checkboxes: dict[str, QCheckBox] = {}
        self._mapping_combos: dict[str, AppComboBox] = {}
        self._mode_combos: dict[str, AppComboBox] = {}

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg
        )
        layout.setSpacing(LAYOUT.space_md)

        self._title = QLabel(self.tr("Sync Subsonic"), self)
        self._title.setObjectName("dialogTitle")
        layout.addWidget(self._title)

        self._description = QLabel(
            self.tr(
                "Choose whether to sync playlists only or include missing music files from your server."
            ),
            self,
        )
        self._description.setObjectName("pageDescription")
        self._description.setWordWrap(True)
        layout.addWidget(self._description)

        self._radio_playlists_only = QRadioButton(
            self.tr("Playlists only (match existing iPod tracks, no downloads)"),
            self,
        )
        self._radio_playlists_only.setChecked(True)
        self._radio_all_songs = QRadioButton(
            self.tr("Include all songs (download missing tracks from server)"),
            self,
        )

        self._scope_button_group = QButtonGroup(self)
        self._scope_button_group.addButton(self._radio_playlists_only)
        self._scope_button_group.addButton(self._radio_all_songs)

        layout.addWidget(self._radio_playlists_only)
        layout.addWidget(self._radio_all_songs)

        tabs = QTabWidget(self)
        tabs.setObjectName("subsonicTabs")

        mapping_scroll = QScrollArea(tabs)
        mapping_scroll.setObjectName("subsonicScroll")
        mapping_scroll.setWidgetResizable(True)
        mapping_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        mapping_scroll.viewport().setStyleSheet("background: transparent;")
        mapping_content = QWidget(mapping_scroll)
        mapping_content.setStyleSheet("background: transparent;")
        mapping_layout = QFormLayout(mapping_content)
        mapping_layout.setContentsMargins(
            LAYOUT.space_sm, LAYOUT.space_sm, LAYOUT.space_sm, LAYOUT.space_sm
        )
        mapping_layout.setSpacing(LAYOUT.space_sm)

        mode_scroll = QScrollArea(tabs)
        mode_scroll.setObjectName("subsonicScroll")
        mode_scroll.setWidgetResizable(True)
        mode_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        mode_scroll.viewport().setStyleSheet("background: transparent;")
        mode_content = QWidget(mode_scroll)
        mode_content.setStyleSheet("background: transparent;")
        mode_layout = QFormLayout(mode_content)
        mode_layout.setContentsMargins(
            LAYOUT.space_sm, LAYOUT.space_sm, LAYOUT.space_sm, LAYOUT.space_sm
        )
        mode_layout.setSpacing(LAYOUT.space_sm)

        for pl in self._subsonic_playlists:
            cb = QCheckBox(
                f"{pl.name} ({pl.song_count} songs)"
                if pl.song_count
                else pl.name,
                mapping_content,
            )
            cb.setChecked(pl.playlist_id in self._saved_selected_ids)
            self._checkboxes[pl.playlist_id] = cb

            m_combo = AppComboBox(mapping_content)
            m_combo.addItem(self.tr("New playlist (same name)"), None)
            saved_target = self._saved_mappings.get(pl.playlist_id)
            current_index = 0
            idx = 1
            for ipod_pl in self._ipod_playlists:
                m_combo.addItem(f"{ipod_pl.name} (iPod)", str(ipod_pl.playlist_id))
                if (
                    saved_target is not None
                    and abs(saved_target) == ipod_pl.playlist_id
                ):
                    current_index = idx
                idx += 1
            m_combo.setCurrentIndex(current_index)
            m_combo.setEnabled(cb.isChecked())
            self._mapping_combos[pl.playlist_id] = m_combo

            mapping_layout.addRow(cb, m_combo)

            mode_combo = AppComboBox(mode_content)
            mode_combo.addItem(
                self.tr("Add / Merge into iPod playlist"), SubsonicSyncMode.MERGE.value
            )
            mode_combo.addItem(
                self.tr("Overwrite iPod playlist entirely"), SubsonicSyncMode.OVERWRITE.value
            )
            if saved_target is not None and saved_target < 0:
                mode_combo.setCurrentIndex(1)
            else:
                mode_combo.setCurrentIndex(0)
            mode_combo.setEnabled(cb.isChecked())
            self._mode_combos[pl.playlist_id] = mode_combo
            mode_layout.addRow(QLabel(f"{pl.name}:"), mode_combo)

            # Toggle combos based on checkbox
            cb.toggled.connect(m_combo.setEnabled)
            cb.toggled.connect(mode_combo.setEnabled)

        mapping_scroll.setWidget(mapping_content)
        mode_scroll.setWidget(mode_content)

        tabs.addTab(mapping_scroll, self.tr("Playlists & Mapping"))
        tabs.addTab(mode_scroll, self.tr("Merge / Overwrite"))
        layout.addWidget(tabs, 1)

        # Quick Select buttons
        actions_bar = QWidget(self)
        actions_bar_layout = QHBoxLayout(actions_bar)
        actions_bar_layout.setContentsMargins(0, 0, 0, 0)
        actions_bar_layout.setSpacing(LAYOUT.space_sm)

        select_all_btn = ActionButton(
            parent=actions_bar, kind=ActionButtonKind.QUIET
        )
        select_all_btn.setText(self.tr("Select All"))
        select_all_btn.clicked.connect(self._select_all)
        deselect_all_btn = ActionButton(
            parent=actions_bar, kind=ActionButtonKind.QUIET
        )
        deselect_all_btn.setText(self.tr("Deselect All"))
        deselect_all_btn.clicked.connect(self._deselect_all)

        actions_bar_layout.addWidget(select_all_btn)
        actions_bar_layout.addWidget(deselect_all_btn)
        actions_bar_layout.addStretch(1)
        layout.addWidget(actions_bar)

        # Dialog Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            Qt.Orientation.Horizontal,
            self,
        )
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setText(self.tr("Sync Playlists"))
        apply_action_button_kind(ok_btn, ActionButtonKind.PRIMARY)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _select_all(self) -> None:
        for cb in self._checkboxes.values():
            cb.setChecked(True)

    def _deselect_all(self) -> None:
        for cb in self._checkboxes.values():
            cb.setChecked(False)

    @property
    def sync_scope(self) -> SubsonicSyncScope:
        """Whether to sync playlists only or include all songs."""
        if self._radio_all_songs.isChecked():
            return SubsonicSyncScope.ALL_SONGS
        return SubsonicSyncScope.PLAYLISTS_ONLY

    def get_selected_playlist_ids(self) -> tuple[str, ...]:
        """Return the tuple of checked Subsonic playlist IDs."""
        return tuple(
            pl.playlist_id
            for pl in self._subsonic_playlists
            if self._checkboxes.get(pl.playlist_id, None) is not None
            and self._checkboxes[pl.playlist_id].isChecked()
        )

    def get_mappings(self) -> tuple[SubsonicPlaylistMapping, ...]:
        """Return the user-configured playlist mappings for checked playlists."""
        result: list[SubsonicPlaylistMapping] = []
        for pl in self._subsonic_playlists:
            cb = self._checkboxes.get(pl.playlist_id)
            if cb is None or not cb.isChecked():
                continue
            m_combo = self._mapping_combos.get(pl.playlist_id)
            mode_combo = self._mode_combos.get(pl.playlist_id)
            raw_target = m_combo.currentData() if m_combo else None
            target_id: int | None = int(raw_target) if raw_target is not None else None
            raw_mode = mode_combo.currentData() if mode_combo else None
            mode = (
                SubsonicSyncMode(raw_mode)
                if raw_mode in ("merge", "overwrite")
                else SubsonicSyncMode.MERGE
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
