"""Date semantics across native records, retained bytes, and SQLite output."""

from dataclasses import replace
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from tests.iPodDB.library.test_photos import (
    _photos_bytes,  # pyright: ignore[reportPrivateUsage]
)
from tests.iPodDB.library.test_writing import library
from tests.iPodDB.SQLiteDB.test_database import (
    _rows,  # pyright: ignore[reportPrivateUsage]
)

from iPodDB.device_time import (
    MAC_EPOCH_UNIX_OFFSET as EPOCH,
)
from iPodDB.device_time import (
    DeviceTimeContext,
    DeviceTimeSource,
    mac_to_unix,
    project_mac,
    unix_to_mac,
)
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import IPodLibrary
from iPodDB.library._smart_projection import project_smart
from iPodDB.library._smart_writing import smart_chunks
from iPodDB.library.playlists import (
    SmartField,
    SmartOperator,
    SmartPlaylist,
    SmartRule,
    SmartRuleGroup,
)
from iPodDB.library.writing import WriteChecksum, WriteTarget
from iPodDB.PhotosDB.parser.parse_PhotosDB import parse_PhotosDB
from iPodDB.PhotosDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.PhotosDB.writer.write_PhotosDB import write_PhotosDB
from iPodDB.SQLiteDB.database import build_sqlite_databases

ZONE = DeviceTimeContext(
    ZoneInfo("America/New_York"), DeviceTimeSource.PREFERENCES_CITY, "America/New_York"
)
WINTER = 1_704_085_200  # 2024-01-01 05:00 UTC, midnight local.
SUMMER = 1_719_806_400  # 2024-07-01 04:00 UTC, midnight local.


def _source() -> IPodLibrary:
    doc = parse_iTunesDB(library().serialize().itunes)
    doc = replace(doc, header=replace(doc.header, timezone_offset=19800))
    for item, instant, offset in zip(
        doc.find_chunks(MhitHeader), (WINTER, SUMMER), (-18000, -14400), strict=True
    ):
        native = instant + EPOCH + offset
        doc = doc.replace_chunk(
            item,
            replace(
                item.chunk,
                header=replace(
                    item.chunk.header,
                    last_modified=native,
                    date_added=native,
                    last_played=native,
                    last_skipped=native,
                    date_released=instant + EPOCH,
                    date_added_to_itunes=instant + EPOCH,
                ),
            ),
        )
    return IPodLibrary.parse(write_iTunesDB(doc), device_time=ZONE)


@pytest.mark.parametrize("offset", [-43200, -19800, 0, 19800, 20700, 50400])
@pytest.mark.parametrize("instant", [-1, 1, WINTER, SUMMER])
def test_fixed_offsets_are_inverse_including_fractional_hours_and_pre_unix(
    offset: int, instant: int
) -> None:
    encoded = unix_to_mac(instant, offset)
    assert encoded == instant + EPOCH + offset
    assert mac_to_unix(encoded, offset) == instant


@pytest.mark.parametrize("offset", [-18000, 19800])
def test_zero_and_native_range_boundaries(offset: int) -> None:
    assert unix_to_mac(0, offset) == mac_to_unix(0, offset) == 0
    for native in (1, 0xFFFFFFFF):
        assert unix_to_mac(mac_to_unix(native, offset), offset) == native
    for invalid in (-EPOCH - offset, 0xFFFFFFFF - EPOCH - offset + 1):
        with pytest.raises(ValueError):
            unix_to_mac(invalid, offset)


def test_city_rules_use_the_event_date_and_utc_fields_do_not_use_the_city() -> None:
    for instant, offset in ((WINTER, -18000), (SUMMER, -14400)):
        assert unix_to_mac(instant, ZONE) == instant + EPOCH + offset
        assert unix_to_mac(instant, ZONE, utc=True) == instant + EPOCH
    source = _source()
    for track, instant in zip(source.snapshot.tracks, (WINTER, SUMMER), strict=True):
        assert track.metadata.last_modified == track.metadata.date_added == instant
        assert track.metadata.last_played == track.metadata.last_skipped == instant
        assert track.metadata.release_date == instant
        assert track.ipod is not None and track.ipod.date_added_to_itunes == instant
    assert source.device_time.database_offset_seconds == 19800


