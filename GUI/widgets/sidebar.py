from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QFrame, QPushButton, QVBoxLayout, QHBoxLayout
from PyQt6.QtGui import QFont


class Sidebar(QFrame):
  category_changed = pyqtSignal(str)
  def __init__(self):
      from ..app import category_glyphs
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
      "background-color: #409cff;"
      "border: none;"
      "color: white;"
      "padding: 10px 0;"
      "}"
      "QPushButton:hover {"
      "background-color: rgba(0,122,204,204);"
      "}"
    )
    self.category_changed.emit(category)
