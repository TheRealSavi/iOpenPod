import os
import logging
from PyQt6.QtWidgets import QApplication
from GUI.app import MainWindow, DeviceManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S'
)


def run_pyqt_app():
    app = QApplication([])

    # Check for ipodTestData before creating window
    project_root = os.path.dirname(os.path.abspath(__file__))
    test_data_path = os.path.join(project_root, "ipodTestData")
    device_manager = DeviceManager.get_instance()

    has_test_data = device_manager.is_valid_ipod_root(test_data_path)

    window = MainWindow()

    # Auto-select ipodTestData if it exists (for development convenience)
    if has_test_data:
        device_manager.device_path = test_data_path
        window.sidebar.updateDeviceButton("ipodTestData")
        print(f"Auto-selected test data: {test_data_path}")

    window.show()

    # Start the event loop
    app.exec()
    print("App closed")


if __name__ == "__main__":
    run_pyqt_app()
