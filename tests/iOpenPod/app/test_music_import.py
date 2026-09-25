"""Actual media reaches the device through the same workspace, review and save."""

import base64
import hashlib
import shutil
import sqlite3
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.test_first_artwork_save import bare_device
from tests.iOpenPod.app.services.test_library_resources import Device, build_device

from iOpenPod.app.library_workspace import LibraryWorkspace
from iOpenPod.app.library_write import LibraryPreparationRequest
from iOpenPod.app.media.importing import MusicImporter
from iOpenPod.app.media.inspection import MediaInspectionError, MediaInspector
from iOpenPod.app.media.models import MediaInspection
from iOpenPod.app.services.device_coordinator import DeviceCoordinator
from iPodDB.iTunesDB.cdb import compress_iTunesCDB, decompress_iTunesCDB
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.constants import FILE_EXTENSION_INT
from iPodDB.library import CoverFormat, CoverPixelFormat, IPodLibrary
from storage import HardwareIdentifiers, HostPath, Storage
from storage.testing import VirtualStoragePlatform

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "media"


def song_file(tmp_path: Path, name: str = "chapters-cover.m4a") -> HostPath:
    if shutil.which("ffprobe") is None:
        pytest.skip("FFprobe is required for real music import")
    path = tmp_path / "misleading.bin"
    path.write_bytes(base64.decodebytes((FIXTURES / (name + ".b64")).read_bytes()))
    return HostPath(path)


def build_nano5_device(tmp_path: Path) -> Device:
    """Reuse the common Library fixture behind a real late-iPod application seam."""

    retained = build_device(tmp_path)
    retained.coordinator.close()
    root = retained.root
    itunes = root / "iPod_Control" / "iTunes"
    (itunes / "iTunesCDB").write_bytes(
        compress_iTunesCDB((itunes / "iTunesDB").read_bytes())
    )
    guid = bytes.fromhex("000A270012345678")
    device_metadata = root / "iPod_Control" / "Device"
    (device_metadata / "SysInfo").write_text(
        f"ModelNumStr: MC027\nFirewireGuid: {guid.hex().upper()}\n",
        encoding="utf-8",
    )
    (device_metadata / "HashInfo").write_bytes(
        b"HASHv0" + guid + bytes(12) + bytes(range(20, 32)) + bytes(range(16))
    )
    postprocess_fixture = (
        Path(__file__).resolve().parents[2]
        / "fixtures"
        / "SQLiteDB"
        / "observed-postprocess-commands.plist"
    )
    (device_metadata / "SysInfoExtended").write_bytes(postprocess_fixture.read_bytes())
    platform = VirtualStoragePlatform()
    platform.add_volume(
        root,
        identifiers=HardwareIdentifiers(
            usb_vendor_id=0x05AC,
            usb_product_id=0x1265,
            transport_serial=guid.hex().upper(),
        ),
    )
    storage = Storage(platform, writer_lock_directory=tmp_path / "nano-locks")
    coordinator = DeviceCoordinator(storage)
    coordinator.select_device(coordinator.discover_devices().candidates[0].id)
    return Device(root, storage, platform, coordinator, {})


