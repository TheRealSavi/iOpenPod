"""Explicit aliases and opt-in recursive links retain bounded scan authority."""

import os
import wave
from collections import Counter
from collections.abc import Callable
from pathlib import Path

import pytest
from PIL import Image

from iOpenPod.app.host_media_fingerprint import FpcalcFingerprinter
from iOpenPod.app.host_media_folders import HostMediaFolder, HostMediaType
from iOpenPod.app.host_media_library import HostMediaScanner
from storage import AtomicHostFile, HostPath, StorageError
from storage.host_directory import HostDirectoryEntry, LocalHostDirectory


def _song(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(8000)
        stream.writeframes(b"\0\0" * 80)


def _link(alias: Path, target: Path, *, directory: bool = False) -> None:
    try:
        alias.symlink_to(target, target_is_directory=directory)
    except OSError as error:
        pytest.skip(f"Host cannot create symbolic links: {error}")


@pytest.fixture(autouse=True)
def fingerprints(monkeypatch: pytest.MonkeyPatch) -> list[HostPath]:
    calls: list[HostPath] = []

    def fingerprint(
        _self: FpcalcFingerprinter, source: HostPath, *, checkpoint: Callable[[], None]
    ) -> str:
        checkpoint()
        calls.append(source)
        return "1,2,3"

    monkeypatch.setattr(FpcalcFingerprinter, "fingerprint", fingerprint)
    return calls


@pytest.mark.parametrize("kind", ["root", "child", "file", "file-link"])
def test_explicit_alias_is_accepted_without_following_children(
    tmp_path: Path, kind: str
) -> None:
    real = tmp_path / "real"
    album = real / "album"
    song = album / "song.wav"
    _song(song)
    _song(tmp_path / "outside.wav")
    _link(album / "unselected.wav", tmp_path / "outside.wav")
    alias = tmp_path / "alias"
    _link(alias, real, directory=True)
    _link(tmp_path / "selected", song)
    scanner = HostMediaScanner()
    if kind in {"root", "child"}:
        selected = alias if kind == "root" else alias / "album"
        pending = scanner.scan(
            (HostMediaFolder(HostPath(selected)),), checkpoint=lambda: None
        )
    else:
        selected = alias / "album/song.wav" if kind == "file" else tmp_path / "selected"
        pending = scanner.scan((), files=(HostPath(selected),), checkpoint=lambda: None)
    library = scanner.complete(pending, frozenset(), checkpoint=lambda: None)
    assert [source.path for source in library.sources] == [HostPath(song)]


@pytest.mark.parametrize("recurse", [False, True])
@pytest.mark.parametrize("follow", [False, True])
def test_link_permission_and_recursion_are_independent(
    tmp_path: Path, recurse: bool, follow: bool
) -> None:
    root = tmp_path / "selected"
    root.mkdir()
    _song(tmp_path / "outside/file.wav")
    _song(tmp_path / "album/nested.wav")
    _link(root / "file.wav", tmp_path / "outside/file.wav")
    _link(root / "album", tmp_path / "album", directory=True)
    pending = HostMediaScanner().scan(
        (HostMediaFolder(HostPath(root), recurse=recurse, follow_symlinks=follow),),
        checkpoint=lambda: None,
    )
    expected: set[HostPath] = (
        {HostPath(tmp_path / "outside/file.wav")} if follow else set()
    )
    if follow and recurse:
        expected.add(HostPath(tmp_path / "album/nested.wav"))
    assert {record.path for record in pending.records} == expected
    if not follow:
        assert any(
            "Follow symbolic links is disabled" in issue.detail
            for issue in pending.issues
        )


@pytest.mark.parametrize("workers", [1, 3])
def test_cycles_aliases_and_hardlinks_do_not_repeat_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fingerprints: list[HostPath],
    workers: int,
) -> None:
    root = tmp_path / "selected"
    album = root / "album"
    song = album / "a.wav"
    _song(song)
    os.link(song, album / "b.wav")
    _link(root / "first", album, directory=True)
    _link(root / "second", album, directory=True)
    _link(album / "parent", root, directory=True)
    _link(album / "self", album, directory=True)
    (album / "list.m3u8").write_text("b.wav\na.wav\n", encoding="utf-8")
    native = LocalHostDirectory.list_entries
    listings: Counter[HostPath] = Counter()

    def listing(
        self: LocalHostDirectory,
        *,
        checkpoint: Callable[[], None],
        on_issue: Callable[[HostPath, OSError | StorageError], None] | None = None,
        include_file: Callable[[str], bool] | None = None,
        include_directories: bool = True,
        include_links: bool = False,
        on_entry: Callable[[HostDirectoryEntry], None] | None = None,
    ) -> tuple[HostDirectoryEntry, ...]:
        listings[self.path] += 1
        return native(
            self,
            checkpoint=checkpoint,
            on_issue=on_issue,
            include_file=include_file,
            include_directories=include_directories,
            include_links=include_links,
            on_entry=on_entry,
        )

    monkeypatch.setattr(LocalHostDirectory, "list_entries", listing)
    scanner = HostMediaScanner(
        AtomicHostFile(tmp_path / "cache.json"), max_directory_workers=workers
    )
    folders = (
        HostMediaFolder(HostPath(root), follow_symlinks=True),
        HostMediaFolder(HostPath(root / "first")),
    )
    for warm in (False, True):
        listings.clear()
        pending = scanner.scan(
            folders, files=(HostPath(song),), checkpoint=lambda: None
        )
        result = scanner.complete(pending, frozenset(), checkpoint=lambda: None)
        assert len(result.snapshot.tracks) == 1
        assert len(result.snapshot.playlists[0].entries) == 2
        assert result.incomplete_playlist_ids == ()
        assert listings == {HostPath(root): 2, HostPath(album): 2}
        assert result.cache.inspected == (0 if warm else 2)
    assert fingerprints == [HostPath(song)]


