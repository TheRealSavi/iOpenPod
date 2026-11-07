"""Source archives are inputs to a release, so corruption must fail closed."""

import hashlib
import io
import json
import socket
import ssl
import tarfile
from email.message import Message
from http.client import IncompleteRead
from pathlib import Path
from unittest.mock import Mock, call
from urllib.error import HTTPError, URLError

import pytest
from scripts.prepare_release_sources import (
    Source,
    fetch,
    read_manifest,
    verify,
    write_notices,
)


def _source(content: bytes, filename: str = "sample.tar.gz") -> Source:
    return Source(
        "sample",
        "1.0",
        "https://example.com/source.tar.gz",
        filename,
        hashlib.sha256(content).hexdigest(),
        len(content),
    )


def test_corrupt_cached_source_is_rejected(tmp_path: Path) -> None:
    source = _source(b"original")
    (tmp_path / source.filename).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        verify(source, tmp_path)


def test_fetch_recovers_from_temporary_dns_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    content = b"original"
    source = _source(content)
    urlopen = Mock(
        side_effect=[
            URLError(
                socket.gaierror(
                    socket.EAI_AGAIN, "Temporary failure in name resolution"
                )
            ),
            io.BytesIO(content),
        ]
    )
    monkeypatch.setattr(
        "scripts.prepare_release_sources.urllib.request.urlopen", urlopen
    )
    sleep = Mock()
    monkeypatch.setattr("scripts.prepare_release_sources.time.sleep", sleep)

    assert fetch(source, tmp_path) == verify(source, tmp_path)
    assert urlopen.call_count == 2
    sleep.assert_called_once_with(2)
    assert not (tmp_path / (source.filename + ".partial")).exists()
    diagnostics = capsys.readouterr().err
    assert source.filename in diagnostics
    assert source.url in diagnostics
    assert "Temporary failure in name resolution" in diagnostics


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("timed out"),
        ConnectionResetError("connection reset"),
        URLError(TimeoutError("timed out")),
        URLError(ConnectionResetError(104, "Connection reset by peer")),
        URLError(ConnectionRefusedError("connection refused")),
        *[
            HTTPError(
                "https://example.com/source", status, "Unavailable", Message(), None
            )
            for status in (408, 429, 500, 502, 503, 504)
        ],
    ],
)
def test_fetch_retries_transient_connection_and_http_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    source = _source(b"original")
    urlopen = Mock(side_effect=[error, io.BytesIO(b"original")])
    monkeypatch.setattr(
        "scripts.prepare_release_sources.urllib.request.urlopen", urlopen
    )
    monkeypatch.setattr("scripts.prepare_release_sources.time.sleep", Mock())

    assert fetch(source, tmp_path) == verify(source, tmp_path)
    assert urlopen.call_count == 2


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("timed out"),
        ConnectionResetError("connection reset"),
        IncompleteRead(b"partial", 100),
    ],
)
def test_fetch_restarts_interrupted_download_from_empty_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    source = _source(b"original")
    response = io.BytesIO()
    monkeypatch.setattr(
        response,
        "read",
        Mock(side_effect=[b"partial content longer than original", error]),
    )
    urlopen = Mock(side_effect=[response, io.BytesIO(b"original")])
    monkeypatch.setattr(
        "scripts.prepare_release_sources.urllib.request.urlopen", urlopen
    )
    sleep = Mock()
    monkeypatch.setattr("scripts.prepare_release_sources.time.sleep", sleep)

    def assert_clean_before_retry(delay: int) -> None:
        assert delay == 2
        assert not (tmp_path / source.filename).exists()
        assert not (tmp_path / (source.filename + ".partial")).exists()

    sleep.side_effect = assert_clean_before_retry
    assert fetch(source, tmp_path).read_bytes() == b"original"
    assert urlopen.call_count == 2
    assert response.closed


