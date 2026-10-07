# Hallmark · component: duplicate review · theme: iOpenPod · genre: modern-minimal
# pre-emit critique: P5 H5 E4 S5 R5 V4
"""Compare album copies, explain Sync choices, and keep cleanup separate."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from PySide6.QtCore import QCoreApplication, QEvent, QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QBoxLayout,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.sync_plan import (
    SyncDuplicatePair,
    SyncDuplicateResolution,
    SyncPlanAction,
    SyncPlanMediaKind,
    host_path_identity,
)
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.themed_buttons import (
    ActionButton,
    ActionButtonKind,
    apply_action_button_kind,
)

if TYPE_CHECKING:
    from PySide6.QtCore import QObject

    from iOpenPod.app.models.sync_selection import SyncSelection
    from iOpenPod.app.sync_plan import SyncDuplicateGroup


@dataclass(slots=True)
class _GroupChoices:
    pairs: dict[str, int] = field(default_factory=dict[str, int])
    adds: set[str] = field(default_factory=set[str])
    removals: set[int] = field(default_factory=set[int])


class SyncDuplicatesDialog(QDialog):
    """Stage choices without changing the selection until Apply choices is pressed.

    Only the current group's members are rendered. Editors are shared by all rows,
    so large collections never allocate a combobox or checkbox for every Track.
    """

    def __init__(self, selection: SyncSelection, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("syncDuplicatesDialog")
        self.setModal(True)
        self.resize(1140, 760)
        self.setMinimumSize(760, 580)
        pending = {group.group_id for group in selection.pending_duplicate_groups}
        resolved = {choice.group_id for choice in selection.duplicate_resolutions}
        self._groups = tuple(
            sorted(
                selection.comparison.duplicate_groups,
                key=lambda group: (
                    group.group_id not in pending,
                    not (group.requires_resolution and group.group_id not in resolved),
                ),
            )
        )
        self._unresolved_selected_paths = selection.unresolved_selected_host_paths
        self._host_selection_removals = {
            (item.media_kind, host_path_identity(item.host_path), item.ipod_id)
            for item in selection.selected_plan.items
            if item.action is SyncPlanAction.REMOVE and item.host_path is not None
        }
        self._choices = self._initial_choices(selection)
        self._resolved = {
            resolution.group_id for resolution in selection.duplicate_resolutions
        }
        self._edited: set[str] = set()
        self._edited_hosts: dict[str, set[str]] = {}
        self._shown_group_id: str | None = None
        self._title = self._label("syncDuplicateTitle")
        self._description = self._label("syncDuplicateDescription")
        self._overview = self._label("syncDuplicateOverview")
        self._group_list = QListWidget(self)
        self._group_list.setObjectName("syncDuplicateGroups")
        self._group_list.setSpacing(LAYOUT.space_2xs)
        self._group_list.setMinimumWidth(LAYOUT.source_list_minimum_width)
        self._next = ActionButton(parent=self, kind=ActionButtonKind.QUIET)
        self._next.setObjectName("syncDuplicateNextGroup")
        self._group_title = self._label("syncDuplicateGroupTitle")
        self._status_badge = self._label("syncDuplicateStatus")
        self._status_badge.setSizePolicy(
            QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred
        )
        self._group_status = self._label("syncDuplicateGroupStatus")
        self._hosts_title = self._label("syncDuplicateSectionTitle")
        self._hosts = self._table("syncDuplicateHosts")
        self._host_empty = self._label("syncDuplicateEmpty")
        self._host_details = self._label("syncDuplicateHostDetails")
        self._host_details.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._host_details_toggle = self._disclosure(
            "syncDuplicateHostDetailsToggle", self._host_details
        )
        self._host_choice_label = self._label("syncDuplicateChoiceLabel")
        self._host_choice = AppComboBox(self)
        self._host_choice.setObjectName("syncDuplicateHostChoice")
        self._host_choice.setSizeAdjustPolicy(
            AppComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self._host_choice.setMinimumContentsLength(10)
        self._host_choice_label.setBuddy(self._host_choice)
        self._host_choice_help = self._label("syncDuplicateChoiceHelp")
        self._ipods_title = self._label("syncDuplicateSectionTitle")
        self._ipods = self._table("syncDuplicateIPods")
        self._ipod_empty = self._label("syncDuplicateEmpty")
        self._ipod_summary = self._label("syncDuplicateIPodSummary")
        self._ipod_details = self._label("syncDuplicateIPodDetails")
        self._ipod_details.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._ipod_details_toggle = self._disclosure(
            "syncDuplicateIPodDetailsToggle", self._ipod_details
        )
        self._remove = QCheckBox(self)
        self._remove.setObjectName("syncDuplicateRemove")
        self._removal_context = self._label("syncDuplicateRemovalContext")
        self._removal_note = self._label("syncDuplicateRemovalNote")
        self._cleanup = QWidget(self)
        cleanup_layout = QVBoxLayout(self._cleanup)
        cleanup_layout.setContentsMargins(LAYOUT.space_xs, 0, 0, 0)
        cleanup_layout.setSpacing(LAYOUT.space_xs)
        cleanup_layout.addWidget(self._removal_context)
        cleanup_layout.addWidget(self._remove)
        cleanup_layout.addWidget(self._removal_note)
        self._cleanup_toggle = self._disclosure("syncDuplicateCleanup", self._cleanup)
        self._skip = ActionButton(parent=self, kind=ActionButtonKind.QUIET)
        self._skip.setObjectName("syncDuplicateSkipGroup")
        self._skip.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        apply_action_button_kind(
            self._buttons.button(QDialogButtonBox.StandardButton.Ok),
            ActionButtonKind.PRIMARY,
        )
        apply_action_button_kind(
            self._buttons.button(QDialogButtonBox.StandardButton.Cancel),
            ActionButtonKind.SECONDARY,
        )
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        host_panel = QWidget(self)
        host_layout = QVBoxLayout(host_panel)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(LAYOUT.space_xs)
        for widget in (
            self._hosts_title,
            self._hosts,
            self._host_empty,
            self._host_choice_label,
            self._host_choice,
            self._host_choice_help,
            self._skip,
            self._host_details_toggle,
            self._host_details,
        ):
            host_layout.addWidget(widget)
        host_layout.addStretch(1)
        ipod_panel = QWidget(self)
        ipod_layout = QVBoxLayout(ipod_panel)
        ipod_layout.setContentsMargins(0, 0, 0, 0)
        ipod_layout.setSpacing(LAYOUT.space_xs)
        for widget in (
            self._ipods_title,
            self._ipods,
            self._ipod_empty,
            self._ipod_summary,
            self._ipod_details_toggle,
            self._ipod_details,
        ):
            ipod_layout.addWidget(widget)
        ipod_layout.addStretch(1)
        self._copies = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self._copies.setSpacing(LAYOUT.space_lg)
        self._copies.addWidget(host_panel, 1)
        self._copies.addWidget(ipod_panel, 1)
        self._detail = QWidget(self)
        self._detail.installEventFilter(self)
        detail_layout = QVBoxLayout(self._detail)
        detail_layout.setContentsMargins(LAYOUT.space_sm, 0, LAYOUT.space_xs, 0)
        detail_layout.setSpacing(LAYOUT.space_sm)
        detail_layout.addWidget(self._group_title)
        detail_layout.addWidget(self._status_badge)
        detail_layout.addWidget(self._group_status)
        detail_layout.addSpacing(LAYOUT.space_xs)
        detail_layout.addLayout(self._copies)
        detail_layout.addWidget(self._cleanup_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        detail_layout.addWidget(self._cleanup)
        detail_layout.addStretch(1)
        detail_scroll = QScrollArea(self)
        detail_scroll.setObjectName("syncDuplicateDetailScroll")
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setFrameShape(QFrame.Shape.NoFrame)
        detail_scroll.setWidget(self._detail)
        sidebar = QWidget(self)
        sidebar.setMinimumWidth(LAYOUT.source_list_minimum_width)
        sidebar.setMaximumWidth(LAYOUT.source_list_width)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(LAYOUT.space_xs)
        sidebar_layout.addWidget(self._overview)
        sidebar_layout.addWidget(self._group_list, 1)
        sidebar_layout.addWidget(self._next)
        split = QSplitter(Qt.Orientation.Horizontal, self)
        split.setChildrenCollapsible(False)
        split.addWidget(sidebar)
        split.addWidget(detail_scroll)
        split.setSizes([220, 860])
        split.setStretchFactor(1, 1)
        split.splitterMoved.connect(self._update_columns)
        self._footer_note = self._label("syncDuplicateFooterNote")
        footer = QHBoxLayout()
        footer.setSpacing(LAYOUT.space_sm)
        footer.addWidget(self._footer_note, 1)
        footer.addWidget(self._buttons)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_md, LAYOUT.space_lg, LAYOUT.space_md
        )
        layout.setSpacing(LAYOUT.space_sm)
        layout.addWidget(self._title)
        layout.addWidget(self._description)
        layout.addSpacing(LAYOUT.space_xs)
        layout.addWidget(split, 1)
        layout.addLayout(footer)
        self._group_list.currentRowChanged.connect(self._show_group)
        self._hosts.currentItemChanged.connect(self._show_host_choice)
        self._ipods.currentItemChanged.connect(self._show_removal)
        self._host_choice.currentIndexChanged.connect(self._choose_host)
        self._remove.toggled.connect(self._choose_removal)
        self._skip.clicked.connect(self._skip_unresolved)
        self._next.clicked.connect(self._next_group)
        self.retranslate_ui()

    def _label(self, name: str) -> QLabel:
        label = QLabel(self)
        label.setObjectName(name)
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setMinimumWidth(0)
        return label

    def _disclosure(self, name: str, content: QWidget) -> ActionButton:
        button = ActionButton(parent=self, kind=ActionButtonKind.QUIET)
        button.setObjectName(name)
        button.setCheckable(True)
        button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        button.toggled.connect(content.setVisible)
        content.hide()
        return button

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._detail and event.type() == QEvent.Type.Resize:
            self._update_columns()
        return super().eventFilter(watched, event)

    def _update_columns(self) -> None:
        self._copies.setDirection(
            QBoxLayout.Direction.LeftToRight
            if self._detail.width() >= 680
            else QBoxLayout.Direction.TopToBottom
        )

    def _next_group(self) -> None:
        self._group_list.setCurrentRow(self._group_list.currentRow() + 1)

    @property
    def resolutions(self) -> tuple[SyncDuplicateResolution, ...]:
        """Return only groups edited in this dialog; untouched choices stay intact."""

        return tuple(
            SyncDuplicateResolution(
                group.group_id,
                pairs=tuple(
                    SyncDuplicatePair(path, ipod_id)
                    for path, ipod_id in self._choices[group.group_id].pairs.items()
                ),
                added_host_paths=frozenset(self._choices[group.group_id].adds),
                removed_ipod_ids=frozenset(self._choices[group.group_id].removals),
            )
            for group in self._groups
            if group.group_id in self._edited
        )

    def preserved_host_paths(self, group_id: str) -> frozenset[str]:
        """Keep membership and Review exclusions for Host choices left untouched."""

        group = next(group for group in self._groups if group.group_id == group_id)
        edited = self._edited_hosts.get(group_id, set())
        return frozenset(
            host.host_path for host in group.hosts if host.host_path not in edited
        )

    def retranslate_ui(self) -> None:
        self.setWindowTitle(self.tr("Review similar media"))
        self._title.setText(self.tr("Keep the copies you want"))
        self._description.setText(
            self.tr(
                "Match existing iPod copies, add separate entries, or skip files. Different albums can keep the same recording."
            )
        )
        self._description.setToolTip(
            self.tr(
                "Audio matching is approximate. Compare the album and file details before choosing a match."
            )
        )
        remaining = sum(
            group.requires_resolution
            and group.group_id not in self._resolved | self._edited
            for group in self._groups
        )
        self._overview.setText(
            self.tr("Groups: %1 · Need choices: %2")
            .replace("%1", str(len(self._groups)))
            .replace("%2", str(remaining))
        )
        self._next.setText(self.tr("Next group →"))
        self._footer_note.setText(self.tr("Nothing changes on your iPod until Sync."))
        self._group_list.setAccessibleName(self.tr("Groups of similar media"))
        self._hosts.setAccessibleName(self.tr("Host files in this group"))
        self._ipods.setAccessibleName(self.tr("iPod items in this group"))
        self._host_choice_label.setText(self.tr("For this Host file"))
        self._host_choice.setAccessibleName(
            self.tr("Action for the selected Host file")
        )
        self._remove.setText(self.tr("Remove this iPod copy during Sync"))
        self._cleanup_toggle.setText(self.tr("Remove iPod copies…"))
        self._host_details_toggle.setText(self.tr("File details…"))
        self._ipod_details_toggle.setText(self.tr("File details…"))
        self._skip.setText(self.tr("Skip remaining files"))
        self._skip.setToolTip(self.tr("Skip unlinked Host files in this group"))
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            self.tr("Apply choices")
            if self._edited
            else self.tr("Back to Review")
            if remaining
            else self.tr("Done")
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(
            QCoreApplication.translate("CommonActions", "Cancel")
        )
        self._host_empty.setText(
            self.tr(
                "No Host files in this group. Keep the iPod copies or review removal below."
            )
        )
        self._ipod_empty.setText(
            self.tr(
                "No copies on your iPod yet. Each file you add becomes a separate entry."
            )
        )
        self._hosts.setHeaderLabels(
            (self.tr("File"), self.tr("Album / position"), self.tr("During Sync"))
        )
        self._ipods.setHeaderLabels(
            (
                self.tr("iPod item"),
                self.tr("Album / position"),
                self.tr("Plays"),
                self.tr("Rating"),
                self.tr("Playlists"),
                self.tr("During Sync"),
            )
        )
        row = max(0, self._group_list.currentRow())
        with QSignalBlocker(self._group_list):
            self._group_list.clear()
            for group in self._groups:
                name = group.hosts[0].name if group.hosts else group.ipods[0].name
                status, _ = self._group_state(group)
                item = QListWidgetItem(name + "\n" + status, self._group_list)
                item.setToolTip(
                    self.tr("%1 Host files · %2 iPod items")
                    .replace("%1", str(len(group.hosts)))
                    .replace("%2", str(len(group.ipods)))
                )
            self._group_list.setCurrentRow(row)
        self._show_group()

    def _group_state(self, group: SyncDuplicateGroup) -> tuple[str, str]:
        if group.group_id in self._edited:
            return self.tr("Ready to apply"), "ready"
        if group.group_id in self._resolved:
            return self.tr("Reviewed"), "ready"
        if group.requires_resolution:
            return self.tr("Needs a choice"), "attention"
        if self._host_removals(group):
            return self.tr("Removal selected"), "attention"
        if group.established_pairs and len(group.established_pairs) == len(
            group.hosts
        ) == len(group.ipods):
            return self.tr("Already matched"), "ready"
        return self.tr("Optional"), "optional"

    def _host_needs_choice(self, group: SyncDuplicateGroup, path: str) -> bool:
        choices = self._choices[group.group_id]
        return (
            group.requires_resolution
            and group.group_id not in self._resolved | self._edited
            and path not in choices.pairs
            and path not in choices.adds
            and not any(pair.host_path == path for pair in group.established_pairs)
        )

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def _table(self, name: str) -> QTreeWidget:
        table = QTreeWidget(self)
        table.setObjectName(name)
        table.setRootIsDecorated(False)
        table.setUniformRowHeights(False)
        table.setWordWrap(True)
        table.setTextElideMode(Qt.TextElideMode.ElideNone)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setMinimumHeight(150)
        table.header().setStretchLastSection(False)
        table.header().setMinimumSectionSize(LAYOUT.control_height_large)
        return table

    def _current_group(self) -> SyncDuplicateGroup | None:
        row = self._group_list.currentRow()
        return self._groups[row] if 0 <= row < len(self._groups) else None

    def _show_group(self) -> None:
        group = self._current_group()
        tracks = group is None or group.media_kind is SyncPlanMediaKind.TRACK
        self._hosts.setColumnHidden(1, not tracks)
        self._ipods.setColumnHidden(1, not tracks)
        for column in (2, 3, 4):
            self._ipods.setColumnHidden(column, True)
        same_names = (
            group is not None
            and len(
                {host.name for host in group.hosts}
                | {ipod.name for ipod in group.ipods}
            )
            == 1
        )
        for table in (self._hosts, self._ipods):
            table.setColumnHidden(0, tracks and same_names)
            table.header().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            table.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            table.header().setSectionResizeMode(
                1 if tracks else 0, QHeaderView.ResizeMode.Stretch
            )
        with QSignalBlocker(self._hosts), QSignalBlocker(self._ipods):
            self._hosts.clear()
            self._ipods.clear()
            if group is not None:
                choices = self._choices[group.group_id]
                established = {
                    pair.host_path: pair.ipod_id for pair in group.established_pairs
                }
                host_removals = self._host_removals(group)
                for host in group.hosts:
                    linked = established.get(
                        host.host_path, choices.pairs.get(host.host_path)
                    )
                    action = (
                        self.tr("Remove (Host selection)")
                        if linked in host_removals
                        else self.tr("Matched")
                        if host.host_path in established
                        else self.tr("Match")
                        if linked is not None
                        else self.tr("Add separately")
                        if host.host_path in choices.adds
                        else self.tr("Choose…")
                        if self._host_needs_choice(group, host.host_path)
                        else self.tr("Skip")
                    )
                    item = QTreeWidgetItem(
                        self._hosts,
                        (
                            host.name,
                            self._album_position(
                                host.album, host.disc_number, host.track_number
                            ),
                            action,
                        ),
                    )
                    item.setData(0, Qt.ItemDataRole.UserRole, host.host_path)
                    item.setToolTip(0, host.detail + "\n" + host.host_path)
                linked_ids = {*established.values(), *choices.pairs.values()}
                for ipod in group.ipods:
                    item = QTreeWidgetItem(
                        self._ipods,
                        (
                            ipod.name,
                            self._album_position(
                                ipod.album, ipod.disc_number, ipod.track_number
                            ),
                            str(ipod.play_count),
                            self.tr("%1 / 5").replace("%1", f"{ipod.rating / 20:g}"),
                            ", ".join(ipod.playlist_names) or self.tr("None"),
                            self.tr("Remove (Host selection)")
                            if ipod.ipod_id in host_removals
                            else self.tr("Remove")
                            if ipod.ipod_id in choices.removals
                            else self.tr("Matched")
                            if ipod.ipod_id in linked_ids
                            else self.tr("Keep"),
                        ),
                    )
                    item.setData(0, Qt.ItemDataRole.UserRole, ipod.ipod_id)
                    item.setToolTip(
                        0, f"#{ipod.ipod_id} · {ipod.detail}\n{ipod.ipod_path or ''}"
                    )
                    item.setToolTip(4, "\n".join(ipod.playlist_names))
                selected_row = next(
                    (
                        index
                        for index, host in enumerate(group.hosts)
                        if host_path_identity(host.host_path)
                        in self._unresolved_selected_paths
                    ),
                    0,
                )
                self._select_row(self._hosts, selected_row)
                self._select_row(self._ipods, 0)
        self._next.setEnabled(self._group_list.currentRow() < len(self._groups) - 1)
        if group is not None:
            self._group_title.setText(
                group.hosts[0].name if group.hosts else group.ipods[0].name
            )
            status, tone = self._group_state(group)
            self._status_badge.setText(status)
            self._status_badge.setProperty("tone", tone)
            self._status_badge.style().unpolish(self._status_badge)
            self._status_badge.style().polish(self._status_badge)
            self._hosts_title.setText(
                self.tr("Host files (%1)").replace("%1", str(len(group.hosts)))
            )
            self._ipods_title.setText(
                self.tr("On your iPod (%1)").replace("%1", str(len(group.ipods)))
            )
            self._host_details_toggle.setAccessibleName(
                self._hosts_title.text() + ": " + self._host_details_toggle.text()
            )
            self._ipod_details_toggle.setAccessibleName(
                self._ipods_title.text() + ": " + self._ipod_details_toggle.text()
            )
            self._group_status.setText(
                self.tr(
                    "Some copies are being removed by your Host selection. Edit that selection to keep them."
                )
                if self._host_removals(group)
                else self.tr(
                    "These copies already have matches. No decision needed; each entry stays separate."
                )
                if len(group.established_pairs) == len(group.hosts) == len(group.ipods)
                else self.tr(
                    "Choose an existing iPod copy for each Host file, or add it separately."
                )
                if group.requires_resolution
                and group.group_id not in self._resolved | self._edited
                else self.tr(
                    "Your choices are ready. Skipped Host files leave existing iPod copies untouched."
                )
                if group.group_id in self._resolved | self._edited
                else self.tr(
                    "Existing matches are kept. Review extra copies only if you want to change them."
                )
            )
            self._host_empty.setVisible(not group.hosts)
            self._hosts.setVisible(bool(group.hosts))
            self._ipod_empty.setVisible(not group.ipods)
            self._ipods.setVisible(bool(group.ipods))
            self._cleanup_toggle.setVisible(bool(group.ipods))
            if group.group_id != self._shown_group_id:
                self._cleanup_toggle.setChecked(
                    bool(
                        self._choices[group.group_id].removals
                        or self._host_removals(group)
                    )
                )
                self._host_details_toggle.setChecked(False)
                self._ipod_details_toggle.setChecked(False)
                self._shown_group_id = group.group_id
        self._removal_note.setText(
            self.tr(
                "Removal also removes this item's Playlist entries and playback history. History and Playlist entries are not merged into another copy. Host files are kept."
            )
            if tracks
            else self.tr(
                "Removal also removes this Photo from its Photo Albums. Host files are kept."
            )
        )
        self._skip.setVisible(
            group is not None
            and any(
                host.host_path
                not in {pair.host_path for pair in group.established_pairs}
                and host.host_path not in self._choices[group.group_id].pairs
                for host in group.hosts
            )
        )
        self._show_host_choice()
        self._show_removal()
        for table in (self._hosts, self._ipods):
            table.setFixedHeight(
                table.header().sizeHint().height()
                + max(2, min(5, table.topLevelItemCount()))
                * (LAYOUT.control_height_large + LAYOUT.space_xs)
                + LAYOUT.space_xs
            )
        self._update_columns()

    def _show_host_choice(self) -> None:
        group = self._current_group()
        item = self._hosts.currentItem()
        for widget in (
            self._host_choice_label,
            self._host_choice,
            self._host_choice_help,
            self._host_details_toggle,
        ):
            widget.setVisible(item is not None)
        if item is None:
            self._host_details.hide()
        with QSignalBlocker(self._host_choice):
            self._host_choice.clear()
            self._host_details.setText(item.toolTip(0) if item is not None else "")
            if group is None or item is None:
                self._host_choice.setEnabled(False)
                return
            path = str(item.data(0, Qt.ItemDataRole.UserRole))
            established = {
                pair.host_path: pair.ipod_id for pair in group.established_pairs
            }
            if path in established:
                self._host_choice.addItem(self.tr("Keep existing match"))
                self._host_choice.setEnabled(False)
                self._host_choice_help.setText(
                    self.tr(
                        "This copy is being removed by your Host selection. Edit that selection to keep it."
                    )
                    if established[path] in self._host_removals(group)
                    else self.tr(
                        "A previous Sync matched these copies. Future Syncs keep using this match."
                    )
                )
                self._select_matching_ipod(established[path])
                return
            self._host_choice.setEnabled(True)
            choices = self._choices[group.group_id]
            undecided = self._host_needs_choice(group, path)
            if undecided:
                self._host_choice.addItem(self.tr("Choose an action…"), None)
            self._host_choice.addItem(self.tr("Skip this file"), "skip")
            self._host_choice.addItem(self.tr("Add a separate copy"), "add")
            occupied = {
                ipod_id for source, ipod_id in choices.pairs.items() if source != path
            } | set(established.values())
            allowed = set(group.pairable_ipod_ids(path)) - occupied - choices.removals
            for ipod in group.ipods:
                if ipod.ipod_id in allowed:
                    self._host_choice.addItem(
                        self.tr("Match: %2 · #%1")
                        .replace("%1", str(ipod.ipod_id))
                        .replace("%2", ipod.album or ipod.name),
                        ipod.ipod_id,
                    )
            value: str | int = choices.pairs.get(
                path, "add" if path in choices.adds else "skip"
            )
            self._host_choice.setCurrentIndex(
                0 if undecided else self._host_choice.findData(value)
            )
            self._host_choice_help.setText(
                self.tr("Choose a match, add a new copy, or explicitly skip this file.")
                if undecided
                else self.tr(
                    "Use the existing iPod copy. Its play history and Playlists are kept."
                )
                if isinstance(value, int)
                else self.tr(
                    "Create another iPod entry using this file's album details."
                )
                if value == "add" and group.media_kind is SyncPlanMediaKind.TRACK
                else self.tr("Create another Photo entry on your iPod.")
                if value == "add"
                else self.tr(
                    "Leave this Host file out of Sync. Existing iPod copies are kept."
                )
            )
            if isinstance(value, int):
                self._select_matching_ipod(value)

    def _select_matching_ipod(self, ipod_id: int) -> None:
        for row in range(self._ipods.topLevelItemCount()):
            item = self._ipods.topLevelItem(row)
            if item is not None and item.data(0, Qt.ItemDataRole.UserRole) == ipod_id:
                self._ipods.setCurrentItem(item)
                self._ipods.scrollToItem(item)
                break

    def _choose_host(self) -> None:
        group = self._current_group()
        item = self._hosts.currentItem()
        if group is None or item is None or not self._host_choice.isEnabled():
            return
        path = str(item.data(0, Qt.ItemDataRole.UserRole))
        value = self._host_choice.currentData()
        if value is None:
            return
        choices = self._choices[group.group_id]
        choices.pairs.pop(path, None)
        choices.adds.discard(path)
        if isinstance(value, int):
            choices.pairs[path] = value
        elif value == "add":
            choices.adds.add(path)
        self._edited.add(group.group_id)
        self._edited_hosts.setdefault(group.group_id, set()).add(path)
        self._refresh_choices()

    def _show_removal(self) -> None:
        group = self._current_group()
        item = self._ipods.currentItem()
        self._ipod_summary.setVisible(item is not None)
        self._ipod_details_toggle.setVisible(item is not None)
        if item is None:
            self._ipod_details.hide()
        with QSignalBlocker(self._remove):
            self._ipod_details.setText(item.toolTip(0) if item is not None else "")
            if group is None or item is None:
                self._remove.setChecked(False)
                self._remove.setEnabled(False)
                return
            ipod_id = int(item.data(0, Qt.ItemDataRole.UserRole))
            ipod = next(ipod for ipod in group.ipods if ipod.ipod_id == ipod_id)
            self._ipod_summary.setText(
                self.tr("%1 plays · %2 / 5 rating\nPlaylists: %3")
                .replace("%1", str(ipod.play_count))
                .replace("%2", f"{ipod.rating / 20:g}")
                .replace("%3", ", ".join(ipod.playlist_names) or self.tr("None"))
                if group.media_kind is SyncPlanMediaKind.TRACK
                else ipod.detail
            )
            choices = self._choices[group.group_id]
            established = {pair.ipod_id for pair in group.established_pairs}
            linked = established | set(choices.pairs.values())
            self._remove.setEnabled(ipod_id not in linked)
            self._remove.setChecked(
                ipod_id in choices.removals or ipod_id in self._host_removals(group)
            )
            self._remove.setToolTip(
                self.tr(
                    "Established links follow Host selection. Change that selection to remove this item."
                )
                if ipod_id in established
                else self.tr(
                    "A linked item is retained. Skip its Host link before removing it."
                )
                if ipod_id in linked
                else self.tr(
                    "Choose removal explicitly; keeping another copy does not remove this one."
                )
            )
            self._removal_context.setText(
                self.tr("Selected copy: %1").replace("%1", ipod.album or ipod.name)
                + "\n"
                + self._remove.toolTip()
            )

    def _choose_removal(self, checked: bool) -> None:
        group = self._current_group()
        item = self._ipods.currentItem()
        if group is None or item is None:
            return
        ipod_id = int(item.data(0, Qt.ItemDataRole.UserRole))
        choices = self._choices[group.group_id]
        if checked:
            choices.removals.add(ipod_id)
        else:
            choices.removals.discard(ipod_id)
        self._edited.add(group.group_id)
        self._refresh_choices(keep_ipod=True)

    def _skip_unresolved(self) -> None:
        group = self._current_group()
        if group is not None:
            choices = self._choices[group.group_id]
            linked = {pair.host_path for pair in group.established_pairs} | set(
                choices.pairs
            )
            self._edited_hosts.setdefault(group.group_id, set()).update(
                host.host_path for host in group.hosts if host.host_path not in linked
            )
            choices.adds.clear()
            self._edited.add(group.group_id)
            self._refresh_choices()

    def _refresh_choices(self, *, keep_ipod: bool = False) -> None:
        host = self._hosts.currentItem()
        ipod = self._ipods.currentItem()
        host_row = self._hosts.indexOfTopLevelItem(host) if host is not None else -1
        ipod_row = self._ipods.indexOfTopLevelItem(ipod) if ipod is not None else -1
        self.retranslate_ui()
        self._select_row(self._hosts, host_row)
        if keep_ipod:
            self._select_row(self._ipods, ipod_row)

    @staticmethod
    def _select_row(table: QTreeWidget, row: int) -> None:
        item = table.topLevelItem(row)
        if item is not None:
            table.setCurrentItem(item)

    def _host_removals(self, group: SyncDuplicateGroup) -> set[int]:
        pairs = {
            **{pair.host_path: pair.ipod_id for pair in group.established_pairs},
            **self._choices[group.group_id].pairs,
        }
        return {
            ipod_id
            for path, ipod_id in pairs.items()
            if (group.media_kind, host_path_identity(path), ipod_id)
            in self._host_selection_removals
        }

    def _album_position(self, album: str, disc: int, track: int) -> str:
        parts = [album or self.tr("Unknown album")]
        if disc:
            parts.append(self.tr("Disc %1").replace("%1", str(disc)))
        if track:
            parts.append(self.tr("Track %1").replace("%1", str(track)))
        return parts[0] + ("\n" + " · ".join(parts[1:]) if len(parts) > 1 else "")

    def _initial_choices(self, selection: SyncSelection) -> dict[str, _GroupChoices]:
        existing = {
            resolution.group_id: resolution
            for resolution in selection.duplicate_resolutions
        }
        selected = selection.selected_plan
        added = {
            host_path_identity(item.host_path)
            for item in selection.review_plan.items
            if item.action is SyncPlanAction.ADD and item.host_path is not None
        }
        removed = {
            (item.media_kind, item.ipod_id)
            for item in selected.items
            if item.action is SyncPlanAction.REMOVE
        }
        choices: dict[str, _GroupChoices] = {}
        for group in self._groups:
            resolution = existing.get(group.group_id)
            linked = {pair.ipod_id for pair in group.established_pairs}
            if resolution is not None:
                linked.update(pair.ipod_id for pair in resolution.pairs)
            choices[group.group_id] = _GroupChoices(
                pairs={pair.host_path: pair.ipod_id for pair in resolution.pairs}
                if resolution is not None
                else {},
                adds={
                    host.host_path
                    for host in group.hosts
                    if host_path_identity(host.host_path) in added
                },
                removals={
                    ipod.ipod_id
                    for ipod in group.ipods
                    if (group.media_kind, ipod.ipod_id) in removed
                    and ipod.ipod_id not in linked
                },
            )
        return choices


__all__ = ["SyncDuplicatesDialog"]