@pytest.mark.parametrize("wall", ["2024-03-10T02:30:00", "2024-11-03T01:30:00"])
def test_gap_and_fold_are_unavailable_instead_of_guessed(wall: str) -> None:
    raw = int(datetime.fromisoformat(wall).replace(tzinfo=UTC).timestamp()) + EPOCH
    with pytest.raises(ValueError, match="ambiguous or nonexistent"):
        mac_to_unix(raw, ZONE)
    assert project_mac(raw, ZONE) == 0


@pytest.mark.parametrize("instant", [1730611800, 1730615400])
def test_either_instant_in_a_repeated_hour_is_rejected_for_new_local_dates(
    instant: int,
) -> None:
    with pytest.raises(ValueError, match="ambiguous"):
        unix_to_mac(instant, ZONE)
    assert unix_to_mac(instant, ZONE, utc=True) == instant + EPOCH


def test_unknown_zone_uses_only_explicit_header_fallback() -> None:
    context = DeviceTimeContext(detail="Unknown city").for_database(-18000)
    assert context.source is DeviceTimeSource.DATABASE_HEADER
    assert mac_to_unix(WINTER + EPOCH - 18000, context) == WINTER
    unknown = context.for_database(86400)
    assert unknown.source is DeviceTimeSource.UNRESOLVED
    assert project_mac(WINTER + EPOCH, unknown) == 0
    with pytest.raises(ValueError, match="unresolved"):
        unix_to_mac(WINTER, unknown)
    assert unix_to_mac(WINTER, unknown, utc=True) == WINTER + EPOCH


