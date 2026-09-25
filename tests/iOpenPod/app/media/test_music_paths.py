"""Short device names remain unique without lengthening collision fallbacks."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import PurePosixPath

import pytest

from iOpenPod.app.media.music_paths import MusicPathAllocator
from storage import DevicePath


@pytest.fixture(autouse=True)
def start_at_first_name(monkeypatch: pytest.MonkeyPatch) -> None:
    def first_slot(_limit: int) -> int:
        return 0

    monkeypatch.setattr("iOpenPod.app.media.music_paths.randbelow", first_slot)


def test_existing_and_pending_names_are_reserved_case_insensitively() -> None:
    allocator = MusicPathAllocator(
        2,
        (
            ":iPod_Control:Music:F00:aAaA.MP3",
            "iPod_Control\\Music\\F01\\aaaa.m4a",
            "iPod_Control/Music/F00/AAAB.m4v",
            "iPod_Control/Music/F00/long-legacy-name.mp3",
        ),
    )
    assert allocator.allocate("M4A") == "iPod_Control/Music/F01/AAAB.m4a"
    assert allocator.allocate("mp3") == "iPod_Control/Music/F00/AAAC.mp3"


def test_untracked_file_collisions_retry_with_another_four_letter_name() -> None:
    checked: list[DevicePath] = []

    def exists(path: DevicePath) -> bool:
        checked.append(path)
        return path.name in {"AAAA.m4a", "AAAB.m4a"}

    allocator = MusicPathAllocator(1, exists=exists)
    assert allocator.allocate("m4a") == "iPod_Control/Music/F00/AAAC.m4a"
    assert [path.name for path in checked] == ["AAAA.m4a", "AAAB.m4a", "AAAC.m4a"]
    assert allocator.allocate("mp3") == "iPod_Control/Music/F00/AAAD.mp3"


def test_concurrent_allocations_are_unique_and_distributed_across_profile_folders() -> (
    None
):
    allocator = MusicPathAllocator(3)

    def allocate(_index: int) -> str:
        return allocator.allocate("m4a")

    with ThreadPoolExecutor(max_workers=8) as workers:
        paths = tuple(workers.map(allocate, range(1200)))
    assert len(set(paths)) == 1200
    for path in map(PurePosixPath, paths):
        assert len(path.stem) == 4 and path.stem.isascii() and path.stem.isupper()
        assert path.suffix == ".m4a"
    assert {
        folder: sum(PurePosixPath(path).parent.name == folder for path in paths)
        for folder in ("F00", "F01", "F02")
    } == {"F00": 400, "F01": 400, "F02": 400}


def test_exhaustion_stops_without_overwriting_or_lengthening_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("iOpenPod.app.media.music_paths._NAMES_PER_DIRECTORY", 2)
    allocator = MusicPathAllocator(1)
    assert allocator.allocate("m4a").endswith("/AAAA.m4a")
    assert allocator.allocate("mp3").endswith("/AAAB.mp3")
    with pytest.raises(ValueError, match=r"No unused four-letter.*rescan"):
        allocator.allocate("m4a")


def test_collision_search_is_cancellable() -> None:
    probes = 0

    def exists(_path: DevicePath) -> bool:
        nonlocal probes
        probes += 1
        return True

    def checkpoint() -> None:
        if probes == 3:
            raise InterruptedError("cancelled")

    with pytest.raises(InterruptedError, match="cancelled"):
        MusicPathAllocator(1, exists=exists).allocate("m4a", checkpoint=checkpoint)
    assert probes == 3


def test_wraps_from_zzzz_to_aaaa_without_lengthening(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def last_slot(limit: int) -> int:
        return limit - 1

    monkeypatch.setattr("iOpenPod.app.media.music_paths.randbelow", last_slot)
    allocator = MusicPathAllocator(2)
    assert allocator.allocate("m4a") == "iPod_Control/Music/F01/ZZZZ.m4a"
    assert allocator.allocate("m4a") == "iPod_Control/Music/F00/AAAA.m4a"


@pytest.mark.parametrize("count", [0, -1])
def test_invalid_directory_count_is_rejected(count: int) -> None:
    with pytest.raises(ValueError, match="at least one"):
        MusicPathAllocator(count)


@pytest.mark.parametrize("extension", ["", "../mp3", "m4a/other", "flac"])
def test_invalid_extension_cannot_escape_device_location(extension: str) -> None:
    with pytest.raises(ValueError, match="supported iPod media"):
        MusicPathAllocator(1).allocate(extension)
