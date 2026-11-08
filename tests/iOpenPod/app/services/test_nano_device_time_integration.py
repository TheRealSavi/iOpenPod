"""Captured Nano city evidence interprets dates without rewriting native history."""

import struct
from dataclasses import replace
from pathlib import Path

import pytest
from tests.iOpenPod.app.services.test_device_coordinator import (
    _install_nano5_hash72_metadata,  # pyright: ignore[reportPrivateUsage]
)
from tests.iOpenPod.app.services.test_library_resources import Device, build_device
from tests.iPodDB.sidecars.test_sidecar_readers import counts

from iOpenPod.app.models.device import DeviceCandidateIssueCode
from iOpenPod.app.services.device_coordinator import DeviceAccessError
from iOpenPod.app.services.ipod_preferences import capture_ipod_preferences
from iPodDB.device_time import DeviceTimeContext, DeviceTimeSource
from iPodDB.iTunesDB.cdb import compress_iTunesCDB, decompress_iTunesCDB
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import IPodLibrary, IssueSeverity, WriteResources
from iPodDB.sidecars import PlaybackSidecar
from storage import DevicePath, FileSnapshot, FilesystemSession, StorageOperationError

NANOS = (
    ("MC027", 34, "1.0.2"),
    ("MC525", 36, "1.2"),
    ("MD480", 37, "1.0.4"),
    ("MKN22", 39, "1.1.2"),
)

# Literal calendar-shaped Mac words and independently specified UTC instants:
# 2024-01-01 00:00 and 2024-07-01 00:00 in New York, winter -5h / summer -4h.
WINTER_WORD = 3_786_912_000
SUMMER_WORD = 3_802_636_800
WINTER_UTC = 1_704_085_200
SUMMER_UTC = 1_719_806_400
NY_XML = (
    b'<iPodSettings version="1.0"><DateTime><TimeZone>41</TimeZone>'
    b"<WorldClock1TimeZone>1</WorldClock1TimeZone>"
    b"<TwentyFourHourClock>1</TwentyFourHourClock>"
    b"<UnknownBias>-86400</UnknownBias></DateTime>"
    b"<Future><Date>{invalid}</Date></Future></iPodSettings>"
)


def _database_path(device: Device) -> Path:
    return device.root / "iPod_Control/iTunes/iTunesCDB"


def _logical_database(device: Device) -> bytes:
    return decompress_iTunesCDB(_database_path(device).read_bytes()).logical_bytes


def _named_path(device: Device) -> Path:
    return device.root / "iPod_Control/Device/iPodSettings.xml"


def _select(device: Device) -> None:
    candidate = device.coordinator.discover_devices().candidates[0]
    device.coordinator.select_device(candidate.id, reconcile_metadata=False)


def _captured_context(
    device: Device, family: int = 36, release: str = "1.2"
) -> DeviceTimeContext:
    """Use the public capture boundary; internal coordinator state stays private."""
    with device.storage.open_session(device.storage.discover().volumes[0]) as session:
        captured = capture_ipod_preferences(
            session,
            device.active.profile,
            firmware_versions=(release,),
            updater_family_ids=(family,),
        )
    offset = parse_iTunesDB(_logical_database(device)).header.timezone_offset
    return captured.device_time.for_database(offset)


def _build_nano(
    tmp_path: Path,
    model: str = "MC525",
    family: int = 36,
    release: str = "1.2",
    *,
    named: bytes | None = NY_XML,
    header_offset: int = 3600,
    binary: bytes | None = b"malformed optional binary clock",
) -> Device:
    device = build_device(tmp_path, model=model, compressed_database=True)
    try:
        metadata = device.root / "iPod_Control/Device"
        if model == "MC027":
            _install_nano5_hash72_metadata(
                device.root, bytes.fromhex("000A270012345678")
            )
        sysinfo = metadata / "SysInfo"
        sysinfo.write_text(
            sysinfo.read_text(encoding="utf-8")
            + f"visibleBuildID: {release}\nUpdaterFamilyID: {family}\n",
            encoding="utf-8",
        )
        if named is not None:
            _named_path(device).write_bytes(named)
        if binary is not None:
            (metadata / "Preferences").write_bytes(binary)
        document = parse_iTunesDB(_logical_database(device))
        document = replace(
            document, header=replace(document.header, timezone_offset=header_offset)
        )
        for slot in document.find_chunks(MhitHeader):
            document = document.replace_chunk(
                slot,
                replace(
                    slot.chunk,
                    header=replace(
                        slot.chunk.header,
                        last_modified=WINTER_WORD,
                        last_played=SUMMER_WORD,
                        last_skipped=SUMMER_WORD,
                        date_released=SUMMER_WORD,
                    ),
                ),
            )
        _database_path(device).write_bytes(compress_iTunesCDB(write_iTunesDB(document)))
        _select(device)
        return device
    except BaseException:
        device.coordinator.close()
        raise


