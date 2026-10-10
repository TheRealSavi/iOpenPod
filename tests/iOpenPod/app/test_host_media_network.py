"""Network-drive classification must not prevent the Host scan and review flow."""

import ctypes
import hashlib
import json
import os
import sys
import wave
from collections.abc import Callable
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image

from iOpenPod.app.host_media_fingerprint import FpcalcFingerprinter
from iOpenPod.app.host_media_folders import create_host_media_folder
from iOpenPod.app.host_media_library import HostMediaCacheStats, HostMediaScanner
from storage import AtomicHostFile, HostPath
from storage.host_input import LocalHostFile

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows network drives")


@pytest.fixture
def remote_drive(monkeypatch: pytest.MonkeyPatch) -> None:
    # Real local files exercise the Windows read and identity checks; only the
    # drive classification is remote. This does not simulate SMB server behavior.
    if sys.platform != "win32":
        pytest.skip("Windows drive classification")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    monkeypatch.setattr(kernel, "GetDriveTypeW", Mock(return_value=4))  # DRIVE_REMOTE

    def load_kernel(*args: object, **kwargs: object) -> ctypes.CDLL:
        return kernel

    monkeypatch.setattr(ctypes, "WinDLL", load_kernel)


def _write_wav(path: Path) -> None:
    with wave.open(os.fspath(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(8_000)
        stream.writeframes(b"\0\0" * 80)


@pytest.mark.parametrize("selection", ["folder", "files"])
def test_network_media_reaches_metadata_catalog_and_relative_playlist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    remote_drive: None,
    selection: str,
) -> None:
    song = tmp_path / "Song.wav"
    _write_wav(song)
    playlist = tmp_path / "Favorites.m3u8"
    playlist.write_text("Song.wav\nSong.wav\n", encoding="utf-8")
    inspected: list[HostPath] = []

    def fingerprint(
        _self: FpcalcFingerprinter, source: HostPath, *, checkpoint: Callable[[], None]
    ) -> str:
        checkpoint()
        inspected.append(source)
        return "1,2,3"

    monkeypatch.setattr(FpcalcFingerprinter, "fingerprint", fingerprint)
    scanner = HostMediaScanner()
    pending = scanner.scan(
        (create_host_media_folder(tmp_path),) if selection == "folder" else (),
        files=(HostPath(song), HostPath(playlist)) if selection == "files" else (),
        checkpoint=lambda: None,
    )
    assert not pending.external_references
    result = scanner.complete(pending, frozenset(), checkpoint=lambda: None)

    assert not result.issues
    assert len(result.snapshot.tracks) == 1
    track = result.snapshot.tracks[0]
    assert track.title == "Song"
    assert track.length_ms == 10
    assert track.metadata.sample_rate_hz == 8_000
    sources = {source.path: source for source in result.sources}
    assert set(sources) == {HostPath(song), HostPath(playlist)}
    assert sources[HostPath(song)].acoustic_fingerprint == "1,2,3"
    assert inspected == [HostPath(song)]
    assert len(result.snapshot.playlists) == 1
    assert [entry.track_id for entry in result.snapshot.playlists[0].entries] == [
        track.track_id,
        track.track_id,
    ]
    assert not result.incomplete_playlist_ids


def test_network_playlist_target_still_requires_review_before_inspection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, remote_drive: None
) -> None:
    song = tmp_path / "Song.wav"
    _write_wav(song)
    selected = tmp_path / "Playlists"
    selected.mkdir()
    playlist = selected / "Favorites.m3u8"
    playlist.write_text("../Song.wav\n", encoding="utf-8")
    inspected: list[HostPath] = []

    def fingerprint(
        _self: FpcalcFingerprinter, source: HostPath, *, checkpoint: Callable[[], None]
    ) -> str:
        checkpoint()
        inspected.append(source)
        assert source != HostPath(song)
        assert Path(source).read_bytes() == song.read_bytes()
        return "1,2,3"

    monkeypatch.setattr(FpcalcFingerprinter, "fingerprint", fingerprint)
    scanner = HostMediaScanner()
    pending = scanner.scan(
        (create_host_media_folder(selected),), checkpoint=lambda: None
    )
    assert len(pending.external_references) == 1
    reference = pending.external_references[0]
    assert reference.target == HostPath(song)
    assert reference.available
    assert reference.playlists == (HostPath(playlist),)
    assert not inspected
    denied = scanner.complete(pending, frozenset(), checkpoint=lambda: None)
    assert not denied.snapshot.tracks
    assert not denied.snapshot.playlists[0].entries
    assert not inspected

    accepted = scanner.complete(
        pending, frozenset({HostPath(song)}), checkpoint=lambda: None
    )
    assert not accepted.issues
    assert {source.path for source in accepted.sources} == {
        HostPath(song),
        HostPath(playlist),
    }
    assert len(accepted.snapshot.tracks) == 1
    assert accepted.snapshot.tracks[0].length_ms == 10
    assert len(accepted.snapshot.playlists[0].entries) == 1
    assert not accepted.incomplete_playlist_ids
    assert len(inspected) == 1
    assert not Path(inspected[0]).exists()


