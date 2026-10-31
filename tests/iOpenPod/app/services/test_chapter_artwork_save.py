"""Native Chapter layouts and flags survive ordinary Library save workflows."""

import struct
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.test_device_coordinator import (
    _install_nano5_hash72_metadata,  # pyright: ignore[reportPrivateUsage]
    _install_sqlite_postprocess_metadata,  # pyright: ignore[reportPrivateUsage]
    _ipod_volume,  # pyright: ignore[reportPrivateUsage]
)
from tests.iPodDB.library.test_native_chapters import chapter_payload, chapter_source
from tests.iPodDB.library.test_write_artwork import BLUE, RED
from tests.iPodDB.SQLiteDB.sqlite_test_support import sqlite_rows

from device_registry import DEFAULT_DEVICE_REGISTRY
from iOpenPod.app.artwork_policy import (
    application_chapter_formats,
    application_cover_formats,
)
from iOpenPod.app.library_write import LibraryPreparationRequest
from iOpenPod.app.services.device_coordinator import DeviceCoordinator
from iPodDB.iTunesDB.cdb import compress_iTunesCDB, decompress_iTunesCDB
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.chapter_data_mhod import (
    MhodChapterDataPayload,
)
from iPodDB.library import (
    ArtworkGroupReference,
    IPodLibrary,
    TimedArtworkAsset,
    TimedArtworkFrame,
    WriteResources,
    WriteTarget,
    content_sha256,
    read_content,
)
from storage import Storage
from storage.testing import VirtualStoragePlatform


