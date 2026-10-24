"""Manual genre Mix selection and per-iPod automatic Mix settings."""

from PySide6.QtCore import (
    QT_TRANSLATE_NOOP,
    QCoreApplication,
    QEvent,
    QModelIndex,
    QPersistentModelIndex,
    QRectF,
    QSize,
    Qt,
)
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QSpinBox,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from iOpenPod.app.genius_mixes import MIX_CATALOG, MixPolicy, MixProposal
from iOpenPod.GUI.presentation.icons import glyph_icon
from iOpenPod.GUI.presentation.theme.manager import ThemeManager
from iOpenPod.GUI.presentation.theme.tokens import (
    LAYOUT,
    LIGHT_TOKENS,
    ThemeTokens,
    TypographyTokens,
    resolve_typography,
)
from iOpenPod.GUI.widgets.themed_buttons import ActionButton, ActionButtonKind

_MIX_LABELS = {
    "rock": QT_TRANSLATE_NOOP("GeniusMixNames", "Rock Mix"),
    "alternative": QT_TRANSLATE_NOOP("GeniusMixNames", "Alternative Mix"),
    "pop": QT_TRANSLATE_NOOP("GeniusMixNames", "Pop Mix"),
    "hard-rock": QT_TRANSLATE_NOOP("GeniusMixNames", "Hard Rock Mix"),
    "metal": QT_TRANSLATE_NOOP("GeniusMixNames", "Metal Mix"),
    "punk": QT_TRANSLATE_NOOP("GeniusMixNames", "Punk Mix"),
    "electronic": QT_TRANSLATE_NOOP("GeniusMixNames", "Electronic Mix"),
    "dance": QT_TRANSLATE_NOOP("GeniusMixNames", "Dance Mix"),
    "hip-hop": QT_TRANSLATE_NOOP("GeniusMixNames", "Hip-Hop Mix"),
    "soul": QT_TRANSLATE_NOOP("GeniusMixNames", "R&B and Soul Mix"),
    "jazz": QT_TRANSLATE_NOOP("GeniusMixNames", "Jazz Mix"),
    "blues": QT_TRANSLATE_NOOP("GeniusMixNames", "Blues Mix"),
    "country": QT_TRANSLATE_NOOP("GeniusMixNames", "Country Mix"),
    "folk": QT_TRANSLATE_NOOP("GeniusMixNames", "Folk and Acoustic Mix"),
    "classical": QT_TRANSLATE_NOOP("GeniusMixNames", "Classical Mix"),
    "reggae": QT_TRANSLATE_NOOP("GeniusMixNames", "Reggae Mix"),
    "latin": QT_TRANSLATE_NOOP("GeniusMixNames", "Latin Mix"),
    "soundtracks": QT_TRANSLATE_NOOP("GeniusMixNames", "Soundtrack Mix"),
    "focus": QT_TRANSLATE_NOOP("GeniusMixNames", "Focus Mix"),
    "love": QT_TRANSLATE_NOOP("GeniusMixNames", "Love Mix"),
    "energy": QT_TRANSLATE_NOOP("GeniusMixNames", "Energy Mix"),
    "relax": QT_TRANSLATE_NOOP("GeniusMixNames", "Relax Mix"),
}

_MIX_COLOR_INDEX = {
    "rock": 3,
    "alternative": 1,
    "pop": 2,
    "hard-rock": 0,
    "metal": 4,
    "punk": 3,
    "electronic": 0,
    "dance": 3,
    "hip-hop": 2,
    "soul": 4,
    "jazz": 0,
    "blues": 5,
    "country": 2,
    "folk": 1,
    "classical": 4,
    "reggae": 1,
    "latin": 3,
    "soundtracks": 5,
    "focus": 0,
    "love": 3,
    "energy": 2,
    "relax": 4,
}