def test_v12_cache_reparses_network_playlist_without_rereading_tracks_or_photos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    song = tmp_path / "Song.wav"
    _write_wav(song)
    photo = tmp_path / "Photo.png"
    Image.new("RGB", (2, 2)).save(photo)
    target = HostPath(Path(r"\\nas\music\External.wav"))
    playlist = tmp_path / "Favorites.m3u8"
    playlist.write_text(f"Song.wav\n{target}\n", encoding="utf-8")
    native_observe = LocalHostFile.observe

    def observe(_cls: type[LocalHostFile], path: HostPath) -> LocalHostFile:
        if path == target:
            # Resolving the reference is the regression under test. No live NAS
            # is needed to report that newly restored target for review.
            raise FileNotFoundError("Test network source is offline")
        return native_observe(path)

    def fingerprint(
        _self: FpcalcFingerprinter, _source: HostPath, *, checkpoint: Callable[[], None]
    ) -> str:
        checkpoint()
        return "1,2,3"

    monkeypatch.setattr(LocalHostFile, "observe", classmethod(observe))
    monkeypatch.setattr(FpcalcFingerprinter, "fingerprint", fingerprint)
    cache = AtomicHostFile(tmp_path / "cache.json")
    folder = create_host_media_folder(tmp_path)
    HostMediaScanner(cache).scan((folder,), checkpoint=lambda: None)

    # A genuine v12 entry has unchanged source facts but no retained UNC target,
    # because its parser rejected that reference before the cache was written.
    document = json.loads(cache.path.read_bytes())
    document["version"] = 12
    entry = next(row for row in document["entries"] if row["kind"] == "playlist")
    entry["metadata"]["references"] = [os.fspath(song)]
    entry["warning"] = "Skipped 1 unsafe or non-local Playlist references."
    document["catalog_sha256"] = hashlib.sha256(
        json.dumps(
            document["entries"],
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    cache.replace_bytes(json.dumps(document).encode())
    native_open = LocalHostFile.open_read

    def reject_media_read(
        self: LocalHostFile,
        *,
        checkpoint: Callable[[], None] | None = None,
        max_bytes: int | None = None,
    ) -> object:
        if self.path in {HostPath(song), HostPath(photo)}:
            pytest.fail("Playlist migration reread unchanged Track or Photo content")
        return native_open(self, checkpoint=checkpoint, max_bytes=max_bytes)

    monkeypatch.setattr(LocalHostFile, "open_read", reject_media_read)
    scanner = HostMediaScanner(cache)
    pending = scanner.scan((folder,), checkpoint=lambda: None)

    assert [reference.target for reference in pending.external_references] == [target]
    assert pending.external_references[0].playlists == (HostPath(playlist),)
    assert not pending.external_references[0].available
    assert not pending.issues
    assert pending.cache == HostMediaCacheStats(reused=2, inspected=1)
    stored = json.loads(cache.path.read_bytes())
    assert stored["version"] == 14
    playlist_entry = next(row for row in stored["entries"] if row["kind"] == "playlist")
    assert playlist_entry["metadata"]["references"] == [
        os.fspath(song),
        os.fspath(target),
    ]
    assert playlist_entry["warning"] == ""

    # The migration is paid once, including across application restarts.
    repeated = HostMediaScanner(cache).scan((folder,), checkpoint=lambda: None)
    assert repeated.cache == HostMediaCacheStats(reused=3)
    assert repeated.external_references == pending.external_references
