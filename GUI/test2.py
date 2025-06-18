from PyQt6.QtCore import QSize
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QSplitter, QPushButton, QWidget, QFrame, QSizePolicy


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.layout = QVBoxLayout()

        # Create frames (no longer scroll areas)
        self.top = QFrame()
        self.bot = QFrame()

        # Create a splitter
        self.split = QSplitter()

        # Add frames to the splitter
        self.split.addWidget(self.top)
        self.split.addWidget(self.bot)

        # Set the main layout for the window
        self.layout.addWidget(self.split)

        # Create layouts and content for the frames
        top_layout = QVBoxLayout()
        top_layout.addWidget(QPushButton("hi"))
        self.top.setLayout(top_layout)

        bot_layout = QVBoxLayout()
        bot_layout.addWidget(QPushButton("hi"))
        self.bot.setLayout(bot_layout)

        # Set frames to allow infinite shrinking
        self.top.setMinimumHeight(0)
        self.top.setMinimumWidth(0)
        self.top.setSizePolicy(QSizePolicy.Policy.Ignored,
                               QSizePolicy.Policy.Ignored)

        self.bot.setMinimumHeight(0)
        self.bot.setMinimumWidth(0)
        self.bot.setSizePolicy(QSizePolicy.Policy.Ignored,
                               QSizePolicy.Policy.Ignored)

        # Fine control over splitter behavior (handleWidth)
        # You can adjust the width for a smoother experience
        self.split.setHandleWidth(10)

        # Override the minimum size hint to avoid snapping
        self.top.minimumSizeHint = lambda: QSize(0, 0)
        self.bot.minimumSizeHint = lambda: QSize(0, 0)

        # Set the central widget and its layout
        central_widget = QWidget()
        central_widget.setLayout(self.layout)
        self.setCentralWidget(central_widget)

        self.show()


# Initialize and run the application
app = QApplication([])
window = MainWindow()
app.exec()
