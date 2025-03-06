import json
import sys
#sys used to access the command line arguments
from PyQt6.QtCore import Qt, QSize, QPropertyAnimation, pyqtProperty, QAbstractAnimation, QThread, pyqtSignal
from PyQt6.QtWidgets import QApplication, QAbstractItemView, QTableWidgetItem, QHeaderView, QTableWidget, QWidget, QScrollArea, QLabel, QFrame, QSplitter, QMainWindow, QPushButton, QVBoxLayout, QHBoxLayout, QGridLayout, QStackedLayout, QTabWidget, QSizePolicy
from PyQt6.QtGui import QColor, QPalette, QFont, QPainter, QFontMetrics, QPixmap
from PIL.ImageQt import ImageQt
from imgMaker import find_image_by_imgId

ITUNESDB_PATH = r"C:\Users\JohnG\Documents\Coding Projects\iOpenPod\iOpenPod\idb.json"
ARTWORKDB_PATH = r"C:\Users\JohnG\Documents\Coding Projects\iOpenPod\iOpenPod\artdb.json"
ITHMB_FOLDER_PATH = r"C:\Users\JohnG\Documents\Coding Projects\iOpenPod\iOpenPod\testData\Artwork"

category_glyphs = {
  "Albums": "💿",
  "Artists": "🧑‍🎤",
  "Tracks": "🎵",
  "Playlists": "📂",
  "Genres": "📜"}

class AlbumLoaderThread(QThread):
  data_loaded = pyqtSignal(list) #signal to return parsed data
  
  def __init__(self ):
    super().__init__()
  def run(self):
    with open(ITUNESDB_PATH, "r") as f:
      data = json.load(f)
      items = []
      
      albums = data.get("mhla", [])
      tracks = data.get("mhlt", [])
      
    
    for album_entry in albums:
      artist = album_entry.get("Artist (Used by Album Item)", "Unknown Artist")
      album = album_entry.get("Album (Used by Album Item)", "Unknown Album")
      matching_tracks = [
        track for track in tracks
        if track.get("Album") == album and track.get("Artist") == artist
      ]
      #if matching tracks has at least 1 track, get its mhii field
      if matching_tracks:
        mhiiLink = matching_tracks[0].get("mhiiLink")
        
      items.append({"artist": artist, "album": album, "mhiiLink": mhiiLink})
    self.data_loaded.emit(items)
    
class TrackLoaderThread(QThread):
  data_loaded = pyqtSignal(list) #signal to return parsed data
  
  def __init__(self ):
    super().__init__()
  
  def run(self):
    with open(ITUNESDB_PATH, "r") as f:
      data = json.load(f)
      items = []
      
      tracks = data.get("mhlt", [])
      
      for track in tracks:
        items.append(track)
        
    self.data_loaded.emit(items)
    
    
    
class ScrollingLabel(QLabel):
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