@pytest.mark.parametrize("first_artwork", [False, True])
def test_song_artwork_and_databases_are_published_and_recoverable(
    tmp_path: Path,
    first_artwork: bool,
) -> None:
    device = bare_device(tmp_path) if first_artwork else build_device(tmp_path)
    try:
        source = song_file(tmp_path)
        song = MusicImporter().inspect(
            source, device.active.profile, checkpoint=lambda: None
        )
        assert song.artwork is not None
        assert song.track.title == "Chapter test" and song.track.metadata.chapters
        workspace = LibraryWorkspace()
        before = device.active.library
        workspace.load(device.active.library)
        workspace.add_songs((song,), workspace.edit_revision)
        wanted = workspace.tracks[-1]
        assert wanted.track_id < 0 and wanted.artwork_id < 0
        request = LibraryPreparationRequest(
            workspace.desired_snapshot(),
            device.active,
            workspace.generation,
            workspace.revision,
            artwork=workspace.artwork_assets,
            media=workspace.media_sources,
        )
        review = device.coordinator.prepare_library(request, lambda _: None, Event())
        assert review.result.prepared is not None, review.result.issues
        assert review.file_changes[0].path == wanted.metadata.location
        assert not (device.root / wanted.metadata.location).exists()
        result = device.save(review)
        assert result.active is not None, result.issues
        media = (device.root / wanted.metadata.location).read_bytes()
        assert hashlib.sha256(media).hexdigest() == song.source.fingerprint.sha256
        parsed = IPodLibrary(
            (device.root / "iPod_Control/iTunes/iTunesDB").read_bytes()
        ).with_artwork((device.root / "iPod_Control/Artwork/ArtworkDB").read_bytes())
        added = next(
            t
            for t in parsed.snapshot.tracks
            if t.metadata.location == wanted.metadata.location
        )
        assert added.track_id > 0 and added.artwork_id > 0
        assert added.ipod is not None and added.metadata.artwork_count == len(
            device.active.profile.capabilities.artwork.cover_formats
        )
        assert len(parsed.snapshot.tracks) == len(before.tracks) + 1
        assert parsed.snapshot.tracks[:-1] == before.tracks
        assert parsed.snapshot == result.active.library
        for fmt in device.active.profile.capabilities.artwork.cover_formats:
            read = parsed.artwork_read(
                added.artwork_id,
                (
                    CoverFormat(
                        fmt.format_id,
                        fmt.width,
                        fmt.height,
                        fmt.row_bytes,
                        CoverPixelFormat(fmt.pixel_format.value),
                    ),
                ),
                fmt.width,
            )
            assert read is not None
            payload = (device.root / read.relative_path).read_bytes()
            pixels = read.decode(payload[read.offset : read.offset + read.length])
            assert pixels.width == fmt.width and pixels.height == fmt.height
            assert len(set(pixels.rgb888)) > 1
        device.restore(result.recovery_path)
        assert not (device.root / wanted.metadata.location).exists()
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("change", ["source", "destination"])
def test_import_refuses_changed_inputs_before_database_publication(
    tmp_path: Path, change: str
) -> None:
    device = build_device(tmp_path)
    try:
        source = song_file(tmp_path)
        song = MusicImporter().inspect(
            source, device.active.profile, checkpoint=lambda: None
        )
        workspace = LibraryWorkspace()
        workspace.load(device.active.library)
        workspace.add_songs((song,), workspace.edit_revision)
        review = device.coordinator.prepare_library(
            LibraryPreparationRequest(
                workspace.desired_snapshot(),
                device.active,
                1,
                1,
                artwork=workspace.artwork_assets,
                media=workspace.media_sources,
            ),
            lambda _: None,
            Event(),
        )
        assert review.result.prepared is not None, review.result.issues
        if change == "source":
            content = Path(source.path).read_bytes()
            Path(source.path).write_bytes(bytes((content[0] ^ 255,)) + content[1:])
        else:
            path = device.root / song.track.metadata.location
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"someone else's file")
        result = device.save(review)
        assert result.active is None
        device.assert_original()
    finally:
        device.coordinator.close()


