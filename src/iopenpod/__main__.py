"""Command-line entry point for the installed iOpenPod application."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from iopenpod import __version__


def run_pyqt_app() -> None:
    """Start the GUI without importing PyQt until it is needed."""

    from iopenpod.application.bootstrap import run_pyqt_app as run

    run()


def main(argv: Sequence[str] | None = None) -> None:
    """Run the installed CLI, launching the GUI unless an option exits first."""

    parser = argparse.ArgumentParser(prog="iopenpod")
    parser.add_argument("--version", action="version", version=__version__)
    parser.parse_args(argv)
    run_pyqt_app()


__all__ = ["main", "run_pyqt_app"]


if __name__ == "__main__":
    main()