class Sidebar(QFrame):
  def __init__(self):
      super().__init__()
      self.setStyleSheet(
        "background-color: rgba(255,255,255,26);"
        "border: 1px solid rgba(255,255,255,51);"
        "border-radius: 10px;"
      )
              
      self.layout = QVBoxLayout(self)
      self.layout.setContentsMargins(10, 10, 10, 10)
      self.layout.setSpacing(15)
      self.setFixedWidth(200)
      
      self.deviceSelectLayout = QHBoxLayout()
      self.deviceSelectLayout.setContentsMargins(0, 0, 0, 0)
      self.deviceSelectLayout.setSpacing(10)
      
      self.deviceButton = QPushButton("📱 Device")
      self.syncButton = QPushButton("🔄️ Sync")
      
      self.deviceButton.setStyleSheet(
        "QPushButton {"
        "background-color: rgba(255,255,255,51);"
        "border: none;"
        "color: white;"
        "padding: 10px 0;"
        "}"
        "QPushButton:hover {"
        "background-color: rgba(255,255,255,102);"
        "}"
      )
      self.syncButton.setStyleSheet(
        "QPushButton {"
        "background-color: rgba(255,255,255,51);"
        "border: none;"
        "color: white;"
        "padding: 10px 0;"
        "}"
        "QPushButton:hover {"
        "background-color: rgba(255,255,255,102);"
        "}"
      )
      self.deviceButton.setFont(QFont("Arial", 12, QFont.Weight.Bold))
      self.syncButton.setFont(QFont("Arial", 12, QFont.Weight.Bold))
      
      self.deviceSelectLayout.addWidget(self.deviceButton)
      self.deviceSelectLayout.addWidget(self.syncButton)
    
      self.layout.addLayout(self.deviceSelectLayout)
      
      self.buttons = {}
      
      for category, glyph in category_glyphs.items():
        btn = QPushButton(f"{glyph} {category}")
        btn.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        
        btn.setStyleSheet(
          "QPushButton {"
          "background-color: rgba(255,255,255,51);"
          "border: none;"
          "color: white;"
          "padding: 10px 0;"
          "}"
          "QPushButton:hover {"
          "background-color: rgba(255,255,255,102);"
          "}"
        )
        
        btn.clicked.connect(lambda clicked, category=category: self.selectCategory(category))
        
        self.layout.addWidget(btn)
        self.buttons[category] = btn
        
      self.layout.addStretch()
      
      self.selectedCategory = list(category_glyphs.keys())[0]
      self.selectCategory(self.selectedCategory)
        
  def selectCategory(self, category):
    # Reset the previous selected button's style
    self.buttons[self.selectedCategory].setStyleSheet(
      "QPushButton {"
      "background-color: rgba(255,255,255,51);"
      "border: none;"
      "color: white;"
      "padding: 10px 0;"
      "}"
      "QPushButton:hover {"
      "background-color: rgba(255,255,255,102);"
      "}"
    )
    
    self.selectedCategory = category
    #set the selected button's style
    self.buttons[self.selectedCategory].setStyleSheet(
      "QPushButton {"
      "background-color: rgba(0,122,204,255);"
      "border: none;"
      "color: white;"
      "padding: 10px 0;"
      "}"
      "QPushButton:hover {"
      "background-color: rgba(0,122,204,204);"
      "}"
)


class MusicBrowser(QWidget):
  def __init__(self):
    super().__init__()
    
    self.layout = QVBoxLayout(self)
    self.layout.setContentsMargins(0, 0, 0, 0)
    
    self.gridTrackSplitter = QSplitter(Qt.Orientation.Vertical)
    self.gridTrackSplitter.setStyleSheet(
      "QSplitter::handle {"
      "background-color: rgba(255,255,255,102);"
      "border: 1px solid rgba(0,0,0,102);"
      "width: 10px;"
      "height: 5px;"
      "margin: 2px;"
      "border-radius: 5px;"
      "}"
    )
    
    self.layout.addWidget(self.gridTrackSplitter)
    
    #Top: Grid Browser
    self.browserGrid = MusicBrowserGrid()
    self.browserGridScroll = QScrollArea()
    self.browserGridScroll.setWidgetResizable(True)
    self.browserGridScroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
    self.browserGridScroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    self.browserGridScroll.setWidget(self.browserGrid)
    
    self.gridTrackSplitter.addWidget(self.browserGridScroll)
    
    self.browserGrid.loadFromJSON()
    
    #Bottom: Track Browser
    self.browserTrack = MusicBrowserList()
    self.gridTrackSplitter.addWidget(self.browserTrack)
    
    self.browserTrack.loadFromJSON()
          