@pytest.mark.parametrize("model,family,release", NANOS)
@pytest.mark.parametrize("binary", (None, b"malformed optional binary clock"))
def test_named_nano_city_survives_read_write_and_source_adoption(
    tmp_path: Path, model: str, family: int, release: str, binary: bytes | None
) -> None:
    device = _build_nano(tmp_path, model, family, release, binary=binary)
    try:
        active = device.active
        context = _captured_context(device, family, release)
        assert context.source is DeviceTimeSource.PREFERENCES_CITY
        assert context.timezone_name == context.zone == "America/New_York"
        assert context.database_offset_seconds == 3600
        first = active.library.tracks[0].metadata
        assert first.last_modified == WINTER_UTC
        assert first.last_played == first.last_skipped == SUMMER_UTC
        # Release dates remain UTC fields rather than local calendar words.
        assert first.release_date == 1_719_792_000

        unrelated = device.prepare(
            replace(active.library, device_name="Nano city dates")
        )
        assert unrelated.result.prepared is not None, unrelated.result.issues
        assert device.save(unrelated).active is not None
        unchanged = parse_iTunesDB(_logical_database(device))
        header = unchanged.find_chunks(MhitHeader)[0].chunk.header
        assert header.last_modified == WINTER_WORD
        assert header.last_played == header.last_skipped == SUMMER_WORD
        assert header.date_released == SUMMER_WORD
        assert unchanged.header.timezone_offset == 3600
        assert device.active.library.tracks[0].metadata.last_played == SUMMER_UTC

        desired = replace(
            device.active.library,
            tracks=tuple(
                replace(
                    track,
                    metadata=replace(
                        track.metadata,
                        last_modified=SUMMER_UTC + 3600,
                        last_played=WINTER_UTC + 3600,
                    ),
                )
                for track in device.active.library.tracks
            ),
        )
        review = device.prepare(desired)
        assert review.result.prepared is not None, review.result.issues
        assert device.save(review).active is not None
        native = parse_iTunesDB(_logical_database(device))
        header = native.find_chunks(MhitHeader)[0].chunk.header
        assert header.last_modified == SUMMER_WORD + 3600
        assert header.last_played == WINTER_WORD + 3600
        assert header.last_skipped == header.date_released == SUMMER_WORD
        assert native.header.timezone_offset == 3600
        assert (
            device.active.library.tracks[0].metadata.last_modified == SUMMER_UTC + 3600
        )
        assert device.active.library.tracks[0].metadata.last_played == WINTER_UTC + 3600
        assert _named_path(device).read_bytes() == NY_XML
        binary_path = device.root / "iPod_Control/Device/Preferences"
        if binary is None:
            assert not binary_path.exists()
        else:
            assert binary_path.read_bytes() == binary
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("change_after_review", (False, True))
@pytest.mark.parametrize(
    "replacement", (None, b"malformed {datetime}", NY_XML.replace(b">41<", b">1<"))
)
def test_named_changes_do_not_block_or_rebase_captured_library_dates(
    tmp_path: Path, change_after_review: bool, replacement: bytes | None
) -> None:
    device = _build_nano(tmp_path)
    try:
        context = _captured_context(device)
        assert context.timezone_name == "America/New_York"
        desired = replace(
            device.active.library,
            tracks=tuple(
                replace(
                    track,
                    metadata=replace(track.metadata, last_played=WINTER_UTC + 3600),
                )
                for track in device.active.library.tracks
            ),
        )

        def change_named() -> None:
            if replacement is None:
                _named_path(device).unlink()
            else:
                _named_path(device).write_bytes(replacement)

        if not change_after_review:
            change_named()
        review = device.prepare(desired)
        assert review.result.prepared is not None, review.result.issues
        if change_after_review:
            change_named()
        result = device.save(review)
        assert result.active is not None, result.issues
        assert device.active.library.tracks[0].metadata.last_played == WINTER_UTC + 3600
        native = (
            parse_iTunesDB(_logical_database(device))
            .find_chunks(MhitHeader)[0]
            .chunk.header
        )
        assert native.last_played == WINTER_WORD + 3600
        if replacement is None:
            assert not _named_path(device).exists()
        else:
            assert _named_path(device).read_bytes() == replacement
    finally:
        device.coordinator.close()


