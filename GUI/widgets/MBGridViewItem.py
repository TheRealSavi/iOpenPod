from PyQt6.QtCore import Qt, QSize
from PyQt6.QtWidgets import QApplication, QLabel, QFrame, QVBoxLayout
from PyQt6.QtGui import QFont, QPixmap
from PIL.ImageQt import ImageQt
from ..imgMaker import find_image_by_imgId
from .scrollingLabel import ScrollingLabel


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
    self.layout = QVBoxLayout(self)
    self.layout.setContentsMargins(5,5,5,5)
    self.layout.setSpacing(5)
    
    self.mhiiLink = mhiiLink
    
    self.img_label = QLabel()
    self.img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    self.img_label.setFixedSize(QSize(200, 200))
    self.img_label.setStyleSheet("border: none; background: transparent;")
    
   
    self.layout.addWidget(self.img_label)
    self.loadImage()
    
    title_label = ScrollingLabel(album)
    title_label.setFont(QFont("Arial", 14, QFont.Weight.Bold))
    title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    title_label.setStyleSheet("border: none; background: transparent;")
    self.layout.addWidget(title_label)
    
    artist_label = ScrollingLabel(artist)
    artist_label.setFont(QFont("Arial", 12))
    artist_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    artist_label.setStyleSheet("border: none; background: transparent;")
    self.layout.addWidget(artist_label)
    
  def loadImage(self):
    from ..app import Worker, ThreadPoolSingleton
    self.worker = Worker(
      self.generateImage, self.mhiiLink
    )
    ThreadPoolSingleton.get_instance().start(self.worker)
    
    
  def generateImage(self, mhiiLink):
    from ..app import ITHMB_FOLDER_PATH, ARTWORKDB_PATH, ensure_readable_color
    result = find_image_by_imgId(ARTWORKDB_PATH, ITHMB_FOLDER_PATH, mhiiLink)
    
    if result is None:
      emoji = "❓" + str(mhiiLink)
      self.img_label.setText(emoji)
      self.img_label.setFont(QFont("Arial", 48))
      return
    
    pil_image, dcol = result
    if pil_image is not None:
      qimage = ImageQt(pil_image)
      pixmap = QPixmap.fromImage(qimage)
      pixmap = pixmap.scaled(200,200, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
      self.img_label.setPixmap(pixmap)
      if dcol:
        r, g, b = ensure_readable_color(*dcol)
        self.setStyleSheet(f"""
        QFrame {{
            background-color: rgb({r}, {g}, {b});
            border: none;
            border-radius: 10px;
            padding: 5px;
            color: white;
        }}
        QFrame:hover {{
            background-color: rgba({r}, {g}, {b}, 200);
        }}
    """)
   
    QApplication.processEvents()
    