@pytest.mark.parametrize("flags", [1, 0x80000001])
@pytest.mark.parametrize(
    ("model", "chapter_ids"),
    [
        pytest.param("MA002", (1028, 1029), id="video5"),
        pytest.param("MA444", (1028, 1029), id="video5.5"),
        pytest.param("MA978", (1055, 1029), id="nano3"),
        pytest.param("MB480", (1071,), id="nano4"),
        pytest.param("MC027", (1073,), id="nano5"),
    ],
)
@pytest.mark.parametrize(
    "timed", [True, False], ids=["chapter-images", "ordinary-cover"]
)
def test_save_coordinates_chapter_flags_only_for_explicit_timeline(
    tmp_path: Path, flags: int, timed: bool, model: str, chapter_ids: tuple[int, ...]
) -> None:
    source = chapter_source(chapter_payload(flags))
    profile = DEFAULT_DEVICE_REGISTRY.profile_for_model_number(model)
    assert profile is not None
    compressed = profile.capabilities.database.supports_compressed_database
    database_name = "iTunesCDB" if compressed else "iTunesDB"
    root = _ipod_volume(
        tmp_path / "ipod", model_number=model, database_name=database_name
    )
    database = root / "iPod_Control/iTunes" / database_name
    logical = source.serialize().itunes
    original = compress_iTunesCDB(logical) if compressed else logical
    database.write_bytes(original)
    if profile.capabilities.database.uses_sqlite_database:
        _install_nano5_hash72_metadata(root, bytes.fromhex("000A270012345678"))
        _install_sqlite_postprocess_metadata(root, ("PRAGMA main.user_version = 42;",))
    else:
        (root / "iPod_Control/Device/SysInfo").write_text(
            f"ModelNumStr: {model}\nFirewireGuid: 000A270012345678\n",
            encoding="utf-8",
        )
    platform = VirtualStoragePlatform()
    platform.add_volume(root, label="Chapter artwork test")
    coordinator = DeviceCoordinator(
        Storage(platform, writer_lock_directory=tmp_path / "locks"),
        volume_presentation_enabled=False,
    )
    try:
        active = coordinator.select_device(
            coordinator.discover_devices().candidates[0].id
        )
        assert active.profile.model_number == model
        first = active.library.tracks[0]
        desired = replace(
            active.library,
            tracks=(
                replace(first, artwork_id=RED.artwork_id),
                *active.library.tracks[1:],
            ),
        )
        asset = (
            TimedArtworkAsset(
                RED.artwork_id,
                (TimedArtworkFrame(0, RED.pixels), TimedArtworkFrame(500, BLUE.pixels)),
            )
            if timed
            else RED
        )
        review = coordinator.prepare_library(
            LibraryPreparationRequest(desired, active, 1, 1, artwork=(asset,)),
            lambda _: None,
            Event(),
        )
        assert review.result.prepared is not None, review.result.issues
        prepared = review.result.prepared
        assert (
            prepared.sqlite is not None
        ) is profile.capabilities.database.uses_sqlite_database
        assert review.plan is not None and review.resources is not None

        # Shared cover/Chapter layouts retain identical pixels. Nano 3 also
        # needs a new F1029 shard for its separate Chapter representation.
        baseline = source.prepare(
            source.analyze(
                source.begin_draft(desired),
                replace(review.plan.target, chapter_formats=()),
            ),
            review.resources,
        )
        assert baseline.prepared is not None, baseline.issues
        actual_files = {
            f.relative_path: (len(f.data), content_sha256(f.data))
            for f in prepared.artwork_files
        }
        cover_files = {
            f.relative_path: (len(f.data), content_sha256(f.data))
            for f in baseline.prepared.artwork_files
        }
        assert cover_files.items() <= actual_files.items()
        extra_files = actual_files.keys() - cover_files.keys()
        if timed and model == "MA978":
            assert len(extra_files) == 1
            assert next(iter(extra_files)).endswith("F1029_1.ithmb")
        else:
            assert not extra_files
        covers = application_cover_formats(active.profile)
        assert len(prepared.artwork_files) == len(
            {f.format_id for f in covers} | (set(chapter_ids) if timed else set())
        )
        assert database.read_bytes() == original

        saved = coordinator.save_library(review, active, lambda _: None, Event())
        assert saved.active is not None, saved.issues
        loaded = IPodLibrary.parse(database.read_bytes()).with_artwork(
            (root / "iPod_Control/Artwork/ArtworkDB").read_bytes()
        )
        track = loaded.snapshot.tracks[0]
        expected_flags = flags | 3 if timed else flags
        assert track.ipod is not None and track.ipod.native_chapters is not None
        assert track.ipod.native_chapters.flags == expected_flags
        assert track.ipod.native_chapters.chapter_artwork_eligible is timed
        assert track.metadata.chapters == first.metadata.chapters
        assert loaded.artwork_display_times(track.artwork_id) == (
            (0, 500) if timed else (0,)
        )

        saved_bytes = database.read_bytes()
        document = parse_iTunesDB(
            decompress_iTunesCDB(saved_bytes).logical_bytes
            if compressed
            else saved_bytes
        )
        first_row = document.find_chunks(MhitHeader)[0].chunk
        chapter_blob = next(
            child.raw_body
            for child in first_row.children
            if isinstance(child.payload, MhodChapterDataPayload)
        )
        if prepared.sqlite is not None:
            extras_path = root / "iPod_Control/iTunes/iTunes Library.itlp/Extras.itdb"
            extras = extras_path.read_bytes()
            assert extras == prepared.sqlite.extras
            assert sqlite_rows(extras, "SELECT data FROM chapter") == ((chapter_blob,),)
        header_offset = chapter_blob.index(b"hedr") - 4
        assert (
            struct.unpack_from(">I", chapter_blob, header_offset + 0x18)[0]
            == expected_flags
        )

        formats = application_chapter_formats(active.profile)
        assert tuple(f.format_id for f in formats) == chapter_ids
        for format_ in formats:
            if not timed and format_.format_id not in {f.format_id for f in covers}:
                continue
            for time, pixels in (
                ((0, RED.pixels), (500, BLUE.pixels)) if timed else ((0, RED.pixels),)
            ):
                read = loaded.artwork_read(
                    track.artwork_id, (format_,), format_.width, display_time_ms=time
                )
                assert read is not None
                encoded = (root / read.relative_path).read_bytes()
                decoded = read.decode(encoded[read.offset : read.offset + read.length])
                assert (decoded.width, decoded.height) == (
                    format_.width,
                    format_.height,
                )
                assert decoded.rgb888 == pixels.rgb888[:3] * (
                    format_.width * format_.height
                )
    finally:
        coordinator.close()


