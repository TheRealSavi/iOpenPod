import os
import sys
import logging
import logging.handlers
import traceback
from PyQt6.QtGui import QPalette, QColor
from PyQt6.QtWidgets import QApplication, QMessageBox
from GUI.app import MainWindow


def _get_log_dir() -> str:
    """Get platform-appropriate log directory, creating it if needed."""
    # Check for user-configured log directory in settings
    try:
        from GUI.settings import AppSettings
        custom = AppSettings.load().log_dir
        if custom:
            os.makedirs(custom, exist_ok=True)
            return custom
    except Exception:
        pass

    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Logs")
    else:
        base = os.environ.get(
            "XDG_STATE_HOME",
            os.path.join(os.path.expanduser("~"), ".local", "state"),
        )
    log_dir = os.path.join(base, "iOpenPod")
    os.makedirs(log_dir, exist_ok=True)
    return log_dir


def _configure_logging() -> str:
    """Set up console + rotating file logging.

    Returns:
        Path to the active log file.
    """
    log_dir = _get_log_dir()
    log_path = os.path.join(log_dir, "iopenpod.log")

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # Console handler — INFO level, compact timestamp
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    ))
    root.addHandler(console)

    # File handler — DEBUG level, 5 MB rotation, keep 3 backups
    file_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root.addHandler(file_handler)

    return log_path


# Configure logging before anything else
_log_file_path = _configure_logging()
logger = logging.getLogger(__name__)


def _get_crash_log_path() -> str:
    """Get path for crash log file."""
    return os.path.join(_get_log_dir(), "crash.log")


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
    logger.info("iOpenPod starting — log file: %s", _log_file_path)
    app = QApplication([])

    # Register bundled Noto fonts so the UI renders correctly on systems
    # that lack them (e.g. Fedora Silverblue, minimal Linux installs).
    from GUI.fonts import load_bundled_fonts
    load_bundled_fonts()

    # Use custom proxy style for dark scrollbars (CSS scrollbar styling is
    # unreliable on Windows with Fusion — this paints them directly).
    from GUI.styles import DarkScrollbarStyle
    app.setStyle(DarkScrollbarStyle("Fusion"))

    # Set a dark palette so Fusion's fallback colors aren't bright grey/blue
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

    window = MainWindow()

    window.show()

    # Start the event loop
    app.exec()
    logger.info("App closed")


def main():
    """Entry point for the iOpenPod application."""
    run_pyqt_app()


if __name__ == "__main__":
    main()
