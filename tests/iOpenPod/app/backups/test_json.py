"""Strict JSON rules shared by every persisted Backup catalog."""

from __future__ import annotations

import pytest

from iOpenPod.app.backups._json import StrictJsonError, loads_strict


def test_strict_json_rejects_unpaired_unicode_surrogates() -> None:
    with pytest.raises(StrictJsonError, match="Unicode surrogate"):
        loads_strict(b'{"note":"\\ud800"}')


def test_strict_json_accepts_a_valid_surrogate_pair() -> None:
    assert loads_strict(b'{"note":"\\ud83d\\ude00"}') == {"note": chr(0x1F600)}
