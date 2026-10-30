"""Nano 5 Chapter artwork flags survive the ordinary CDB/Extras save workflow."""

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

from iOpenPod.app.artwork_policy import application_chapter_formats
from iOpenPod.app.library_write import LibraryPreparationRequest
from iOpenPod.app.services.device_coordinator import DeviceCoordinator
from iPodDB.iTunesDB.cdb import compress_iTunesCDB, decompress_iTunesCDB
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.chapter_data_mhod import (
    MhodChapterDataPayload,
)
from iPodDB.library import (
    IPodLibrary,
    TimedArtworkAsset,
    TimedArtworkFrame,
    content_sha256,
)
from storage import Storage
from storage.testing import VirtualStoragePlatform


@pytest.mark.parametrize("flags", [1, 0x80000001])
@pytest.mark.parametrize(
    "timed", [True, False], ids=["chapter-images", "ordinary-cover"]
)
def test_nano5_save_coordinates_chapter_flags_only_for_explicit_timeline(
    tmp_path: Path, flags: int, timed: bool
) -> None:
    source = chapter_source(chapter_payload(flags))
    root = _ipod_volume(
        tmp_path / "nano5", model_number="MC027", database_name="iTunesCDB"
    )
    cdb = root / "iPod_Control/iTunes/iTunesCDB"
    original = compress_iTunesCDB(source.serialize().itunes)
    cdb.write_bytes(original)
    _install_nano5_hash72_metadata(root, bytes.fromhex("000A270012345678"))
    _install_sqlite_postprocess_metadata(root, ("PRAGMA main.user_version = 42;",))
    platform = VirtualStoragePlatform()
    platform.add_volume(root, label="Nano 5")
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
        assert prepared.sqlite is not None
        assert review.plan is not None and review.resources is not None

        # Sharing F1073 between roles must not duplicate or change any pixels.
        baseline = source.prepare(
            source.analyze(
                source.begin_draft(desired),
                replace(review.plan.target, chapter_formats=()),
            ),
            review.resources,
        )
        assert baseline.prepared is not None, baseline.issues
        assert tuple(
            (f.relative_path, len(f.data), content_sha256(f.data))
            for f in prepared.artwork_files
        ) == tuple(
            (f.relative_path, len(f.data), content_sha256(f.data))
            for f in baseline.prepared.artwork_files
        )
        assert len(prepared.artwork_files) == 4
        assert cdb.read_bytes() == original

        saved = coordinator.save_library(review, active, lambda _: None, Event())
        assert saved.active is not None, saved.issues
        loaded = IPodLibrary.parse(cdb.read_bytes()).with_artwork(
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

        document = parse_iTunesDB(decompress_iTunesCDB(cdb.read_bytes()).logical_bytes)
        first_row = document.find_chunks(MhitHeader)[0].chunk
        chapter_blob = next(
            child.raw_body
            for child in first_row.children
            if isinstance(child.payload, MhodChapterDataPayload)
        )
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
        assert tuple(f.format_id for f in formats) == (1073,)
        for time, pixels in (
            ((0, RED.pixels), (500, BLUE.pixels)) if timed else ((0, RED.pixels),)
        ):
            read = loaded.artwork_read(
                track.artwork_id, formats, 240, display_time_ms=time
            )
            assert read is not None
            encoded = (root / read.relative_path).read_bytes()
            decoded = read.decode(encoded[read.offset : read.offset + read.length])
            assert (decoded.width, decoded.height) == (240, 240)
            assert decoded.rgb888 == pixels.rgb888[:3] * (240 * 240)
    finally:
        coordinator.close()
