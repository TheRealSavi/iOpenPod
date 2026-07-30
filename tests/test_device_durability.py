from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from iopenpod.device import durability
from iopenpod.device import info as device_info


def _create_database(ipod_root: Path) -> Path:
    path = ipod_root / "iPod_Control" / "iTunes" / "iTunesDB"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"mhbd")
    return path


def test_linux_filesystem_flush_targets_the_ipod_and_checks_success(
    monkeypatch,
    tmp_path: Path,
) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(durability.sys, "platform", "linux")
    monkeypatch.setattr(
        durability.shutil,
        "which",
        lambda command: f"/usr/bin/{command}",
    )

    def fake_run(args, **_kwargs):
        commands.append(args)
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(durability.subprocess, "run", fake_run)

    success, message = durability.flush_filesystem(tmp_path)

    assert success is True
    assert message == "pending writes flushed"
    assert commands == [["sync", "-f", str(tmp_path)]]


@pytest.mark.skipif(
    durability.sys.platform != "linux" or not durability.shutil.which("sync"),
    reason="requires native Linux sync -f",
)
def test_linux_filesystem_flush_native_temp_directory(tmp_path: Path) -> None:
    success, message = durability.flush_filesystem(tmp_path)

    assert success is True, message


def test_linux_filesystem_flush_fails_closed_when_sync_is_unavailable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(durability.sys, "platform", "linux")
    monkeypatch.setattr(durability.shutil, "which", lambda _command: None)

    success, message = durability.flush_filesystem(tmp_path)

    assert success is False
    assert "unavailable" in message