@pytest.mark.parametrize(
    "name",
    ["tone.mp3", "tone-vbr.mp3", "tone.m4a", "lossless.m4a", "tone.wav", "tone.aiff"],
)
def test_observed_music_encoding_is_independent_of_filename(
    tmp_path: Path, name: str
) -> None:
    device = build_nano5_device(tmp_path)
    try:
        song = MusicImporter().inspect(
            song_file(tmp_path, name), device.active.profile, checkpoint=lambda: None
        )
        assert song.track.length_ms > 0 and song.track.metadata.sample_rate_hz == 44100
        assert song.track.metadata.variable_bitrate == (name == "tone-vbr.mp3")
        assert song.source.media.file.relative_path == song.track.metadata.location
        assert song.source.media.file.size == song.track.size_bytes
        destination = Path(song.track.metadata.location)
        assert len(destination.stem) == 4
        assert all("A" <= character <= "Z" for character in destination.stem)
        directory_count = (
            device.active.profile.capabilities.database.music_directory_count
        )
        assert destination.parent.name in {
            f"F{index:02d}" for index in range(directory_count)
        }
        assert song.track.metadata.location.endswith(
            ".m4a" if name == "lossless.m4a" else Path(name).suffix
        )
        workspace = LibraryWorkspace()
        workspace.load(device.active.library)
        workspace.add_songs((song,), workspace.edit_revision)
        review = device.coordinator.prepare_library(
            LibraryPreparationRequest(
                workspace.desired_snapshot(),
                device.active,
                1,
                1,
                media=workspace.media_sources,
            ),
            lambda _: None,
            Event(),
        )
        assert review.result.prepared is not None, review.result.issues
        assert review.result.prepared.sqlite is not None
        document = parse_iTunesDB(
            decompress_iTunesCDB(review.result.prepared.itunes).logical_bytes
        )
        header = tuple(document.find_chunks(MhitHeader))[-1].chunk.header
        expected = {
            "tone.mp3": (b"MP3 ", 1, 12),
            "tone-vbr.mp3": (b"MP3 ", 1, 12),
            "tone.m4a": (b"M4A ", 0, 51),
            "lossless.m4a": (b"M4A ", 0, 0),
            "tone.wav": (b"WAV ", 0, 0),
            "tone.aiff": (b"AIFF", 0, 0),
        }[name]
        assert (header.filetype, header.mp3_flag, header.mpeg_audio_type) == (
            int.from_bytes(expected[0], "big"),
            expected[1],
            expected[2],
        )
        assert header.vbr_flag == int(name == "tone-vbr.mp3")
        expected_sqlite = {
            "tone.mp3": (301, FILE_EXTENSION_INT["mp3"], 1),
            "tone-vbr.mp3": (301, FILE_EXTENSION_INT["mp3"], 1),
            "tone.m4a": (502, FILE_EXTENSION_INT["m4a"], 3),
            "lossless.m4a": (503, FILE_EXTENSION_INT["m4a"], 3),
            "tone.wav": (110, FILE_EXTENSION_INT["wav"], 1),
            "tone.aiff": (111, FILE_EXTENSION_INT["aiff"], 1),
        }[name]
        library_database = sqlite3.connect(":memory:")
        locations_database = sqlite3.connect(":memory:")
        try:
            library_database.deserialize(review.result.prepared.sqlite.library)
            locations_database.deserialize(review.result.prepared.sqlite.locations)
            item_pid, audio_format = library_database.execute(
                "SELECT item.pid,avformat_info.audio_format FROM item "
                "JOIN avformat_info ON item.pid=avformat_info.item_pid "
                "WHERE item.title=? ORDER BY item.physical_order DESC LIMIT 1",
                (song.track.title,),
            ).fetchone()
            extension, kind_id = locations_database.execute(
                "SELECT extension,kind_id FROM location WHERE item_pid=?",
                (item_pid,),
            ).fetchone()
        finally:
            library_database.close()
            locations_database.close()
        assert (audio_format, extension, kind_id) == expected_sqlite
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("name", ["tone.m4a", "lossless.m4a"])
def test_unknown_compatibility_facts_do_not_pass_as_supported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    device = build_device(tmp_path)
    try:
        source = song_file(tmp_path, name)
        inspector = MediaInspector()
        observed = inspector.inspect(source, checkpoint=lambda: None)
        missing = replace(
            observed,
            streams=tuple(
                replace(
                    stream,
                    bitrate_bps=None,
                    bits_per_sample=None,
                    bits_per_raw_sample=None,
                )
                for stream in observed.streams
            ),
        )

        def inspect_captured(*_args: object, **_kwargs: object) -> MediaInspection:
            return missing

        monkeypatch.setattr(inspector, "inspect_captured", inspect_captured)
        with pytest.raises(MediaInspectionError, match="Prepare"):
            MusicImporter(inspector).inspect(
                source, device.active.profile, checkpoint=lambda: None
            )
    finally:
        device.coordinator.close()


def test_pending_import_removal_and_reset_clear_resources(tmp_path: Path) -> None:
    device = build_device(tmp_path)
    try:
        song = MusicImporter().inspect(
            song_file(tmp_path), device.active.profile, checkpoint=lambda: None
        )
        workspace = LibraryWorkspace()
        workspace.load(device.active.library)
        revision = workspace.edit_revision
        workspace.add_songs((song,), revision)
        with pytest.raises(ValueError, match="changed"):
            workspace.add_songs((song,), revision)
        workspace.remove_tracks(
            (workspace.tracks[-1].track_id,), workspace.edit_revision
        )
        assert not workspace.media_sources and not workspace.artwork_assets
        workspace.add_songs((song,), workspace.edit_revision)
        workspace.reset_changes()
        assert (
            not workspace.media_sources
            and not workspace.artwork_assets
            and not workspace.dirty
        )
    finally:
        device.coordinator.close()