class MusicBrowserGrid(QWidget):
  def __init__(self):
    super().__init__()
    self.layout = QGridLayout(self)
    self.layout.setContentsMargins(0, 0, 0, 0)
    self.layout.setSpacing(10)
    self.layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
    self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
    self.gridItems = []
    
  def loadFromJSON(self):
    self.thread = AlbumLoaderThread()
    self.thread.data_loaded.connect(self.populateGrid)
    self.thread.start()
    
  def populateGrid(self, items):
    
    # Clear the layout (remove previous widgets)
    while self.layout.count():
      item = self.layout.takeAt(0)
      if item.widget():
        item.widget().setParent(None)
                
    self.columnCount = max(1, self.width() // (220 + 10))
    for i, item in enumerate(items):
      row = i // self.columnCount
      col = i % self.columnCount
      
      if isinstance(item, dict):
        # Create a new GridItem if item is a dictionary
        gridItem = MusicBrowserGridItem(item["album"], item["artist"], item["mhiiLink"])
        self.gridItems.append(gridItem)
      elif isinstance(item, MusicBrowserGridItem):
        # Reuse an existing GridItem
        gridItem = item
      else:
        raise TypeError("populateGrid() expected a dict or MusicBrowserGridItem")
      
      
      self.layout.addWidget(gridItem, row, col)
  
  def resizeEvent(self, event):
    newCols = max(1, self.width() // (220 + 10))
    if hasattr(self, "columnCount") and self.columnCount == newCols:
       super().resizeEvent(event)
       return
    
    if self.gridItems:
      self.populateGrid(self.gridItems)
   
    

class MusicBrowserList(QWidget):
  def __init__(self):
    super().__init__()
    self.layout = QHBoxLayout(self)
    self.layout.setContentsMargins(0, 0, 0, 0)
    self.tracks = []
    
  def loadFromJSON(self):
    self.thread = TrackLoaderThread()
    self.thread.data_loaded.connect(self.populateTable)
    self.thread.start()
      
  def populateTable(self, tracks):
      self.tracks = tracks

      # Collect all unique keys from all tracks
      all_keys = set(key for track in self.tracks for key in track.keys())
      
      # Create the table
      self.table = QTableWidget()
      self.table.setRowCount(len(self.tracks))
      self.table.setColumnCount(len(all_keys))
      
      # Set the headers
      self.table.setHorizontalHeaderLabels(sorted(all_keys))
      self.table.setSortingEnabled(True)
      self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
      self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
       
      # Stretch headers to fill the window
      header = self.table.horizontalHeader()
      header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
      
      # Populate the table
      for row, track in enumerate(self.tracks):
          for col, key in enumerate(sorted(all_keys)):
              value = track.get(key, "")  # Get the value or an empty string if key is missing
              self.table.setItem(row, col, QTableWidgetItem(str(value)))
      
      self.layout.addWidget(self.table)
      
      
class MusicBrowserGridItem(QFrame):
  def __init__(self, album, artist, mhiiLink):
    super().__init__()
    self.setFixedSize(QSize(220, 300))
    self.setStyleSheet("""
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
    layout = QVBoxLayout(self)
    layout.setContentsMargins(5,5,5,5)
    layout.setSpacing(5)
    
    img_label = QLabel()
    img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    img_label.setFixedSize(QSize(200, 200))
    img_label.setStyleSheet("border: none; background: transparent;")
    
    pil_image = find_image_by_imgId(ARTWORKDB_PATH, ITHMB_FOLDER_PATH, mhiiLink)
    if pil_image is not None:
      qimage = ImageQt(pil_image)
      pixmap = QPixmap.fromImage(qimage)
      pixmap = pixmap.scaled(200,200, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
      img_label.setPixmap(pixmap)
    else:
      emoji = "❓" + str(mhiiLink)
      img_label.setText(emoji)
      img_label.setFont(QFont("Arial", 48))
   
    layout.addWidget(img_label)
    
    title_label = ScrollingLabel(album)
    title_label.setFont(QFont("Arial", 14, QFont.Weight.Bold))
    title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    title_label.setStyleSheet("border: none; background: transparent;")
    layout.addWidget(title_label)
    
    artist_label = ScrollingLabel(artist)
    artist_label.setFont(QFont("Arial", 12))
    artist_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    artist_label.setStyleSheet("border: none; background: transparent;")
    layout.addWidget(artist_label)
    
    
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
        
        
        
    
#Need only 1 QApplication instance per application
#Pass in the command line arguments to the app
#TODO: Later in development if args arent needed,
#      replace with []
app = QApplication(sys.argv)

window = MainWindow()
window.show() #Window is hidden by default

#Start the event loop
app.exec()

#Rest of code is not reached until the window is closed