def _mix_colors(key: str, tokens: ThemeTokens) -> tuple[QColor, QColor]:
    accents = (
        tokens.artwork_blue,
        tokens.artwork_green,
        tokens.artwork_gold,
        tokens.artwork_coral,
        tokens.artwork_violet,
        tokens.artwork_slate,
    )
    source = QColor(accents[_MIX_COLOR_INDEX[key]])
    hue = source.hue()
    saturation = source.saturation()
    surface = QColor()
    surface.setHsv(hue, max(55, saturation // 2), 44)
    ink = QColor()
    ink.setHsv(hue, max(165, saturation), 245)
    return surface, ink


def _mix_icon(proposal: MixProposal, tokens: ThemeTokens) -> QIcon:
    _, ink = _mix_colors(proposal.definition.key, tokens)
    return glyph_icon(f"genius-mixes/{proposal.definition.key}", 56, ink)


class _MixCardDelegate(QStyledItemDelegate):
    """Paint one compact, keyboard-readable Mix card in the horizontal chooser."""

    def __init__(
        self, tokens: ThemeTokens, typography: TypographyTokens, parent: QWidget
    ) -> None:
        super().__init__(parent)
        self._tokens = tokens
        self._typography = typography
        light_theme = QColor(tokens.window).lightness() >= 128
        self._selected_icon = glyph_icon(
            "check-circle",
            20,
            QColor(tokens.accent_ink if light_theme else tokens.text),
        )

    def sizeHint(
        self,
        _option: QStyleOptionViewItem,
        _index: QModelIndex | QPersistentModelIndex,
    ) -> QSize:
        return QSize(196, 180)

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        tokens = self._tokens
        state = option.state
        selected = bool(state & QStyle.StateFlag.State_Selected)
        hovered = bool(state & QStyle.StateFlag.State_MouseOver)
        focused = bool(state & QStyle.StateFlag.State_HasFocus)
        key = str(index.data(Qt.ItemDataRole.UserRole))
        surface, ink = _mix_colors(key, tokens)
        light_theme = QColor(tokens.window).lightness() >= 128
        card = QRectF(option.rect).adjusted(4, 4, -4, -4)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        background = surface.lighter(125 if selected else 115 if hovered else 100)
        painter.setBrush(background)
        border = QColor(ink)
        border.setAlpha(255 if selected else 120 if hovered else 55)
        painter.setPen(QPen(border, 2 if selected else 1))
        painter.drawRoundedRect(card, LAYOUT.radius_panel, LAYOUT.radius_panel)
        if focused:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(tokens.focus), 2))
            painter.drawRoundedRect(
                card.adjusted(2, 2, -2, -2),
                LAYOUT.radius_control,
                LAYOUT.radius_control,
            )
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if isinstance(icon, QIcon):
            icon.paint(
                painter,
                QRectF(card.center().x() - 28, card.top() + 25, 56, 56).toRect(),
            )
        if selected:
            self._selected_icon.paint(
                painter,
                QRectF(card.right() - 32, card.top() + 12, 20, 20).toRect(),
            )
        title = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        title_font = QFont(self._typography.display)
        title_font.setPointSizeF(self._typography.album_card_title_pt)
        title_font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(title_font)
        painter.setPen(QColor(tokens.accent_ink if light_theme else tokens.text))
        painter.drawText(
            QRectF(card.left() + 12, card.top() + 110, card.width() - 24, 48),
            Qt.AlignmentFlag.AlignHCenter
            | Qt.AlignmentFlag.AlignTop
            | Qt.TextFlag.TextWordWrap,
            title,
        )
        painter.restore()


class AddGeniusMixesDialog(QDialog):
    def __init__(
        self,
        proposals: tuple[MixProposal, ...],
        parent: QWidget | None = None,
        *,
        theme_manager: ThemeManager | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("addGeniusMixesDialog")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(832, 350)
        self.setMinimumSize(520, 350)
        self._proposals = tuple(proposal for proposal in proposals if proposal.eligible)
        tokens = theme_manager.tokens if theme_manager is not None else LIGHT_TOKENS
        typography = (
            theme_manager.typography
            if theme_manager is not None
            else resolve_typography()
        )
        self._heading = QLabel(self)
        self._heading.setObjectName("geniusMixDialogHeading")
        self._grid = QListWidget(self)
        self._grid.setObjectName("geniusMixProposals")
        self._grid.setViewMode(QListView.ViewMode.IconMode)
        self._grid.setFlow(QListView.Flow.LeftToRight)
        self._grid.setWrapping(False)
        self._grid.setMovement(QListView.Movement.Static)
        self._grid.setResizeMode(QListView.ResizeMode.Fixed)
        self._grid.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self._grid.setGridSize(QSize(196, 180))
        self._grid.setFixedHeight(200)
        self._grid.setSpacing(LAYOUT.space_2xs)
        self._grid.setMouseTracking(True)
        self._grid.setItemDelegate(_MixCardDelegate(tokens, typography, self._grid))
        self._grid.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._grid.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._grid.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._grid.horizontalScrollBar().setStyleSheet(
            "QScrollBar:horizontal {"
            f" height: {LAYOUT.space_xs}px; background: transparent; border: none;"
            " }"
            "QScrollBar::handle:horizontal {"
            f" margin: {LAYOUT.space_3xs + 1}px 0;"
            f" background: {tokens.border_strong};"
            f" border-radius: {LAYOUT.space_3xs // 2}px;"
            " }"
            "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {"
            " width: 0; border: none; background: transparent;"
            " }"
            "QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {"
            " background: transparent;"
            " }"
        )
        for proposal in self._proposals:
            item = QListWidgetItem(self._grid)
            item.setData(Qt.ItemDataRole.UserRole, proposal.definition.key)
            item.setIcon(_mix_icon(proposal, tokens))
            item.setSizeHint(QSize(196, 180))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty = QLabel(self)
        self._empty.setObjectName("geniusMixEmpty")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setVisible(not self._proposals)
        self._grid.setVisible(bool(self._proposals))
        self._cancel = ActionButton(parent=self)
        self._cancel.clicked.connect(self.reject)
        self._add = ActionButton(parent=self, kind=ActionButtonKind.PRIMARY)
        self._add.setObjectName("confirmAddGeniusMixes")
        self._add.setDefault(True)
        self._add.setEnabled(False)
        self._add.clicked.connect(self.accept)
        self._grid.itemSelectionChanged.connect(
            lambda: self._add.setEnabled(bool(self.selected_keys))
        )
        actions = QHBoxLayout()
        actions.setSpacing(LAYOUT.space_sm)
        actions.addStretch(1)
        actions.addWidget(self._cancel)
        actions.addWidget(self._add)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg
        )
        layout.setSpacing(0)
        layout.addWidget(self._heading)
        layout.addSpacing(LAYOUT.space_md)
        layout.addWidget(self._grid, 1)
        layout.addWidget(self._empty, 1)
        layout.addSpacing(LAYOUT.space_lg)
        layout.addLayout(actions)
        self.retranslate_ui()
        self._cancel.setFocus()

    @property
    def selected_keys(self) -> tuple[str, ...]:
        return tuple(
            str(item.data(Qt.ItemDataRole.UserRole))
            for item in self._grid.selectedItems()
        )

    def retranslate_ui(self) -> None:
        self.setWindowTitle(self.tr("Add Genius Mixes"))
        self._heading.setText(self.tr("Add Genius Mixes"))
        self._grid.setAccessibleName(self.tr("Proposed Genius Mixes"))
        self._empty.setText(self.tr("No Genius Mixes are available to add."))
        for index, proposal in enumerate(self._proposals):
            item = self._grid.item(index)
            item.setText(
                QCoreApplication.translate(
                    "GeniusMixNames", str(_MIX_LABELS[proposal.definition.key])
                )
            )
            item.setToolTip(self.tr("Select to add this mix"))
        self._cancel.setText(self.tr("Cancel"))
        self._add.setText(self.tr("Add"))

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)


