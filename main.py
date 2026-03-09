import os
import sys
import logging
import logging.handlers
import traceback


def _get_log_dir() -> str:
    """Get log directory, defaulting to ~/iOpenPod/logs."""
    # Check for user-configured log directory in settings
    try:
        from GUI.settings import AppSettings
        custom = AppSettings.load().log_dir
        if custom:
            os.makedirs(custom, exist_ok=True)
            return custom
    except Exception:
        pass

    from GUI.settings import _default_data_dir
    log_dir = os.path.join(_default_data_dir(), "logs")
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
    file_handler.setLevel(logging.INFO)
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
        from PyQt6.QtWidgets import QApplication, QMessageBox
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
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QIcon
    from GUI.app import MainWindow
    app = QApplication([])

    # Register bundled Noto fonts so the UI renders correctly on systems
    # that lack them (e.g. Fedora Silverblue, minimal Linux installs).
    from GUI.fonts import load_bundled_fonts
    load_bundled_fonts()

    # Use custom proxy style for dark scrollbars (CSS scrollbar styling is
    # unreliable on Windows with Fusion — this paints them directly).
    from GUI.styles import Colors, DarkScrollbarStyle, Metrics, build_palette
    app.setStyle(DarkScrollbarStyle("Fusion"))

    # Scale all pixel metrics to match the current screen size / DPI.
    Metrics.apply_scaling()

    # Apply the selected color theme (reads settings; must come after
    # QApplication exists so system-theme detection works).
    from GUI.settings import get_settings
    _s = get_settings()
    Colors.apply_theme(_s.theme, _s.high_contrast)

    # Build a palette from the active Colors and apply it.
    app.setPalette(build_palette())

    # App icon (window title bar, taskbar, system tray)
    _icon_dir = os.path.join(os.path.dirname(__file__), "assets", "icons")
    app_icon = QIcon()
    for _sz in (16, 24, 32, 48, 64, 128, 256):
        app_icon.addFile(os.path.join(_icon_dir, f"icon-{_sz}.png"))
    app.setWindowIcon(app_icon)

    # Apply global stylesheet (built after scaling so pixel values are correct)
    from GUI.styles import app_stylesheet
    app.setStyleSheet(app_stylesheet())

    window = MainWindow()  # noqa: F821 — imported at top of function

    window.show()

    # Start the event loop
    app.exec()
    logger.info("App closed")


def main():
    """Entry point for the iOpenPod application."""
    run_pyqt_app()


if __name__ == "__main__":
    main()
