"""Executable composition and developer diagnostics, outside domain packages."""

import argparse
import logging
import os
import sys
import traceback
from importlib import import_module
from importlib.metadata import version
from importlib.resources import files
from pathlib import Path

from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.shared.to_json import chunk_to_json

os.environ.setdefault("COPYFILE_DISABLE", "1")

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="iOpenPod")

    from iOpenPod.app.core.version import get_version

    parser.add_argument("--version", action="version", version=get_version())
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Check packaged resources and native runtimes without accessing devices.",
    )
    parser.add_argument(
        "--smoke-test-report",
        type=Path,
        help="Write smoke-test diagnostics here (also works without a console).",
    )

    parser.add_argument(
        "--json-from-itdb",
        nargs=2,
        metavar=("ITDB_PATH", "OUTPUT_PATH"),
        help="Parse an iTunesDB and write its typed tree as JSON.",
    )

    parser.add_argument(
        "--chunk_browser",
        action="store_true",
        help="Open the iTunesDB chunk object browser.",
    )

    return parser


def main(
    argv: list[str] | None = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.smoke_test_report and not args.smoke_test:
        parser.error("--smoke-test-report requires --smoke-test")

    if args.smoke_test:
        try:
            check_runtime()
        except Exception:
            report = traceback.format_exc()
            result = 1
        else:
            report = "iOpenPod packaged runtime check passed.\n"
            result = 0
        if args.smoke_test_report:
            args.smoke_test_report.write_text(report, encoding="utf-8")
        elif sys.stderr is not None:
            sys.stderr.write(report)
        return result

    from iOpenPod.app.core.runtime import configure_frozen_runtime

    configure_frozen_runtime()
    initialize_application()

    if run_cli(args):
        logger.info("iOpenPod CLI stopped.")
        return 0

    exit_code = start_gui()

    logger.info("iOpenPod stopped.")
    return exit_code


def initialize_application() -> None:
    from iOpenPod.app.core.logging import setup_logger
    from iOpenPod.app.core.settings.definitions import LOGGING_PATH
    from iOpenPod.app.core.settings.service import SettingsService
    from iOpenPod.app.core.settings.stores import (
        DeviceSettingsStore,
        create_global_settings_store,
    )
    from storage import Storage

    storage = Storage()
    settings = SettingsService(
        global_store=create_global_settings_store(storage),
        device_store=DeviceSettingsStore(),
    )
    log_path = settings.get(LOGGING_PATH)

    setup_logger(log_path)

    logger.info("iOpenPod Starting...")

    _log_startup_version()

    logger.info("Log Path: %s", log_path)

    from iOpenPod.app.core.certifi_ssl import install_certifi_ssl

    install_certifi_ssl()


def _log_startup_version() -> None:
    from iOpenPod.app.core.version import get_version
    from iOpenPod.app.updates.backend import InstallChannel
    from iOpenPod.app.updates.platform import detect_install_channel

    try:
        channel = detect_install_channel()
    except Exception:
        logger.warning("Could not detect installation source", exc_info=True)
        channel = InstallChannel.UNKNOWN
    logger.info("Version: %s · %s", get_version(), channel.display_name)


def run_cli(
    args: argparse.Namespace,
) -> bool:
    logger.info(f"CLI Args: {args}")
    if args.json_from_itdb:
        export_itdb_json(args.json_from_itdb)
        return True

    if args.chunk_browser:
        run_chunk_browser()
        return True

    return False


def start_gui() -> int:
    from iOpenPod.app.app import start_ui

    return start_ui()


def run_chunk_browser() -> None:
    from iPodDB.tools.chunk_browser import ChunkBrowser

    app = ChunkBrowser()
    app.mainloop()


def export_itdb_json(
    paths: list[str],
) -> None:
    itdb_path, output_path = map(Path, paths)

    if output_path.is_dir():
        output_path /= f"{itdb_path.name}.json"

    if _paths_refer_to_same_file(itdb_path, output_path):
        raise ValueError("ITDB_PATH and OUTPUT_PATH must refer to different files")

    parsed_chunk = parse_iTunesDB(itdb_path.read_bytes())

    output_path.parent.mkdir(parents=True, exist_ok=True)

    output_path.write_text(chunk_to_json(parsed_chunk), encoding="utf-8")

    logger.info("JSON written to %s", output_path)


def _paths_refer_to_same_file(source: Path, destination: Path) -> bool:
    try:
        if source.samefile(destination):
            return True
    except FileNotFoundError:
        pass

    return source.resolve() == destination.resolve()


def run_with_crash_logging() -> int:
    """Run the shared desktop entry point and log uncaught application failures."""
    from multiprocessing import freeze_support

    freeze_support()
    try:
        return main()
    except Exception:
        logger.critical("iOpenPod crashed due to an uncaught exception", exc_info=True)
        raise


def check_runtime() -> None:
    """Raise on missing GUI imports, assets, analysis, or native runtime code."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QByteArray
    from PySide6.QtGui import QImage
    from PySide6.QtMultimedia import QMediaPlayer
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtWidgets import QApplication

    from iOpenPod.app.core.runtime import configure_frozen_runtime

    configure_frozen_runtime()

    from iOpenPod.app.app import start_ui
    from iOpenPod.app.synesthesia import DeterministicMusicAnalyzer
    from iOpenPod.GUI.presentation.application_icon import application_icon
    from iPodDB.iTunesDB.writer.signature import compute_hashab

    # Import the actual startup graph without creating settings or discovering
    # devices. Resource-only checks miss missing application modules in a bundle.
    assert callable(start_ui), "GUI entry point missing"
    assert callable(DeterministicMusicAnalyzer), "Deferred analysis backend missing"
    native_bindings = {
        "win32": (
            "winrt.windows.media",
            "winrt.windows.media.interop",
            "winrt.windows.foundation.collections",
            "winrt.windows.storage.streams",
        ),
        "darwin": ("MediaPlayer", "AppKit"),
    }
    for module in native_bindings.get(sys.platform, ()):
        import_module(module)
    assert version("iOpenPod")
    app = QApplication.instance() or QApplication([])
    assert not application_icon().isNull(), "Application icon missing"
    resources = files("iOpenPod")
    image = resources.joinpath("assets/ipod_images/iPodGeneric.png").read_bytes()
    assert not QImage.fromData(image).isNull(), "Device image missing"
    glyph = resources.joinpath("assets/glyphs/music.svg").read_bytes()
    assert QSvgRenderer(QByteArray(glyph)).isValid(), "SVG support missing"
    rule = resources.joinpath("assets/linux/61-iopenpod.rules").read_text()
    assert "ID_IOPENPOD_PRODUCT_SERIAL" in rule
    shaders = resources.joinpath("GUI/synesthesia/shader_sources")
    assert shaders.joinpath("field_sim.comp.qsb").read_bytes(), "Shaders missing"
    assert len(compute_hashab(bytes(20), bytes(8))) == 57, "HASHAB runtime missing"
    # Exercise lazy-loaded analysis code; a top-level import alone misses it.
    import librosa
    import numpy as np

    assert librosa.feature.rms(y=np.zeros(4096, dtype=np.float32)).size
    # HPSS imports the scikit-learn-backed decomposition module. Sample dataset
    # and alternate GUI exclusions must not remove the actual analysis runtime.
    harmonic, percussive = librosa.decompose.hpss(np.ones((32, 16), dtype=np.float32))
    assert harmonic.shape == percussive.shape == (32, 16)
    player = QMediaPlayer()
    player.stop()
    app.processEvents()


if __name__ == "__main__":
    raise SystemExit(
        run_with_crash_logging(),
    )
