from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QAbstractItemView, QTableWidgetItem, QHeaderView, QTableWidget, QFrame, QVBoxLayout


class MusicBrowserList(QFrame):
    def __init__(self):
        super().__init__()
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.tracks = []
        self.table = QTableWidget()
        self.layout.addWidget(self.table)
        self.setupTable()

    def setupTable(self):
        self.table.setSortingEnabled(True)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.table.setHorizontalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)

        # Use 'Interactive' resizing for better performance
        header = self.table.horizontalHeader()
        header.setSectionsMovable(True)
        header.setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive)  # User can adjust
        header.setStretchLastSection(True)  # Only the last column stretches

    def loadFromJSON(self):
        from ..app import Worker, TrackLoaderThread, ThreadPoolSingleton
        self.worker1 = Worker(TrackLoaderThread)
        self.worker1.signals.result.connect(self.populateTable)
        ThreadPoolSingleton.get_instance().start(self.worker1)

    def populateTable(self, tracks):
        self.tracks = tracks

        # Collect all unique keys from all tracks
        all_keys = sorted(
            set(key for track in self.tracks for key in track.keys()))
        specific_order = ["Album", "Album Artist", "Artist", "Title", "Genre"]
        self.final_column_order = specific_order + \
            [key for key in all_keys if key not in specific_order]

        # Update table properties
        self.table.setColumnCount(len(self.final_column_order))
        self.table.setHorizontalHeaderLabels(self.final_column_order)

        self.addTracks()

    def addTracks(self):
        """Optimized method to populate the table quickly."""
        self.table.setUpdatesEnabled(False)  # Disable UI updates
        self.table.clearContents()  # Clear previous data efficiently
        self.table.setRowCount(len(self.tracks))  # Set row count in one call

        for row, track in enumerate(self.tracks):
            for col, key in enumerate(self.final_column_order):
                value = track.get(key, "")  # Get the value or empty string
                self.table.setItem(row, col, QTableWidgetItem(str(value)))

        self.table.setUpdatesEnabled(True)  # Enable UI updates
