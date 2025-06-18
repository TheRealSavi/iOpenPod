import json
import os
import sys
import traceback
from PyQt6.QtCore import QRunnable, pyqtSignal, pyqtSlot, QObject, QThreadPool
from PyQt6.QtWidgets import QApplication, QWidget, QMainWindow, QHBoxLayout
from GUI.widgets.musicBrowser import MusicBrowser
from GUI.widgets.sidebar import Sidebar

ITUNESDB_PATH = r"C:\Users\JohnG\Documents\Coding Projects\iOpenPod\iOpenPod\idb.json"
ARTWORKDB_PATH = r"C:\Users\JohnG\Documents\Coding Projects\iOpenPod\iOpenPod\artdb.json"
ITHMB_FOLDER_PATH = r"C:\Users\JohnG\Documents\Coding Projects\iOpenPod\iOpenPod\testData\Artwork"
SPINNER_PATH = os.path.join(os.path.dirname(__file__), "spinner.svg")


class ThreadPoolSingleton:
    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = QThreadPool.globalInstance()
        return cls._instance


category_glyphs = {
    "Albums": "💿",
    "Artists": "🧑‍🎤",
    "Tracks": "🎵",
    "Playlists": "📂",
    "Genres": "📜"}


class Worker(QRunnable):
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    @pyqtSlot()
    def run(self):
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception:
            traceback.print_exc()
            exectype, value = sys.exc_info()[:2]
            self.signals.error.emit((exectype, value, traceback.format_exc()))
        else:
            self.signals.result.emit(result)
        finally:
            self.signals.finished.emit()


class WorkerSignals(QObject):
    finished = pyqtSignal()
    error = pyqtSignal(tuple)
    result = pyqtSignal(object)
    progress = pyqtSignal(int)


def AlbumLoaderThread():
    with open(ITUNESDB_PATH, "r") as f:
        data = json.load(f)
        items = []

    albums = data.get("mhla", [])
    tracks = data.get("mhlt", [])

    for album_entry in albums:
        artist = album_entry.get(
            "Artist (Used by Album Item)", "Unknown Artist")
        album = album_entry.get("Album (Used by Album Item)", "Unknown Album")

        matching_tracks = [
            track for track in tracks
            if track.get("Album") == album and track.get("Artist") == artist
        ]

        # if matching tracks has at least 1 track, get its mhii field
        mhiiLink = None
        if len(matching_tracks) > 0:
            mhiiLink = matching_tracks[0].get("mhiiLink")

        items.append({"artist": artist, "album": album, "mhiiLink": mhiiLink})
    return items


def TrackLoaderThread():
    with open(ITUNESDB_PATH, "r") as f:
        data = json.load(f)
        items = []

    tracks = data.get("mhlt", [])

    for track in tracks:
        items.append(track)
    return items


def ensure_readable_color(r, g, b, text_color=(255, 255, 255)):
    """
    Adjusts the background color to ensure at least 4.5:1 contrast with text.
    """
    def relative_luminance(rgb):
        """Calculate luminance as per WCAG formula."""
        def to_linear(c):
            c /= 255
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

        r, g, b = [to_linear(c) for c in rgb]
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    bg_lum = relative_luminance((r, g, b))
    text_lum = relative_luminance(text_color)

    # Ensure L_light > L_dark for ratio calculation
    L1, L2 = max(bg_lum, text_lum), min(bg_lum, text_lum)
    contrast = (L1 + 0.05) / (L2 + 0.05)

    # If contrast is too low, adjust brightness
    while contrast < 4.5:
        r, g, b = [min(255, c * 1.1) for c in (r, g, b)]  # Lighten
        bg_lum = relative_luminance((r, g, b))
        L1, L2 = max(bg_lum, text_lum), min(bg_lum, text_lum)
        contrast = (L1 + 0.05) / (L2 + 0.05)

        if contrast >= 4.5:
            break

        r, g, b = [max(0, c * 0.9) for c in (r, g, b)]  # Darken
        bg_lum = relative_luminance((r, g, b))
        L1, L2 = max(bg_lum, text_lum), min(bg_lum, text_lum)
        contrast = (L1 + 0.05) / (L2 + 0.05)

    return (int(r), int(g), int(b))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("iOpenPod")
        self.setGeometry(100, 100, 1280, 720)

        self.mainLayout = QHBoxLayout()

        self.contentContainer = QWidget()
        self.contentContainer.setLayout(self.mainLayout)
        self.setCentralWidget(self.contentContainer)

        self.sidebar = Sidebar()
        self.mainLayout.addWidget(self.sidebar)

        self.musicBrowser = MusicBrowser()
        self.mainLayout.addWidget(self.musicBrowser)

        self.sidebar.category_changed.connect(
            self.musicBrowser.updateCategory)  # Connect the signal to the slot
