"""Quick test to verify scrollbar styling with DarkScrollbarStyle."""
import sys
from PyQt6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget
from PyQt6.QtGui import QPalette, QColor
from GUI.styles import DarkScrollbarStyle

app = QApplication(sys.argv)
app.setStyle(DarkScrollbarStyle("Fusion"))

p = QPalette()
p.setColor(QPalette.ColorRole.Window, QColor(26, 26, 46))
p.setColor(QPalette.ColorRole.Base, QColor(22, 22, 36))
p.setColor(QPalette.ColorRole.Button, QColor(30, 30, 48))
p.setColor(QPalette.ColorRole.Mid, QColor(30, 30, 48))
p.setColor(QPalette.ColorRole.Dark, QColor(18, 18, 30))
p.setColor(QPalette.ColorRole.Midlight, QColor(40, 40, 60))
app.setPalette(p)

w = QWidget()
w.setStyleSheet("background: #1a1a2e;")
layout = QVBoxLayout(w)
t = QTableWidget(50, 15)
for r in range(50):
    for c in range(15):
        t.setItem(r, c, QTableWidgetItem(f"Cell {r},{c} some test data here"))

t.setStyleSheet("QTableWidget { background-color: rgba(0,0,0,20); border: none; color: white; }")
layout.addWidget(t)
w.resize(600, 400)
w.setWindowTitle("Scrollbar Test")
w.show()
print("Test window open — check scrollbars then close")
app.exec()
