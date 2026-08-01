from __future__ import annotations

from datetime import UTC, datetime

from iopenpod.itunesdb_shared.device_time import DeviceTimeContext
from iopenpod.itunesdb_shared.field_base import MAC_EPOCH_OFFSET
from iopenpod.itunesdb_shared.mhod_defs import (
    SPL_AUTHORABLE_FIELD_IDS,
    SPL_HOST_BINARY_AND_FIELD_KEYS,
    SPL_HOST_BOOLEAN_FIELD_KEYS,
    SPL_HOST_DATE_FIELD_KEYS,
    SPL_HOST_EVALUABLE_FIELD_IDS,
    SPL_HOST_INT_FIELD_KEYS,
    SPL_HOST_STRING_FIELD_KEYS,
)
from iopenpod.itunesdb_writer.mhit_writer import TrackInfo
from iopenpod.itunesdb_writer.mhod_spl_writer import SmartPlaylistRule
from iopenpod.sync._track_conversion import trackinfo_to_eval_dict
from iopenpod.sync.spl_evaluator import eval_rule


def test_authorable_fields_are_a_subset_of_host_evaluable_fields() -> None:
    assert SPL_AUTHORABLE_FIELD_IDS <= SPL_HOST_EVALUABLE_FIELD_IDS


def test_trackinfo_conversion_supplies_newly_supported_smart_playlist_fields() -> None:
    track = TrackInfo(
        title="Episode",
        location=":iPod_Control:Music:F00:EPISODE.m4v",
        db_track_id=42,
        last_modified=1_700_000_000,
        artwork_count=1,
        mhii_link=99,
        purchased_aac_flag=1,
        sort_show="Example Show",
    )

    eval_track = trackinfo_to_eval_dict(track)

    required_keys = (
        set(SPL_HOST_STRING_FIELD_KEYS.values())
        | set(SPL_HOST_INT_FIELD_KEYS.values())
        | set(SPL_HOST_DATE_FIELD_KEYS.values())
        | set(SPL_HOST_BOOLEAN_FIELD_KEYS.values())
        | set(SPL_HOST_BINARY_AND_FIELD_KEYS.values())
    )
    assert required_keys <= eval_track.keys()
    assert eval_track["last_modified"] == 1_700_000_000
    assert eval_track["has_artwork"] is True
    assert eval_track["artwork_id_ref"] == 99
    assert eval_track["purchased_flag"] == 1
    assert eval_track["Sort Show"] == "Example Show"
    assert eval_track["location_kind"] == 1

    assert eval_rule(
        SmartPlaylistRule(
            field_id=0x0A,
            action_id=0x00000001,
            from_value=MAC_EPOCH_OFFSET + 1_700_000_000,
        ),
        eval_track,
    )
    assert eval_rule(SmartPlaylistRule(field_id=0x25, action_id=0x00000001), eval_track)
    assert eval_rule(SmartPlaylistRule(field_id=0x29, action_id=0x00000001), eval_track)
    assert eval_rule(
        SmartPlaylistRule(
            field_id=0x53,
            action_id=0x01000001,
            string_value="Example Show",
        ),
        eval_track,
    )
    assert eval_rule(
        SmartPlaylistRule(field_id=0x85, action_id=0x00000400, from_value=1),
        eval_track,
    )


def test_absolute_date_rule_uses_the_device_timezone() -> None:
    rule = SmartPlaylistRule(
        field_id=0x17,
        action_id=0x00000001,
        # 2026-08-01 12:22:23 as an iPod-local Mac timestamp.
        from_value=3_868_431_743,
    )
    track = {
        "last_played": int(
            datetime(2026, 8, 1, 10, 22, 23, tzinfo=UTC).timestamp()
        ),
    }

    assert eval_rule(
        rule,
        track,
        time_context=DeviceTimeContext.from_timezone_name("Europe/Rome"),
    )
    assert not eval_rule(
        rule,
        track,
        time_context=DeviceTimeContext.from_timezone_name("America/New_York"),
    )
