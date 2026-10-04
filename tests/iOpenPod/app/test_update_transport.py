"""Signed download bounds hold even when server lengths and contents are wrong."""

import hashlib
import io
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.test_portable_updates import asset

from iOpenPod.app.updates import transport
from iOpenPod.app.updates.releases import MAX_METADATA


@pytest.mark.parametrize("payload", [b"", b"ne", b"bad", b"new-and-extra"])
def test_download_requires_exact_signed_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: bytes
) -> None:
    client = transport.UpdateTransport()

    def response(_url: str) -> io.BytesIO:
        return io.BytesIO(payload)

    monkeypatch.setattr(client, "_open", response)
    selected = replace(asset(), size=3, sha256=hashlib.sha256(b"new").hexdigest())
    with pytest.raises(ValueError, match="expected"):
        client.download(
            selected, tmp_path / "download", Event(), lambda _progress: None
        )


def test_download_keeps_existing_files_and_cancel_never_reports_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = transport.UpdateTransport()

    def response(_url: str) -> io.BytesIO:
        return io.BytesIO(b"new")

    monkeypatch.setattr(client, "_open", response)
    selected = replace(asset(), size=3, sha256=hashlib.sha256(b"new").hexdigest())
    path = tmp_path / "download"
    path.write_bytes(b"user content")
    with pytest.raises(FileExistsError):
        client.download(selected, path, Event(), lambda _p: None)
    assert path.read_bytes() == b"user content"
    cancel = Event()
    cancel.set()
    progress: list[float] = []
    with pytest.raises(InterruptedError):
        client.download(selected, tmp_path / "canceled", cancel, progress.append)
    assert not progress
    client.download(selected, tmp_path / "verified", Event(), progress.append)
    assert (tmp_path / "verified").read_bytes() == b"new" and progress[-1] == 1


def test_metadata_limit_and_cancellation(monkeypatch: pytest.MonkeyPatch) -> None:
    client = transport.UpdateTransport()

    def response(_url: str) -> io.BytesIO:
        return io.BytesIO(b"x" * (MAX_METADATA + 1))

    monkeypatch.setattr(client, "_open", response)
    with pytest.raises(ValueError, match="size limit"):
        client.metadata("https://github.com/feed", Event())
    cancel = Event()
    cancel.set()
    with pytest.raises(InterruptedError):
        client.metadata("https://github.com/feed", cancel)