class GeniusMixSettingsDialog(QDialog):
    def __init__(self, policy: MixPolicy, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("geniusMixSettingsDialog")
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setMinimumWidth(420)
        self._description = QLabel(self)
        self._description.setWordWrap(True)
        self._count_label = QLabel(self)
        self._count = QSpinBox(self)
        self._count.setObjectName("automaticGeniusMixCount")
        self._count.setMinimumHeight(LAYOUT.control_height)
        self._count.setRange(0, len(MIX_CATALOG))
        self._count.setValue(policy.count)
        self._count_label.setBuddy(self._count)
        self._expiry_label = QLabel(self)
        self._expiry = QSpinBox(self)
        self._expiry.setObjectName("automaticGeniusMixExpiry")
        self._expiry.setMinimumHeight(LAYOUT.control_height)
        self._expiry.setRange(1, 3650)
        self._expiry.setValue(policy.expiry_days)
        self._expiry_label.setBuddy(self._expiry)
        self._help = QLabel(self)
        self._help.setWordWrap(True)
        form = QFormLayout()
        form.addRow(self._count_label, self._count)
        form.addRow(self._expiry_label, self._expiry)
        self._cancel = ActionButton(parent=self)
        self._cancel.clicked.connect(self.reject)
        self._save = ActionButton(parent=self, kind=ActionButtonKind.PRIMARY)
        self._save.setObjectName("saveGeniusMixSettings")
        self._save.setDefault(True)
        self._save.clicked.connect(self.accept)
        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(self._cancel)
        actions.addWidget(self._save)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg, LAYOUT.space_lg
        )
        layout.addWidget(self._description)
        layout.addLayout(form)
        layout.addWidget(self._help)
        layout.addLayout(actions)
        self.retranslate_ui()

    @property
    def policy(self) -> MixPolicy:
        return MixPolicy(self._count.value(), self._expiry.value())

    def retranslate_ui(self) -> None:
        self.setWindowTitle(self.tr("Genius Mix Settings"))
        self._description.setText(
            self.tr("Automatically keep a selection of mixes on this iPod during Sync.")
        )
        self._count_label.setText(self.tr("Count"))
        self._count.setAccessibleName(self.tr("Automatic mix count"))
        self._count.setSpecialValueText(self.tr("Off"))
        self._expiry_label.setText(self.tr("Expiry (days)"))
        self._expiry.setAccessibleName(self.tr("Mix expiry in days"))
        self._help.setText(
            self.tr(
                "Expired mixes are replaced with a different random mix at the next Sync. If none is available, the current mix stays. Manual mixes never expire and do not count toward Count. Reducing Count removes excess automatic mixes at the next Sync."
            )
        )
        self._cancel.setText(self.tr("Cancel"))
        self._save.setText(self.tr("Save"))

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)
