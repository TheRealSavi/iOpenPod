"""Original-informed, grouped Review for an immutable selected Sync Plan."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.models.sync_plan_table_model import (
    SyncPlanFilterModel,
    SyncPlanTableModel,
)
from iOpenPod.app.sync_plan import SyncPlan, SyncPlanAction, SyncPlanMediaKind
from iOpenPod.GUI.presentation.i18n.text import (
    english_count_fallback,
    item_count_text,
    planned_change_count_text,
)
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.browser_chrome import PageHeader
from iOpenPod.GUI.widgets.search_field import SearchField
from iOpenPod.GUI.widgets.sync_review_group import SyncReviewGroup
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, ActionButtonKind

if TYPE_CHECKING:
    from iOpenPod.app.models.sync_selection import SyncSelection

_CHANGE_ACTIONS = frozenset(
    {
        SyncPlanAction.ADD,
        SyncPlanAction.UPDATE,
        SyncPlanAction.REMOVE,
        SyncPlanAction.ATTENTION,
    }
)


class SyncPlanPage(QWidget):
    """Review actions by category without changing earlier Host media selection."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("syncPlanPage")
        self._plan: SyncPlan | None = None
        self._selection: SyncSelection | None = None
        self._model = SyncPlanTableModel(self)
        self._proxy = SyncPlanFilterModel(self)
        self._proxy.setSourceModel(self._model)
        self._proxy.set_actions(_CHANGE_ACTIONS)

        self._header = PageHeader(self)
        self._header.title_label.setObjectName("syncPlanTitle")
        self._state = QLabel(self._header)
        self._state.setObjectName("pageMeta")
        self._header.add_action(self._state)
        self._description = QLabel(self)
        self._description.setObjectName("syncPlanDescription")
        self._description.setWordWrap(True)
        self._attention = QLabel(self)
        self._attention.setObjectName("syncPlanAttention")
        self._attention.setWordWrap(True)
        self._attention.hide()

        self._action_filter = AppComboBox(self)
        self._action_filter.setObjectName("syncPlanActionFilter")
        self._media_filter = AppComboBox(self)
        self._media_filter.setObjectName("syncPlanMediaFilter")
        for combo in (self._action_filter, self._media_filter):
            combo.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._search = SearchField(self)
        self._search.setObjectName("syncPlanSearch")
        self._results = QLabel(self)
        self._results.setObjectName("syncPlanResults")
        filters = QHBoxLayout()
        filters.setSpacing(LAYOUT.space_xs)
        filters.addWidget(self._action_filter)
        filters.addWidget(self._media_filter)
        filters.addStretch(1)
        filters.addWidget(self._search)
        filters.addWidget(self._results)

        self._groups: list[SyncReviewGroup] = []
        groups_body = QWidget(self)
        groups_body.setObjectName("syncReviewGroups")
        groups_layout = QVBoxLayout(groups_body)
        groups_layout.setContentsMargins(0, 0, LAYOUT.space_2xs, 0)
        groups_layout.setSpacing(LAYOUT.space_xs)
        for action, media in (
            (SyncPlanAction.ADD, SyncPlanMediaKind.TRACK),
            (SyncPlanAction.REMOVE, SyncPlanMediaKind.TRACK),
            (SyncPlanAction.UPDATE, SyncPlanMediaKind.TRACK),
            (SyncPlanAction.ADD, SyncPlanMediaKind.PHOTO),
            (SyncPlanAction.REMOVE, SyncPlanMediaKind.PHOTO),
            (SyncPlanAction.UPDATE, SyncPlanMediaKind.PHOTO),
            (SyncPlanAction.ATTENTION, None),
            (SyncPlanAction.UNCHANGED, None),
        ):
            group = SyncReviewGroup(self._proxy, action, media, groups_body)
            group.checkedRequested.connect(partial(self._set_group_checked, group))
            groups_layout.addWidget(group)
            self._groups.append(group)
        groups_layout.addStretch(1)
        self._scroll = QScrollArea(self)
        self._scroll.setObjectName("syncReviewScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setWidget(groups_body)
        self._empty = QLabel(self)
        self._empty.setObjectName("syncPlanEmpty")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setWordWrap(True)
        self._content = QStackedWidget(self)
        self._content.setObjectName("syncPlanContent")
        self._content.addWidget(self._scroll)
        self._content.addWidget(self._empty)

        # The workspace places these controls in its persistent review footer.
        self.review_actions = QWidget(self)
        actions_layout = QHBoxLayout(self.review_actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(LAYOUT.space_xs)
        self._select_all = ActionButton(parent=self.review_actions)
        self._select_all.setObjectName("syncReviewSelectAll")
        self._select_none = ActionButton(parent=self.review_actions)
        self._select_none.setObjectName("syncReviewSelectNone")
        self._expand_all = ActionButton(
            parent=self.review_actions, kind=ActionButtonKind.QUIET
        )
        self._expand_all.setObjectName("syncReviewExpandAll")
        self._collapse_all = ActionButton(
            parent=self.review_actions, kind=ActionButtonKind.QUIET
        )
        self._collapse_all.setObjectName("syncReviewCollapseAll")
        for button in (
            self._select_all,
            self._select_none,
            self._expand_all,
            self._collapse_all,
        ):
            actions_layout.addWidget(button)
        actions_layout.addStretch(1)
        self.review_actions.hide()
        self._select_all.clicked.connect(lambda: self._set_all_checked(True))
        self._select_none.clicked.connect(lambda: self._set_all_checked(False))
        self._expand_all.clicked.connect(lambda: self._set_expanded(True))
        self._collapse_all.clicked.connect(lambda: self._set_expanded(False))

        body = QVBoxLayout()
        body.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_sm, LAYOUT.space_lg, LAYOUT.space_md
        )
        body.setSpacing(LAYOUT.space_sm)
        body.addWidget(self._description)
        body.addWidget(self._attention)
        body.addLayout(filters)
        body.addWidget(self._content, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._header)
        layout.addLayout(body, 1)

        self._action_filter.currentIndexChanged.connect(self._filter_action)
        self._media_filter.currentIndexChanged.connect(self._filter_media)
        self._search.queryChanged.connect(self._proxy.set_query)
        self._proxy.modelReset.connect(self._filtered)
        self._proxy.rowsInserted.connect(self._filtered)
        self._proxy.rowsRemoved.connect(self._filtered)
        self.retranslate_ui()

    @property
    def plan(self) -> SyncPlan | None:
        return self._plan

    @property
    def model(self) -> SyncPlanTableModel:
        return self._model

    @property
    def proxy(self) -> SyncPlanFilterModel:
        return self._proxy

    @property
    def selection_summary(self) -> str:
        selected = self._plan.change_count if self._plan is not None else 0
        return english_count_fallback(
            "%1 of %Ln media change(s) selected",
            self.tr(
                "%1 of %Ln media change(s) selected",
                "",
                self._model.plan.change_count,
            ),
            self._model.plan.change_count,
        ).replace("%1", f"{selected:,}")

    def load_plan(self, plan: SyncPlan) -> None:
        self._set_selection(None)
        self._plan = plan
        self._model.replace_plan(plan)
        self._update_summary()
        self._filtered()

    def load_review(self, selection: SyncSelection) -> None:
        self._set_selection(selection)
        self._refresh_review()

    def clear_plan(self) -> None:
        self._set_selection(None)
        self._plan = None
        self._model.replace_plan(None)
        self._set_expanded(False)
        self._search.clear()
        self._proxy.set_query("")
        self._action_filter.setCurrentIndex(self._action_filter.findData("changes"))
        self._media_filter.setCurrentIndex(self._media_filter.findData("all"))
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        action_data = self._action_filter.currentData()
        media_data = self._media_filter.currentData()
        self._header.set_title(self.tr("Review Sync"))
        self._search.setPlaceholderText(self.tr("Search changes"))
        self._search.setAccessibleName(self.tr("Search the Sync Plan"))
        self._action_filter.setAccessibleName(self.tr("Filter Sync actions"))
        self._media_filter.setAccessibleName(self.tr("Filter media type"))
        self._action_filter.clear()
        for label, value in (
            (self.tr("Planned changes"), "changes"),
            (self.tr("All items"), "all"),
            (self.tr("Add"), SyncPlanAction.ADD.value),
            (self.tr("Update"), SyncPlanAction.UPDATE.value),
            (self.tr("Remove"), SyncPlanAction.REMOVE.value),
            (self.tr("In sync"), SyncPlanAction.UNCHANGED.value),
            (self.tr("Needs attention"), SyncPlanAction.ATTENTION.value),
        ):
            self._action_filter.addItem(label, value)
        self._media_filter.clear()
        for label, value in (
            (self.tr("Tracks + Photos"), "all"),
            (self.tr("Tracks"), SyncPlanMediaKind.TRACK.value),
            (self.tr("Photos"), SyncPlanMediaKind.PHOTO.value),
        ):
            self._media_filter.addItem(label, value)
        self._restore_filter(self._action_filter, action_data, "changes")
        self._restore_filter(self._media_filter, media_data, "all")
        self._select_all.setText(
            QCoreApplication.translate("CommonActions", "Select All")
        )
        self._select_none.setText(self.tr("Select None"))
        self._select_all.setToolTip(
            self.tr("Select all changes, including removals hidden by filters")
        )
        self._select_none.setToolTip(
            self.tr("Deselect all changes, including those hidden by filters")
        )
        self._expand_all.setText(self.tr("Expand All"))
        self._collapse_all.setText(self.tr("Collapse All"))
        for group in self._groups:
            group.retranslate_ui()
        self._model.retranslate()
        self._update_summary()
        self._filtered()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)

    def _update_summary(self) -> None:
        plan = self._plan or SyncPlan(())
        self._state.setText(
            self.selection_summary
            if self._selection is not None
            else planned_change_count_text(plan.change_count)
            if self._plan is not None
            else self.tr("No plan prepared")
        )
        self._description.setText(
            self.tr(
                "Choose the changes to include. iPod-only removals start unchecked."
            )
            if self._selection is not None
            else self.tr(
                "Review the proposed changes. Nothing has been changed on the iPod."
            )
        )
        self._attention.setVisible(plan.attention_count > 0)
        self._attention.setText(
            self._count_text(
                plan.attention_count,
                self.tr(
                    "1 item needs attention and is excluded from Sync. Expand Needs Attention to inspect it."
                ),
                self.tr(
                    "%1 items need attention and are excluded from Sync. Expand Needs Attention to inspect them."
                ),
            )
        )
        editable = self._selection is not None and self._model.plan.change_count > 0
        self._select_all.setEnabled(editable)
        self._select_none.setEnabled(editable)

    def _set_selection(self, selection: SyncSelection | None) -> None:
        if selection is self._selection:
            return
        if self._selection is not None:
            self._selection.changed.disconnect(self._refresh_review)
        self._selection = selection
        if selection is not None:
            selection.changed.connect(self._refresh_review)

    def _refresh_review(self) -> None:
        if self._selection is None:
            return
        self._plan = self._selection.selected_plan
        self._model.replace_plan(self._selection.review_plan, self._selection)
        self._update_summary()
        self._filtered()

    def _set_group_checked(self, group: SyncReviewGroup, checked: bool) -> None:
        if self._selection is not None:
            self._selection.set_review_items_checked(group.items(), checked)

    def _set_all_checked(self, checked: bool) -> None:
        if self._selection is not None:
            self._selection.set_review_items_checked(self._model.plan.items, checked)

    def _set_expanded(self, expanded: bool) -> None:
        for group in self._groups:
            group.set_expanded(expanded)

    def _filter_action(self) -> None:
        value = self._action_filter.currentData()
        if value == "changes":
            self._proxy.set_actions(_CHANGE_ACTIONS)
        elif value == "all":
            self._proxy.set_actions(None)
        else:
            try:
                action = SyncPlanAction(str(value))
            except ValueError:
                self._proxy.set_actions(_CHANGE_ACTIONS)
            else:
                self._proxy.set_actions(frozenset({action}))
        self._filtered()

    def _filter_media(self) -> None:
        try:
            media_kind = SyncPlanMediaKind(str(self._media_filter.currentData()))
        except ValueError:
            media_kind = None
        self._proxy.set_media_kind(media_kind)
        self._filtered()

    def _filtered(self) -> None:
        count = self._proxy.rowCount()
        self._results.setText(item_count_text(count))
        for group in self._groups:
            group.refresh()
        self._expand_all.setEnabled(count > 0)
        self._collapse_all.setEnabled(count > 0)
        if count:
            self._content.setCurrentWidget(self._scroll)
            return
        if self._plan is None:
            message = self.tr("Run Sync with Host to prepare a plan.")
        elif not self._model.plan.change_count and not self._model.plan.attention_count:
            message = self.tr(
                "No media changes to review. Your selected media is already in sync. Choose All items to inspect it, or edit your selection."
            )
        else:
            message = self.tr(
                "No items match these filters. Change a filter or clear the search to see the rest of the plan."
            )
        self._empty.setText(message)
        self._content.setCurrentWidget(self._empty)

    @staticmethod
    def _restore_filter(combo: AppComboBox, value: object, fallback: str) -> None:
        index = combo.findData(value)
        if index < 0:
            index = combo.findData(fallback)
        combo.setCurrentIndex(max(0, index))

    @staticmethod
    def _count_text(count: int, singular: str, plural: str) -> str:
        return singular if count == 1 else plural.replace("%1", f"{count:,}")


__all__ = ["SyncPlanPage"]
