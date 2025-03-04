import os
import json
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QComboBox, QGridLayout, QScrollArea, QFrame, QSplitter, QSizePolicy
)
from PyQt6.QtGui import QFont, QPixmap, QPainter, QFontMetrics
from PyQt6.QtCore import Qt, QSize, QPropertyAnimation, pyqtProperty, QAbstractAnimation
import sys

# Load JSON data from data.json in the parent directory.
base_path = os.path.dirname(os.path.abspath(__file__))
json_file = os.path.join(base_path, "..", "data.json")
with open(json_file, "r", encoding="utf-8") as f:
    json_data = json.load(f)

def elide_text(text, font, max_width):
    fm = QFontMetrics(font)
    return fm.elidedText(text, Qt.TextElideMode.ElideRight, max_width)

class ScrollingLabel(QLabel):
    """
    A QLabel that elides its text if too long, and when hovered, smoothly scrolls to reveal the full text.
    """
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._offset = 0
        self.animation = None
        self.setToolTip(text)

    def getOffset(self):
        return self._offset

    def setOffset(self, value):
        self._offset = value
        self.update()

    offset = pyqtProperty(int, fget=getOffset, fset=setOffset)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setFont(self.font())
        fm = QFontMetrics(self.font())
        full_width = fm.horizontalAdvance(self.text())
        if full_width > self.width():
            draw_rect = self.rect()
            draw_rect.setWidth(full_width)
            draw_rect.translate(-self._offset, 0)
            painter.drawText(draw_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.text())
        else:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.text())

    def enterEvent(self, event):
      fm = QFontMetrics(self.font())
      full_width = fm.horizontalAdvance(self.text())
      if full_width > self.width():
        scroll_distance = full_width - self.width()
        scroll_speed = 0.05  # Adjust speed: pixels per millisecond

        duration = int(scroll_distance / scroll_speed)  # Compute duration

        if self.animation is not None and self.animation.state() == QAbstractAnimation.State.Running:
            self.animation.stop()
        self.animation = QPropertyAnimation(self, b"offset")
        self.animation.setDuration(duration)
        self.animation.setStartValue(0)
        self.animation.setEndValue(scroll_distance)
        self.animation.setLoopCount(-1)
        self.animation.start()
      super().enterEvent(event)

    def leaveEvent(self, event):
        if self.animation is not None:
            self.animation.stop()
        self.setOffset(0)
        super().leaveEvent(event)

