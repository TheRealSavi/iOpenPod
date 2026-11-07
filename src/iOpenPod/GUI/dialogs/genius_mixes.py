"""Manual genre Mix selection and per-iPod automatic Mix settings.

Hallmark · component: Genius Mix chooser · genre: atmospheric · theme: iOpenPod
Pre-emit critique: P4 H4 E4 S4 R5 V4 · contrast: pass (40-41)
Audience: iPod music collectors · task: select mixes · tone: premium technical
States: default, hover, focus, pressed, disabled; shared actions own feedback states.
"""

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
from PySide6.QtGui import (
    QColor,
    QFocusEvent,
    QFont,
    QFontMetrics,
    QIcon,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFormLayout,
    QFrame,
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
from iOpenPod.GUI.presentation.theme.dynamic import (
    GeniusArtworkColors,
    genius_artwork_colors,
)
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


def _mix_colors(key: str, tokens: ThemeTokens) -> GeniusArtworkColors:
    accents = (
        tokens.artwork_blue,
        tokens.artwork_green,
        tokens.artwork_gold,
        tokens.artwork_coral,
        tokens.artwork_violet,
        tokens.artwork_slate,
    )
    return genius_artwork_colors(accents[_MIX_COLOR_INDEX[key]], tokens)


def _mix_icon(proposal: MixProposal, tokens: ThemeTokens) -> QIcon:
    colors = _mix_colors(proposal.definition.key, tokens)
    return glyph_icon(f"genius-mixes/{proposal.definition.key}", 80, colors.ink)


class _MixList(QListWidget):
    """Retain native multi-selection while exposing transient press feedback."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.pressed_index = QPersistentModelIndex()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.pressed_index = QPersistentModelIndex(
                self.indexAt(event.position().toPoint())
            )
        super().mousePressEvent(event)
        self.viewport().update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self.pressed_index = QPersistentModelIndex()
        super().mouseReleaseEvent(event)
        self.viewport().update()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Space:
            self.pressed_index = QPersistentModelIndex(self.currentIndex())
        super().keyPressEvent(event)
        self.viewport().update()

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        self.pressed_index = QPersistentModelIndex()
        super().keyReleaseEvent(event)
        self.viewport().update()

    def focusOutEvent(self, event: QFocusEvent) -> None:
        self.pressed_index = QPersistentModelIndex()
        super().focusOutEvent(event)
        self.viewport().update()

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.EnabledChange:
            self.pressed_index = QPersistentModelIndex()
            self.setCursor(
                Qt.CursorShape.PointingHandCursor
                if self.isEnabled()
                else Qt.CursorShape.ArrowCursor
            )
        super().changeEvent(event)


class _MixCardDelegate(QStyledItemDelegate):
    """Paint one compact, keyboard-readable Mix card in the horizontal chooser."""

    def __init__(
        self, tokens: ThemeTokens, typography: TypographyTokens, parent: _MixList
    ) -> None:
        super().__init__(parent)
        self._tokens = tokens
        self._typography = typography
        self._view = parent

    @property
    def title_font(self) -> QFont:
        font = QFont(self._typography.display)
        font.setPointSizeF(self._typography.album_card_title_pt)
        font.setWeight(QFont.Weight.DemiBold)
        return font

    @property
    def card_size(self) -> QSize:
        metrics = QFontMetrics(self.title_font)
        return QSize(
            max(208, metrics.height() * 8),
            184 + metrics.height() + LAYOUT.space_2xl,
        )

    def set_theme(self, tokens: ThemeTokens) -> None:
        self._tokens = tokens

    def sizeHint(
        self,
        _option: QStyleOptionViewItem,
        _index: QModelIndex | QPersistentModelIndex,
    ) -> QSize:
        return self.card_size

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        tokens = self._tokens
        state = option.state
        enabled = bool(state & QStyle.StateFlag.State_Enabled)
        selected = bool(state & QStyle.StateFlag.State_Selected)
        hovered = enabled and bool(state & QStyle.StateFlag.State_MouseOver)
        focused = bool(state & QStyle.StateFlag.State_HasFocus)
        pressed = enabled and index == self._view.pressed_index
        key = str(index.data(Qt.ItemDataRole.UserRole))
        colors = _mix_colors(key, tokens)
        card = QRectF(option.rect).adjusted(4, 4, -4, -4)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setLayoutDirection(option.direction)
        fill = (
            tokens.surface_pressed
            if pressed
            else tokens.surface_selected
            if selected
            else tokens.surface_hover
            if hovered
            else tokens.surface
        )
        painter.setBrush(QColor(fill))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(card, LAYOUT.radius_panel, LAYOUT.radius_panel)

        # Symbolic record artwork, separate from the semantic selection surface.
        artwork = QRectF(card.left(), card.top(), card.width(), 176)
        clip = QPainterPath()
        clip.addRoundedRect(card, LAYOUT.radius_panel, LAYOUT.radius_panel)
        painter.save()
        painter.setClipPath(clip)
        painter.fillRect(
            artwork, colors.field if enabled else QColor(tokens.surface_alt)
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(colors.line if enabled else QColor(tokens.border), 1))
        center = artwork.center()
        for diameter in (112, 140, 168):
            orbit = QRectF(
                center.x() - diameter / 2,
                center.y() - diameter / 2,
                diameter,
                diameter,
            )
            painter.drawArc(orbit, 25 * 16, 130 * 16)
            painter.drawArc(orbit, 205 * 16, 130 * 16)
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if isinstance(icon, QIcon):
            icon.paint(
                painter,
                QRectF(center.x() - 40, center.y() - 40, 80, 80).toRect(),
                Qt.AlignmentFlag.AlignCenter,
                QIcon.Mode.Normal if enabled else QIcon.Mode.Disabled,
            )
        painter.restore()

        # A persistent checkbox affordance makes multi-selection discoverable.
        marker_x = (
            card.left() + LAYOUT.space_sm
            if option.direction == Qt.LayoutDirection.RightToLeft
            else card.right() - LAYOUT.space_sm - LAYOUT.checkbox_indicator_size
        )
        marker = QRectF(
            marker_x,
            card.top() + LAYOUT.space_sm,
            LAYOUT.checkbox_indicator_size,
            LAYOUT.checkbox_indicator_size,
        )
        marker_fill = tokens.accent if enabled and selected else tokens.surface
        painter.setBrush(QColor(marker_fill))
        painter.setPen(QPen(QColor(tokens.accent) if selected else colors.ink, 1))
        painter.drawEllipse(marker)
        if selected:
            painter.setPen(
                QPen(
                    QColor(tokens.accent_ink if enabled else tokens.text_disabled),
                    2,
                    Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                    Qt.PenJoinStyle.RoundJoin,
                )
            )
            check = QPainterPath()
            check.moveTo(marker.left() + 6, marker.top() + 12)
            check.lineTo(marker.left() + 10, marker.top() + 16)
            check.lineTo(marker.left() + 18, marker.top() + 8)
            painter.drawPath(check)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(
            QPen(
                QColor(
                    tokens.accent
                    if selected
                    else tokens.border_strong
                    if hovered
                    else tokens.border
                ),
                2 if selected else 1,
            )
        )
        painter.drawRoundedRect(card, LAYOUT.radius_panel, LAYOUT.radius_panel)
        if focused:
            painter.setPen(QPen(QColor(tokens.focus), 2, Qt.PenStyle.DashLine))
            painter.drawRoundedRect(
                card.adjusted(-3, -3, 3, 3),
                LAYOUT.radius_panel + 3,
                LAYOUT.radius_panel + 3,
            )
        title = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        painter.setFont(self.title_font)
        painter.setPen(QColor(tokens.text if enabled else tokens.text_disabled))
        caption = QRectF(
            card.left() + LAYOUT.space_md,
            artwork.bottom(),
            card.width() - 2 * LAYOUT.space_md,
            card.bottom() - artwork.bottom(),
        )
        painter.drawText(
            caption,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeading,
            QFontMetrics(self.title_font).elidedText(
                title, Qt.TextElideMode.ElideRight, int(caption.width())
            ),
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
        self.resize(920, 424)
        self.setMinimumWidth(520)
        self._theme_manager = theme_manager
        self._proposals = tuple(proposal for proposal in proposals if proposal.eligible)
        tokens = theme_manager.tokens if theme_manager is not None else LIGHT_TOKENS
        typography = (
            theme_manager.typography
            if theme_manager is not None
            else resolve_typography()
        )
        self._heading = QLabel(self)
        self._heading.setObjectName("geniusMixDialogHeading")
        self._heading.setWordWrap(True)
        self._emblem = QLabel(self)
        self._emblem.setFixedSize(
            LAYOUT.minimum_touch_target, LAYOUT.minimum_touch_target
        )
        self._grid = _MixList(self)
        self._grid.setObjectName("geniusMixProposals")
        self._grid.setViewMode(QListView.ViewMode.IconMode)
        self._grid.setFlow(QListView.Flow.LeftToRight)
        self._grid.setWrapping(False)
        self._grid.setMovement(QListView.Movement.Static)
        self._grid.setResizeMode(QListView.ResizeMode.Fixed)
        self._grid.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        self._delegate = _MixCardDelegate(tokens, typography, self._grid)
        self._grid.setGridSize(self._delegate.card_size)
        self._grid.setFixedHeight(self._delegate.card_size.height() + LAYOUT.space_xl)
        self._grid.setSpacing(LAYOUT.space_2xs)
        self._grid.setMouseTracking(True)
        self._grid.setCursor(Qt.CursorShape.PointingHandCursor)
        self._grid.setItemDelegate(self._delegate)
        self._grid.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._grid.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._grid.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for proposal in self._proposals:
            item = QListWidgetItem(self._grid)
            item.setData(Qt.ItemDataRole.UserRole, proposal.definition.key)
            item.setSizeHint(self._delegate.card_size)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty = QLabel(self)
        self._empty.setObjectName("geniusMixEmpty")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setWordWrap(True)
        self._empty.setMinimumHeight(self._delegate.card_size.height())
        self._empty.setVisible(not self._proposals)
        self._grid.setVisible(bool(self._proposals))
        self._selection = QLabel(self)
        self._selection.setObjectName("geniusMixSelectionSummary")
        self._selection.setWordWrap(True)
        self._cancel = ActionButton(parent=self, kind=ActionButtonKind.QUIET)
        self._cancel.clicked.connect(self.reject)
        self._add = ActionButton(
            parent=self, kind=ActionButtonKind.PRIMARY, glyph="plus"
        )
        self._add.setObjectName("confirmAddGeniusMixes")
        self._add.setDefault(True)
        self._add.setEnabled(False)
        self._add.clicked.connect(self.accept)
        self._grid.itemSelectionChanged.connect(self._update_selection)
        for action in (self._cancel, self._add):
            action.setMinimumHeight(LAYOUT.control_height_large)
            action.setMinimumWidth(96)
        footer = QFrame(self)
        footer.setObjectName("geniusMixDialogFooter")
        actions = QHBoxLayout(footer)
        actions.setContentsMargins(
            LAYOUT.space_xl, LAYOUT.space_md, LAYOUT.space_xl, LAYOUT.space_md
        )
        actions.setSpacing(LAYOUT.space_sm)
        actions.addWidget(self._selection, 1)
        actions.addWidget(self._cancel)
        actions.addWidget(self._add)
        header = QHBoxLayout()
        header.setContentsMargins(
            LAYOUT.space_xl, LAYOUT.space_lg, LAYOUT.space_xl, LAYOUT.space_lg
        )
        header.setSpacing(LAYOUT.space_md)
        header.addWidget(self._emblem)
        header.addWidget(self._heading, 1)
        shelf = QVBoxLayout()
        shelf.setContentsMargins(
            LAYOUT.space_xl - LAYOUT.space_2xs,
            0,
            LAYOUT.space_xl - LAYOUT.space_2xs,
            LAYOUT.space_md,
        )
        shelf.addWidget(self._grid)
        shelf.addWidget(self._empty)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(header)
        layout.addLayout(shelf, 1)
        layout.addWidget(footer)
        if theme_manager is not None:
            theme_manager.effectiveThemeChanged.connect(self._refresh_theme)
        self._refresh_theme()
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
            instruction = self.tr("Select to add this mix")
            item.setToolTip(f"{item.text()}\n{instruction}")
        self._cancel.setText(QCoreApplication.translate("CommonActions", "Cancel"))
        self._add.setText(self.tr("Add"))
        self._update_selection()

    def _update_selection(self) -> None:
        count = len(self.selected_keys)
        self._add.setEnabled(count > 0)
        self._selection.setText(
            self.tr("%1 selected").replace("%1", str(count))
            if count
            else self.tr("Select your mixes")
            if self._proposals
            else ""
        )

    def _refresh_theme(self) -> None:
        tokens = (
            self._theme_manager.tokens
            if self._theme_manager is not None
            else LIGHT_TOKENS
        )
        self._delegate.set_theme(tokens)
        self._emblem.setPixmap(
            glyph_icon(
                "atom", LAYOUT.minimum_touch_target, QColor(tokens.accent)
            ).pixmap(
                QSize(LAYOUT.minimum_touch_target, LAYOUT.minimum_touch_target),
                self.devicePixelRatioF(),
            )
        )
        for row, proposal in enumerate(self._proposals):
            self._grid.item(row).setIcon(_mix_icon(proposal, tokens))
        self._grid.viewport().update()

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
        self._cancel.setText(QCoreApplication.translate("CommonActions", "Cancel"))
        self._save.setText(self.tr("Save"))

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate_ui()
        super().changeEvent(event)
