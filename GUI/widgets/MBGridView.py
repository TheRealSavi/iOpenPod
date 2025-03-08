from PyQt6.QtCore import Qt, QRect, QTimer, QSize, QEvent
from PyQt6.QtWidgets import QApplication, QFrame, QGridLayout
from .MBGridViewItem import MusicBrowserGridItem

class MusicBrowserGrid(QFrame):
  
  def __init__(self):
    
    super().__init__()
    self.layout = QGridLayout(self)
    self.layout.setContentsMargins(0, 0, 0, 0)
    self.layout.setSpacing(10)
    self.layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

    self.gridItems = []
    
    # self.gridItemPool = {}
    # self.virtualizationTimer = QTimer(self)
    # self.virtualizationTimer.setSingleShot(True)
    # self.virtualizationTimer.timeout.connect(self.updateVisItems)
    
    # self.scrollConnect = False
    
  def loadFromJSON(self):
    from ..app import AlbumLoaderThread, ThreadPoolSingleton, Worker
    self.worker = Worker(
      AlbumLoaderThread
    )
    self.worker.signals.result.connect(self.populateGrid)
    ThreadPoolSingleton.get_instance().start(self.worker)
    
  def populateGrid(self, items):
    #store all the items for virtualization
    # self.gridItems = items
    
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
        QApplication.processEvents()
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
