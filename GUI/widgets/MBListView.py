from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QAbstractItemView, QTableWidgetItem, QHeaderView, QTableWidget, QFrame, QVBoxLayout

class MusicBrowserList(QFrame):
  def __init__(self):
    super().__init__()
    self.layout = QVBoxLayout(self)
    self.layout.setContentsMargins(0, 0, 0, 0)
    self.tracks = []
   
  
    
  def loadFromJSON(self):
    from ..app import Worker, TrackLoaderThread, ThreadPoolSingleton
    self.worker1 = Worker(
      TrackLoaderThread
    )
    self.worker1.signals.result.connect(self.populateTable)
    ThreadPoolSingleton.get_instance().start(self.worker1)
      
  def populateTable(self, tracks):
    self.tracks = tracks

    # Collect all unique keys from all tracks
    all_keys = sorted(set(key for track in self.tracks for key in track.keys()))
    specific_order = ["Album", "Album Artist", "Artist", "Title", "Genre"]
    self.final_column_order = specific_order + [key for key in all_keys if key not in specific_order]
    
    # Create the table
    self.table = QTableWidget()
    self.table.setRowCount(len(self.tracks))
    self.table.setColumnCount(len(all_keys))
    self.table.setSortingEnabled(True)
    self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
    self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    self.layout.addWidget(self.table)
    self.table.hide()
    
    # Set the headers
    self.table.setHorizontalHeaderLabels(self.final_column_order)
    header = self.table.horizontalHeader()
    header.setSectionsMovable(True)
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(len(self.final_column_order) - 1, QHeaderView.ResizeMode.Stretch)
   
    self.table.setStyleSheet("""
            QTableWidget {
                border: 1px solid #444;
                background-color: #2c2c2c;
                color: white;
                selection-background-color: #3a3a3a;
                selection-color: white;
            }
            QTableWidget::item {
                padding: 5px;
                border: 1px solid #444;
                background-color: #2c2c2c;
            }
            QTableWidget::item:selected {
                background-color: #5a5a5a;
                color: white;
            }
            QTableWidget::horizontalHeader {
                background-color: #333;
                color: white;
                font-weight: bold;
                border: none;
                padding: 5px;
            }
            QTableWidget::verticalHeader {
                background-color: #333;
                color: white;
                font-weight: bold;
                border: none;
                padding: 5px;
            }
            QHeaderView::section {
                padding: 5px;
                background-color: #333;
                color: white;
                border: 1px solid #444;
                font-weight: bold;
            }
            QHeaderView::section:focus {
                background-color: #444;
            }
        """)
    
    self.addTracks()
      
      
  def addTracks(self):
    # Populate the table
    for row, track in enumerate(self.tracks):
      for col, key in enumerate(self.final_column_order):
        value = track.get(key, "")  # Get the value or an empty string if key is missing
        self.table.setItem(row, col, QTableWidgetItem(str(value)))