def test_windows_filesystem_flush_checks_the_committed_database_file(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_path = _create_database(tmp_path)
    flushed_handles: list[int] = []
    monkeypatch.setattr(durability.sys, "platform", "win32")
    monkeypatch.setattr(
        durability,
        "_windows_flush_file_buffers",
        lambda file_descriptor: flushed_handles.append(file_descriptor),
        raising=False,
    )
    success, message = durability.flush_filesystem(tmp_path)

    assert success is True
    assert str(database_path) in message
    assert len(flushed_handles) == 1


def test_windows_filesystem_flush_uses_identified_classic_active_database(
    monkeypatch,
    tmp_path: Path,
) -> None:
    itunes_dir = tmp_path / "iPod_Control" / "iTunes"
    itunes_dir.mkdir(parents=True)
    stale_database = itunes_dir / "iTunesCDB"
    active_database = itunes_dir / "iTunesDB"
    stale_database.write_bytes(b"mhbd-stale")
    active_database.write_bytes(b"mhbd-active")
    monkeypatch.setattr(durability.sys, "platform", "win32")
    monkeypatch.setattr(
        device_info,
        "get_current_device",
        lambda: SimpleNamespace(
            path=str(tmp_path),
            model_family="iPod Classic",
            generation="6th Gen",
        ),
    )
    monkeypatch.setattr(
        durability,
        "_windows_flush_file_buffers",
        lambda _file_descriptor: None,
        raising=False,
    )
    monkeypatch.setattr(
        durability,
        "_windows_flush_volume_anchor",
        lambda _path, **_kwargs: (True, "Windows volume buffers flushed"),
    )

    success, message = durability.flush_filesystem(tmp_path)

    assert success is True
    assert str(active_database) in message
    assert str(stale_database) not in message


def test_windows_file_flush_is_not_a_complete_volume_barrier(
    monkeypatch,
    tmp_path: Path,
) -> None:
    database_path = _create_database(tmp_path)
    monkeypatch.setattr(durability.sys, "platform", "win32")
    monkeypatch.setattr(
        durability,
        "_windows_flush_file_buffers",
        lambda _file_descriptor: None,
        raising=False,
    )
    monkeypatch.setattr(
        durability,
        "_windows_flush_volume_anchor",
        lambda _path, **_kwargs: (False, "volume access denied"),
    )

    success, message = durability.flush_filesystem(
        tmp_path,
        require_volume_barrier=True,
    )

    assert success is False
    assert str(database_path) in message
    assert "volume access denied" in message


def test_windows_filesystem_flush_uses_volume_without_committed_database(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(durability.sys, "platform", "win32")
    calls: list[Path] = []
    monkeypatch.setattr(
        durability,
        "_windows_flush_volume_anchor",
        lambda path, **_kwargs: (
            calls.append(path) or True,
            "Windows volume buffers flushed",
        ),
    )

    success, message = durability.flush_filesystem(tmp_path)

    assert success is True
    assert message == "Windows volume buffers flushed"
    assert calls == [tmp_path]


@pytest.mark.skipif(
    durability.sys.platform != "win32",
    reason="exercises native Windows volume-handle resolution",
)
def test_windows_database_free_native_flush_has_safe_unprivileged_fallback(
    tmp_path: Path,
) -> None:
    success, message = durability.flush_filesystem(
        tmp_path,
        allow_unavailable=True,
    )

    assert success is True
    assert "volume" in message.casefold()


def test_macos_filesystem_flush_uses_full_drive_barrier(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _create_database(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(durability.sys, "platform", "darwin")
    monkeypatch.setattr(durability.os, "sync", lambda: calls.append("sync"), raising=False)
    monkeypatch.setattr(
        durability,
        "_macos_full_fsync",
        lambda _file_descriptor: calls.append("fullfsync"),
        raising=False,
    )

    success, message = durability.flush_filesystem(tmp_path)

    assert success is True
    assert "full filesystem flush" in message
    assert calls == ["sync", "fullfsync"]


def test_macos_filesystem_flush_uses_sync_when_database_was_removed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(durability.sys, "platform", "darwin")
    monkeypatch.setattr(
        durability.os,
        "sync",
        lambda: calls.append("sync"),
        raising=False,
    )

    success, message = durability.flush_filesystem(tmp_path)

    assert success is True
    assert "no regular full-fsync anchor" in message
    assert calls == ["sync"]


def test_windows_filesystem_flush_reports_failed_file_barrier(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _create_database(tmp_path)
    monkeypatch.setattr(durability.sys, "platform", "win32")

    def fail_flush(_file_descriptor: int) -> None:
        raise OSError("FlushFileBuffers failed")

    monkeypatch.setattr(
        durability,
        "_windows_flush_file_buffers",
        fail_flush,
        raising=False,
    )

    success, message = durability.flush_filesystem(tmp_path)

    assert success is False
    assert "FlushFileBuffers failed" in message


def test_flush_parent_directory_uses_a_posix_directory_barrier(
    monkeypatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "iPod_Control" / "iTunes" / "iTunesDB"
    target.parent.mkdir(parents=True)
    calls: list[tuple[str, int | str]] = []
    monkeypatch.setattr(durability.sys, "platform", "linux")
    monkeypatch.setattr(
        durability.os,
        "open",
        lambda path, flags: calls.append(("open", path)) or 73,
    )
    monkeypatch.setattr(
        durability.os,
        "fsync",
        lambda descriptor: calls.append(("fsync", descriptor)),
    )
    monkeypatch.setattr(
        durability.os,
        "close",
        lambda descriptor: calls.append(("close", descriptor)),
    )

    durability.flush_parent_directory(target)

    assert calls == [
        ("open", str(target.parent)),
        ("fsync", 73),
        ("close", 73),
    ]


def test_durable_replace_flushes_the_committed_parent_directory(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "iTunesDB.tmp"
    target = tmp_path / "iTunesDB"
    events: list[tuple[str, Path]] = []
    monkeypatch.setattr(
        durability.os,
        "replace",
        lambda old, new: events.append(("replace", Path(new))),
    )
    monkeypatch.setattr(
        durability,
        "flush_parent_directory",
        lambda path: events.append(("directory", Path(path).parent)),
        raising=False,
    )

    durability.durable_replace(source, target)

    assert events == [("replace", target), ("directory", target.parent)]


def test_durable_publish_new_never_replaces_an_existing_file(
    tmp_path: Path,
) -> None:
    source = tmp_path / "manifest.tmp"
    target = tmp_path / "manifest.json"
    source.write_bytes(b"new")
    target.write_bytes(b"preserved")

    with pytest.raises(FileExistsError):
        durability.durable_publish_new(source, target)

    assert target.read_bytes() == b"preserved"
    assert source.read_bytes() == b"new"


def test_durable_publish_new_commits_and_removes_its_temp(
    tmp_path: Path,
) -> None:
    source = tmp_path / "manifest.tmp"
    target = tmp_path / "manifest.json"
    source.write_bytes(b"verified")

    cleanup_complete = durability.durable_publish_new(source, target)

    assert cleanup_complete is True
    assert target.read_bytes() == b"verified"
    assert not source.exists()


def test_durable_publish_new_falls_back_when_hard_links_are_unavailable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "manifest.tmp"
    target = tmp_path / "manifest.json"
    source.write_bytes(b"verified")
    monkeypatch.setattr(
        durability.os,
        "link",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("hard links unavailable")
        ),
    )

    cleanup_complete = durability.durable_publish_new(source, target)

    assert cleanup_complete is True
    assert target.read_bytes() == b"verified"
    assert not source.exists()


def test_durable_publish_new_reports_only_temp_cleanup_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "manifest.tmp"
    target = tmp_path / "manifest.json"
    source.write_bytes(b"verified")
    original_unlink = durability.durable_unlink

    def fail_source_cleanup(
        path: str | Path,
        *,
        missing_ok: bool = False,
    ) -> None:
        if Path(path) == source:
            raise OSError("temp cleanup failed")
        original_unlink(path, missing_ok=missing_ok)

    monkeypatch.setattr(durability, "durable_unlink", fail_source_cleanup)

    cleanup_complete = durability.durable_publish_new(source, target)

    assert cleanup_complete is False
    assert target.read_bytes() == b"verified"
    assert source.read_bytes() == b"verified"


def test_unique_sibling_temp_does_not_follow_predictable_temp_symlink(
    tmp_path: Path,
) -> None:
    target = tmp_path / "iTunesDB"
    outside = tmp_path / "outside"
    outside.write_bytes(b"outside-safe")
    predictable = tmp_path / "iTunesDB.tmp"
    try:
        predictable.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlink creation is unavailable: {exc}")

    temp_path, temp_file = durability.open_unique_sibling_temp(target, mode="wb")
    with temp_file as file:
        file.write(b"new-database")
        durability.flush_written_file(file)
    durability.durable_replace(temp_path, target)

    assert temp_path != predictable
    assert target.read_bytes() == b"new-database"
    assert outside.read_bytes() == b"outside-safe"
    assert predictable.is_symlink()