def test_fetch_stops_after_bounded_retries_with_source_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _source(b"original")
    error = URLError(socket.gaierror(socket.EAI_AGAIN, "Temporary DNS failure"))
    urlopen = Mock(side_effect=error)
    sleep = Mock()
    monkeypatch.setattr(
        "scripts.prepare_release_sources.urllib.request.urlopen", urlopen
    )
    monkeypatch.setattr("scripts.prepare_release_sources.time.sleep", sleep)

    with pytest.raises(URLError) as caught:
        fetch(source, tmp_path)

    assert caught.value is error
    assert urlopen.call_count == 4
    assert sleep.call_args_list == [call(2), call(4), call(8)]
    assert source.filename in error.__notes__[0]
    assert source.url in error.__notes__[0]
    assert "attempt 4/4" in error.__notes__[0]
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "error",
    [
        URLError(socket.gaierror(socket.EAI_NONAME, "Unknown host")),
        URLError(ssl.SSLCertVerificationError("Untrusted certificate")),
        HTTPError("https://example.com/source", 403, "Forbidden", Message(), None),
        HTTPError("https://example.com/source", 404, "Not found", Message(), None),
        PermissionError("Access denied"),
    ],
)
def test_fetch_does_not_retry_permanent_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    urlopen = Mock(side_effect=error)
    sleep = Mock()
    monkeypatch.setattr(
        "scripts.prepare_release_sources.urllib.request.urlopen", urlopen
    )
    monkeypatch.setattr("scripts.prepare_release_sources.time.sleep", sleep)

    with pytest.raises(type(error)) as caught:
        fetch(_source(b"original"), tmp_path)

    assert caught.value is error
    assert urlopen.call_count == 1
    sleep.assert_not_called()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("content", [b"tampered", b"short"])
def test_fetch_rejects_corrupt_download_without_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: bytes
) -> None:
    urlopen = Mock(return_value=io.BytesIO(content))
    sleep = Mock()
    monkeypatch.setattr(
        "scripts.prepare_release_sources.urllib.request.urlopen", urlopen
    )
    monkeypatch.setattr("scripts.prepare_release_sources.time.sleep", sleep)

    with pytest.raises(ValueError, match="mismatch"):
        fetch(_source(b"original"), tmp_path)

    assert urlopen.call_count == 1
    sleep.assert_not_called()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("content", [b"original", b"tampered", b"short"])
def test_fetch_verifies_cached_source_without_downloading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: bytes
) -> None:
    source = _source(b"original")
    destination = tmp_path / source.filename
    destination.write_bytes(content)
    urlopen = Mock()
    monkeypatch.setattr(
        "scripts.prepare_release_sources.urllib.request.urlopen", urlopen
    )

    if content == b"original":
        assert fetch(source, tmp_path) == destination
    else:
        with pytest.raises(ValueError, match="mismatch"):
            fetch(source, tmp_path)

    urlopen.assert_not_called()
    assert destination.read_bytes() == content


def test_manifest_rejects_traversal_before_download(tmp_path: Path) -> None:
    manifest = tmp_path / "sources.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "name": "sample",
                    "version": "1.0",
                    "url": "https://example.com/source",
                    "filename": "../outside.tar.gz",
                    "sha256": "0" * 64,
                    "size": 8,
                }
            ]
        )
    )
    with pytest.raises(ValueError, match="Unsafe"):
        read_manifest(manifest)


def test_notice_collection_reads_text_without_extracting_paths_or_links(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "sample.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        text = b"Copyright Example. Permission is granted."
        member = tarfile.TarInfo("../../LICENCE")
        member.size = len(text)
        output.addfile(member, io.BytesIO(text))
        link = tarfile.TarInfo("source/LICENSE-link")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../private-file"
        output.addfile(link)
    notices = tmp_path / "notices"
    notices.mkdir()
    record = write_notices(_source(archive.read_bytes()), archive, notices)
    notice_text = (notices / str(record["file"])).read_text()
    assert "Permission is granted" in notice_text
    assert "LICENSE-link" not in notice_text
    assert not (tmp_path / "LICENCE").exists()


def test_checked_in_source_manifest_is_well_formed() -> None:
    root = Path(__file__).resolve().parents[1]
    records = read_manifest(root / "packaging" / "third-party" / "sources.json")
    assert {"pyside-setup", "ffmpeg", "pywinrt", "hashab"}.issubset(
        {record.name for record in records}
    )
