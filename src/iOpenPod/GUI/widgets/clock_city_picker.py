# Hallmark · component: city picker · modern-minimal · iOpenPod semantic palette
# pre-emit critique: P5 H5 E4 S5 R5 V4 · searchable native choices, keyboard access
"""Searchable city choice using the existing native theme."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCompleter, QListView, QWidget

from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iPodDB.alarms import ClockCity


class ClockCityPicker(AppComboBox):
    """Search only native choices; arbitrary typed text cannot create a city."""

    def __init__(
        self, cities: tuple[ClockCity, ...], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("alarmCity")
        self.setEditable(True)
        self.setInsertPolicy(AppComboBox.InsertPolicy.NoInsert)
        self.setSizeAdjustPolicy(
            AppComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.setMinimumContentsLength(20)
        for city in sorted(cities, key=lambda row: row.name.casefold()):
            self.addItem(f"{city.name} · {city.region_name}", city)
        completer = QCompleter(self.model(), self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        popup = QListView(self)
        popup.setProperty("themedComboPopup", True)
        popup.setFont(self.font())
        popup.setMouseTracking(True)
        completer.setPopup(popup)
        self.setCompleter(completer)
        self.setCurrentIndex(-1)
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        current = self.currentText()
        regions = (
            self.tr("Africa"),
            self.tr("Asia"),
            self.tr("Atlantic"),
            self.tr("Australia"),
            self.tr("Europe"),
            self.tr("North America"),
            self.tr("Pacific"),
            self.tr("South America"),
        )
        selected = self.selected_city()
        for index in range(self.count()):
            city: object = self.itemData(index)
            if isinstance(city, ClockCity):
                self.setItemText(index, f"{city.name} · {regions[city.region]}")
        if selected is not None:
            self.setCurrentIndex(self.findData(selected))
        else:
            self.setEditText(current)
        self.setAccessibleName(self.tr("City"))
        if (line := self.lineEdit()) is not None:
            line.setPlaceholderText(self.tr("Search cities…"))
            line.setClearButtonEnabled(True)

    def selected_city(self) -> ClockCity | None:
        text = self.currentText().strip().casefold()
        matches: list[ClockCity] = []
        for index in range(self.count()):
            city: object = self.itemData(index)
            if isinstance(city, ClockCity) and text in (
                city.name.casefold(),
                self.itemText(index).casefold(),
            ):
                matches.append(city)
        return matches[0] if len(matches) == 1 else None
