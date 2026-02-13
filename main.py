import os
import sys
import logging
import traceback
from PyQt6.QtGui import QPalette, QColor
from PyQt6.QtWidgets import QApplication, QMessageBox
from GUI.app import MainWindow, DeviceManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S'
)

logger = logging.getLogger(__name__)


def _get_crash_log_path() -> str:
    """Get path for crash log file."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Logs")
    else:
        base = os.environ.get("XDG_STATE_HOME", os.path.join(os.path.expanduser("~"), ".local", "state"))

    log_dir = os.path.join(base, "iOpenPod")
    os.makedirs(log_dir, exist_ok=True)
    return os.path.join(log_dir, "crash.log")


def global_exception_handler(exc_type, exc_value, exc_tb):
    """Global exception handler to catch unhandled exceptions.

    Logs the error, saves a crash report, and shows a user-friendly dialog
    instead of silently crashing.
    """
    # Don't catch keyboard interrupt
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return

    # Format the traceback
    tb_lines = traceback.format_exception(exc_type, exc_value, exc_tb)
    tb_text = "".join(tb_lines)

    # Log to file
    crash_log_path = _get_crash_log_path()
    try:
        from datetime import datetime
        with open(crash_log_path, "a", encoding="utf-8") as f:
            f.write(f"\n{'=' * 60}\n")
            f.write(f"Crash at {datetime.now().isoformat()}\n")
            f.write(f"{'=' * 60}\n")
            f.write(tb_text)
            f.write("\n")
    except Exception:
        pass  # Don't fail while handling failure

    # Log to console
    logger.critical(f"Unhandled exception: {exc_type.__name__}: {exc_value}")
    logger.critical(tb_text)

    # Show user-friendly dialog if Qt app is running
    try:
        app = QApplication.instance()
        if app:
            error_msg = (
                f"An unexpected error occurred:\n\n"
                f"{exc_type.__name__}: {exc_value}\n\n"
                f"A crash report has been saved to:\n{crash_log_path}\n\n"
                f"Please report this issue on GitHub."
            )
            QMessageBox.critical(None, "iOpenPod Error", error_msg)
    except Exception:
        pass  # Don't fail while handling failure


# Install global exception handler
sys.excepthook = global_exception_handler


def run_pyqt_app():
    app = QApplication([])

    # Use custom proxy style for dark scrollbars (CSS scrollbar styling is
    # unreliable on Windows with Fusion — this paints them directly).
    from GUI.styles import DarkScrollbarStyle
    app.setStyle(DarkScrollbarStyle("Fusion"))

    # Set a dark palette so Fusion's fallback colours aren't bright grey/blue
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(26, 26, 46))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Base, QColor(22, 22, 36))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(30, 30, 48))
    palette.setColor(QPalette.ColorRole.Text, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Button, QColor(30, 30, 48))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(64, 156, 255))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Mid, QColor(30, 30, 48))
    palette.setColor(QPalette.ColorRole.Dark, QColor(18, 18, 30))
    palette.setColor(QPalette.ColorRole.Midlight, QColor(40, 40, 60))
    palette.setColor(QPalette.ColorRole.Shadow, QColor(0, 0, 0))
    palette.setColor(QPalette.ColorRole.Light, QColor(50, 50, 70))
    app.setPalette(palette)

    # Apply global stylesheet
    from GUI.styles import APP_STYLESHEET
    app.setStyleSheet(APP_STYLESHEET)

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
