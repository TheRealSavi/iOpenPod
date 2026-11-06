"""Host date input/display is explicit and tolerates unusable Library dates."""

import pytest
from whenever import SYSTEM_TZ, Instant, OffsetDateTime, TimeDelta

from iOpenPod.app.core.dates import (
    HostDateZone,
    parse_iso_instant,
    refresh_host_timezone,
)
from iOpenPod.app.metadata_fields import (
    FieldKind,
    display_value,
    metadata_fields,
    parse_field,
)
from iOpenPod.app.models.track_columns import TrackColumn, track_column_display_value
from iPodDB.library import Track, TrackMetadata


@pytest.mark.parametrize(
    ("text", "zone", "expected"),
    [
        ("2024-01-02", "America/New_York", "2024-01-02T05:00:00Z"),
        ("2024-01-02 03:04:05", "America/New_York", "2024-01-02T08:04:05Z"),
        ("2024-01-02T03:04:05+02:00", "America/New_York", "2024-01-02T01:04:05Z"),
        ("2024-11-03T01:30:00", "America/New_York", "2024-11-03T05:30:00Z"),
        ("2024-03-10T02:30:00", "America/New_York", "2024-03-10T07:30:00Z"),
        ("1969-12-31T23:59:59.5", TimeDelta.ZERO, "1969-12-31T23:59:59.5Z"),
    ],
)
def test_host_iso_input_has_explicit_timezone_policy(
    text: str, zone: str | TimeDelta, expected: str
) -> None:
    assert parse_iso_instant(text, naive_zone=zone) == Instant.parse_iso(expected)


def test_invalid_host_input_does_not_silently_choose_a_date() -> None:
    with pytest.raises(ValueError):
        parse_iso_instant("not a date", naive_zone=TimeDelta.ZERO)


def test_unavailable_host_zone_uses_utc_for_valid_text_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    try:
        with monkeypatch.context() as patch:
            patch.setenv("TZ", "Not/A_Zone")
            assert not refresh_host_timezone()
            assert (
                parse_iso_instant(
                    "1969-12-31 23:59:59", naive_zone=HostDateZone.SYSTEM
                ).timestamp()
                == -1
            )
            assert (
                parse_iso_instant(
                    "1970-01-01T01:59:59+02:00", naive_zone=HostDateZone.SYSTEM
                ).timestamp()
                == -1
            )
            with pytest.raises(ValueError):
                parse_iso_instant("not a date", naive_zone=HostDateZone.SYSTEM)
    finally:
        refresh_host_timezone()


def test_unavailable_named_host_zone_uses_same_utc_approximation() -> None:
    assert (
        parse_iso_instant("1969-12-31 23:59:59", naive_zone="Not/A_Zone").timestamp()
        == -1
    )
    with pytest.raises(ValueError):
        parse_iso_instant("2024-01-01", naive_zone=TimeDelta(hours=24))


def test_metadata_editor_accepts_signed_dates_and_round_trips_explicit_offset() -> None:
    field = next(
        item for item in metadata_fields() if item.path == "metadata.date_added"
    )
    timestamp = Instant.from_utc(1960, 7, 1, 12).timestamp()
    rendered = display_value(timestamp, FieldKind.DATE)
    assert OffsetDateTime.parse_iso(rendered).timestamp() == timestamp
    assert parse_field(field, rendered) == timestamp
    assert parse_field(field, str(timestamp)) == timestamp
    assert parse_field(field, "1969-12-31T23:59:59.5Z") == -1
    assert parse_field(field, "") == 0
    assert display_value(10**100, FieldKind.DATE) == str(10**100)


@pytest.mark.parametrize("timestamp", [0, 10**100, -(10**100)])
def test_track_table_handles_missing_and_unrepresentable_dates(timestamp: int) -> None:
    track = Track(1, "", "", "", 0, metadata=TrackMetadata(date_added=timestamp))
    assert track_column_display_value(track, TrackColumn.DATE_ADDED) == "—"


def test_track_table_displays_pre_unix_dates_in_the_host_zone() -> None:
    instant = Instant.from_utc(1960, 7, 1, 12)
    track = Track(
        1, "", "", "", 0, metadata=TrackMetadata(date_added=instant.timestamp())
    )
    assert track_column_display_value(track, TrackColumn.DATE_ADDED) == (
        instant.to_tz(SYSTEM_TZ).date().format_iso()
    )
