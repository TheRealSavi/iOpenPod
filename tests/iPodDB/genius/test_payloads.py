"""Independent binary fixtures for the evidenced native Genius blob layouts."""

import struct
from dataclasses import replace

import pytest

from iPodDB.genius import (
    GeniusCluster,
    GeniusClusterRule,
    GeniusConfig,
    GeniusFormatError,
    GeniusMetadata,
    GeniusNoOpRule,
    GeniusPayloadKind,
    GeniusRandomRule,
    GeniusSimilarities,
    GeniusSkipRule,
    GeniusSpacingRule,
    OpaqueGeniusPayload,
    make_limited_genius_config,
    make_no_rule_genius_config,
    parse_genius_config,
    parse_genius_metadata,
    parse_genius_similarities,
    serialize_genius_config,
    serialize_genius_metadata,
    serialize_genius_similarities,
)
from iPodDB.shared.errors import iPodDBWriteError


def test_similarity_framing_retains_distinct_unknown_regions_on_edit() -> None:
    source = (
        struct.pack("<III3Q", 0, 30, 3, 0, 0xFFFFFFFFFFFFFFFF, 0) + b"in" + b"outside"
    )
    payload = parse_genius_similarities(source)
    assert isinstance(payload, GeniusSimilarities)
    assert payload.candidates == (0, 0xFFFFFFFFFFFFFFFF, 0)
    assert payload.payload_tail == b"in"
    assert payload.trailing_data == b"outside"
    assert serialize_genius_similarities(payload) == source

    edited = serialize_genius_similarities(replace(payload, candidates=(102, 101)))
    assert edited == struct.pack("<III2Q", 0, 22, 2, 102, 101) + b"inoutside"
    reread = parse_genius_similarities(edited)
    assert isinstance(reread, GeniusSimilarities)
    assert reread.payload_tail == payload.payload_tail
    assert reread.trailing_data == payload.trailing_data


def test_empty_similarities_preserves_the_count_word() -> None:
    source = struct.pack("<III", 0, 4, 0)
    payload = parse_genius_similarities(source)
    assert payload == GeniusSimilarities(())
    assert serialize_genius_similarities(payload) == source


@pytest.mark.parametrize(
    "source",
    [
        b"",
        b"\0\0\0",
        struct.pack("<I", 0),
        struct.pack("<II", 0, 4),
        struct.pack("<III", 0, 3, 0),
        struct.pack("<III", 0, 4, 1),
        struct.pack("<III", 0, 12, 1),
        struct.pack("<III", 0, 0xFFFFFFFF, 0xFFFFFFFF),
    ],
)
def test_malformed_similarities_are_not_opaque(source: bytes) -> None:
    with pytest.raises(GeniusFormatError):
        parse_genius_similarities(source)


def test_compressed_similarity_variant_stays_opaque() -> None:
    source = struct.pack("<I", 1) + b"1.2.3" + b"\0" * 47 + b"compressed bytes"
    payload = parse_genius_similarities(source)
    assert isinstance(payload, OpaqueGeniusPayload)
    assert payload.kind is GeniusPayloadKind.SIMILARITIES
    assert payload.data == source
    assert serialize_genius_similarities(payload) == source


@pytest.mark.parametrize("count", [0, 4, 21])
def test_metadata_has_variable_key_count_and_preserved_partial_key(count: int) -> None:
    keys = tuple(range(count))
    source = struct.pack(f"<{count}Q", *keys) + b"partial"
    payload = parse_genius_metadata(source)
    assert isinstance(payload, GeniusMetadata)
    assert payload.keys == keys
    assert payload.trailing_data == b"partial"
    assert serialize_genius_metadata(payload) == source
    edited = serialize_genius_metadata(replace(payload, keys=(0xFFFFFFFFFFFFFFFF,)))
    assert edited == b"\xff" * 8 + b"partial"


def test_metadata_constraint_keys_are_not_rewritten_as_candidate_ids() -> None:
    payload = GeniusMetadata((0, 0, 2**63, 2**64 - 1))
    assert parse_genius_metadata(serialize_genius_metadata(payload)) == payload


