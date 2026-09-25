"""Typed Playlist drafts with recursive Smart Playlist rule editing."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal, DecimalException
from typing import TYPE_CHECKING

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.GUI.presentation.theme.tokens import LAYOUT
from iOpenPod.GUI.widgets.app_combo_box import AppComboBox
from iOpenPod.GUI.widgets.themed_buttons import (
    ActionButton,
    ActionButtonKind,
    apply_action_button_kind,
)
from iPodDB.library import (
    Playlist,
    PlaylistKind,
    PlaylistSort,
    PlaylistSortOrder,
    SmartField,
    SmartLimitSort,
    SmartLimitUnit,
    SmartLocation,
    SmartMatch,
    SmartMediaKind,
    SmartOperator,
    SmartPlaylist,
    SmartPlaylistLimit,
    SmartPlaylistReference,
    SmartRule,
    SmartRuleGroup,
    SmartValueKind,
    playlist_sort_from_value,
    smart_operators,
    smart_value_kind,
    validate_smart_playlist,
)

if TYPE_CHECKING:
    from collections.abc import Mapping


def _tr(text: str) -> str:
    return QCoreApplication.translate("PlaylistEditorDialog", text)


def kind_label(kind: PlaylistKind) -> str:
    return {
        PlaylistKind.PLAYLIST: _tr("Playlist"),
        PlaylistKind.SMART: _tr("Smart Playlist"),
        PlaylistKind.FOLDER: _tr("Playlist Folder"),
    }[kind]


def playlist_sort_label(order: PlaylistSortOrder) -> str:
    return {
        PlaylistSortOrder.DEFAULT: _tr("Default"),
        PlaylistSortOrder.MANUAL: _tr("Manual"),
        PlaylistSortOrder.TITLE: _tr("Title"),
        PlaylistSortOrder.ALBUM: _tr("Album"),
        PlaylistSortOrder.ARTIST: _tr("Artist"),
        PlaylistSortOrder.BITRATE: _tr("Bitrate"),
        PlaylistSortOrder.GENRE: _tr("Genre"),
        PlaylistSortOrder.KIND: _tr("Kind"),
        PlaylistSortOrder.DATE_MODIFIED: _tr("Date modified"),
        PlaylistSortOrder.TRACK_NUMBER: _tr("Track number"),
        PlaylistSortOrder.SIZE: _tr("Size"),
        PlaylistSortOrder.DURATION: _tr("Time"),
        PlaylistSortOrder.YEAR: _tr("Year"),
        PlaylistSortOrder.SAMPLE_RATE: _tr("Sample rate"),
        PlaylistSortOrder.COMMENT: _tr("Comment"),
        PlaylistSortOrder.DATE_ADDED: _tr("Date added"),
        PlaylistSortOrder.EQUALIZER: _tr("Equalizer"),
        PlaylistSortOrder.COMPOSER: _tr("Composer"),
        PlaylistSortOrder.PLAY_COUNT: _tr("Play count"),
        PlaylistSortOrder.LAST_PLAYED: _tr("Last played"),
        PlaylistSortOrder.DISC_NUMBER: _tr("Disc number"),
        PlaylistSortOrder.RATING: _tr("Rating"),
        PlaylistSortOrder.RELEASE_DATE: _tr("Release date"),
        PlaylistSortOrder.BPM: _tr("BPM"),
        PlaylistSortOrder.GROUPING: _tr("Grouping"),
        PlaylistSortOrder.CATEGORY: _tr("Category"),
        PlaylistSortOrder.DESCRIPTION: _tr("Description"),
    }[order]


def field_label(field: SmartField) -> str:
    labels = {
        SmartField.TITLE: _tr("Title"),
        SmartField.ARTIST: _tr("Artist"),
        SmartField.ALBUM: _tr("Album"),
        SmartField.GENRE: _tr("Genre"),
        SmartField.YEAR: _tr("Year"),
        SmartField.PLAY_COUNT: _tr("Play count"),
        SmartField.RATING: _tr("Rating (stars)"),
        SmartField.BITRATE: _tr("Bitrate (kbps)"),
        SmartField.SAMPLE_RATE: _tr("Sample rate (Hz)"),
        SmartField.DURATION: _tr("Duration (milliseconds)"),
        SmartField.SIZE: _tr("Size (bytes)"),
        SmartField.ARTWORK: _tr("Has artwork"),
        SmartField.BPM: _tr("BPM"),
        SmartField.FILE_FORMAT: _tr("File format"),
        SmartField.TRACK_NUMBER: _tr("Track number"),
        SmartField.COMMENT: _tr("Comment"),
        SmartField.COMPOSER: _tr("Composer"),
        SmartField.DISC_NUMBER: _tr("Disc number"),
        SmartField.CHECKED: _tr("Checked"),
        SmartField.COMPILATION: _tr("Compilation"),
        SmartField.GROUPING: _tr("Grouping"),
        SmartField.DESCRIPTION: _tr("Description"),
        SmartField.CATEGORY: _tr("Category"),
        SmartField.SKIP_COUNT: _tr("Skip count"),
        SmartField.ALBUM_ARTIST: _tr("Album artist"),
        SmartField.SORT_TITLE: _tr("Sort title"),
        SmartField.SORT_ALBUM: _tr("Sort album"),
        SmartField.SORT_ARTIST: _tr("Sort artist"),
        SmartField.SORT_ALBUM_ARTIST: _tr("Sort album artist"),
        SmartField.SORT_COMPOSER: _tr("Sort composer"),
        SmartField.SORT_SHOW: _tr("Sort show"),
        SmartField.PLAYLIST: _tr("Playlist"),
        SmartField.PURCHASED: _tr("Purchased"),
        SmartField.MEDIA_KIND: _tr("Media kind"),
        SmartField.LOCATION: _tr("Location"),
        SmartField.DATE_MODIFIED: _tr("Date modified"),
        SmartField.DATE_ADDED: _tr("Date added"),
        SmartField.LAST_PLAYED: _tr("Last played"),
        SmartField.LAST_SKIPPED: _tr("Last skipped"),
    }
    return labels[field]


def operator_label(operator: SmartOperator) -> str:
    return {
        SmartOperator.IS: _tr("is"),
        SmartOperator.IS_NOT: _tr("is not"),
        SmartOperator.CONTAINS: _tr("contains"),
        SmartOperator.NOT_CONTAINS: _tr("does not contain"),
        SmartOperator.BEGINS_WITH: _tr("begins with"),
        SmartOperator.ENDS_WITH: _tr("ends with"),
        SmartOperator.GREATER_THAN: _tr("is greater than"),
        SmartOperator.LESS_THAN: _tr("is less than"),
        SmartOperator.BETWEEN: _tr("is between"),
        SmartOperator.IS_TRUE: _tr("is true"),
        SmartOperator.IS_FALSE: _tr("is false"),
        SmartOperator.IN_LAST: _tr("in the last"),
        SmartOperator.NOT_IN_LAST: _tr("not in the last"),
    }[operator]


def rules_editable(smart: SmartPlaylist) -> bool:
    try:
        validate_smart_playlist(smart)
    except ValueError:
        return False
    return True


def smart_summary(
    smart: SmartPlaylist, playlist_names: Mapping[int, str] | None = None
) -> str:
    if not rules_editable(smart):
        return _tr(
            "This Smart Playlist uses rules that cannot be edited yet. Its saved tracks are available below."
        )

    def describe(group: SmartRuleGroup) -> str:
        parts: list[str] = []
        for rule in group.rules:
            if isinstance(rule, SmartRuleGroup):
                parts.append("(" + describe(rule) + ")")
            elif isinstance(rule, SmartRule):
                value = (
                    ""
                    if smart_value_kind(rule.field) is SmartValueKind.BOOLEAN
                    else _rule_value_text(
                        rule.field,
                        rule.value,
                        rule.operator,
                        playlist_names,
                    )
                )
                if rule.upper_value is not None:
                    value += _tr(" and %1").replace(
                        "%1",
                        _rule_value_text(
                            rule.field,
                            rule.upper_value,
                            rule.operator,
                            playlist_names,
                        ),
                    )
                if rule.operator in (
                    SmartOperator.IN_LAST,
                    SmartOperator.NOT_IN_LAST,
                ) and isinstance(rule.value, int):
                    quantity, unit = _relative_period(rule.value)
                    value = f"{quantity} {_tr(unit)}"
                parts.append(
                    f"{field_label(rule.field)} {operator_label(rule.operator)} {value}".strip()
                )
        joiner = _tr(" AND ") if group.match is SmartMatch.ALL else _tr(" OR ")
        return joiner.join(parts) or (
            _tr("All tracks") if group.match is SmartMatch.ALL else _tr("No tracks")
        )

    summary = (
        describe(smart.rules)
        if smart.match_rules and smart.rules.rules
        else _tr("All tracks")
    )
    if smart.checked_only:
        summary += _tr(" · Checked tracks only")
    if smart.limit is not None:
        summary += (
            _tr(" · Limit: %1 %2")
            .replace("%1", str(smart.limit.value))
            .replace("%2", limit_unit_label(smart.limit.unit))
        )
    return summary


def limit_unit_label(unit: SmartLimitUnit) -> str:
    return {
        SmartLimitUnit.TRACKS: _tr("tracks"),
        SmartLimitUnit.MINUTES: _tr("minutes"),
        SmartLimitUnit.HOURS: _tr("hours"),
        SmartLimitUnit.MEGABYTES: _tr("MB"),
        SmartLimitUnit.GIGABYTES: _tr("GB"),
    }[unit]


def limit_sort_label(sort: SmartLimitSort) -> str:
    return {
        SmartLimitSort.RANDOM: _tr("Random"),
        SmartLimitSort.TITLE: _tr("Title"),
        SmartLimitSort.ALBUM: _tr("Album"),
        SmartLimitSort.ARTIST: _tr("Artist"),
        SmartLimitSort.GENRE: _tr("Genre"),
        SmartLimitSort.DATE_ADDED: _tr("Date added"),
        SmartLimitSort.PLAY_COUNT: _tr("Play count"),
        SmartLimitSort.LAST_PLAYED: _tr("Last played"),
        SmartLimitSort.RATING: _tr("Rating"),
    }[sort]


def _rule_value_text(
    field: SmartField,
    value: object,
    operator: SmartOperator = SmartOperator.IS,
    playlist_names: Mapping[int, str] | None = None,
) -> str:
    if isinstance(value, SmartPlaylistReference):
        return (
            playlist_names.get(value.playlist_id)
            if playlist_names is not None
            else None
        ) or _tr("Playlist %1").replace("%1", str(value.playlist_id))
    if isinstance(value, SmartMediaKind):
        return _media_kind_label(value)
    if isinstance(value, SmartLocation):
        return _location_label(value)
    if field is SmartField.RATING and isinstance(value, int):
        return format(Decimal(value) / 20, "g")
    if (
        smart_value_kind(field) is SmartValueKind.DATE
        and isinstance(value, int)
        and operator not in (SmartOperator.IN_LAST, SmartOperator.NOT_IN_LAST)
    ):
        return datetime.fromtimestamp(value, UTC).strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def _media_kind_label(kind: SmartMediaKind) -> str:
    return {
        SmartMediaKind.MUSIC: _tr("Music"),
        SmartMediaKind.MUSIC_VIDEO: _tr("Music video"),
        SmartMediaKind.MOVIE: _tr("Movie"),
        SmartMediaKind.TV_SHOW: _tr("TV show"),
        SmartMediaKind.PODCAST: _tr("Podcast"),
        SmartMediaKind.AUDIOBOOK: _tr("Audiobook"),
        SmartMediaKind.VOICE_MEMO: _tr("Voice memo"),
        SmartMediaKind.ITUNES_EXTRA: _tr("iTunes Extras"),
    }[kind]


def _location_label(location: SmartLocation) -> str:
    return {
        SmartLocation.LOCAL: _tr("On this device"),
        SmartLocation.CLOUD: _tr("In iCloud"),
    }[location]


_PERIOD_UNITS = (
    ("seconds", 1),
    ("minutes", 60),
    ("hours", 3600),
    ("days", 86400),
    ("weeks", 604800),
)


def _relative_period(seconds: int) -> tuple[int, str]:
    for name, factor in reversed(_PERIOD_UNITS):
        if seconds % factor == 0:
            return seconds // factor, name
    return seconds, "seconds"


class _RuleRow(QWidget):
    def __init__(
        self,
        rule: SmartRule,
        parent: QWidget,
        playlist_options: tuple[tuple[int, str], ...] = (),
    ) -> None:
        super().__init__(parent)
        self._playlist_options = playlist_options
        self._initial_field: SmartField | None = rule.field
        self._initial_value = rule.value
        self.setObjectName("smartRuleRow")
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.field = AppComboBox(self)
        self.field.setAccessibleName(self.tr("Rule field"))
        for field in SmartField:
            self.field.addItem(field_label(field), field.value)
        self.field.setCurrentIndex(self.field.findData(rule.field.value))
        self.operator = AppComboBox(self)
        self.operator.setAccessibleName(self.tr("Rule condition"))
        self.value = QLineEdit(
            _rule_value_text(rule.field, rule.value, rule.operator), self
        )
        self.value.setAccessibleName(self.tr("Rule value"))
        self.choice = AppComboBox(self)
        self.choice.setAccessibleName(self.tr("Rule choice"))
        self.upper = QLineEdit(self)
        self.upper.setAccessibleName(self.tr("Upper rule value"))
        self.upper.setPlaceholderText(self.tr("Upper value"))
        if rule.upper_value is not None:
            self.upper.setText(
                _rule_value_text(rule.field, rule.upper_value, rule.operator)
            )
        self.period_unit = AppComboBox(self)
        self.period_unit.setAccessibleName(self.tr("Rule time unit"))
        for name, factor in _PERIOD_UNITS:
            self.period_unit.addItem(_tr(name), factor)
        if rule.operator in (
            SmartOperator.IN_LAST,
            SmartOperator.NOT_IN_LAST,
        ) and isinstance(rule.value, int):
            quantity, unit = _relative_period(rule.value)
            self.value.setText(str(quantity))
            self.period_unit.setCurrentIndex(
                next(i for i, (name, _) in enumerate(_PERIOD_UNITS) if name == unit)
            )
        else:
            self.period_unit.setCurrentIndex(3)
        self.remove = ActionButton(
            self.tr("Remove"),
            self,
            kind=ActionButtonKind.DANGER,
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(LAYOUT.space_xs)
        layout.addWidget(self.field, 3)
        layout.addWidget(self.operator, 3)
        layout.addWidget(self.value, 5)
        layout.addWidget(self.choice, 5)
        layout.addWidget(self.upper, 5)
        layout.addWidget(self.period_unit)
        layout.addWidget(self.remove)
        self.field.currentIndexChanged.connect(self._field_changed)
        self.operator.currentIndexChanged.connect(self._operator_changed)
        self._field_changed()
        self.operator.setCurrentIndex(self.operator.findData(rule.operator.value))

    def _field_changed(self) -> None:
        field = SmartField(self.field.currentData())
        previous = self.operator.currentData()
        operators = smart_operators(field)
        self.operator.clear()
        for operator in operators:
            self.operator.addItem(operator_label(operator), operator.value)
        index = self.operator.findData(previous)
        self.operator.setCurrentIndex(max(0, index))
        self._populate_choice(
            field,
            self._initial_value if field is self._initial_field else None,
        )
        self._initial_field = None
        self._operator_changed()

    def _populate_choice(self, field: SmartField, selected: object | None) -> None:
        self.choice.clear()
        data: str | int | None
        if field is SmartField.MEDIA_KIND:
            for kind in SmartMediaKind:
                self.choice.addItem(_media_kind_label(kind), kind.value)
            data = selected.value if isinstance(selected, SmartMediaKind) else None
        elif field is SmartField.LOCATION:
            for location in SmartLocation:
                self.choice.addItem(_location_label(location), location.value)
            data = selected.value if isinstance(selected, SmartLocation) else None
        elif field is SmartField.PLAYLIST:
            for playlist_id, name in self._playlist_options:
                self.choice.addItem(name, playlist_id)
            data = (
                selected.playlist_id
                if isinstance(selected, SmartPlaylistReference)
                else None
            )
            if data is not None and self.choice.findData(data) < 0:
                self.choice.addItem(
                    self.tr("Missing Playlist (%1)").replace("%1", str(data)), data
                )
        else:
            data = None
        index = self.choice.findData(data)
        self.choice.setCurrentIndex(index if index >= 0 else 0)

    def _operator_changed(self) -> None:
        kind = smart_value_kind(SmartField(self.field.currentData()))
        choice = kind in (SmartValueKind.CHOICE, SmartValueKind.PLAYLIST)
        self.value.setVisible(kind is not SmartValueKind.BOOLEAN and not choice)
        self.choice.setVisible(choice)
        relative = self.operator.currentData() in (
            SmartOperator.IN_LAST.value,
            SmartOperator.NOT_IN_LAST.value,
        )
        self.period_unit.setVisible(relative)
        self.value.setPlaceholderText(
            self.tr("Amount of time")
            if relative
            else self.tr("UTC: YYYY-MM-DD HH:MM:SS")
            if kind is SmartValueKind.DATE
            else self.tr("Value")
        )
        self.value.setToolTip(self.value.placeholderText())
        self.upper.setVisible(
            self.operator.currentData() == SmartOperator.BETWEEN.value
        )

    def rule(self) -> SmartRule:
        field = SmartField(self.field.currentData())
        operator = SmartOperator(self.operator.currentData())
        value: str | int | SmartMediaKind | SmartLocation | SmartPlaylistReference = (
            self.value.text()
        )
        upper: str | int | None = (
            self.upper.text().strip() if operator is SmartOperator.BETWEEN else None
        )
        kind = smart_value_kind(field)
        if kind is SmartValueKind.BOOLEAN:
            value = 0
        elif kind is SmartValueKind.CHOICE:
            value = (
                SmartMediaKind(self.choice.currentData())
                if field is SmartField.MEDIA_KIND
                else SmartLocation(self.choice.currentData())
            )
        elif kind is SmartValueKind.PLAYLIST:
            playlist_id = self.choice.currentData()
            if not isinstance(playlist_id, int):
                raise ValueError(self.tr("Choose a Playlist for this rule."))
            value = SmartPlaylistReference(playlist_id)
        elif kind is not SmartValueKind.TEXT:

            def number(text: str | int) -> int:
                if field is SmartField.RATING:
                    return self._rating(text)
                if operator in (SmartOperator.IN_LAST, SmartOperator.NOT_IN_LAST):
                    try:
                        seconds = Decimal(text) * int(self.period_unit.currentData())
                        if (
                            not seconds.is_finite()
                            or not 0 < seconds <= 0x7FFFFFFFFFFFFFFF
                            or seconds != seconds.to_integral_value()
                        ):
                            raise ValueError
                        return int(seconds)
                    except (DecimalException, ValueError):
                        raise ValueError(
                            self.tr(
                                "Enter a positive period with whole-second precision."
                            )
                        ) from None
                if kind is SmartValueKind.DATE and operator not in (
                    SmartOperator.IN_LAST,
                    SmartOperator.NOT_IN_LAST,
                ):
                    try:
                        date = datetime.fromisoformat(str(text))
                        if date.microsecond:
                            raise ValueError("Date conditions use whole seconds")
                        if date.tzinfo is None:
                            date = date.replace(tzinfo=UTC)
                        return int(date.timestamp())
                    except (ValueError, OverflowError, OSError):
                        raise ValueError(
                            self.tr("Enter a UTC date: YYYY-MM-DD HH:MM:SS.")
                        ) from None
                try:
                    return int(text)
                except ValueError:
                    raise ValueError(
                        self.tr("Enter a whole number for numeric rules.")
                    ) from None

            value = number(self.value.text())
            upper = number(self.upper.text().strip()) if upper is not None else None
        assert isinstance(
            value,
            str | int | SmartMediaKind | SmartLocation | SmartPlaylistReference,
        )
        assert upper is None or isinstance(upper, str | int)
        return SmartRule(field, operator, value, upper)

    def _rating(self, text: str | int) -> int:
        try:
            rating = Decimal(text) * 20
            if (
                not rating.is_finite()
                or not 0 <= rating <= 100
                or rating != rating.to_integral_value()
            ):
                raise ValueError
            return int(rating)
        except (DecimalException, ValueError):
            raise ValueError(
                self.tr("Use a rating between 0 and 5 stars, in steps of 0.05.")
            ) from None


class _RuleGroupEditor(QWidget):
    """A group retains its conjunction and child order, including nested groups."""

    def __init__(
        self,
        group: SmartRuleGroup,
        parent: QWidget,
        depth: int = 0,
        playlist_options: tuple[tuple[int, str], ...] = (),
    ) -> None:
        super().__init__(parent)
        self._depth = depth
        self._playlist_options = playlist_options
        self.setObjectName("smartRuleGroup")
        self.setProperty("ruleGroupDepth", depth)
        self.setProperty(
            "ruleGroupTone",
            "base" if depth % 2 == 0 else "alternate",
        )
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Maximum,
        )
        self._children: list[_RuleRow | _RuleGroupEditor] = []
        self._layout = QVBoxLayout(self)
        inset = LAYOUT.space_sm if depth else LAYOUT.space_md
        self._layout.setContentsMargins(inset, inset, inset, inset)
        self._layout.setSpacing(LAYOUT.space_xs)
        row = QHBoxLayout()
        row.setSpacing(LAYOUT.space_xs)
        row.addWidget(QLabel(self.tr("Match"), self))
        self.match = AppComboBox(self)
        self.match.setAccessibleName(self.tr("Rule group match"))
        self.match.addItem(self.tr("all"), SmartMatch.ALL.value)
        self.match.addItem(self.tr("any"), SmartMatch.ANY.value)
        self.match.setCurrentIndex(self.match.findData(group.match.value))
        row.addWidget(self.match)
        row.addWidget(
            QLabel(
                self.tr("of the following rules")
                if depth == 0
                else self.tr("of these rules"),
                self,
            )
        )
        row.addStretch(1)
        add = ActionButton(self.tr("Add Rule"), self)
        add.clicked.connect(
            lambda: self.add_rule(
                SmartRule(SmartField.ARTIST, SmartOperator.CONTAINS, "")
            )
        )
        row.addWidget(add)
        add_group = ActionButton(self.tr("Add Group"), self)
        add_group.setEnabled(depth < 64)
        add_group.clicked.connect(lambda: self.add_group(SmartRuleGroup()))
        row.addWidget(add_group)
        self.remove = ActionButton(
            self.tr("Remove Group"),
            self,
            kind=ActionButtonKind.DANGER,
        )
        self.remove.setVisible(depth > 0)
        row.addWidget(self.remove)
        self._layout.addLayout(row)
        for rule in group.rules:
            if isinstance(rule, SmartRuleGroup):
                self.add_group(rule)
            elif isinstance(rule, SmartRule):
                self.add_rule(rule)

    def add_rule(self, rule: SmartRule) -> None:
        self._add(_RuleRow(rule, self, self._playlist_options))

    def add_group(self, group: SmartRuleGroup) -> None:
        self._add(
            _RuleGroupEditor(
                group,
                self,
                self._depth + 1,
                self._playlist_options,
            )
        )

    def _add(self, child: _RuleRow | _RuleGroupEditor) -> None:
        self._children.append(child)
        self._layout.addWidget(child)
        child.remove.clicked.connect(lambda: self._remove(child))

    def _remove(self, child: _RuleRow | _RuleGroupEditor) -> None:
        self._children.remove(child)
        self._layout.removeWidget(child)
        child.deleteLater()

    def rule(self) -> SmartRuleGroup:
        return SmartRuleGroup(
            SmartMatch(self.match.currentData()),
            tuple(child.rule() for child in self._children),
        )


class PlaylistEditorDialog(QDialog):
    """Return a typed edit; application code owns validation and application."""

    def __init__(
        self,
        kind: PlaylistKind,
        playlist: Playlist | None = None,
        parent: QWidget | None = None,
        *,
        playlists: tuple[Playlist, ...] = (),
    ) -> None:
        super().__init__(parent)
        self.setObjectName("playlistEditor")
        self.setWindowTitle(
            self.tr("Edit %1" if playlist else "New %1").replace("%1", kind_label(kind))
        )
        self.resize(
            900 if kind is PlaylistKind.SMART else 480,
            620 if kind is PlaylistKind.SMART else 280,
        )
        self._original = playlist.smart if playlist is not None else None
        self._smart = self._original or SmartPlaylist()
        self._can_edit_rules = rules_editable(self._smart)
        self._kind = kind
        current_id = playlist.playlist_id if playlist is not None else None
        self._playlist_options = tuple(
            (candidate.playlist_id, candidate.name)
            for candidate in playlists
            if candidate.playlist_id != current_id and not candidate.system_managed
        )
        self.smart: SmartPlaylist | None = self._original
        self.name = QLineEdit(playlist.name if playlist else "", self)
        self.name.setObjectName("playlistNameInput")
        self.description = QLineEdit(playlist.description if playlist else "", self)
        form = QFormLayout()
        form.addRow(self.tr("Name"), self.name)
        form.addRow(self.tr("Description"), self.description)
        initial_sort = (
            playlist.sort_order
            if playlist is not None
            else PlaylistSortOrder.DEFAULT
            if kind is PlaylistKind.FOLDER
            else PlaylistSortOrder.MANUAL
        )
        self._sort_order = AppComboBox(self)
        self._sort_order.setAccessibleName(self.tr("Playlist sort order"))
        for order in PlaylistSortOrder:
            self._sort_order.addItem(playlist_sort_label(order), order.value)
        if self._sort_order.findData(initial_sort.value) < 0:
            self._sort_order.addItem(
                self.tr("Unsupported (%1)").replace("%1", str(initial_sort.value)),
                initial_sort.value,
            )
        self._sort_order.setCurrentIndex(self._sort_order.findData(initial_sort.value))
        form.addRow(self.tr("Sort order"), self._sort_order)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT.space_md,
            LAYOUT.space_md,
            LAYOUT.space_md,
            LAYOUT.space_md,
        )
        layout.setSpacing(LAYOUT.space_sm)
        layout.addLayout(form)
        if kind is PlaylistKind.SMART:
            self._build_rules(layout)
        self._error = QLabel(self)
        self._error.setWordWrap(True)
        self._error.setObjectName("playlistEditorError")
        layout.addWidget(self._error)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(
            self.tr("Apply Changes")
        )
        apply_action_button_kind(
            buttons.button(QDialogButtonBox.StandardButton.Save),
            ActionButtonKind.PRIMARY,
        )
        apply_action_button_kind(
            buttons.button(QDialogButtonBox.StandardButton.Cancel),
            ActionButtonKind.SECONDARY,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.name.setFocus()

    @property
    def sort_order(self) -> PlaylistSort:
        return playlist_sort_from_value(int(self._sort_order.currentData()))

    def _build_rules(self, layout: QVBoxLayout) -> None:
        self._match_rules = QCheckBox(self.tr("Match rules"), self)
        self._match_rules.setChecked(self._smart.match_rules)
        layout.addWidget(self._match_rules)
        scroll = QScrollArea(self)
        scroll.setObjectName("smartRulesScroll")
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(180)
        if self._can_edit_rules:
            self._group = _RuleGroupEditor(
                self._smart.rules,
                self,
                playlist_options=self._playlist_options,
            )
            scroll.setWidget(self._group)
        else:
            explanation = QLabel(smart_summary(self._smart), self)
            explanation.setWordWrap(True)
            scroll.setWidget(explanation)
        layout.addWidget(scroll, 1)
        self._limit_enabled = QCheckBox(self.tr("Limit to"), self)
        self._limit_value = QLineEdit(
            str(self._smart.limit.value if self._smart.limit else 25), self
        )
        self._limit_value.setAccessibleName(self.tr("Track limit"))
        self._limit_unit = AppComboBox(self)
        for unit in SmartLimitUnit:
            self._limit_unit.addItem(limit_unit_label(unit), unit.value)
        self._limit_sort = AppComboBox(self)
        self._limit_sort.setAccessibleName(self.tr("Select tracks by"))
        for sort in SmartLimitSort:
            self._limit_sort.addItem(limit_sort_label(sort), sort.value)
        self._descending = QCheckBox(self.tr("Descending"), self)
        if self._smart.limit:
            self._limit_enabled.setChecked(True)
            self._limit_unit.setCurrentIndex(
                self._limit_unit.findData(self._smart.limit.unit.value)
            )
            self._limit_sort.setCurrentIndex(
                self._limit_sort.findData(self._smart.limit.sort.value)
            )
            self._descending.setChecked(self._smart.limit.descending)
        limit_row = QHBoxLayout()
        for widget in (
            self._limit_enabled,
            self._limit_value,
            self._limit_unit,
            self._limit_sort,
            self._descending,
        ):
            limit_row.addWidget(widget)
        layout.addLayout(limit_row)
        self._checked = QCheckBox(self.tr("Checked tracks only"), self)
        self._checked.setChecked(self._smart.checked_only)
        self._live = QCheckBox(self.tr("Live updating"), self)
        self._live.setChecked(self._smart.live_update)
        layout.addWidget(self._checked)
        layout.addWidget(self._live)
        for control in (
            self._match_rules,
            self._limit_enabled,
            self._limit_value,
            self._limit_unit,
            self._limit_sort,
            self._descending,
            self._checked,
            self._live,
        ):
            control.setEnabled(self._can_edit_rules)

    def accept(self) -> None:
        if not self.name.text().strip():
            self._error.setText(self.tr("Give this playlist or folder a name."))
            self.name.setFocus()
            return
        if self._kind is PlaylistKind.SMART and self._can_edit_rules:
            try:
                limit = None
                if self._limit_enabled.isChecked():
                    limit = SmartPlaylistLimit(
                        int(self._limit_value.text()),
                        SmartLimitUnit(self._limit_unit.currentData()),
                        SmartLimitSort(self._limit_sort.currentData()),
                        self._descending.isChecked(),
                    )
                smart = replace(
                    self._smart,
                    rules=self._group.rule(),
                    match_rules=self._match_rules.isChecked(),
                    checked_only=self._checked.isChecked(),
                    live_update=self._live.isChecked(),
                    limit=limit,
                )
                validate_smart_playlist(smart)
            except ValueError as error:
                self._error.setText(str(error))
                return
            self.smart = self._smart if smart == self._smart else smart
        super().accept()
