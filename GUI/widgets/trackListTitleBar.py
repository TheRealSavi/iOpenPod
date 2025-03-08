from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QFrame, QLabel, QPushButton, QWidget

class TrackListTitleBar(QFrame):
  def __init__(self, splitterToControl):
    super().__init__()
    self.splitter = splitterToControl
    self.dragging = False
    self.dragStartPos = QPoint()
    self.setMouseTracking(True)
    self.layout = QHBoxLayout(self)
    self.layout.setContentsMargins(2,2,2,2)
    #self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    self.splitter.splitterMoved.connect(self.enforceMinHeight)

    
    # Set minimum and maximum height
    self.setMinimumHeight(30)  # Minimum height in pixels
    self.setMaximumHeight(30)  # Maximum height in pixels
    self.setFixedHeight(30)
    
    self.setStyleSheet("""
            QFrame {
                background-color: #409cff;
                border: none;
                border-radius: 5px;
                color: white;
            }
            QLabel {
                font-weight: bold;
                font-size: 14px;
                color: white;
                margin-left: 10px;
            }
            QPushButton {
                background-color: transparent;
                border: none;
                color: white;
                font-size: 12px;
                font-weight: bold;
                width: 30px;
                height: 30px;
                border-radius: 3px;
                margin-right: 5px;  /* Right margin for buttons */
            }
            QPushButton:hover {
                background-color: #ff375f;  /* Hover effect for buttons */
            }
            QPushButton:pressed {
                background-color: #888888;  /* Pressed effect for buttons */
            }
        """)
    
    self.title = QLabel("Tracks")
    self.button1 = QPushButton("-")
    self.button2 = QPushButton("X")
    self.layout.addWidget(self.title)
    self.layout.addStretch()
    self.layout.addWidget(self.button1)
    self.layout.addWidget(self.button2)
   
  
  def mousePressEvent(self, event):
    if event.button()== Qt.MouseButton.LeftButton:
      if self.childAt(event.pos()) is None:
        self.dragging = True
        self.dragStartPos = event.globalPosition().toPoint()
        event.accept()
      else:
        event.ignore()
        
  def mouseMoveEvent(self, event):
    if self.dragging:
      delta = event.globalPosition().toPoint().y() - self.dragStartPos.y()
      self.dragStartPos = event.globalPosition().toPoint()
      
      current_pos = self.splitter.handle(1).y()
      new_pos = self.splitter.mapFromGlobal(event.globalPosition().toPoint()).y()
      
      max_pos = self.splitter.parent().height() - self.splitter.handleWidth()
      
      new_pos = max(0, min(new_pos, max_pos))
      
      #move the splitter handle
      self.splitter.moveSplitter(new_pos, 1)
      event.accept()
    else:
      event.ignore()
      
  def mouseReleaseEvent(self, event):
    if event.button() == Qt.MouseButton.LeftButton:
      self.dragging = False
      event.accept()
      
  def enterEvent(self, event):
    if self.childAt(event.position().toPoint()) is None:
      QApplication.setOverrideCursor(Qt.CursorShape.SizeVerCursor)
    else:
      QApplication.restoreOverrideCursor()
      
  def leaveEvent(self, event):
    QApplication.restoreOverrideCursor()
    super().leaveEvent(event)
  
  def enforceMinHeight(self):
    sizes = self.splitter.sizes()
    min_height = self.minimumHeight()
    if sizes[1] <= min_height:
      for child in self.parent().children():
        if isinstance(child, QWidget) and child != self:
          child.hide()
    else:
      for child in self.parent().children():
        if isinstance(child, QWidget):
          child.show()

    if sizes[1] < min_height:
        sizes[1] = min_height
        sizes[0] = max(sizes[0] - sizes[1], 0)
        self.splitter.setSizes(sizes)
    