def test_all_known_config_entries_and_control_tail_have_one_inverse() -> None:
    source = (
        struct.pack("<I", 7)
        + struct.pack("<IIIQI2Q", 2, 0, 2, 2**63, 2, 2**63, 1)
        + struct.pack("<QI", 1, 0)
        + struct.pack("<5I", 3, 1, 2, 6, 6)
        + struct.pack("<5I", 3, 2, 2, 10, 6)
        + struct.pack("<5I", 4, 2, 604800, 0, 50)
        + struct.pack("<3I", 5, 70, 100)
        + struct.pack("<5I", 1, 20, 50, 10, 10)
        + struct.pack("<I", 6)
        + struct.pack("<QII", 0, 10, 20)
        + b"unknown"
    )
    payload = parse_genius_config(source)
    assert payload == GeniusConfig(
        (
            GeniusClusterRule(
                0,
                (
                    GeniusCluster(2**63, (2**63, 1)),
                    GeniusCluster(1, ()),
                ),
            ),
            GeniusSpacingRule(1, 2, 6, 6),
            GeniusSpacingRule(2, 2, 10, 6),
            GeniusSkipRule(2, 604800, 0, 50),
            GeniusRandomRule(70, 100),
            GeniusSpacingRule(20, 50, 10, 10, opcode=1),
            GeniusNoOpRule(),
        ),
        struct.pack("<QII", 0, 10, 20) + b"unknown",
    )
    assert serialize_genius_config(payload) == source
    assert isinstance(payload, GeniusConfig)
    edited = replace(payload, entries=(GeniusSpacingRule(3, 1, 4, 0),))
    assert serialize_genius_config(edited) == (
        struct.pack("<6I", 1, 3, 3, 1, 4, 0) + payload.control_tail
    )


@pytest.mark.parametrize("tail", [b"", b"x", b"short", b"12345678", b"123456789012"])
def test_config_optional_control_tail_is_not_interpreted_as_entries(
    tail: bytes,
) -> None:
    source = struct.pack("<I", 0) + tail
    payload = parse_genius_config(source)
    assert payload == GeniusConfig((), tail)
    assert serialize_genius_config(payload) == source


def test_observed_compact_config_constructors_match_independent_bytes() -> None:
    tail = struct.pack("<11I", 70, 100, 1, 20, 50, 10, 10, 0, 0, 10, 20)
    expected_empty = struct.pack("<I", 0) + tail
    expected_limited = (
        struct.pack("<I", 3)
        + struct.pack("<5I", 3, 2, 2, 10, 6)
        + struct.pack("<5I", 3, 3, 3, 10, 6)
        + struct.pack("<5I", 4, 2, 604800, 0, 50)
        + tail
    )
    assert len(expected_empty) == 48
    assert len(expected_limited) == 108
    assert serialize_genius_config(make_no_rule_genius_config()) == expected_empty
    assert serialize_genius_config(make_limited_genius_config()) == expected_limited
    assert parse_genius_config(expected_empty) == make_no_rule_genius_config()
    assert parse_genius_config(expected_limited) == make_limited_genius_config()


@pytest.mark.parametrize("opcode", [0, 7, 8, 0xFFFFFFFF])
def test_unknown_config_opcode_retains_entire_record(opcode: int) -> None:
    source = struct.pack("<III", 2, 6, opcode) + b"not a known entry"
    payload = parse_genius_config(source)
    assert isinstance(payload, OpaqueGeniusPayload)
    assert payload.kind is GeniusPayloadKind.CONFIG
    assert serialize_genius_config(payload) == source


@pytest.mark.parametrize(
    "source",
    [
        b"",
        b"\x01\0\0",
        struct.pack("<I", 1),
        struct.pack("<II", 1, 1),
        struct.pack("<II", 1, 3),
        struct.pack("<II", 1, 4),
        struct.pack("<II", 1, 5),
        struct.pack("<II", 1, 2),
        struct.pack("<IIII", 1, 2, 0, 1),
        struct.pack("<IIIIQI", 1, 2, 0, 1, 1, 1),
        struct.pack("<IIII", 1, 2, 0, 0xFFFFFFFF),
        struct.pack("<IIIIQI", 1, 2, 0, 1, 1, 0xFFFFFFFF),
        struct.pack("<I", 0xFFFFFFFF),
    ],
)
def test_truncated_config_entries_and_counts_fail(source: bytes) -> None:
    with pytest.raises(GeniusFormatError):
        parse_genius_config(source)


