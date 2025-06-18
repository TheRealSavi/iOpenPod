import json
from PyQt6.QtWidgets import QApplication
from iTunesDB_Parser.parser import parse_itunesdb
from ArtworkDB_Parser.parser import parse_artworkdb
from GUI.app import MainWindow


def run_pyqt_app():
    app = QApplication([])

    window = MainWindow()
    window.show()  # Window is hidden by default

    # Start the event loop
    app.exec()
    # Rest of code is not reached until the window is closed
    print("close")


def start_parsing():
    result = parse_itunesdb(
        r"C:\Users\JohnG\Documents\Coding Projects\iOpenPod\iOpenPod\testData\iTunes\iTunesDB")
    print(str(result))
    with open("idb.json", "w") as f:
        json.dump(result, f, indent=2)


def start_art():
    result = parse_artworkdb(
        r"C:\Users\JohnG\Documents\Coding Projects\iOpenPod\iOpenPod\testData\Artwork\ArtworkDB")
    print("done")
    with open("artdb.json", "w") as f:
        json.dump(result, f, indent=2)


if __name__ == "__main__":
    run_pyqt_app()
