"""Contract tests for explicit Device and Host path values."""

from pathlib import Path

import pytest

from storage import (
    DevicePath,
    FileContent,
    HostPath,
    InvalidDevicePathError,
    InvalidHostPathError,
    TransactionState,
)
from storage._transaction_journal import (
    JournalEntry,
    TransactionJournal,
    decode,
    encode,
)


@pytest.mark.parametrize(
    "value",
    (
        "",
        ".",
        "..",
        "../Music",
        "Music/../Database",
        "/absolute/path",
        "//server/share",
        "C:/Windows",
        "Music//Track.mp3",
        "Music/./Track.mp3",
        "Music:Track.mp3",
        "Music/Track\0.mp3",
    ),
)
def test_device_path_rejects_non_relative_or_ambiguous_values(value: str) -> None:
    with pytest.raises(InvalidDevicePathError):
        DevicePath(value)


def test_device_path_normalizes_separators_and_supports_safe_composition() -> None:
    base = DevicePath("iPod_Control\\Music")
    child = base.joinpath("F00", "Track.mp3")

    assert str(base) == "iPod_Control/Music"
    assert str(child) == "iPod_Control/Music/F00/Track.mp3"
    assert child.parts == ("iPod_Control", "Music", "F00", "Track.mp3")
    assert child.name == "Track.mp3"
    assert child.parent == DevicePath("iPod_Control/Music/F00")
    assert child.is_relative_to(base)
    assert not base.is_relative_to(child)


def test_device_path_from_parts_preserves_literal_backslashes() -> None:
    path = DevicePath.from_parts(("iPod_Control", "artist\\track.mp3"))

    assert path.parts == ("iPod_Control", "artist\\track.mp3")
    assert str(path) == "iPod_Control/artist\\track.mp3"


def test_version_two_transaction_journal_preserves_exact_path_parts() -> None:
    path = DevicePath.from_parts(("iPod_Control", "artist\\track.mp3"))
    content = FileContent(1, "0" * 64)
    journal = TransactionJournal(
        "device",
        "volume",
        TransactionState.COMMITTED,
        (JournalEntry(path, None, content),),
        (),
        recovery_material_identity="recovery",
    )

    restored = decode(encode(journal))

    assert restored.entries[0].path.parts == path.parts


def test_host_path_requires_an_explicit_absolute_path(tmp_path: Path) -> None:
    path = HostPath(tmp_path / "track.mp3")

    assert Path(path) == tmp_path / "track.mp3"

    with pytest.raises(InvalidHostPathError):
        HostPath(Path("relative") / "track.mp3")
