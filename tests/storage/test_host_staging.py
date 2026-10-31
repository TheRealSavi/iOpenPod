"""Large staging uses the selected Host volume and safely reaps crashed owners."""

import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
from typing import BinaryIO

import pytest

from storage import host_staging
from storage._writer_lock import _open_lock_file  # pyright: ignore[reportPrivateUsage]
from storage.content_workspace import StagedContent, content_workspace
from storage.host_staging import RetainedStagingDirectory, cleanup_stale_staging
from storage.media_processing import media_workspace


@pytest.mark.parametrize("workers", (1, 4))
def test_retained_workspaces_keep_a_bounded_number_of_owner_descriptors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, workers: int
) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    opened: list[BinaryIO] = []
    open_lock = _open_lock_file

    def observe(path: Path) -> BinaryIO:
        stream = open_lock(path)
        opened.append(stream)
        return stream

    monkeypatch.setattr(host_staging, "_open_lock_file", observe)

    def prepare(index: int) -> ExitStack:
        with ExitStack() as resources:
            workspace = resources.enter_context(
                media_workspace(checkpoint=lambda: None)
            )
            Path(workspace.output_path(".mp3")).write_bytes(bytes([index]))
            return resources.pop_all()

    with ExitStack() as resources, ThreadPoolExecutor(max_workers=workers) as pool:
        for lifetime in pool.map(prepare, range(48)):
            resources.enter_context(lifetime)
        assert sum(not stream.closed for stream in opened) <= 1
        assert cleanup_stale_staging() == 0
    assert all(stream.closed for stream in opened)


