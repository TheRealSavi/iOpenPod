# SPDX-License-Identifier: LGPL-3.0-only
# Backported Qt declarations; see ../README.md for upstream provenance.
class QStyleOption:
    version: int
    type: int
    state: PySide6.QtWidgets.QStyle.StateFlag
    direction: PySide6.QtCore.Qt.LayoutDirection
    rect: PySide6.QtCore.QRect
    fontMetrics: PySide6.QtGui.QFontMetrics
    palette: PySide6.QtGui.QPalette
    styleObject: PySide6.QtCore.QObject

class QStyleOptionComplex:
    subControls: PySide6.QtWidgets.QStyle.SubControl
    activeSubControls: PySide6.QtWidgets.QStyle.SubControl

class QStyleOptionViewItem:
    displayAlignment: PySide6.QtCore.Qt.AlignmentFlag
    decorationAlignment: PySide6.QtCore.Qt.AlignmentFlag
    textElideMode: PySide6.QtCore.Qt.TextElideMode
    decorationPosition: PySide6.QtWidgets.QStyleOptionViewItem.Position
    decorationSize: PySide6.QtCore.QSize
    font: PySide6.QtGui.QFont
    showDecorationSelected: bool
    features: PySide6.QtWidgets.QStyleOptionViewItem.ViewItemFeature
    locale: PySide6.QtCore.QLocale
    widget: PySide6.QtWidgets.QWidget
    index: PySide6.QtCore.QModelIndex
    checkState: PySide6.QtCore.Qt.CheckState
    icon: PySide6.QtGui.QIcon
    text: str
    viewItemPosition: PySide6.QtWidgets.QStyleOptionViewItem.ViewItemPosition
    backgroundBrush: PySide6.QtGui.QBrush

class QStyleOptionSlider:
    orientation: PySide6.QtCore.Qt.Orientation
    minimum: int
    maximum: int
    tickPosition: PySide6.QtWidgets.QSlider.TickPosition
    tickInterval: int
    upsideDown: bool
    sliderPosition: int
    sliderValue: int
    singleStep: int
    pageStep: int
    notchTarget: float
    dialWrapping: bool
    keyboardModifiers: PySide6.QtCore.Qt.KeyboardModifier

class QStyleOptionButton:
    features: PySide6.QtWidgets.QStyleOptionButton.ButtonFeature
    text: str
    icon: PySide6.QtGui.QIcon
    iconSize: PySide6.QtCore.QSize

class QStyleOptionToolButton:
    features: PySide6.QtWidgets.QStyleOptionToolButton.ToolButtonFeature
    icon: PySide6.QtGui.QIcon
    iconSize: PySide6.QtCore.QSize
    text: str
    arrowType: PySide6.QtCore.Qt.ArrowType
    toolButtonStyle: PySide6.QtCore.Qt.ToolButtonStyle
    pos: PySide6.QtCore.QPoint
    font: PySide6.QtGui.QFont

class QLayout:
    def takeAt(self, index: int, /) -> PySide6.QtWidgets.QLayoutItem | None: ...

class QLayoutItem:
    def widget(self, /) -> PySide6.QtWidgets.QWidget | None: ...

class QBoxLayout:
    def takeAt(self, arg__1: int, /) -> PySide6.QtWidgets.QLayoutItem | None: ...

class QFormLayout:
    @typing.overload
    def itemAt(self, index: int, /) -> PySide6.QtWidgets.QLayoutItem | None: ...
    @typing.overload
    def itemAt(self, row: int, role: PySide6.QtWidgets.QFormLayout.ItemRole, /) -> PySide6.QtWidgets.QLayoutItem | None: ...

class QButtonGroup:
    def checkedButton(self, /) -> PySide6.QtWidgets.QAbstractButton | None: ...

class QTreeWidget:
    def currentItem(self, /) -> PySide6.QtWidgets.QTreeWidgetItem | None: ...

class QTreeWidgetItem:
    def child(self, index: int, /) -> PySide6.QtWidgets.QTreeWidgetItem | None: ...

class QMainWindow:
    def centralWidget(self, /) -> PySide6.QtWidgets.QWidget | None: ...

class QStackedWidget:
    def currentWidget(self, /) -> PySide6.QtWidgets.QWidget | None: ...

class QTabWidget:
    def widget(self, index: int, /) -> PySide6.QtWidgets.QWidget | None: ...
