"""Application bootstrap and composition-root wiring."""

from __future__ import annotations

import logging
import logging.handlers
import os
import ssl
import sys
import traceback

from iopenpod.infrastructure.settings_paths import default_data_dir
from iopenpod.infrastructure.version import get_version
from iopenpod.resources import resource_path

from .context import AppContext, create_app_context
from .qt_runtime import configure_qt_multimedia_logging, linux_qt_dependency_error

# Prevent macOS from creating ._AppleDouble resource fork files on FAT32 iPods
os.environ.setdefault("COPYFILE_DISABLE", "1")
configure_qt_multimedia_logging()

_LOG_FILE_PATH: str | None = None


def _get_log_dir(context: AppContext) -> str:
    """Resolve the log directory using the settings service."""

    try:
        custom = context.settings.get_global_snapshot().log_dir
        if custom:
            os.makedirs(custom, exist_ok=True)
            return custom
    except Exception:
        pass

    log_dir = os.path.join(default_data_dir(), "logs")
    os.makedirs(log_dir, exist_ok=True)
    return log_dir


def _configure_logging(context: AppContext) -> str:
    """Set up console and rotating file logging."""

    global _LOG_FILE_PATH
    if _LOG_FILE_PATH is not None:
        return _LOG_FILE_PATH

    log_dir = _get_log_dir(context)
    log_path = os.path.join(log_dir, "iopenpod.log")

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # Pillow emits very verbose TIFF/PNG tag traces at DEBUG when the root
    # file handler captures debug logs. Keep third-party internals quiet unless
    # a developer explicitly lowers these loggers during a diagnostic session.
    for noisy_logger in (
        "PIL",
        "PIL.Image",
        "PIL.PngImagePlugin",
        "PIL.TiffImagePlugin",
    ):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)

    if not any(isinstance(handler, logging.StreamHandler) for handler in root.handlers):
        console = logging.StreamHandler()
        console.setLevel(logging.INFO)
        console.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        root.addHandler(console)

    if not any(
        isinstance(handler, logging.handlers.RotatingFileHandler)
        and getattr(handler, "baseFilename", "") == os.path.abspath(log_path)
        for handler in root.handlers
    ):
        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        root.addHandler(file_handler)

    _LOG_FILE_PATH = log_path
    return log_path


def _install_certifi_ssl() -> None:
    """Set Python's default HTTPS context to use the certifi CA bundle."""

    try:
        import certifi

        ssl._create_default_https_context = lambda: ssl.create_default_context(  # type: ignore[attr-defined]
            cafile=certifi.where()
        )
    except ImportError:
        pass


def _get_crash_log_path(context: AppContext) -> str:
    return os.path.join(_get_log_dir(context), "crash.log")


def _build_exception_handler(context: AppContext):
    logger = logging.getLogger(__name__)

    def _handler(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return

        tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        crash_log_path = _get_crash_log_path(context)
        try:
            from datetime import datetime

            with open(crash_log_path, "a", encoding="utf-8") as handle:
                handle.write(f"\n{'=' * 60}\n")
                handle.write(f"Crash at {datetime.now().isoformat()}\n")
                handle.write(f"{'=' * 60}\n")
                handle.write(tb_text)
                handle.write("\n")
        except Exception:
            pass

        logger.critical("Unhandled exception: %s: %s", exc_type.__name__, exc_value)
        logger.critical(tb_text)

        try:
            from PyQt6.QtWidgets import QApplication, QMessageBox

            app = QApplication.instance()
            if app:
                QMessageBox.critical(
                    None,
                    "iOpenPod Error",
                    (
                        "An unexpected error occurred:\n\n"
                        f"{exc_type.__name__}: {exc_value}\n\n"
                        f"A crash report has been saved to:\n{crash_log_path}\n\n"
                        "Please report this issue on GitHub."
                    ),
                )
        except Exception:
            pass

    return _handler


def run_pyqt_app(context: AppContext | None = None) -> None:
    """Create the application context, QApplication, and main window."""

    context = context or create_app_context()
    log_path = _configure_logging(context)
    _install_certifi_ssl()
    sys.excepthook = _build_exception_handler(context)

    logger = logging.getLogger(__name__)
    logger.info(
        "iOpenPod v%s starting — log file: %s",
        get_version(),
        log_path,
    )

    qt_dependency_error = linux_qt_dependency_error()
    if qt_dependency_error:
        logger.error("%s", qt_dependency_error)
        print(qt_dependency_error, file=sys.stderr)
        raise SystemExit(1)

    if sys.platform == "linux" and getattr(sys, "frozen", False):
        os.environ.setdefault("QT_IM_MODULE", "")

    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QFont, QIcon
    from PyQt6.QtWidgets import QApplication

    from iopenpod.gui.app import MainWindow
    from iopenpod.gui.fonts import load_bundled_fonts
    from iopenpod.gui.styles import (
        FONT_FAMILY,
        Colors,
        DarkScrollbarStyle,
        Metrics,
        app_stylesheet,
        build_palette,
        resolve_accent_color,
    )

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication([])

    load_bundled_fonts()
    app.setStyle(DarkScrollbarStyle("Fusion"))

    settings_snapshot = context.settings.get_effective_snapshot()
    Colors.apply_theme_selection(
        settings_snapshot.theme_mode,
        settings_snapshot.light_theme,
        settings_snapshot.dark_theme,
        settings_snapshot.high_contrast,
        resolve_accent_color(settings_snapshot.accent_color),
    )
    Metrics.apply_font_scale(settings_snapshot.font_scale)
    app.setFont(QFont(FONT_FAMILY, Metrics.FONT_MD))
    app.setPalette(build_palette())

    icon_dir = resource_path("assets", "icons")
    app_icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        app_icon.addFile(str(icon_dir / f"icon-{size}.png"))
    app.setWindowIcon(app_icon)
    app.setStyleSheet(app_stylesheet())

    window = MainWindow(context=context)
    window.show()
    app.exec()
    logger.info("App closed")


def main() -> None:
    """Entry point for packaged and source runs."""

    run_pyqt_app()