class TrackContainer(QWidget):
    """
    Displays the track list with a redesigned title bar that includes styled minimize/restore 
    and close buttons that respond to hover.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.normal_height = 350  # Desired expanded height
        self.is_minimized = False
        self._initUI()
        self.setMinimumHeight(30)  # Always show at least the title bar

    def _initUI(self):
        self.setStyleSheet("background-color: rgba(255,255,255,51); border-radius: 10px;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)  # Spacing between title bar and track list.
        # Title bar
        self.title_bar = QWidget()
        self.title_bar.setFixedHeight(30)
        self.title_bar.setStyleSheet(
            "background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(255,255,255,51), stop:1 rgba(255,255,255,26));"
            "border-top-left-radius: 10px; border-top-right-radius: 10px;"
            "padding: 5px; color: white;"
        )
        title_layout = QHBoxLayout(self.title_bar)
        title_layout.setContentsMargins(5, 0, 5, 0)
        self.title_label = QLabel("Tracks")
        self.title_label.setStyleSheet("color: white;")
        title_layout.addWidget(self.title_label)
        title_layout.addStretch()
        # Toggle button with bounding design.
        self.toggle_btn = QPushButton("-")
        self.toggle_btn.setFixedSize(20, 20)
        self.toggle_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(249, 226, 175, 255);
                border: 1px solid rgba(255,255,255,102);
                border-radius: 4px;
                color: white;
            }
            QPushButton:hover {
                background-color: rgba(250, 179, 135,255);
            }
        """)
        self.toggle_btn.clicked.connect(self.toggle_minimize)
        # Close button with bounding design.
        self.close_btn = QPushButton("x")
        self.close_btn.setFixedSize(20, 20)
        self.close_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(235, 160, 172, 255);
                border: 1px solid rgba(255,255,255,102);
                border-radius: 4px;
                color: white;
            }
            QPushButton:hover {
                background-color: rgba(243, 139, 168,255);
            }
        """)
        self.close_btn.clicked.connect(self.close_container)
        title_layout.addWidget(self.toggle_btn)
        title_layout.addWidget(self.close_btn)
        layout.addWidget(self.title_bar)
        # Track list widget.
        self.track_list = QListWidget()
        self.track_list.setStyleSheet("background-color: rgba(255,255,255,51); border: none; color: white; padding: 5px;")
        layout.addWidget(self.track_list)
        self.setVisible(False)

    def toggle_minimize(self):
        if self.is_minimized:
            self.restore()
        else:
            self.minimize()

    def minimize(self):
        self.track_list.hide()
        self.setFixedHeight(self.title_bar.height())
        self.toggle_btn.setText("[]")
        self.is_minimized = True

    def restore(self):
        self.track_list.show()
        self.setMinimumHeight(30)
        self.setMaximumHeight(16777215)
        self.resize(self.width(), self.normal_height)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.updateGeometry()
        self.toggle_btn.setText("-")
        self.is_minimized = False

    def close_container(self):
        self.setVisible(False)

    def populate(self, tracks, title="Tracks"):
        self.track_list.clear()
        if not tracks:
            self.track_list.addItem("No tracks found.")
        else:
            for track in tracks:
                self.track_list.addItem(track["Title"])
        self.title_label.setText(title)
        self.restore()
        self.setVisible(True)

class MusicBrowser(QWidget):
    """
    Main window that displays a fixed-width sidebar for category selection, a grid view of items,
    and an integrated track container.
    For Albums, grid items display a large image with two left-aligned text lines (album title and artist).
    For Artists and Genres, a similar design is used with one left-aligned text line.
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Music Browser")
        self.setGeometry(100, 100, 900, 600)
        self.setStyleSheet("background-color: rgba(18,18,18,204); color: white;")
        self.current_category = "Albums"
        self._initUI()

    def _initUI(self):
        main_layout = QVBoxLayout(self)
        content_layout = QHBoxLayout()
        # Sidebar container.
        sidebar_widget = QWidget()
        sidebar_widget.setFixedWidth(150)
        sidebar_widget.setStyleSheet(
            "background-color: rgba(255,255,255,26);"
            "border: 1px solid rgba(255,255,255,51);"
            "border-radius: 10px;"
        )
        sidebar_layout = QVBoxLayout(sidebar_widget)
        sidebar_layout.setContentsMargins(10, 10, 10, 10)
        sidebar_layout.setSpacing(15)
        self.buttons = {}
        # Responsive sidebar buttons.
        for category, glyph in [("Albums", "💿"), ("Artists", "🧑‍🎤"), ("Tracks", "🎵"), ("Genres", "📜")]:
            btn = QPushButton(f"{glyph} {category}")
            btn.setFont(QFont("Arial", 12, QFont.Weight.Bold))
            btn.setStyleSheet("""
                QPushButton { 
                    background-color: rgba(255,255,255,51);
                    border: none; 
                    padding: 10px; 
                    color: white; 
                }
                QPushButton:hover { 
                    background-color: rgba(255,255,255,102);
                }
            """)
            btn.clicked.connect(lambda checked, c=category: self.show_category(c))
            sidebar_layout.addWidget(btn)
            self.buttons[category] = btn
        sidebar_layout.addStretch()
        content_layout.addWidget(sidebar_widget)
        # Main area: vertical splitter with grid view and track container.
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        # Top: grid container.
        self.grid_container = QWidget()
        grid_layout = QVBoxLayout(self.grid_container)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        # Filter bar.
        self.filter_widget = QWidget()
        filter_layout = QHBoxLayout(self.filter_widget)
        filter_layout.setContentsMargins(5, 5, 5, 5)
        self.genre_filter = QComboBox()
        genres = sorted({track["Genre"] for track in json_data["mhlt"]})
        self.genre_filter.addItems(["All"] + genres)
        self.genre_filter.setStyleSheet(
            "background-color: rgba(255,255,255,51);"
            "border: 1px solid rgba(255,255,255,102);"
            "border-radius: 5px; padding: 5px; color: white;"
        )
        self.genre_filter.currentTextChanged.connect(lambda: self.show_category(self.current_category))
        filter_layout.addWidget(QLabel("Filter by Genre:"))
        filter_layout.addWidget(self.genre_filter)
        self.filter_widget.setStyleSheet(
            "background-color: rgba(255,255,255,26); border-radius: 10px; padding: 5px;"
        )
        grid_layout.addWidget(self.filter_widget)
        # Grid display area in a scroll area.
        self.main_display = QGridLayout()
        self.main_display.setSpacing(10)
        self.main_display.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        grid_widget = QWidget()
        grid_widget.setLayout(self.main_display)
        grid_widget.setStyleSheet("background-color: transparent;")
        scroll_area = QScrollArea()
        scroll_area.setWidget(grid_widget)
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("border: none;")
        grid_layout.addWidget(scroll_area)
        self.splitter.addWidget(self.grid_container)
        # Bottom: track container.
        self.track_container = TrackContainer()
        self.splitter.addWidget(self.track_container)
        self.track_container.setVisible(False)
        content_layout.addWidget(self.splitter)
        main_layout.addLayout(content_layout)
        # Taskbar at bottom (for restoring minimized track container), hidden by default.
        self.taskbar = QWidget()
        taskbar_layout = QHBoxLayout(self.taskbar)
        taskbar_layout.setContentsMargins(5, 5, 5, 5)
        self.tracks_task_btn = QPushButton("Tracks")
        self.tracks_task_btn.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        self.tracks_task_btn.setStyleSheet(
            "background-color: rgba(255,255,255,204);"
            "border: none; border-radius: 5px; padding: 5px; color: black;"
        )
        self.tracks_task_btn.clicked.connect(self.restore_tracks)
        taskbar_layout.addWidget(self.tracks_task_btn)
        taskbar_layout.addStretch()
        self.taskbar.setVisible(False)
        main_layout.addWidget(self.taskbar)
        self.setLayout(main_layout)
        self.show_category(self.current_category)
        self.splitter.splitterMoved.connect(self._enforce_minimum_track_height)

    def _enforce_minimum_track_height(self, pos, index):
        sizes = self.splitter.sizes()
        min_height = self.track_container.minimumHeight()
        if sizes[1] < min_height:
            sizes[1] = min_height
            sizes[0] = max(sizes[0] + sizes[1] - min_height, 0)
            self.splitter.setSizes(sizes)

    def clear_grid(self):
        while self.main_display.count():
            item = self.main_display.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def show_category(self, category):
        self.current_category = category
        self.clear_grid()
        if category == "Tracks":
            self.track_container.populate(self._get_all_tracks(), title="All Tracks")
        else:
            self.track_container.setVisible(False)
            self.taskbar.setVisible(False)
            self._populate_grid(category)

    def _populate_grid(self, category):
        if category == "Albums":
            items = [(album["Album (Used by Album Item)"],
                      album.get("Artist (Used by Album Item)", "Unknown"))
                     for album in json_data["mhla"]]
        elif category == "Artists":
            items = sorted({album.get("Artist (Used by Album Item)", "Unknown") for album in json_data["mhla"]})
        elif category == "Genres":
            items = sorted({track["Genre"] for track in json_data["mhlt"]})
        self._update_grid(items, category)

    def _create_grid_item(self, item, category):
        frame = QFrame()
        frame.setFixedSize(QSize(220, 300))
        frame.setStyleSheet("""
            QFrame {
                background-color: rgba(255,255,255,26);
                border: none;
                border-radius: 10px;
                padding: 5px;
                color: white;
            }
            QFrame:hover {
                background-color: rgba(255,255,255,38);
            }
        """)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        # Choose placeholder emoji based on category.
        if category == "Albums":
            emoji = "💿"
        elif category == "Artists":
            emoji = "🧑‍🎤"
        elif category == "Genres":
            emoji = "📜"
        else:
            emoji = "📀"
        img_label = QLabel(emoji)
        img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        img_label.setFont(QFont("Arial", 48))
        img_label.setFixedSize(200, 200)
        img_label.setStyleSheet("border: none; background: transparent;")
        layout.addWidget(img_label)
        if category == "Albums":
            title_label = ScrollingLabel(item[0])
            title_label.setFont(QFont("Arial", 14, QFont.Weight.Bold))
            title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            title_label.setStyleSheet("border: none; background: transparent;")
            artist_label = ScrollingLabel(item[1])
            artist_label.setFont(QFont("Arial", 12))
            artist_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            artist_label.setStyleSheet("border: none; background: transparent;")
            layout.addWidget(title_label)
            layout.addWidget(artist_label)
        else:
            text_label = ScrollingLabel(item)
            text_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
            text_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            text_label.setStyleSheet("border: none; background: transparent; padding-top: 5px;")
            layout.addWidget(text_label)
            layout.addWidget(QLabel(""))  # spacer
        frame.mousePressEvent = lambda event, i=item, c=category: self.show_tracks_for_item(i, c)
        return frame

    def _update_grid(self, items, category):
        self.clear_grid()
        col_count = max(1, self.width() // 250)
        row, col = 0, 0
        if category == "Albums":
            for item in items:
                grid_item = self._create_grid_item(item, category)
                self.main_display.addWidget(grid_item, row, col)
                col += 1
                if col >= col_count:
                    col = 0
                    row += 1
        else:
            for item in items:
                grid_item = self._create_grid_item(item, category)
                self.main_display.addWidget(grid_item, row, col)
                col += 1
                if col >= col_count:
                    col = 0
                    row += 1

    def show_tracks_for_item(self, item, category):
        if category == "Albums":
            tracks = [track for track in json_data["mhlt"] if track["Album"] == item[0]]
            title = item[0]
        elif category == "Artists":
            tracks = [track for track in json_data["mhlt"] if track["Artist"] == item]
            title = item
        elif category == "Genres":
            genre_filter = self.genre_filter.currentText()
            if genre_filter != "All":
                tracks = [track for track in json_data["mhlt"] if track["Genre"] == genre_filter]
            else:
                tracks = [track for track in json_data["mhlt"] if track["Genre"] == item]
            title = item
        else:
            tracks = []
            title = "Tracks"
        self.track_container.populate(tracks, title=title)
        self.splitter.setSizes([self.height() - self.track_container.normal_height, self.track_container.normal_height])
        self.updateTaskbarVisibility()

    def _get_all_tracks(self):
        genre_filter = self.genre_filter.currentText()
        if genre_filter != "All":
            return [track for track in json_data["mhlt"] if track["Genre"] == genre_filter]
        return json_data["mhlt"]

    def restore_tracks(self):
        self.track_container.restore()
        self.splitter.setSizes([self.height() - self.track_container.normal_height, self.track_container.normal_height])
        self.updateTaskbarVisibility()

    def updateTaskbarVisibility(self):
        if self.track_container.height() <= self.track_container.title_bar.height() + 5:
            self.taskbar.setVisible(True)
        else:
            self.taskbar.setVisible(False)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.show_category(self.current_category)
        if self.track_container.isVisible():
            self.splitter.setSizes([self.height() - self.track_container.normal_height, self.track_container.normal_height])

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MusicBrowser()
    window.show()
    sys.exit(app.exec())
