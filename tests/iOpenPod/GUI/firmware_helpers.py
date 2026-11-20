"""Pump Qt events while waiting for firmware workers in GUI tests."""

from collections.abc import Callable
from time import monotonic

from PySide6.QtTest import QTest


def until(predicate: Callable[[], bool]) -> None:
    deadline = monotonic() + 3
    while not predicate() and monotonic() < deadline:
        QTest.qWait(10)
    assert predicate()