@pytest.mark.parametrize("reverse", [False, True])
def test_overlapping_link_grants_preserve_each_media_scope(
    tmp_path: Path, reverse: bool
) -> None:
    root = tmp_path / "root"
    album = root / "album"
    _song(album / "song.wav")
    Image.new("RGB", (2, 2)).save(album / "photo.png")
    _song(tmp_path / "outside/elsewhere.wav")
    Image.new("RGB", (2, 2)).save(tmp_path / "outside/elsewhere.png")
    _link(album / "outside", tmp_path / "outside", directory=True)
    _link(root / "alias", album, directory=True)
    # Recursing through audio grants cannot inherit the Photo-only root's type.
    folders = (
        HostMediaFolder(
            HostPath(root),
            media_types=frozenset({HostMediaType.AUDIO}),
            follow_symlinks=True,
        ),
        HostMediaFolder(
            HostPath(album),
            recurse=False,
            media_types=frozenset({HostMediaType.PHOTOS}),
            follow_symlinks=True,
        ),
    )
    pending = HostMediaScanner().scan(
        tuple(reversed(folders)) if reverse else folders, checkpoint=lambda: None
    )
    assert {record.path for record in pending.records} == {
        HostPath(album / "song.wav"),
        HostPath(album / "photo.png"),
        HostPath(tmp_path / "outside/elsewhere.wav"),
    }


def test_broken_and_cyclic_links_are_reported(tmp_path: Path) -> None:
    _link(tmp_path / "broken.wav", tmp_path / "missing.wav")
    _link(tmp_path / "cycle.wav", tmp_path / "cycle.wav")
    pending = HostMediaScanner().scan(
        (HostMediaFolder(HostPath(tmp_path), follow_symlinks=True),),
        checkpoint=lambda: None,
    )
    assert not pending.records
    assert {issue.path for issue in pending.issues} == {
        HostPath(tmp_path / "broken.wav"),
        HostPath(tmp_path / "cycle.wav"),
    }
    assert all("could not be followed" in issue.detail for issue in pending.issues)


def test_indirect_playlist_link_remains_unavailable(tmp_path: Path) -> None:
    _song(tmp_path / "outside/song.wav")
    root = tmp_path / "selected"
    root.mkdir()
    _link(root / "alias.wav", tmp_path / "outside/song.wav")
    (root / "list.m3u8").write_text("alias.wav\n", encoding="utf-8")
    pending = HostMediaScanner().scan(
        (HostMediaFolder(HostPath(root), follow_symlinks=True),),
        checkpoint=lambda: None,
    )
    assert len(pending.external_references) == 1
    assert not pending.external_references[0].available


def test_retargeting_selected_root_does_not_redirect_later_scan_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _song(tmp_path / "first/song.wav")
    _song(tmp_path / "second/other.wav")
    alias = tmp_path / "alias"
    _link(alias, tmp_path / "first", directory=True)

    def fingerprint(
        _self: FpcalcFingerprinter, source: HostPath, *, checkpoint: Callable[[], None]
    ) -> str:
        alias.unlink()
        _link(alias, tmp_path / "second", directory=True)
        return "1,2,3"

    monkeypatch.setattr(FpcalcFingerprinter, "fingerprint", fingerprint)
    scanner = HostMediaScanner()
    pending = scanner.scan((HostMediaFolder(HostPath(alias)),), checkpoint=lambda: None)
    result = scanner.complete(pending, frozenset(), checkpoint=lambda: None)
    assert [source.path for source in result.sources] == [
        HostPath(tmp_path / "first/song.wav")
    ]