@pytest.mark.parametrize(
    "named",
    (
        None,
        b"malformed {datetime}",
        NY_XML.replace(b">41<", b">0<"),
        NY_XML.replace(b">41<", b">65577<"),
        NY_XML.replace(b">41<", b">4294967337<"),
        NY_XML.replace(b">41<", b">118<"),
        NY_XML.replace(
            b"<TimeZone>41</TimeZone>", b"<TimeZone>41</TimeZone><TimeZone>1</TimeZone>"
        ),
        NY_XML.replace(b"<TimeZone>41</TimeZone>", b""),
    ),
    ids=(
        "missing",
        "malformed",
        "zero",
        "no-low-word-alias",
        "overflow",
        "cape-town-mismatch",
        "duplicate",
        "absent-city",
    ),
)
@pytest.mark.parametrize("header_offset", (-18000, 86400))
def test_unusable_named_clock_uses_header_or_utc_without_mutating_native_dates(
    tmp_path: Path, named: bytes | None, header_offset: int
) -> None:
    # A familiar binary city location is not a substitute for named Nano evidence.
    binary = bytearray(2960)
    struct.pack_into("<I", binary, 0, 0x3E)
    struct.pack_into("<I", binary, 0xB70, 41)
    device = _build_nano(
        tmp_path, named=named, header_offset=header_offset, binary=bytes(binary)
    )
    try:
        context = _captured_context(device)
        assert context.timezone_name is None
        assert context.source is (
            DeviceTimeSource.DATABASE_HEADER
            if header_offset == -18000
            else DeviceTimeSource.UNRESOLVED
        )
        assert device.active.library.tracks[0].metadata.last_played == (
            1_719_810_000 if header_offset == -18000 else 1_719_792_000
        )
        assert any(
            issue.code is DeviceCandidateIssueCode.TIMEZONE_UNCERTAIN
            for issue in device.active.candidate.issues
        )
        review = device.prepare(
            replace(device.active.library, device_name="Unknown Nano clock")
        )
        assert review.result.prepared is not None, review.result.issues
        assert device.save(review).active is not None
        native = parse_iTunesDB(_logical_database(device))
        assert native.find_chunks(MhitHeader)[0].chunk.header.last_played == SUMMER_WORD
        assert native.header.timezone_offset == header_offset
        assert (device.root / "iPod_Control/Device/Preferences").read_bytes() == binary
        if named is None:
            assert not _named_path(device).exists()
        else:
            assert _named_path(device).read_bytes() == named
    finally:
        device.coordinator.close()


