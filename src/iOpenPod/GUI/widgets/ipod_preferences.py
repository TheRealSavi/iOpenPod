"""Captured firmware preferences with explicit connection-bound edit drafts."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import TYPE_CHECKING

from PySide6.QtCore import QCoreApplication, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSpinBox, QVBoxLayout, QWidget

from iOpenPod.app import developer_flags
from iOpenPod.app.models.ipod_preferences import IPodPreferenceEdit
from iOpenPod.GUI.presentation.i18n.workflow import workflow_text
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.search_field import SearchField
from iOpenPod.GUI.widgets.setting_group import SettingGroup, SettingRow
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, ActionButtonKind

if TYPE_CHECKING:
    from PySide6.QtGui import QShowEvent

    from iOpenPod.app.models.device import ActiveIPod
    from iOpenPod.app.models.ipod_preferences import (
        IPodPreference,
        IPodPreferenceSection,
    )
    from iOpenPod.app.preferences_controller import PreferencesController


@dataclass(frozen=True, slots=True)
class _SearchGroup:
    container: QWidget
    rows: tuple[tuple[SettingRow, str], ...]


@dataclass(frozen=True, slots=True)
class _SearchSection:
    container: QWidget
    groups: tuple[_SearchGroup, ...]


class IPodPreferencesView(QWidget):
    """Only application-projected choices may be authored; unknown bytes stay put."""

    stateChanged = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        controller: PreferencesController | None = None,
    ) -> None:
        super().__init__(parent)
        self._controller = controller
        self._active: ActiveIPod | None = controller.active_ipod if controller else None
        self._draft: dict[tuple[str, str], int] = {}
        self._submission_message = ""
        self._saved_notice = False
        self._search_sections: list[_SearchSection] = []
        self.setObjectName("ipodPreferencesView")
        self.setMaximumWidth(960)
        self._title = QLabel(self)
        self._title.setObjectName("sectionTitle")
        self._status = QLabel(self)
        self._status.setObjectName("ipodPreferencesStatus")
        self._status.setTextFormat(Qt.TextFormat.PlainText)
        self._status.setWordWrap(True)
        self._note = QLabel(self)
        self._note.setObjectName("settingDescription")
        self._note.setTextFormat(Qt.TextFormat.PlainText)
        self._note.setWordWrap(True)
        self._body = QWidget(self)
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(LAYOUT.space_sm)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(LAYOUT.space_sm)
        layout.addWidget(self._title)
        layout.addWidget(self._status)
        layout.addWidget(self._note)
        self._search = SearchField(self)
        self._search.setObjectName("ipodPreferencesSearch")
        self._search.queryChanged.connect(self._filter_rows)
        layout.addWidget(self._search)
        self._draft_note = QLabel(self)
        self._draft_note.setObjectName("ipodPreferencesDraftNote")
        self._draft_note.setTextFormat(Qt.TextFormat.PlainText)
        self._draft_note.setWordWrap(True)
        layout.addWidget(self._draft_note)
        self._refresh: ActionButton | None = None
        self._revert: ActionButton | None = None
        self._apply: ActionButton | None = None
        if controller is not None:
            actions = QHBoxLayout()
            self._refresh = ActionButton(parent=self)
            self._refresh.setObjectName("ipodPreferencesRefresh")
            self._revert = ActionButton(parent=self)
            self._revert.setObjectName("ipodPreferencesRevert")
            self._apply = ActionButton(parent=self, kind=ActionButtonKind.PRIMARY)
            self._apply.setObjectName("ipodPreferencesApply")
            actions.addWidget(self._refresh)
            actions.addStretch(1)
            actions.addWidget(self._revert)
            actions.addWidget(self._apply)
            layout.addLayout(actions)
            self._refresh.clicked.connect(controller.refresh)
            self._revert.clicked.connect(self._revert_draft)
            self._apply.clicked.connect(self._apply_draft)
            controller.changed.connect(self._controller_changed)
            controller.saved.connect(self._saved)
        layout.addWidget(self._body)
        self._no_matches = QLabel(self)
        self._no_matches.setObjectName("ipodPreferencesNoMatches")
        self._no_matches.setTextFormat(Qt.TextFormat.PlainText)
        self._no_matches.hide()
        layout.addWidget(self._no_matches)
        self.retranslate_ui()

    def set_active_ipod(self, active: ActiveIPod | None) -> None:
        if active is not self._active:
            self._draft.clear()
            self._submission_message = ""
            self._saved_notice = False
            self._search.set_query("")
        self._active = active
        self.retranslate_ui()

    def _sections(self) -> tuple[IPodPreferenceSection, ...]:
        if self._controller is not None and self._controller.catalog.sections:
            return self._controller.catalog.sections
        return self._active.preferences if self._active else ()

    def _controller_changed(self) -> None:
        assert self._controller is not None
        self.set_active_ipod(self._controller.active_ipod)

    def _saved(self) -> None:
        self._draft.clear()
        self._submission_message = ""
        self._saved_notice = True
        self.retranslate_ui()

    def _revert_draft(self) -> None:
        if self._controller is not None and not self._controller.busy:
            self._draft.clear()
            self._submission_message = ""
            self._saved_notice = False
            self.retranslate_ui()

    def _apply_draft(self) -> None:
        controller = self._controller
        if (
            controller is None
            or not self._draft
            or not controller.can_write
            or controller.active_ipod is not self._active
        ):
            return
        edits = tuple(
            IPodPreferenceEdit(section, key, value)
            for (section, key), value in self._draft.items()
        )
        self._submission_message = ""
        if not controller.save(edits):
            self._submission_message = self.tr(
                "The changes could not be submitted. Refresh the preferences and try again."
            )
            self._update_actions()

    def _selected(
        self, key: tuple[str, str], value: int, original: int, target: ActiveIPod | None
    ) -> None:
        if (
            target is not self._active
            or self._controller is None
            or self._controller.active_ipod is not target
        ):
            return
        if value == original:
            self._draft.pop(key, None)
        else:
            self._draft[key] = value
        self._submission_message = ""
        self._saved_notice = False
        self._update_actions()

    @property
    def status_text(self) -> str:
        controller = self._controller
        if controller is None:
            return self.tr("iPod preferences are read-only.")
        if self._active is None:
            return self.tr("Choose an iPod to view its preferences.")
        if controller.busy:
            return self.tr("Reading or saving iPod preferences…")
        if controller.message:
            return workflow_text(controller.message)
        if not developer_flags.ENABLE_IPOD_PREFERENCES_WRITES:
            return self.tr("iPod preferences are read-only.")
        if self._submission_message:
            return self._submission_message
        if self._saved_notice:
            return self.tr(
                "Preferences file saved. Check the settings on your iPod after ejecting."
            )
        if self._draft:
            return self.tr(
                "Changes are not saved yet. Choose Apply to save them to this iPod."
            )
        if not any(
            row.edit is not None for section in self._sections() for row in section.rows
        ):
            return self.tr(
                "iPod preferences are read-only for this model and firmware."
            )
        if not controller.can_write:
            return self.tr(
                "Preferences cannot be saved while another device operation is in progress or the iPod is read-only."
            )
        return self.tr("Change the preferences below, then choose Apply.")

    def _update_actions(self) -> None:
        controller = self._controller
        self._draft_note.setText(self.status_text if controller else "")
        self._draft_note.setVisible(controller is not None)
        if controller is not None:
            assert (
                self._apply is not None
                and self._revert is not None
                and self._refresh is not None
            )
            self._apply.setEnabled(
                bool(self._draft)
                and controller.can_write
                and controller.active_ipod is self._active
            )
            self._revert.setEnabled(bool(self._draft) and not controller.busy)
            self._apply.setVisible(developer_flags.ENABLE_IPOD_PREFERENCES_WRITES)
            self._revert.setVisible(developer_flags.ENABLE_IPOD_PREFERENCES_WRITES)
            self._refresh.setEnabled(self._active is not None and not controller.busy)
        self.stateChanged.emit()

    def _control(
        self, section_key: str, row: IPodPreference, parent: QWidget
    ) -> QWidget:
        spec = (
            row.edit
            if self._controller is not None
            and developer_flags.ENABLE_IPOD_PREFERENCES_WRITES
            else None
        )
        key = (section_key, row.key)
        target = self._active
        name = f"ipodPreference_{section_key}_{row.key}"
        if spec is not None and spec.choices:
            combo = AppComboBox(parent)
            combo.setObjectName(name)
            original = spec.value
            selected = self._draft.get(key, original)
            if original not in {choice.value for choice in spec.choices}:
                combo.addItem(self.tr("Keep current setting"), original)
                combo.setToolTip(workflow_text(row.value))
            for choice in spec.choices:
                combo.addItem(workflow_text(choice.label), choice.value)
            combo.setCurrentIndex(combo.findData(selected))
            combo.setAccessibleName(workflow_text(row.title))
            combo.setEnabled(bool(self._controller and self._controller.can_write))

            def selected_choice() -> None:
                value: object = combo.currentData()
                if isinstance(value, int):
                    self._selected(key, value, original, target)

            combo.currentIndexChanged.connect(selected_choice)
            return combo
        if spec is not None and spec.minimum is not None and spec.maximum is not None:
            # A widget-only minimum represents "keep"; it is never sent to the
            # writer, so an unknown native integer is never clamped into a write.
            spin = QSpinBox(parent)
            spin.setObjectName(name)
            spin.setProperty("ipodPreferenceEditor", True)
            original = spec.value
            unknown = not spec.minimum <= original <= spec.maximum
            sentinel = spec.minimum - 1
            spin.setRange(sentinel if unknown else spec.minimum, spec.maximum)
            if unknown:
                spin.setSpecialValueText(self.tr("Keep current setting"))
                spin.setToolTip(workflow_text(row.value))
            selected = self._draft.get(key, original)
            spin.setValue(sentinel if unknown and selected == original else selected)
            spin.setKeyboardTracking(False)
            spin.setAccessibleName(workflow_text(row.title))
            spin.setEnabled(bool(self._controller and self._controller.can_write))

            def selected_value(value: int) -> None:
                self._selected(
                    key,
                    original if unknown and value == sentinel else value,
                    original,
                    target,
                )

            spin.valueChanged.connect(selected_value)
            return spin
        value = QLabel(workflow_text(row.value), parent)
        value.setObjectName(name)
        value.setAccessibleName(workflow_text(row.title))
        value.setTextFormat(Qt.TextFormat.PlainText)
        value.setWordWrap(True)
        value.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        return value

    def retranslate_ui(self) -> None:
        self._title.setText(self.tr("iPod Preferences"))
        self._search.setPlaceholderText(self.tr("Search preferences"))
        self._search.setAccessibleName(self.tr("Search preferences"))
        self._search.setVisible(self._active is not None)
        self._no_matches.setText(self.tr("No preferences match your search."))
        self._no_matches.hide()
        editable = self._controller is not None and any(
            row.edit is not None for section in self._sections() for row in section.rows
        )
        self._note.setText(
            self.tr(
                "Changes are saved to the iPod's preferences file. The iPod may keep its current settings until it reloads them; check the settings on the iPod after ejecting."
            )
            if editable
            else self.tr(
                "Settings stored on your iPod. Only verified settings can be changed here; other values are preserved."
            )
        )
        self._note.setVisible(
            self._active is not None and developer_flags.ENABLE_IPOD_PREFERENCES_WRITES
        )
        if self._refresh is not None:
            self._refresh.setText(
                QCoreApplication.translate("CommonActions", "Refresh")
            )
        if self._apply is not None:
            self._apply.setText(QCoreApplication.translate("CommonActions", "Apply"))
        if self._revert is not None:
            self._revert.setText(self.tr("Revert"))
        self._search_sections.clear()
        while item := self._body_layout.takeAt(0):
            widget = item.widget()
            if widget is not None:
                # A queued layout show can run before deferred deletion.
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        active = self._active
        if active is None:
            self._status.setText(
                self.tr("Connect and select an iPod to view its preferences.")
            )
            self._update_actions()
            return
        self._status.setText(active.display_name)
        sections = self._sections()
        available = {
            (section.key, row.key)
            for section in sections
            for row in section.rows
            if row.edit is not None
        }
        self._draft = {
            key: value for key, value in self._draft.items() if key in available
        }
        if not sections:
            label = QLabel(
                self.tr("Preferences have not been loaded for this iPod."), self._body
            )
            label.setWordWrap(True)
            self._body_layout.addWidget(label)
        for section in sections:
            container = QWidget(self._body)
            section_layout = QVBoxLayout(container)
            section_layout.setContentsMargins(0, 0, 0, 0)
            section_layout.setSpacing(LAYOUT.space_sm)
            title = QLabel(workflow_text(section.title), container)
            title.setObjectName("sectionTitle")
            title.setTextFormat(Qt.TextFormat.PlainText)
            section_layout.addWidget(title)
            if section.detail:
                detail = QLabel(workflow_text(section.detail), container)
                detail.setObjectName(f"ipodPreferenceStatus_{section.key}")
                detail.setTextFormat(Qt.TextFormat.PlainText)
                detail.setWordWrap(True)
                section_layout.addWidget(detail)
            categories: dict[str, list[IPodPreference]] = {}
            for row in section.rows:
                categories.setdefault(row.category, []).append(row)
            groups: list[_SearchGroup] = []
            # Everyday controls come before opaque firmware state, while every
            # observation remains searchable and available in the same page.
            for category, rows in sorted(
                categories.items(),
                key=lambda item: (
                    item[0] in ("Internal", "Temporary settings", "Resume")
                ),
            ):
                category_container = QWidget(container)
                category_layout = QVBoxLayout(category_container)
                category_layout.setContentsMargins(0, 0, 0, 0)
                category_layout.setSpacing(LAYOUT.space_xs)
                if category and len(categories) > 1:
                    heading = QLabel(workflow_text(category), category_container)
                    heading.setTextFormat(Qt.TextFormat.PlainText)
                    heading.setObjectName("sectionTitle")
                    category_layout.addWidget(heading)
                group = SettingGroup(category_container)
                searchable: list[tuple[SettingRow, str]] = []
                for row in rows:
                    value = self._control(section.key, row, group)
                    description = workflow_text(row.detail) if row.detail else ""
                    widget = SettingRow(workflow_text(row.title), "", value, group)
                    for label in widget.findChildren(QLabel):
                        label.setTextFormat(Qt.TextFormat.PlainText)
                    context = [workflow_text(row.value)]
                    if description:
                        context.append(description)
                    if row.raw_value:
                        context.append(
                            self.tr("Stored value: {value}").format(value=row.raw_value)
                        )
                    if description or row.raw_value:
                        # Long firmware notes are available on demand; they do
                        # not overwhelm the ordinary settings list. Never let
                        # captured XML text become rich-text markup.
                        explanation = "\n".join(context)
                        value.setToolTip(
                            "<qt>" + escape(explanation).replace("\n", "<br>") + "</qt>"
                        )
                        value.setAccessibleDescription(explanation)
                        widget.setToolTip(value.toolTip())
                    group.add_row(widget)
                    searchable.append(
                        (
                            widget,
                            " ".join(
                                (
                                    workflow_text(row.title),
                                    workflow_text(row.value),
                                    description,
                                    row.raw_value,
                                    workflow_text(row.category),
                                    row.key,
                                )
                            ).casefold(),
                        )
                    )
                category_layout.addWidget(group)
                section_layout.addWidget(category_container)
                groups.append(_SearchGroup(category_container, tuple(searchable)))
            self._body_layout.addWidget(container)
            self._search_sections.append(_SearchSection(container, tuple(groups)))
        self._filter_rows(self._search.text())
        self._update_actions()

    def _filter_rows(self, query: str) -> None:
        """Filtering hides views without changing drafts or publication authority."""
        query = query.strip().casefold()
        any_rows = False
        for section in self._search_sections:
            section_visible = not query
            for group in section.groups:
                visible = False
                for widget, text in group.rows:
                    matches = not query or query in text
                    widget.setVisible(matches)
                    visible |= matches
                group.container.setVisible(visible)
                section_visible |= visible
                any_rows |= visible
            section.container.setVisible(section_visible)
        self._no_matches.setVisible(bool(query) and not any_rows)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._controller is not None and not self._draft:
            self._controller.refresh()
