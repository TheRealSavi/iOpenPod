from PyQt6.QtCore import Qt, QSize
from PyQt6.QtWidgets import QScrollArea, QFrame, QSplitter, QStackedLayout, QSizePolicy
from .MBGridView import MusicBrowserGrid
from .MBListView import MusicBrowserList
from .trackListTitleBar import TrackListTitleBar

class MusicBrowser(QFrame):
  def __init__(self):
    super().__init__()
    
    self.layoutSwitch = QStackedLayout(self)
    self.layoutSwitch.setContentsMargins(0, 0, 0, 0)
    
    self.gridTrackSplitter = QSplitter(Qt.Orientation.Vertical)


    #Top: Grid Browser
    self.browserGrid = MusicBrowserGrid()
    
    self.browserGridScroll = QScrollArea()
    self.browserGridScroll.setWidgetResizable(True)
    self.browserGridScroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
    self.browserGridScroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    self.browserGridScroll.setMinimumHeight(0)
    self.browserGridScroll.setMinimumWidth(0)
    self.browserGridScroll.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
    self.browserGridScroll.minimumSizeHint = lambda: QSize(0, 0)
    self.browserGridScroll.setWidget(self.browserGrid)
    
    self.gridTrackSplitter.addWidget(self.browserGridScroll)
       
    
    #Bottom: Track Browser
    self.browserTrack = MusicBrowserList()
    self.browserTrack.setMinimumHeight(0)
    self.browserTrack.setMinimumWidth(0)
    self.browserTrack.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
    self.browserTrack.minimumSizeHint = lambda: QSize(0, 0)
    self.gridTrackSplitter.addWidget(self.browserTrack)
    
    #Track Browser TitleBar
    self.trackListTitleBar = TrackListTitleBar(self.gridTrackSplitter)
    self.browserTrack.layout.insertWidget(0, self.trackListTitleBar)
    
    #splitter prop
    self.gridTrackSplitter.handle(1).setEnabled(False)
    self.gridTrackSplitter.setCollapsible(0, True)
    self.gridTrackSplitter.setHandleWidth(1)
    self.gridTrackSplitter.setStretchFactor(0, 1)
    self.gridTrackSplitter.setMinimumSize(0,0)
    
    #load contents
    self.browserGrid.loadFromJSON()
    self.browserTrack.loadFromJSON()
    
    #add to layouts
    self.layoutSwitch.addWidget(self.gridTrackSplitter)

    
  def updateCategory(self, category):
    print(f"Selected: {category}")  
       