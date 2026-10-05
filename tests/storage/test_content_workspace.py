"""Memory overflow preserves content, file identity, and temporary-file lifetime."""

import hashlib
from pathlib import Path

import pytest

from storage import ConcurrentModificationError
from storage.content_workspace import (
    ContentFileBuffer,
    StagedContent,
    content_workspace,
)


def test_aggregate_budget_spills_only_overflow_and_cleans_files() -> None:
    with content_workspace(memory_budget=5, checkpoint=lambda: None) as workspace:
        assert workspace.store(b"first") == b"first"
        assert workspace.remaining_bytes == 0
        content = workspace.store(b"second")
        assert isinstance(content, StagedContent)
        path = Path(content.path)
        assert content.read_at(1, 3) == b"eco"
        assert len(content) == 6
        assert content.sha256 == hashlib.sha256(b"second").hexdigest()
        with pytest.raises(ValueError, match="out of bounds"):
            content.read_at(4, 3)
    assert not path.exists()


def test_growing_output_moves_its_prefix_to_disk_and_releases_memory() -> None:
    with content_workspace(memory_budget=5, checkpoint=lambda: None) as workspace:
        output = workspace.new_buffer()
        output.append(b"abc")
        assert workspace.remaining_bytes == 2
        output.append(b"def")
        output.append(b"ghi")
        content = output.finish()
        assert isinstance(content, StagedContent)
        assert content.read_at(0, 9) == b"abcdefghi"
        assert content.sha256 == hashlib.sha256(b"abcdefghi").hexdigest()
        assert workspace.remaining_bytes == 5
        assert workspace.store(b"small") == b"small"
        with pytest.raises(ValueError, match="frozen"):
            output.append(b"late")


def test_staged_content_rejects_a_changed_file() -> None:
    with content_workspace(memory_budget=0, checkpoint=lambda: None) as workspace:
        content = workspace.store(b"original")
        assert isinstance(content, StagedContent)
        Path(content.path).write_bytes(b"changed")
        with pytest.raises(ConcurrentModificationError):
            content.read_at(0, len(content))


def test_abandoned_output_releases_its_memory_and_closed_workspace_rejects_use() -> (
    None
):
    with content_workspace(memory_budget=5, checkpoint=lambda: None) as workspace:
        output = workspace.new_buffer()
        output.append(b"first")
        output.close()
        assert workspace.remaining_bytes == 5
        assert workspace.store(b"other") == b"other"
    with pytest.raises(ValueError, match="closed"):
        workspace.new_buffer()


def test_cancellation_closes_unfinished_outputs_and_removes_private_files() -> None:
    cancelled = False
    directory: Path | None = None

    def checkpoint() -> None:
        if cancelled:
            raise InterruptedError("cancelled")

    with (
        pytest.raises(InterruptedError),
        content_workspace(memory_budget=0, checkpoint=checkpoint) as workspace,
    ):
        content = workspace.store(b"finished")
        assert isinstance(content, StagedContent)
        directory = Path(content.path).parent
        output = workspace.new_buffer()
        output.append(b"unfinished")
        cancelled = True
        output.append(b"cancel")
    assert directory is not None and not directory.exists()


def test_cleanup_continues_if_an_output_reports_a_close_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed: list[ContentFileBuffer] = []
    original_close = ContentFileBuffer.close

    def close_with_error(buffer: ContentFileBuffer) -> None:
        original_close(buffer)
        closed.append(buffer)
        raise OSError("failed to flush output")

    with (
        pytest.raises(OSError, match="failed to flush"),
        content_workspace(memory_budget=0, checkpoint=lambda: None) as workspace,
    ):
        first = workspace.new_buffer()
        first.append(b"first")
        second = workspace.new_buffer()
        second.append(b"second")
        monkeypatch.setattr(ContentFileBuffer, "close", close_with_error)
    assert len(closed) == 2
    assert closed[0] is not closed[1]