def test_public_write_keeps_context_header_and_unchanged_dates() -> None:
    source = _source()
    raw = source.serialize().itunes
    assert source.prepare(source.analyze(source.begin_draft())).prepared is not None
    desired = replace(
        source.snapshot,
        tracks=tuple(
            replace(
                t, metadata=replace(t.metadata, last_played=SUMMER, release_date=WINTER)
            )
            for t in source.snapshot.tracks
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    checked = parse_iTunesDB(result.prepared.itunes)
    assert checked.header.timezone_offset == 19800
    for old, new in zip(
        parse_iTunesDB(raw).find_chunks(MhitHeader),
        checked.find_chunks(MhitHeader),
        strict=True,
    ):
        assert new.chunk.header.last_modified == old.chunk.header.last_modified
        assert new.chunk.header.last_played == SUMMER + EPOCH - 14400
        assert new.chunk.header.date_released == WINTER + EPOCH
    assert (
        IPodLibrary.parse(
            result.prepared.itunes, device_time=source.device_time
        ).snapshot
        == result.prepared.snapshot
    )
    assert source.serialize().itunes == raw


def test_smart_absolute_range_uses_both_seasons_but_duration_is_unchanged() -> None:
    smart = SmartPlaylist(
        rules=SmartRuleGroup(
            rules=(
                SmartRule(
                    SmartField.LAST_PLAYED, SmartOperator.BETWEEN, WINTER, SUMMER
                ),
                SmartRule(SmartField.DATE_ADDED, SmartOperator.IN_LAST, 86400),
            )
        )
    )
    assert project_smart(smart_chunks(smart, (), ZONE), ZONE) == smart


def test_smart_absolute_unix_epoch_is_not_a_missing_date() -> None:
    smart = SmartPlaylist(
        rules=SmartRuleGroup(
            rules=(SmartRule(SmartField.DATE_ADDED, SmartOperator.IS, 0),)
        )
    )
    assert project_smart(smart_chunks(smart, (), ZONE), ZONE) == smart


def test_sqlite_uses_utc_2001_epoch_without_header_or_city_shift() -> None:
    result = build_sqlite_databases(
        _source().snapshot, database_id=99, checksum=WriteChecksum.NONE
    )
    assert _rows(
        result.library,
        "SELECT date_purchased,date_released FROM store_info ORDER BY item_pid",
    ) == tuple((t - 978307200, t - 978307200) for t in (WINTER, SUMMER))
    assert _rows(
        result.library, "SELECT date_modified,date_released FROM item ORDER BY pid"
    ) == tuple((t - 978307200, t - 978307200) for t in (WINTER, SUMMER))
    assert _rows(
        result.locations, "SELECT date_created FROM location ORDER BY item_pid"
    ) == tuple((t - 978307200,) for t in (WINTER, SUMMER))
    assert _rows(
        result.dynamic,
        "SELECT date_played,date_skipped FROM item_stats ORDER BY item_pid",
    ) == tuple((t - 978307200, t - 978307200) for t in (WINTER, SUMMER))


def test_photo_date_conversion_and_ambiguous_byte_preservation() -> None:
    doc = parse_PhotosDB(_photos_bytes())
    item = doc.find_chunks(MhiiHeader)[0]
    ambiguous = int(datetime(2024, 11, 3, 1, 30, tzinfo=UTC).timestamp()) + EPOCH
    doc = doc.replace_chunk(
        item,
        replace(
            item.chunk,
            header=replace(
                item.chunk.header,
                original_date=WINTER + EPOCH - 18000,
                exif_taken_date=ambiguous,
            ),
        ),
    )
    source = _source().with_photos(write_PhotosDB(doc))
    photos = source.snapshot.photos
    assert photos is not None
    photo = photos.photos[0]
    assert (photo.original_date, photo.taken_date) == (WINTER, 0)
    assert any(i.code == "source.unavailable_dates" for i in source.time_warnings)
    desired = replace(
        source.snapshot,
        photos=replace(
            photos, photos=(replace(photo, original_date=SUMMER, rating=80),)
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is not None, result.issues
    assert result.prepared.photos is not None
    native = (
        parse_PhotosDB(result.prepared.photos).find_chunks(MhiiHeader)[0].chunk.header
    )
    assert native.original_date == SUMMER + EPOCH - 14400
    assert native.exif_taken_date == ambiguous


def test_unresolved_dates_preserve_native_bytes_but_block_sqlite_regeneration() -> None:
    document = parse_iTunesDB(_source().serialize().itunes)
    document = replace(document, header=replace(document.header, timezone_offset=86400))
    source = IPodLibrary.parse(write_iTunesDB(document))
    assert source.snapshot.tracks[0].metadata.last_played == 0
    desired = replace(source.snapshot, device_name="Renamed")
    draft = source.begin_draft(desired)
    result = source.prepare(source.analyze(draft))
    assert result.prepared is not None, result.issues
    assert (
        parse_iTunesDB(result.prepared.itunes)
        .find_chunks(MhitHeader)[0]
        .chunk.header.last_played
        == document.find_chunks(MhitHeader)[0].chunk.header.last_played
    )
    plan = source.analyze(draft, WriteTarget(sqlite_database=True))
    assert any(i.code == "source.sqlite_unavailable_dates" for i in plan.issues)
    assert source.prepare(plan).prepared is None


def test_ambiguous_new_track_date_is_rejected_by_analysis() -> None:
    source = _source()
    track = source.snapshot.tracks[0]
    desired = replace(
        source.snapshot,
        tracks=(
            replace(track, metadata=replace(track.metadata, last_played=1730611800)),
            source.snapshot.tracks[1],
        ),
    )
    result = source.prepare(source.analyze(source.begin_draft(desired)))
    assert result.prepared is None
    assert any("ambiguous" in i.message for i in result.issues)
