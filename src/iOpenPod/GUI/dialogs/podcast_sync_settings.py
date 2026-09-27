"""Per-Podcast settings for automatic Episode selection and removal during Sync."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.podcasts.models import (
    PodcastClearAge,
    PodcastClearMethod,
    PodcastFillMode,
    PodcastSyncSettings,
)
from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, ActionButtonKind


class PodcastSyncSettingsDialog(QDialog):
    """Stage a show's retention choices without writing or starting a Sync."""

    def __init__(
        self,
        title: str,
        settings: PodcastSyncSettings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("podcastSyncSettingsDialog")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumWidth(480)

        self._title = QLabel(title, self)
        self._title.setObjectName("dialogTitle")
        self._title.setTextFormat(Qt.TextFormat.PlainText)
        self._title.setWordWrap(True)
        self._description = QLabel(self)
        self._description.setObjectName("pageDescription")
        self._description.setWordWrap(True)

        self._slots_label = QLabel(self)
        self._slots = QSpinBox(self)
        self._slots.setObjectName("podcastSyncEpisodeSlots")
        self._slots.setMinimumHeight(LAYOUT.control_height)
        self._slots.setRange(1, 50)
        self._slots.setValue(settings.episode_slots)
        self._slots_label.setBuddy(self._slots)

        self._fill_label = QLabel(self)
        self._fill = AppComboBox(self)
        self._fill.setObjectName("podcastSyncFillMode")
        for fill_mode in PodcastFillMode:
            self._fill.addItem("", fill_mode.value)
        self._fill.setCurrentIndex(self._fill.findData(settings.fill_mode.value))
        self._fill_label.setBuddy(self._fill)

        self._clear_listened = QCheckBox(self)
        self._clear_listened.setObjectName("podcastSyncClearListened")
        self._clear_listened.setChecked(settings.clear_when_listened)

        self._age_label = QLabel(self)
        self._age = AppComboBox(self)
        self._age.setObjectName("podcastSyncClearAge")
        for clear_age in PodcastClearAge:
            self._age.addItem("", clear_age.value)
        self._age.setCurrentIndex(self._age.findData(settings.clear_older_than.value))
        self._age_label.setBuddy(self._age)

        self._method_label = QLabel(self)
        self._method = AppComboBox(self)
        self._method.setObjectName("podcastSyncClearMethod")
        for clear_method in PodcastClearMethod:
            self._method.addItem("", clear_method.value)
        self._method.setCurrentIndex(self._method.findData(settings.clear_method.value))
        self._method_label.setBuddy(self._method)

        self._help = QLabel(self)
        self._help.setObjectName("pageDescription")
        self._help.setWordWrap(True)
        self._help.setMinimumWidth(400)

        self._clearing_title = QLabel(self)
        self._clearing_title.setObjectName("sectionTitle")
        self._clearing_title.setContentsMargins(0, LAYOUT.space_sm, 0, 0)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(LAYOUT.space_sm)
        form.addRow(self._slots_label, self._slots)
        form.addRow(self._fill_label, self._fill)
        form.addRow(self._clearing_title)
        form.addRow(self._clear_listened)
        form.addRow(self._age_label, self._age)
        form.addRow(self._method_label, self._method)

        self._cancel = ActionButton(parent=self)
        self._cancel.setObjectName("podcastSyncSettingsCancel")
        self._cancel.clicked.connect(self.reject)
        self._save = ActionButton(parent=self, kind=ActionButtonKind.PRIMARY)
        self._save.setObjectName("podcastSyncSettingsSave")
        self._save.setDefault(True)
        self._save.clicked.connect(self.accept)
        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(self._cancel)
        actions.addWidget(self._save)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT.space_lg,
            LAYOUT.space_lg,
            LAYOUT.space_lg,
            LAYOUT.space_lg,
        )
        layout.setSpacing(LAYOUT.space_sm)
        layout.addWidget(self._title)
        layout.addWidget(self._description)
        layout.addLayout(form)
        layout.addWidget(self._help)
        layout.addLayout(actions)
        self._fill.currentIndexChanged.connect(self._update_help)
        self._slots.valueChanged.connect(self._update_help)
        self._age.currentIndexChanged.connect(self._update_help)
        self._method.currentIndexChanged.connect(self._update_help)
        self.retranslate_ui()

    @property
    def selected_settings(self) -> PodcastSyncSettings:
        return PodcastSyncSettings(
            episode_slots=self._slots.value(),
            fill_mode=PodcastFillMode(str(self._fill.currentData())),
            clear_when_listened=self._clear_listened.isChecked(),
            clear_older_than=PodcastClearAge(str(self._age.currentData())),
            clear_method=PodcastClearMethod(str(self._method.currentData())),
        )

    def retranslate_ui(self) -> None:
        self.setWindowTitle(self.tr("Podcast Sync Settings"))
        self._description.setText(
            self.tr("Choose what to keep on your iPod when you sync.")
        )
        self._slots_label.setText(self.tr("Keep"))
        self._slots.setAccessibleName(self.tr("Episodes to keep"))
        self._slots.setToolTip(
            self.tr(
                "How many episodes to add automatically. You can still add extra episodes yourself."
            )
        )
        self._fill_label.setText(self.tr("Add"))
        self._fill.setAccessibleName(self.tr("Which episodes to add"))
        self._clearing_title.setText(self.tr("Make room"))
        self._clear_listened.setText(self.tr("After listening"))
        self._clear_listened.setAccessibleName(self.tr("Make room after listening"))
        self._age_label.setText(self.tr("Or after"))
        self._age.setAccessibleName(self.tr("Make room after time on iPod"))
        self._age.setToolTip(self.tr("Time since an episode was added to the iPod."))
        self._method_label.setText(self.tr("Remove"))
        self._method.setAccessibleName(self.tr("When to remove episodes"))
        labels = {
            "newest": self.tr("Newest episodes"),
            "next": self.tr("Next in order"),
            "never": self.tr("Never"),
            "immediate": self.tr("Every sync"),
            "1_day": self.tr("1 day on iPod"),
            "3_days": self.tr("3 days on iPod"),
            "1_week": self.tr("1 week on iPod"),
            "2_weeks": self.tr("2 weeks on iPod"),
            "1_month": self.tr("1 month on iPod"),
            "2_months": self.tr("2 months on iPod"),
            "3_months": self.tr("3 months on iPod"),
            "remove": self.tr("At next sync"),
            "replace": self.tr("Only when replaced"),
        }
        for combo in (self._fill, self._age, self._method):
            for index in range(combo.count()):
                combo.setItemText(index, labels[str(combo.itemData(index))])
        self._cancel.setText(self.tr("Cancel"))
        self._save.setText(self.tr("Save"))
        self._update_help()

    @Slot()
    @Slot(int)
    def _update_help(self, _index: int | None = None) -> None:
        newest = self._fill.currentData() == "newest"
        self._slots.setSuffix(
            self.tr(" episode") if self._slots.value() == 1 else self.tr(" episodes")
        )
        self._fill.setToolTip(
            self.tr("Adds the newest available episodes when there's room.")
            if newest
            else self.tr(
                "Continues after the newest episode you've listened to. "
                "Starts with the oldest if you haven't listened yet."
            )
        )
        self._method.setToolTip(
            self.tr("Keep old episodes until their replacements are ready.")
            if self._method.currentData() == "replace"
            else self.tr("Remove episodes even if there isn't another to add.")
        )
        skips_unlistened = not newest and self._age.currentData() != "never"
        self._help.setText(
            self.tr("Unlistened episodes removed after this time are skipped.")
            if skips_unlistened
            else ""
        )
        self._help.setVisible(skips_unlistened)

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)


__all__ = ["PodcastSyncSettingsDialog"]