@pytest.mark.parametrize("name", ("TMPDIR", "TEMP", "TMP"))
def test_explicit_temporary_volume_is_used_for_media_and_spilled_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    for variable in ("TMPDIR", "TEMP", "TMP"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv(name, str(tmp_path))
    with (
        media_workspace(checkpoint=lambda: None) as media,
        content_workspace(memory_budget=0, checkpoint=lambda: None) as content,
    ):
        output = Path(media.output_path(".mp3"))
        output.write_bytes(b"media")
        spilled = content.store(b"overflow")
        assert isinstance(spilled, StagedContent)
        assert output.is_relative_to(tmp_path)
        assert Path(spilled.path).is_relative_to(tmp_path)
        assert cleanup_stale_staging() == 0
        assert output.read_bytes() == b"media"
        assert spilled.read_at(0, len(spilled)) == b"overflow"
    assert not output.exists()
    assert not Path(spilled.path).exists()


def test_tmpdir_takes_precedence_and_invalid_override_does_not_fall_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    chosen = tmp_path / "chosen"
    chosen.mkdir()
    monkeypatch.setenv("TMPDIR", str(chosen))
    monkeypatch.setenv("TEMP", str(tmp_path))
    monkeypatch.setenv("TMP", str(tmp_path))
    with media_workspace(checkpoint=lambda: None) as workspace:
        assert Path(workspace.output_path(".mp3")).is_relative_to(chosen)
    monkeypatch.setenv("TMPDIR", str(tmp_path / "missing"))
    with pytest.raises(OSError), media_workspace(checkpoint=lambda: None):
        pytest.fail("An unavailable staging override silently fell back")
    assert cleanup_stale_staging() == 0


@pytest.mark.parametrize("kind", ("media", "content", "chaptered"))
def test_abrupt_process_exit_leaves_only_owned_files_for_startup_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    script = """
import os, sys
from pathlib import Path
from storage.media_processing import media_workspace
from storage.content_workspace import content_workspace
from storage.host_staging import RetainedStagingDirectory
if sys.argv[1] == 'media':
    with media_workspace(checkpoint=lambda: None) as workspace:
        path = Path(workspace.output_path('.mp3'))
        path.write_bytes(bytes(256 * 1024))
        print(path, flush=True)
        os._exit(17)
elif sys.argv[1] == 'content':
    with content_workspace(memory_budget=0, checkpoint=lambda: None) as workspace:
        content = workspace.store(bytes(256 * 1024))
        print(content.path, flush=True)
        os._exit(17)
else:
    directory = RetainedStagingDirectory('iopenpod-chaptered-')
    path = Path(directory.name) / 'chaptered.m4a'
    path.write_bytes(bytes(256 * 1024))
    print(path, flush=True)
    os._exit(17)
"""
    crashed = subprocess.run(
        [sys.executable, "-c", script, kind],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert crashed.returncode == 17, crashed.stderr
    path = Path(crashed.stdout.strip())
    assert path.is_relative_to(tmp_path)
    assert path.stat().st_size == 256 * 1024
    assert cleanup_stale_staging() == 1
    assert not path.parent.exists()
    assert cleanup_stale_staging() == 0


def test_draft_owned_staging_lives_until_explicit_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    directory = RetainedStagingDirectory("iopenpod-chaptered-")
    try:
        path = Path(directory.name) / "chaptered.m4a"
        path.write_bytes(b"prepared album")
        assert cleanup_stale_staging() == 0
        assert path.read_bytes() == b"prepared album"
    finally:
        directory.cleanup()
    directory.cleanup()
    assert not Path(directory.name).exists()


def test_cleanup_in_another_process_cannot_remove_a_live_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    with media_workspace(checkpoint=lambda: None) as workspace:
        path = Path(workspace.output_path(".mp3"))
        path.write_bytes(b"prepared media")
        checked = subprocess.run(
            [
                sys.executable,
                "-c",
                "from storage.host_staging import cleanup_stale_staging; "
                "print(cleanup_stale_staging())",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        assert checked.stdout.strip() == "0"
        assert path.read_bytes() == b"prepared media"


def test_closing_one_workspace_keeps_other_workspaces_owned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    first = RetainedStagingDirectory("iopenpod-chaptered-")
    second = RetainedStagingDirectory("iopenpod-content-")
    try:
        path = Path(second.name) / "retained"
        path.write_bytes(b"still in use")
        first.cleanup()
        checked = subprocess.run(
            [
                sys.executable,
                "-c",
                "from storage.host_staging import cleanup_stale_staging; "
                "print(cleanup_stale_staging())",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        assert checked.stdout.strip() == "0"
        assert path.read_bytes() == b"still in use"
    finally:
        first.cleanup()
        second.cleanup()
    assert not tuple(Path(second.name).parent.glob(".iopenpod-process-*"))


def test_crashed_shared_owner_reaps_all_workspaces_but_preserves_live_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    with media_workspace(checkpoint=lambda: None) as live:
        path = Path(live.output_path(".mp3"))
        path.write_bytes(b"live media")
        script = """
import os
from contextlib import ExitStack
from pathlib import Path
from storage.media_processing import media_workspace
with ExitStack() as resources:
    for _ in range(4):
        workspace = resources.enter_context(media_workspace(checkpoint=lambda: None))
        Path(workspace.output_path('.mp3')).write_bytes(b'crashed media')
    os._exit(17)
"""
        crashed = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, timeout=10, check=False
        )
        assert crashed.returncode == 17, crashed.stderr
        assert cleanup_stale_staging() == 4
        assert cleanup_stale_staging() == 0
        assert path.read_bytes() == b"live media"
    assert cleanup_stale_staging() == 0
    assert not tuple(path.parent.parent.glob(".iopenpod-process-*"))


def test_cleanup_still_recovers_legacy_workspace_markers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    directory = RetainedStagingDirectory("iopenpod-chaptered-")
    root = Path(directory.name).parent
    directory.cleanup()
    legacy = root / "iopenpod-media-legacy"
    legacy.mkdir(mode=0o700)
    (legacy / ".iopenpod-owner").write_bytes(b"iopenpod-host-staging-v1\n")
    (legacy / "source").write_bytes(b"abandoned media")
    assert cleanup_stale_staging() == 1
    assert not legacy.exists()


def test_failed_normal_cleanup_leaves_an_unlocked_owner_for_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path))

    def fail_removal(_name: str, **_kwargs: object) -> None:
        raise PermissionError("prepared file is temporarily busy")

    with (
        monkeypatch.context() as failure,
        pytest.raises(PermissionError, match="temporarily busy"),
    ):
        failure.setattr(
            tempfile.TemporaryDirectory, "_rmtree", staticmethod(fail_removal)
        )
        with media_workspace(checkpoint=lambda: None) as workspace:
            path = Path(workspace.output_path(".mp3"))
            path.write_bytes(b"prepared media")
    assert path.exists()
    assert cleanup_stale_staging() == 1
    assert not path.parent.exists()
    assert not tuple(path.parent.parent.glob(".iopenpod-process-*"))


@pytest.mark.parametrize(
    "owner",
    (
        b"../outside",
        b".cleanup-lock",
        b".iopenpod-process-" + b"0" * 32,
        b".iopenpod-process-" + b"g" * 32,
        b".iopenpod-process-" + b"0" * 32 + b"\ntrailing bytes",
        b"\xff" * 32,
    ),
)
def test_cleanup_preserves_shared_markers_without_a_valid_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, owner: bytes
) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    directory = RetainedStagingDirectory("iopenpod-chaptered-")
    root = Path(directory.name).parent
    directory.cleanup()
    abandoned = root / "iopenpod-media-untrusted"
    abandoned.mkdir(mode=0o700)
    (abandoned / ".iopenpod-owner").write_bytes(
        b"iopenpod-host-staging-v2\n" + owner + b"\n"
    )
    original = abandoned / "source"
    original.write_bytes(b"keep me")
    assert cleanup_stale_staging() == 0
    assert original.read_bytes() == b"keep me"


def test_concurrent_startup_cleanup_does_not_race_workspace_creation_or_close(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    cleaner = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "from storage.host_staging import cleanup_stale_staging; "
            "[cleanup_stale_staging() for _ in range(5000)]",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        for _ in range(600):
            with media_workspace(checkpoint=lambda: None) as workspace:
                output = Path(workspace.output_path(".mp3"))
                output.write_bytes(b"prepared data")
            assert not output.parent.exists()
        _, errors = cleaner.communicate(timeout=20)
        assert cleaner.returncode == 0, errors
    finally:
        if cleaner.poll() is None:
            cleaner.kill()
        cleaner.communicate(timeout=10)


def test_cleanup_ignores_unmarked_and_unexpected_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    with media_workspace(checkpoint=lambda: None) as workspace:
        root = Path(workspace.output_path(".mp3")).parent.parent
    unrelated = root / "iopenpod-media-unmarked"
    unrelated.mkdir(mode=0o700)
    original = unrelated / "source"
    original.write_bytes(b"unowned data")
    marker = unrelated / ".iopenpod-owner"
    assert cleanup_stale_staging() == 0
    assert not marker.exists()
    assert original.read_bytes() == b"unowned data"
    marker.write_bytes(b"not a staging marker")
    assert cleanup_stale_staging() == 0
    assert original.read_bytes() == b"unowned data"
    # A valid marker alone must not authorize recursive deletion.
    marker.write_bytes(b"iopenpod-host-staging-v1\n")
    (unrelated / "unexpected").mkdir()
    assert cleanup_stale_staging() == 0
    assert original.read_bytes() == b"unowned data"


def test_cleanup_does_not_follow_linked_workspaces_or_payloads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    with media_workspace(checkpoint=lambda: None) as workspace:
        root = Path(workspace.output_path(".mp3")).parent.parent
    outside = tmp_path / "outside"
    outside.mkdir()
    original = outside / "source"
    original.write_bytes(b"unowned data")
    linked = root / "iopenpod-media-linked"
    try:
        linked.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Host does not permit symbolic links")
    assert cleanup_stale_staging() == 0
    assert original.read_bytes() == b"unowned data"
    linked.unlink()
    linked.mkdir(mode=0o700)
    (linked / ".iopenpod-owner").write_bytes(b"iopenpod-host-staging-v1\n")
    (linked / "source").symlink_to(original)
    assert cleanup_stale_staging() == 0
    assert original.read_bytes() == b"unowned data"


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory permissions")
def test_cleanup_rejects_a_shared_staging_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    with media_workspace(checkpoint=lambda: None) as workspace:
        root = Path(workspace.output_path(".mp3")).parent.parent
    root.chmod(0o777)
    try:
        assert cleanup_stale_staging() == 0
        with (
            pytest.raises(ValueError, match="private"),
            media_workspace(checkpoint=lambda: None),
        ):
            pytest.fail("Shared staging root was accepted")
    finally:
        root.chmod(0o700)