@pytest.mark.parametrize("version", [None, 0, 1, 3, 20])
def test_unknown_versions_preserve_bytes_without_guessing_layout(
    version: int | None,
) -> None:
    source = b"unknown future payload"
    for parse, serialize in (
        (parse_genius_config, serialize_genius_config),
        (parse_genius_metadata, serialize_genius_metadata),
        (parse_genius_similarities, serialize_genius_similarities),
    ):
        payload = parse(source, version=version)
        assert isinstance(payload, OpaqueGeniusPayload)
        assert payload.version == version
        assert serialize(payload) == source


@pytest.mark.parametrize("key", [-1, 2**64, True])
def test_writers_reject_invalid_key_values(key: int) -> None:
    with pytest.raises(iPodDBWriteError):
        serialize_genius_metadata(GeniusMetadata((key,)))
    with pytest.raises(iPodDBWriteError):
        serialize_genius_similarities(GeniusSimilarities((key,)))
    with pytest.raises(iPodDBWriteError):
        serialize_genius_config(
            GeniusConfig((GeniusClusterRule(0, (GeniusCluster(key, ()),)),))
        )


@pytest.mark.parametrize("value", [-1, 2**32, True])
def test_config_writers_reject_invalid_unsigned_parameters(value: int) -> None:
    entries = (
        GeniusSpacingRule(value, 1, 2, 3),
        GeniusClusterRule(value, ()),
        GeniusSkipRule(value, 604800, 0, 50),
        GeniusRandomRule(value, 100),
    )
    for entry in entries:
        with pytest.raises(iPodDBWriteError):
            serialize_genius_config(GeniusConfig((entry,)))


def test_wrong_opaque_kind_cannot_be_written_to_another_table() -> None:
    payload = parse_genius_metadata(b"future", version=3)
    assert isinstance(payload, OpaqueGeniusPayload)
    with pytest.raises(iPodDBWriteError, match="another table"):
        serialize_genius_config(payload)
    with pytest.raises(iPodDBWriteError, match="another table"):
        serialize_genius_similarities(payload)


def test_known_writer_cannot_silently_change_version() -> None:
    with pytest.raises(iPodDBWriteError, match="version 2"):
        serialize_genius_config(GeniusConfig((), version=3))
    with pytest.raises(iPodDBWriteError, match="version 2"):
        serialize_genius_metadata(GeniusMetadata((), version=None))
    with pytest.raises(iPodDBWriteError, match="version 2"):
        serialize_genius_similarities(GeniusSimilarities((), version=1))


def test_metadata_suffix_cannot_change_interpreted_key_count() -> None:
    with pytest.raises(iPodDBWriteError, match="another key"):
        serialize_genius_metadata(GeniusMetadata((), b"12345678"))


def test_payload_read_and_write_limits_precede_large_count_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("iPodDB.genius.codec.MAX_GENIUS_PAYLOAD_BYTES", 16)
    for parse in (
        parse_genius_config,
        parse_genius_metadata,
        parse_genius_similarities,
    ):
        with pytest.raises(GeniusFormatError, match="byte limit"):
            parse(b"\0" * 17)
        with pytest.raises(GeniusFormatError, match="byte limit"):
            parse(b"\0" * 17, version=3)
    with pytest.raises(iPodDBWriteError, match="byte limit"):
        serialize_genius_similarities(GeniusSimilarities((1,)))
    with pytest.raises(iPodDBWriteError, match="byte limit"):
        serialize_genius_metadata(GeniusMetadata((1, 2, 3)))
    with pytest.raises(iPodDBWriteError, match="byte limit"):
        serialize_genius_config(GeniusConfig((GeniusSkipRule(2, 604800, 0, 50),)))
    with pytest.raises(iPodDBWriteError, match="byte limit"):
        serialize_genius_config(
            OpaqueGeniusPayload(GeniusPayloadKind.CONFIG, 3, b"\0" * 17, "future")
        )


def test_unknown_diagnostics_do_not_dump_payload_values(
    caplog: pytest.LogCaptureFixture,
) -> None:
    source = struct.pack("<III", 0, 8, 0) + b"hide" + b"sensitive"
    parse_genius_similarities(source)
    messages = [record.message for record in caplog.records]
    assert len(messages) == 1
    assert "regions=2" in messages[0]
    assert "hide" not in messages[0]
    assert "sensitive" not in messages[0]
