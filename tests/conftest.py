"""Cross-platform pytest configuration."""

import os


def pytest_configure() -> None:
    """Use Qt's headless platform during automated widget tests."""

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