def test_nano3_reapplying_saved_timeline_adds_only_missing_f1029(
    tmp_path: Path,
) -> None:
    source = chapter_source(chapter_payload(0x80000001))
    profile = DEFAULT_DEVICE_REGISTRY.profile_for_model_number("MA978")
    assert profile is not None
    first = source.snapshot.tracks[0]
    desired = replace(
        source.snapshot,
        tracks=(replace(first, artwork_id=RED.artwork_id), *source.snapshot.tracks[1:]),
    )
    original_result = source.prepare(
        source.analyze(
            source.begin_draft(desired),
            WriteTarget(
                database_version=0x30,
                cover_formats=application_cover_formats(profile),
                artwork_root_value=6,
            ),
        ),
        WriteResources(
            artwork=(
                TimedArtworkAsset(
                    RED.artwork_id,
                    (
                        TimedArtworkFrame(0, RED.pixels),
                        TimedArtworkFrame(500, BLUE.pixels),
                    ),
                ),
            ),
            file_inventory=(),
        ),
    )
    assert original_result.prepared is not None, original_result.issues
    original = original_result.prepared
    assert original.artwork is not None
    root = _ipod_volume(tmp_path / "nano3", model_number="MA978")
    database = root / "iPod_Control/iTunes/iTunesDB"
    database.write_bytes(original.itunes)
    artwork_path = root / "iPod_Control/Artwork/ArtworkDB"
    artwork_path.parent.mkdir()
    artwork_path.write_bytes(original.artwork)
    original_files: dict[str, bytes] = {}
    for file in original.artwork_files:
        data = read_content(file.data, 0, len(file.data))
        original_files[file.relative_path] = data
        (root / file.relative_path).write_bytes(data)
    (root / "iPod_Control/Device/SysInfo").write_text(
        "ModelNumStr: MA978\nFirewireGuid: 000A270012345678\n", encoding="utf-8"
    )
    platform = VirtualStoragePlatform()
    platform.add_volume(root, label="Nano 3 retained timeline")
    coordinator = DeviceCoordinator(
        Storage(platform, writer_lock_directory=tmp_path / "locks"),
        volume_presentation_enabled=False,
    )
    try:
        active = coordinator.select_device(
            coordinator.discover_devices().candidates[0].id
        )
        first = active.library.tracks[0]
        desired = replace(
            active.library,
            tracks=(
                replace(first, artwork_id=RED.artwork_id),
                *active.library.tracks[1:],
            ),
        )
        review = coordinator.prepare_library(
            LibraryPreparationRequest(
                desired,
                active,
                1,
                1,
                artwork=(
                    TimedArtworkAsset(
                        RED.artwork_id,
                        tuple(
                            TimedArtworkFrame(
                                time, ArtworkGroupReference(first.artwork_id, time)
                            )
                            for time in (0, 500)
                        ),
                    ),
                ),
            ),
            lambda _: None,
            Event(),
        )
        assert review.result.prepared is not None, review.result.issues
        added = review.result.prepared.artwork_files
        assert len(added) == 1
        assert added[0].relative_path.endswith("F1029_1.ithmb")
        saved = coordinator.save_library(review, active, lambda _: None, Event())
        assert saved.active is not None, saved.issues
        assert all(
            (root / name).read_bytes() == data for name, data in original_files.items()
        )
        loaded = IPodLibrary.parse(database.read_bytes()).with_artwork(
            artwork_path.read_bytes()
        )
        track = loaded.snapshot.tracks[0]
        assert track.ipod is not None and track.ipod.native_chapters is not None
        assert track.ipod.native_chapters.flags == 0x80000003
        assert track.metadata.chapters == first.metadata.chapters
        formats = tuple(
            f for f in application_chapter_formats(profile) if f.format_id == 1029
        )
        for time, pixels in ((0, RED.pixels), (500, BLUE.pixels)):
            read = loaded.artwork_read(
                track.artwork_id, formats, 200, display_time_ms=time
            )
            assert read is not None
            data = (root / read.relative_path).read_bytes()
            decoded = read.decode(data[read.offset : read.offset + read.length])
            assert (decoded.width, decoded.height) == (200, 200)
            assert decoded.rgb888 == pixels.rgb888[:3] * (200 * 200)
    finally:
        coordinator.close()
