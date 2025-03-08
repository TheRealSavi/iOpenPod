from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication, QFrame, QGridLayout
from .MBGridViewItem import MusicBrowserGridItem

class MusicBrowserGrid(QFrame):
  
  def __init__(self):
    super().__init__()
    self.layout = QGridLayout(self)
    self.layout.setContentsMargins(0, 0, 0, 0)
    self.layout.setSpacing(10)
    self.layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

    self.gridItems = []  # Already added items
    self.pendingItems = []  # Items waiting to be added
    self.timerActive = False  # Prevent duplicate timers
    self.columnCount = 1  # Default column count
    
  def loadFromJSON(self):
    from ..app import AlbumLoaderThread, ThreadPoolSingleton, Worker
    self.worker = Worker(AlbumLoaderThread)
    self.worker.signals.result.connect(self.populateGrid)
    ThreadPoolSingleton.get_instance().start(self.worker)

  def populateGrid(self, items):
    # Only clear layout if new data is coming in (not resizing)
    if not self.gridItems:
      while self.layout.count():
        item = self.layout.takeAt(0)
        if item.widget():
          item.widget().deleteLater()  # Properly delete instead of detaching

    # Recalculate column count
    self.columnCount = max(1, self.width() // (220 + 10))

    if not self.gridItems:
      # If first load, reset pendingItems
      self.pendingItems = list(enumerate(items))
    else:
      # Recalculate positions of already-added items
      self.rearrangeGrid()

    # Start incremental loading if not active
    if self.pendingItems and not self.timerActive:
      self.timerActive = True
      self.addNextItem()

  def addNextItem(self):
    if not self.pendingItems:
      self.timerActive = False
      return

    i, item = self.pendingItems.pop(0)
    row = i // self.columnCount
    col = i % self.columnCount

    if isinstance(item, dict):
      gridItem = MusicBrowserGridItem(item["album"], item["artist"], item["mhiiLink"])
      self.gridItems.append(gridItem)
    elif isinstance(item, MusicBrowserGridItem):
      gridItem = item
    else:
      raise TypeError("populateGrid() expected a dict or MusicBrowserGridItem")

    self.layout.addWidget(gridItem, row, col)

    # Schedule the next item while ensuring responsiveness
    QTimer.singleShot(1000 // 144, self.addNextItem)

  def rearrangeGrid(self):
    """Rearrange grid items based on the new column count without clearing them."""
    if not self.gridItems:
      return

    self.columnCount = max(1, self.width() // (220 + 10))

    for i, gridItem in enumerate(self.gridItems):
      row = i // self.columnCount
      col = i % self.columnCount
      self.layout.addWidget(gridItem, row, col)  # Just update positions, no removing

  def resizeEvent(self, event):
    newCols = max(1, self.width() // (220 + 10))
    if self.columnCount != newCols:
      self.rearrangeGrid()  # Only rearrange if column count changes
    
    super().resizeEvent(event)  # Always call this last