def test_failed_named_snapshot_is_nonblocking_while_session_remains_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    read = FilesystemSession.read_snapshot

    def fail_named(
        self: FilesystemSession, path: DevicePath, *, max_bytes: int
    ) -> FileSnapshot:
        if path.name == "iPodSettings.xml":
            raise StorageOperationError("optional named clock unavailable")
        return read(self, path, max_bytes=max_bytes)

    monkeypatch.setattr(FilesystemSession, "read_snapshot", fail_named)
    device = _build_nano(tmp_path, header_offset=-18000)
    try:
        assert _captured_context(device).source is DeviceTimeSource.DATABASE_HEADER
        assert device.active.library.tracks[0].metadata.last_played == 1_719_810_000
        review = device.prepare(
            replace(device.active.library, device_name="Clock capture failed")
        )
        assert review.result.prepared is not None, review.result.issues
        assert device.save(review).active is not None
        assert _named_path(device).read_bytes() == NY_XML
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("family,release", ((36, "1.1"), (34, "1.2")))
def test_named_clock_requires_the_connected_models_qualified_release_and_family(
    tmp_path: Path, family: int, release: str
) -> None:
    device = _build_nano(tmp_path, family=family, release=release, header_offset=-18000)
    try:
        context = _captured_context(device, family, release)
        assert context.source is DeviceTimeSource.DATABASE_HEADER
        assert context.timezone_name is None
        assert device.active.library.tracks[0].metadata.last_played == 1_719_810_000
        assert all(
            section.key != "named_clock" for section in device.active.preferences
        )
        assert _named_path(device).read_bytes() == NY_XML
    finally:
        device.coordinator.close()


def test_disconnect_during_named_clock_capture_is_still_a_real_disconnect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = _build_nano(tmp_path)
    raw = _database_path(device).read_bytes()
    read = FilesystemSession.read_snapshot

    def disconnect_named(
        self: FilesystemSession, path: DevicePath, *, max_bytes: int
    ) -> FileSnapshot:
        if path.name == "iPodSettings.xml":
            device.platform.disconnect(device.root)
        return read(self, path, max_bytes=max_bytes)

    monkeypatch.setattr(FilesystemSession, "read_snapshot", disconnect_named)
    try:
        with pytest.raises(DeviceAccessError):
            _select(device)
        assert device.coordinator.active_ipod is None
        assert _database_path(device).read_bytes() == raw
        assert _named_path(device).read_bytes() == NY_XML
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("model,family,release", NANOS)
@pytest.mark.parametrize(
    "native", (3_855_781_800, 3_876_341_400), ids=("spring-gap", "autumn-fold")
)
def test_nano_named_context_preserves_play_counts_gap_fold_words_and_counters(
    tmp_path: Path, model: str, family: int, release: str, native: int
) -> None:
    device = _build_nano(tmp_path, model, family, release)
    try:
        context = _captured_context(device, family, release)
        assert context.source is DeviceTimeSource.PREFERENCES_CITY
        assert context.timezone_name == "America/New_York"
        raw = _logical_database(device)
        source = IPodLibrary.parse(raw, device_time=context)
        original = source.snapshot.tracks[0]
        sidecar = PlaybackSidecar(
            "Play Counts", counts(((2, native, 0, 0xFFFFFFFF, 0, 3, native),))
        )
        loaded = source.with_sidecars((sidecar,))
        assert len(loaded.sidecar_issues) == 1
        assert loaded.sidecar_issues[0].code == "source.approximate_playback_dates"
        assert loaded.sidecar_issues[0].severity is IssueSeverity.WARNING
        assert loaded.consumed_sidecars == (sidecar,)
        assert loaded.snapshot.tracks[0].play_count == original.play_count + 2
        assert (
            loaded.snapshot.tracks[0].metadata.skip_count
            == original.metadata.skip_count + 3
        )
        result = loaded.prepare(
            loaded.analyze(loaded.begin_draft()),
            WriteResources(pending_playback_sidecars=False),
        )
        assert result.prepared is not None, result.issues
        header = (
            parse_iTunesDB(result.prepared.itunes)
            .find_chunks(MhitHeader)[0]
            .chunk.header
        )
        assert header.last_played == header.last_skipped == native
        assert header.play_count_1 == original.play_count + 2
        assert header.skip_count == original.metadata.skip_count + 3
        adopted = IPodLibrary.parse(result.prepared.itunes, device_time=context)
        assert adopted.device_time == context
        unchanged = adopted.prepare(adopted.analyze(adopted.begin_draft())).prepared
        assert unchanged is not None
        retained = (
            parse_iTunesDB(unchanged.itunes).find_chunks(MhitHeader)[0].chunk.header
        )
        assert retained.last_played == retained.last_skipped == native
        assert _named_path(device).read_bytes() == NY_XML
        assert _logical_database(device) == raw
    finally:
        device.coordinator.close()
