from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from iopenpod.artworkdb_writer import artwork_writer as aw
from iopenpod.artworkdb_writer import rgb565
from iopenpod.artworkdb_writer.art_extractor import extract_art
from iopenpod.device.write_guard import DeviceWriteSafetyError

REQUIRED_FMT = 1055
EXTRA_KNOWN_FMT = 1060
UNKNOWN_FMT = 9999
VIDEO_SMALL_FMT = 1028
VIDEO_LARGE_FMT = 1029


def test_unknown_device_path_does_not_guess_classic_artwork_formats(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "iopenpod.device.get_current_device_for_path",
        lambda _path: None,
    )

    assert rgb565.get_artwork_format_definitions(str(tmp_path)) == {}
    assert rgb565.get_artwork_formats(str(tmp_path)) == {}


def test_pending_artwork_revalidates_before_each_atomic_replace(
    monkeypatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []
    pending_renames = []
    for index in range(2):
        temp = tmp_path / f"art-{index}.tmp"
        final = tmp_path / f"art-{index}.ithmb"
        temp.write_bytes(bytes([index]))
        pending_renames.append((str(temp), str(final)))

    original_replace = aw.durable_replace

    def replace(source, target) -> None:
        events.append("replace")
        original_replace(source, target)

    monkeypatch.setattr(aw, "durable_replace", replace)
    pending = aw.PendingArtworkWrite(
        db_track_id_to_art_info={},
        _pending_renames=pending_renames,
    )

    pending.commit(before_replace=lambda: events.append("revalidate"))

    assert events == ["revalidate", "replace", "revalidate", "replace"]


def test_extract_art_accepts_direct_image_file(tmp_path) -> None:
    image_path = tmp_path / "manual.png"
    Image.new("RGB", (4, 4), (12, 34, 56)).save(image_path)

    assert extract_art(str(image_path)) == image_path.read_bytes()


def _make_ipod_root(tmp_path: Path) -> tuple[Path, Path]:
    ipod_root = tmp_path / "ipod"
    artwork_dir = ipod_root / "iPod_Control" / "Artwork"
    artwork_dir.mkdir(parents=True)
    return ipod_root, artwork_dir


def _make_track(db_track_id: int, *, hint: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        db_track_id=db_track_id,
        title=f"Track {db_track_id}",
        album="Album",
        artist="Artist",
        album_artist="Artist",
        mhii_link=0,
        artwork_count=0,
        artwork_size=0,
        _iop_artwork_sync_hint=hint,
    )


def _format_ref(ithmb_path: Path, *, size: int = 4) -> aw.ExistingFormatRef:
    return aw.ExistingFormatRef(
        path=str(ithmb_path),
        ithmb_offset=0,
        size=size,
        width=1,
        height=1,
        hpad=0,
        vpad=0,
    )


def _existing_art_entry(
    ithmb_path: Path,
    *,
    song_id: int = 1,
    format_id: int = REQUIRED_FMT,
) -> dict[int, dict]:
    return {
        42: {
            "song_id": song_id,
            "src_img_size": 99,
            "formats": {
                format_id: _format_ref(ithmb_path),
            },
        },
    }


def test_classify_existing_entry_formats_buckets_writer_ownership(
    monkeypatch,
    tmp_path: Path,
) -> None:
    required_ithmb = tmp_path / f"F{REQUIRED_FMT}_1.ithmb"
    extra_ithmb = tmp_path / f"F{EXTRA_KNOWN_FMT}_1.ithmb"
    unknown_ithmb = tmp_path / f"F{UNKNOWN_FMT}_1.ithmb"
    required_ithmb.write_bytes(b"REQ!")
    extra_ithmb.write_bytes(b"EXT!")
    unknown_ithmb.write_bytes(b"UNKN")

    monkeypatch.setattr(aw, "expected_size_bytes", lambda *_args, **_kwargs: 4)

    classified = aw._classify_existing_entry_formats(
        {
            "formats": {
                REQUIRED_FMT: _format_ref(required_ithmb),
                EXTRA_KNOWN_FMT: _format_ref(extra_ithmb),
                UNKNOWN_FMT: _format_ref(unknown_ithmb),
            },
        },
        [REQUIRED_FMT],
        {},
    )

    assert set(classified.required_known) == {REQUIRED_FMT}
    assert set(classified.extra_known) == {EXTRA_KNOWN_FMT}
    assert set(classified.unknown_passthrough) == {UNKNOWN_FMT}
    assert classified.known_present == {REQUIRED_FMT, EXTRA_KNOWN_FMT}
    assert isinstance(classified.unknown_passthrough[UNKNOWN_FMT], aw.PassthroughFormatRef)


def test_classify_existing_entry_formats_accepts_known_registry_stride(
    tmp_path: Path,
) -> None:
    fmt_id = 1016
    width = 57
    height = 57
    stride = 58
    payload_size = stride * height * 2
    ithmb_path = tmp_path / f"F{fmt_id}_1.ithmb"
    ithmb_path.write_bytes(b"\0" * payload_size)
    fmt_override = aw.ArtworkFormat(
        fmt_id,
        width,
        height,
        stride * 2,
        "RGB565_LE",
        "cover_small_alt",
        "Known padded cover art",
    )

    classified = aw._classify_existing_entry_formats(
        {
            "formats": {
                fmt_id: aw.ExistingFormatRef(
                    path=str(ithmb_path),
                    ithmb_offset=0,
                    size=payload_size,
                    width=width,
                    height=height,
                    hpad=0,
                    vpad=0,
                ),
            },
        },
        [fmt_id],
        {fmt_id: fmt_override},
    )

    assert set(classified.required_known) == {fmt_id}
    assert classified.known_present == {fmt_id}


def test_load_preserved_art_payloads_allows_shared_ithmb_offsets(
    tmp_path: Path,
) -> None:
    ithmb_path = tmp_path / f"F{REQUIRED_FMT}_1.ithmb"
    ithmb_path.write_bytes(b"DATA")
    existing_entry = {
        "src_img_size": 99,
        "formats": {
            REQUIRED_FMT: _format_ref(ithmb_path),
        },
    }
    first_ref = aw.ArtworkAssetRef("preserve", 42)
    second_ref = aw.ArtworkAssetRef("preserve", 43)
    decisions = {
        1: aw.TrackArtworkDecision(
            db_track_id=1,
            kind=aw.ArtworkDecisionKind.PRESERVE_FALLBACK,
            asset_ref=first_ref,
            existing_entry=existing_entry,
        ),
        2: aw.TrackArtworkDecision(
            db_track_id=2,
            kind=aw.ArtworkDecisionKind.PRESERVE_FALLBACK,
            asset_ref=second_ref,
            existing_entry=existing_entry,
        ),
    }

    payloads, _salvaged, dropped = aw._load_preserved_art_payloads(
        decisions,
        [REQUIRED_FMT],
        {
            first_ref: [REQUIRED_FMT],
            second_ref: [REQUIRED_FMT],
        },
        {},
        {REQUIRED_FMT: (1, 1)},
        {},
    )

    assert dropped == 0
    assert set(payloads) == {first_ref, second_ref}
    assert payloads[first_ref].formats[REQUIRED_FMT].size == 4
    assert payloads[second_ref].formats[REQUIRED_FMT].size == 4


def test_classify_existing_entry_formats_keeps_known_format_with_unexpected_size(
    tmp_path: Path,
    caplog,
) -> None:
    ithmb_path = tmp_path / f"F{EXTRA_KNOWN_FMT}_1.ithmb"
    ithmb_path.write_bytes(b"ODD!")

    with caplog.at_level(logging.DEBUG):
        classified = aw._classify_existing_entry_formats(
            {
                "formats": {
                    EXTRA_KNOWN_FMT: _format_ref(ithmb_path, size=4),
                },
            },
            [REQUIRED_FMT],
            {},
        )

    assert set(classified.extra_known) == {EXTRA_KNOWN_FMT}
    assert classified.known_present == {EXTRA_KNOWN_FMT}
    assert "carrying forward on-device bytes" in caplog.text


def test_image_from_bytes_reports_offending_artwork_source_path(monkeypatch) -> None:
    bomb = Image.DecompressionBombError(
        "Image size (200000000 pixels) exceeds limit of 178956970 pixels, could be decompression bomb DOS attack.",
    )

    def fake_open(_stream):
        raise bomb

    monkeypatch.setattr(rgb565.Image, "open", fake_open)

    try:
        rgb565.image_from_bytes(b"not-an-image", source_path="/music/Album/cover.tif")
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected decompression bomb error")

    assert "Offending image: /music/Album/cover.tif" in message
    assert "decompression bomb DOS attack" in message


def test_collect_rewrite_targets_keeps_known_formats_owned_and_unknown_passthrough(
    monkeypatch,
    tmp_path: Path,
    caplog,
) -> None:
    required_ithmb = tmp_path / f"F{REQUIRED_FMT}_1.ithmb"
    extra_ithmb = tmp_path / f"F{EXTRA_KNOWN_FMT}_1.ithmb"
    unknown_ithmb = tmp_path / f"F{UNKNOWN_FMT}_1.ithmb"
    required_ithmb.write_bytes(b"REQ!")
    extra_ithmb.write_bytes(b"EXT!")
    unknown_ithmb.write_bytes(b"UNKN")
    asset_ref = aw.ArtworkAssetRef("preserve", 42)

    monkeypatch.setattr(aw, "expected_size_bytes", lambda *_args, **_kwargs: 4)

    with caplog.at_level(logging.WARNING):
        targets, passthrough = aw._collect_rewrite_targets(
            {
                1: aw.TrackArtworkDecision(
                    db_track_id=1,
                    kind=aw.ArtworkDecisionKind.PRESERVE_FALLBACK,
                    asset_ref=asset_ref,
                    existing_entry={
                        "formats": {
                            REQUIRED_FMT: _format_ref(required_ithmb),
                            # Bad old payload metadata should not make us forget a known extra format.
                            EXTRA_KNOWN_FMT: _format_ref(extra_ithmb, size=2),
                            UNKNOWN_FMT: _format_ref(unknown_ithmb),
                        },
                    },
                ),
            },
            [REQUIRED_FMT],
            {},
        )

    assert targets[asset_ref] == [REQUIRED_FMT, EXTRA_KNOWN_FMT]
    assert set(passthrough[asset_ref]) == {UNKNOWN_FMT}
    assert passthrough[asset_ref][UNKNOWN_FMT].path == str(unknown_ithmb)
    assert f"unknown artwork format {UNKNOWN_FMT} at {unknown_ithmb}" in caplog.text
    assert f"extra known artwork format {EXTRA_KNOWN_FMT} at {extra_ithmb}" in caplog.text


def test_collect_rewrite_targets_warns_for_unknown_formats_on_clear_art(
    monkeypatch,
    tmp_path: Path,
    caplog,
) -> None:
    unknown_ithmb = tmp_path / f"F{UNKNOWN_FMT}_1.ithmb"
    unknown_ithmb.write_bytes(b"UNKN")

    monkeypatch.setattr(aw, "expected_size_bytes", lambda *_args, **_kwargs: 4)

    with caplog.at_level(logging.WARNING):
        targets, passthrough = aw._collect_rewrite_targets(
            {
                1: aw.TrackArtworkDecision(
                    db_track_id=1,
                    kind=aw.ArtworkDecisionKind.CLEAR_ART,
                    existing_entry={
                        "formats": {
                            UNKNOWN_FMT: _format_ref(unknown_ithmb),
                        },
                    },
                ),
            },
            [REQUIRED_FMT],
            {},
        )

    assert targets == {}
    assert passthrough == {}
    assert f"unknown artwork format {UNKNOWN_FMT} at {unknown_ithmb}" in caplog.text


def test_write_artworkdb_preserves_unchanged_art_without_reencoding(
    monkeypatch,
    tmp_path: Path,
) -> None:
    ipod_root, artwork_dir = _make_ipod_root(tmp_path)
    pc_file = tmp_path / "song.mp3"
    pc_file.write_bytes(b"music")
    existing_ithmb = artwork_dir / f"F{REQUIRED_FMT}_1.ithmb"
    existing_ithmb.write_bytes(b"OLD!")

    monkeypatch.setattr(aw, "read_existing_artwork", lambda *_args, **_kwargs: _existing_art_entry(existing_ithmb))
    monkeypatch.setattr(aw, "get_artwork_format_definitions", lambda _ipod_path: {})
    monkeypatch.setattr(aw, "expected_size_bytes", lambda *_args, **_kwargs: 4)

    def _fail_extract(_path: str) -> bytes | None:
        raise AssertionError("unchanged artwork should use the preserve fast-path")

    monkeypatch.setattr(aw, "extract_art_with_folder", _fail_extract)

    result = aw.write_artworkdb(
        str(ipod_root),
        [_make_track(1, hint="preserve_existing")],
        pc_file_paths={1: str(pc_file)},
        artwork_formats={REQUIRED_FMT: (1, 1)},
    )

    assert result[1] == (100, 99)
    assert existing_ithmb.read_bytes() == b"OLD!"


def test_write_artworkdb_reuses_lowest_file_when_preserved_art_fits(
    monkeypatch,
    tmp_path: Path,
) -> None:
    ipod_root, artwork_dir = _make_ipod_root(tmp_path)
    existing_ithmb = artwork_dir / f"F{REQUIRED_FMT}_1.ithmb"
    preserved_track_count = 100
    existing_payload = b"OLD!" * preserved_track_count
    existing_ithmb.write_bytes(existing_payload)

    existing_art = {
        1000 + index: {
            "song_id": index + 1,
            "src_img_size": 99,
            "formats": {
                REQUIRED_FMT: aw.ExistingFormatRef(
                    path=str(existing_ithmb),
                    ithmb_offset=index * 4,
                    size=4,
                    width=1,
                    height=1,
                ),
            },
        }
        for index in range(preserved_track_count)
    }
    preserved_tracks = [_make_track(index + 1) for index in range(preserved_track_count)]
    changed_tracks = [
        _make_track(preserved_track_count + index + 1)
        for index in range(4)
    ]
    later_changed_tracks = [
        _make_track(preserved_track_count + len(changed_tracks) + index + 1)
        for index in range(4)
    ]
    shared_art_path = tmp_path / "shared.png"
    shared_art_path.write_bytes(b"source image placeholder")
    later_shared_art_path = tmp_path / "later-shared.png"
    later_shared_art_path.write_bytes(b"later source image placeholder")

    parse_written_artworkdb = aw.read_existing_artwork
    read_calls = 0

    def _read_existing(artworkdb_path: str, artwork_path: str):
        nonlocal read_calls
        read_calls += 1
        if read_calls == 1:
            return existing_art
        return parse_written_artworkdb(artworkdb_path, artwork_path)

    monkeypatch.setattr(aw, "read_existing_artwork", _read_existing)
    monkeypatch.setattr(aw, "get_artwork_format_definitions", lambda _ipod_path: {})
    monkeypatch.setattr(aw, "expected_size_bytes", lambda *_args, **_kwargs: 4)
    extract_calls = 0

    def _extract(path: str) -> bytes:
        nonlocal extract_calls
        extract_calls += 1
        return Path(path).name.encode("ascii")

    monkeypatch.setattr(aw, "extract_art_with_folder", _extract)
    monkeypatch.setattr(
        aw,
        "image_from_bytes",
        lambda _bytes, **_kwargs: Image.new("RGB", (1, 1), (9, 8, 7)),
    )
    encode_calls = 0

    def _encode(_img, _fmt_id, *_args, **_kwargs):
        nonlocal encode_calls
        encode_calls += 1
        return aw.EncodedFormatPayload(
            data=b"NEW!",
            width=1,
            height=1,
            size=4,
            stride_pixels=1,
        )

    monkeypatch.setattr(aw, "encode_image_for_format", _encode)

    result = aw.write_artworkdb(
        str(ipod_root),
        [*preserved_tracks, *changed_tracks, *later_changed_tracks],
        pc_file_paths={
            track.db_track_id: str(shared_art_path)
            for track in changed_tracks
        },
        artwork_formats={REQUIRED_FMT: (1, 1)},
    )

    assert len(result) == preserved_track_count + len(changed_tracks)
    assert extract_calls == 1
    assert encode_calls == 1
    assert existing_ithmb.read_bytes() == existing_payload + b"NEW!"
    assert not (artwork_dir / f"F{REQUIRED_FMT}_2.ithmb").exists()

    rewritten = parse_written_artworkdb(
        str(artwork_dir / "ArtworkDB"),
        str(artwork_dir),
    )
    refs_by_song_id = {
        entry["song_id"]: entry["formats"][REQUIRED_FMT]
        for entry in rewritten.values()
    }
    assert len(refs_by_song_id) == preserved_track_count + len(changed_tracks)
    assert refs_by_song_id[1].ithmb_filename == f"F{REQUIRED_FMT}_1.ithmb"
    assert refs_by_song_id[changed_tracks[0].db_track_id].ithmb_filename == (
        f"F{REQUIRED_FMT}_1.ithmb"
    )

    second_result = aw.write_artworkdb(
        str(ipod_root),
        [*preserved_tracks, *changed_tracks, *later_changed_tracks],
        pc_file_paths={
            track.db_track_id: str(later_shared_art_path)
            for track in later_changed_tracks
        },
        artwork_formats={REQUIRED_FMT: (1, 1)},
    )

    assert len(second_result) == (
        preserved_track_count + len(changed_tracks) + len(later_changed_tracks)
    )
    assert extract_calls == 2
    assert encode_calls == 2
    assert existing_ithmb.read_bytes() == existing_payload + b"NEW!NEW!"
    assert not (artwork_dir / f"F{REQUIRED_FMT}_2.ithmb").exists()

    rewritten = parse_written_artworkdb(
        str(artwork_dir / "ArtworkDB"),
        str(artwork_dir),
    )
    refs_by_song_id = {
        entry["song_id"]: entry["formats"][REQUIRED_FMT]
        for entry in rewritten.values()
    }
    assert refs_by_song_id[changed_tracks[0].db_track_id].ithmb_filename == (
        f"F{REQUIRED_FMT}_1.ithmb"
    )
    assert refs_by_song_id[later_changed_tracks[0].db_track_id].ithmb_filename == (
        f"F{REQUIRED_FMT}_1.ithmb"
    )


def test_write_artworkdb_reuses_lowest_file_after_art_clear(
    monkeypatch,
    tmp_path: Path,
) -> None:
    ipod_root, artwork_dir = _make_ipod_root(tmp_path)
    base_ithmb = artwork_dir / f"F{REQUIRED_FMT}_1.ithmb"
    tail_ithmb = artwork_dir / f"F{REQUIRED_FMT}_2.ithmb"
    base_ithmb.write_bytes(b"BASE")
    tail_ithmb.write_bytes(b"LIVE")
    source = tmp_path / "new.mp3"
    source.write_bytes(b"audio")
    existing_art = {
        101: {
            "song_id": 1,
            "src_img_size": 4,
            "formats": {REQUIRED_FMT: _format_ref(base_ithmb)},
        },
        102: {
            "song_id": 2,
            "src_img_size": 4,
            "formats": {REQUIRED_FMT: _format_ref(tail_ithmb)},
        },
    }

    parse_written_artworkdb = aw.read_existing_artwork
    monkeypatch.setattr(aw, "read_existing_artwork", lambda *_args: existing_art)
    monkeypatch.setattr(aw, "get_artwork_format_definitions", lambda _path: {})
    monkeypatch.setattr(aw, "expected_size_bytes", lambda *_args, **_kwargs: 4)
    monkeypatch.setattr(aw, "extract_art_with_folder", lambda _path: b"new")
    monkeypatch.setattr(
        aw,
        "image_from_bytes",
        lambda *_args, **_kwargs: Image.new("RGB", (1, 1), (9, 8, 7)),
    )
    monkeypatch.setattr(
        aw,
        "encode_image_for_format",
        lambda *_args, **_kwargs: aw.EncodedFormatPayload(
            data=b"NEW!",
            width=1,
            height=1,
            size=4,
            stride_pixels=1,
        ),
    )

    result = aw.write_artworkdb(
        str(ipod_root),
        [_make_track(1, hint="clear_art"), _make_track(2), _make_track(3)],
        pc_file_paths={3: str(source)},
        artwork_formats={REQUIRED_FMT: (1, 1)},
    )

    assert set(result) == {2, 3}
    assert base_ithmb.read_bytes() == b"NEW!"
    assert tail_ithmb.read_bytes() == b"LIVE"

    rewritten = parse_written_artworkdb(
        str(artwork_dir / "ArtworkDB"),
        str(artwork_dir),
    )
    refs_by_song_id = {
        entry["song_id"]: entry["formats"][REQUIRED_FMT]
        for entry in rewritten.values()
    }
    assert set(refs_by_song_id) == {2, 3}
    assert refs_by_song_id[2].ithmb_filename == f"F{REQUIRED_FMT}_2.ithmb"
    assert refs_by_song_id[2].ithmb_offset == 0
    assert refs_by_song_id[3].ithmb_filename == f"F{REQUIRED_FMT}_1.ithmb"
    assert refs_by_song_id[3].ithmb_offset == 0


def test_write_artworkdb_uses_lowest_numbered_file_that_fits(
    monkeypatch,
    tmp_path: Path,
) -> None:
    ipod_root, artwork_dir = _make_ipod_root(tmp_path)
    first_ithmb = artwork_dir / f"F{REQUIRED_FMT}_1.ithmb"
    second_ithmb = artwork_dir / f"F{REQUIRED_FMT}_2.ithmb"
    first_ithmb.write_bytes(b"ONE!")
    second_ithmb.write_bytes(b"TWO!")
    source = tmp_path / "new.mp3"
    source.write_bytes(b"audio")
    existing_art = {
        101: {
            "song_id": 1,
            "src_img_size": 4,
            "formats": {REQUIRED_FMT: _format_ref(first_ithmb)},
        },
        102: {
            "song_id": 2,
            "src_img_size": 4,
            "formats": {REQUIRED_FMT: _format_ref(second_ithmb)},
        },
    }

    parse_written_artworkdb = aw.read_existing_artwork
    monkeypatch.setattr(aw, "read_existing_artwork", lambda *_args: existing_art)
    monkeypatch.setattr(aw, "get_artwork_format_definitions", lambda _path: {})
    monkeypatch.setattr(aw, "expected_size_bytes", lambda *_args, **_kwargs: 4)
    monkeypatch.setattr(aw, "extract_art_with_folder", lambda _path: b"new")
    monkeypatch.setattr(
        aw,
        "image_from_bytes",
        lambda *_args, **_kwargs: Image.new("RGB", (1, 1), (9, 8, 7)),
    )
    monkeypatch.setattr(
        aw,
        "encode_image_for_format",
        lambda *_args, **_kwargs: aw.EncodedFormatPayload(
            data=b"NEW!",
            width=1,
            height=1,
            size=4,
            stride_pixels=1,
        ),
    )

    result = aw.write_artworkdb(
        str(ipod_root),
        [_make_track(1), _make_track(2), _make_track(3)],
        pc_file_paths={3: str(source)},
        artwork_formats={REQUIRED_FMT: (1, 1)},
    )

    assert set(result) == {1, 2, 3}
    assert first_ithmb.read_bytes() == b"ONE!NEW!"
    assert second_ithmb.read_bytes() == b"TWO!"

    rewritten = parse_written_artworkdb(
        str(artwork_dir / "ArtworkDB"),
        str(artwork_dir),
    )
    refs_by_song_id = {
        entry["song_id"]: entry["formats"][REQUIRED_FMT]
        for entry in rewritten.values()
    }
    assert refs_by_song_id[1].ithmb_filename == f"F{REQUIRED_FMT}_1.ithmb"
    assert refs_by_song_id[1].ithmb_offset == 0
    assert refs_by_song_id[2].ithmb_filename == f"F{REQUIRED_FMT}_2.ithmb"
    assert refs_by_song_id[2].ithmb_offset == 0
    assert refs_by_song_id[3].ithmb_filename == f"F{REQUIRED_FMT}_1.ithmb"
    assert refs_by_song_id[3].ithmb_offset == 4


def test_write_artworkdb_uses_next_file_when_lowest_file_is_full(
    monkeypatch,
    tmp_path: Path,
) -> None:
    ipod_root, artwork_dir = _make_ipod_root(tmp_path)
    first_ithmb = artwork_dir / f"F{REQUIRED_FMT}_1.ithmb"
    first_ithmb.write_bytes(b"ONE!")
    source = tmp_path / "new.mp3"
    source.write_bytes(b"audio")
    existing_art = {
        101: {
            "song_id": 1,
            "src_img_size": 4,
            "formats": {REQUIRED_FMT: _format_ref(first_ithmb)},
        },
    }

    parse_written_artworkdb = aw.read_existing_artwork
    monkeypatch.setattr(aw, "ITHMB_MAX_SIZE_BYTES", 7)
    monkeypatch.setattr(aw, "read_existing_artwork", lambda *_args: existing_art)
    monkeypatch.setattr(aw, "get_artwork_format_definitions", lambda _path: {})
    monkeypatch.setattr(aw, "expected_size_bytes", lambda *_args, **_kwargs: 4)
    monkeypatch.setattr(aw, "extract_art_with_folder", lambda _path: b"new")
    monkeypatch.setattr(
        aw,
        "image_from_bytes",
        lambda *_args, **_kwargs: Image.new("RGB", (1, 1), (9, 8, 7)),
    )
    monkeypatch.setattr(
        aw,
        "encode_image_for_format",
        lambda *_args, **_kwargs: aw.EncodedFormatPayload(
            data=b"NEW!",
            width=1,
            height=1,
            size=4,
            stride_pixels=1,
        ),
    )

    result = aw.write_artworkdb(
        str(ipod_root),
        [_make_track(1), _make_track(2)],
        pc_file_paths={2: str(source)},
        artwork_formats={REQUIRED_FMT: (1, 1)},
    )

    assert set(result) == {1, 2}
    assert first_ithmb.read_bytes() == b"ONE!"
    assert (artwork_dir / f"F{REQUIRED_FMT}_2.ithmb").read_bytes() == b"NEW!"

    rewritten = parse_written_artworkdb(
        str(artwork_dir / "ArtworkDB"),
        str(artwork_dir),
    )
    refs_by_song_id = {
        entry["song_id"]: entry["formats"][REQUIRED_FMT]
        for entry in rewritten.values()
    }
    assert refs_by_song_id[1].ithmb_filename == f"F{REQUIRED_FMT}_1.ithmb"
    assert refs_by_song_id[1].ithmb_offset == 0
    assert refs_by_song_id[2].ithmb_filename == f"F{REQUIRED_FMT}_2.ithmb"
    assert refs_by_song_id[2].ithmb_offset == 0


def test_write_artworkdb_reuses_base_when_clear_leaves_no_live_art(
    monkeypatch,
    tmp_path: Path,
) -> None:
    ipod_root, artwork_dir = _make_ipod_root(tmp_path)
    base_ithmb = artwork_dir / f"F{REQUIRED_FMT}_1.ithmb"
    base_ithmb.write_bytes(b"BASE")
    source = tmp_path / "new.mp3"
    source.write_bytes(b"audio")
    existing_art = {
        101: {
            "song_id": 1,
            "src_img_size": 4,
            "formats": {REQUIRED_FMT: _format_ref(base_ithmb)},
        },
    }

    parse_written_artworkdb = aw.read_existing_artwork
    monkeypatch.setattr(aw, "read_existing_artwork", lambda *_args: existing_art)
    monkeypatch.setattr(aw, "get_artwork_format_definitions", lambda _path: {})
    monkeypatch.setattr(aw, "expected_size_bytes", lambda *_args, **_kwargs: 4)
    monkeypatch.setattr(aw, "extract_art_with_folder", lambda _path: b"new")
    monkeypatch.setattr(
        aw,
        "image_from_bytes",
        lambda *_args, **_kwargs: Image.new("RGB", (1, 1), (9, 8, 7)),
    )
    monkeypatch.setattr(
        aw,
        "encode_image_for_format",
        lambda *_args, **_kwargs: aw.EncodedFormatPayload(
            data=b"NEW!",
            width=1,
            height=1,
            size=4,
            stride_pixels=1,
        ),
    )

    result = aw.write_artworkdb(
        str(ipod_root),
        [_make_track(1, hint="clear_art"), _make_track(2)],
        pc_file_paths={2: str(source)},
        artwork_formats={REQUIRED_FMT: (1, 1)},
    )

    assert set(result) == {2}
    assert base_ithmb.read_bytes() == b"NEW!"
    assert not (artwork_dir / f"F{REQUIRED_FMT}_2.ithmb").exists()

    rewritten = parse_written_artworkdb(
        str(artwork_dir / "ArtworkDB"),
        str(artwork_dir),
    )
    refs_by_song_id = {
        entry["song_id"]: entry["formats"][REQUIRED_FMT]
        for entry in rewritten.values()
    }
    assert set(refs_by_song_id) == {2}
    assert refs_by_song_id[2].ithmb_filename == f"F{REQUIRED_FMT}_1.ithmb"
    assert refs_by_song_id[2].ithmb_offset == 0


def test_write_artworkdb_reuses_lowest_file_after_earlier_shards_clear(
    monkeypatch,
    tmp_path: Path,
) -> None:
    ipod_root, artwork_dir = _make_ipod_root(tmp_path)
    base_ithmb = artwork_dir / f"F{REQUIRED_FMT}_1.ithmb"
    middle_ithmb = artwork_dir / f"F{REQUIRED_FMT}_2.ithmb"
    tail_ithmb = artwork_dir / f"F{REQUIRED_FMT}_3.ithmb"
    base_ithmb.write_bytes(b"BASE")
    middle_ithmb.write_bytes(b"MID!")
    tail_ithmb.write_bytes(b"LIVE")
    source = tmp_path / "new.mp3"
    source.write_bytes(b"audio")
    existing_art = {
        101: {
            "song_id": 1,
            "src_img_size": 4,
            "formats": {REQUIRED_FMT: _format_ref(base_ithmb)},
        },
        102: {
            "song_id": 2,
            "src_img_size": 4,
            "formats": {REQUIRED_FMT: _format_ref(middle_ithmb)},
        },
        103: {
            "song_id": 3,
            "src_img_size": 4,
            "formats": {REQUIRED_FMT: _format_ref(tail_ithmb)},
        },
    }

    parse_written_artworkdb = aw.read_existing_artwork
    monkeypatch.setattr(aw, "read_existing_artwork", lambda *_args: existing_art)
    monkeypatch.setattr(aw, "get_artwork_format_definitions", lambda _path: {})
    monkeypatch.setattr(aw, "expected_size_bytes", lambda *_args, **_kwargs: 4)
    monkeypatch.setattr(aw, "extract_art_with_folder", lambda _path: b"new")
    monkeypatch.setattr(
        aw,
        "image_from_bytes",
        lambda *_args, **_kwargs: Image.new("RGB", (1, 1), (9, 8, 7)),
    )
    monkeypatch.setattr(
        aw,
        "encode_image_for_format",
        lambda *_args, **_kwargs: aw.EncodedFormatPayload(
            data=b"NEW!",
            width=1,
            height=1,
            size=4,
            stride_pixels=1,
        ),
    )

    result = aw.write_artworkdb(
        str(ipod_root),
        [
            _make_track(1, hint="clear_art"),
            _make_track(2, hint="clear_art"),
            _make_track(3),
            _make_track(4),
        ],
        pc_file_paths={4: str(source)},
        artwork_formats={REQUIRED_FMT: (1, 1)},
    )

    assert set(result) == {3, 4}
    assert base_ithmb.read_bytes() == b"NEW!"
    assert middle_ithmb.read_bytes() == b"MID!"
    assert tail_ithmb.read_bytes() == b"LIVE"

    rewritten = parse_written_artworkdb(
        str(artwork_dir / "ArtworkDB"),
        str(artwork_dir),
    )
    refs_by_song_id = {
        entry["song_id"]: entry["formats"][REQUIRED_FMT]
        for entry in rewritten.values()
    }
    assert set(refs_by_song_id) == {3, 4}
    assert refs_by_song_id[3].ithmb_filename == f"F{REQUIRED_FMT}_3.ithmb"
    assert refs_by_song_id[3].ithmb_offset == 0
    assert refs_by_song_id[4].ithmb_filename == f"F{REQUIRED_FMT}_1.ithmb"
    assert refs_by_song_id[4].ithmb_offset == 0


def test_write_artworkdb_preserve_only_does_not_replace_ithmb(
    monkeypatch,
    tmp_path: Path,
) -> None:
    ipod_root, artwork_dir = _make_ipod_root(tmp_path)
    existing_ithmb = artwork_dir / f"F{REQUIRED_FMT}_1.ithmb"
    existing_ithmb.write_bytes(b"OLD!")
    progress: list[str] = []
    replaced: list[str] = []
    original_replace = aw.os.replace

    monkeypatch.setattr(aw, "read_existing_artwork", lambda *_args, **_kwargs: _existing_art_entry(existing_ithmb))
    monkeypatch.setattr(aw, "get_artwork_format_definitions", lambda _ipod_path: {})
    monkeypatch.setattr(aw, "expected_size_bytes", lambda *_args, **_kwargs: 4)

    def _record_replace(src: str, dst: str) -> None:
        replaced.append(Path(dst).name)
        original_replace(src, dst)

    monkeypatch.setattr(aw.os, "replace", _record_replace)

    result = aw.write_artworkdb(
        str(ipod_root),
        [_make_track(1, hint="preserve_existing")],
        pc_file_paths={},
        artwork_formats={REQUIRED_FMT: (1, 1)},
        progress_callback=progress.append,
    )

    assert result[1] == (100, 99)
    assert existing_ithmb.read_bytes() == b"OLD!"
    assert f"F{REQUIRED_FMT}_1.ithmb" not in replaced
    assert replaced == ["ArtworkDB"]
    assert any("no image data rewritten" in message for message in progress)
    assert not any("writing 1 image" in message for message in progress)


def test_write_artworkdb_preserve_only_relinks_tracks_to_new_mhii_ids(
    monkeypatch,
    tmp_path: Path,
) -> None:
    ipod_root, artwork_dir = _make_ipod_root(tmp_path)
    existing_ithmb = artwork_dir / f"F{REQUIRED_FMT}_1.ithmb"
    existing_ithmb.write_bytes(b"ONE!TWO!")
    parse_written_artworkdb = aw.read_existing_artwork
    read_state = {"calls": 0}

    def _existing(_artworkdb_path: str, _artwork_dir: str) -> dict[int, dict]:
        if read_state["calls"] > 0:
            return parse_written_artworkdb(_artworkdb_path, _artwork_dir)
        read_state["calls"] += 1
        return {
            42: {
                "song_id": 1,
                "src_img_size": 99,
                "formats": {
                    REQUIRED_FMT: aw.ExistingFormatRef(
                        path=str(existing_ithmb),
                        ithmb_offset=0,
                        size=4,
                        width=1,
                        height=1,
                    ),
                },
            },
            43: {
                "song_id": 2,
                "src_img_size": 88,
                "formats": {
                    REQUIRED_FMT: aw.ExistingFormatRef(
                        path=str(existing_ithmb),
                        ithmb_offset=4,
                        size=4,
                        width=1,
                        height=1,
                    ),
                },
            },
        }

    monkeypatch.setattr(aw, "read_existing_artwork", _existing)
    monkeypatch.setattr(aw, "get_artwork_format_definitions", lambda _ipod_path: {})
    monkeypatch.setattr(aw, "expected_size_bytes", lambda *_args, **_kwargs: 4)

    result = aw.write_artworkdb(
        str(ipod_root),
        [_make_track(1, hint="preserve_existing"), _make_track(2, hint="preserve_existing")],
        pc_file_paths={},
        artwork_formats={REQUIRED_FMT: (1, 1)},
        start_img_id=500,
    )

    assert result == {
        1: (500, 99),
        2: (501, 88),
    }
    assert existing_ithmb.read_bytes() == b"ONE!TWO!"

    rewritten = aw.read_existing_artwork(str(artwork_dir / "ArtworkDB"), str(artwork_dir))
    assert set(rewritten) == {500, 501}
    assert {entry["song_id"]: img_id for img_id, entry in rewritten.items()} == {
        1: 500,
        2: 501,
    }
    refs_by_song_id = {
        entry["song_id"]: entry["formats"][REQUIRED_FMT]
        for entry in rewritten.values()
    }
    assert refs_by_song_id[1].ithmb_filename == f"F{REQUIRED_FMT}_1.ithmb"
    assert refs_by_song_id[1].ithmb_offset == 0
    assert refs_by_song_id[2].ithmb_filename == f"F{REQUIRED_FMT}_1.ithmb"
    assert refs_by_song_id[2].ithmb_offset == 4


def test_write_artworkdb_clears_removed_art_without_pruning_existing_ithmb(
    monkeypatch,
    tmp_path: Path,
) -> None:
    ipod_root, artwork_dir = _make_ipod_root(tmp_path)
    pc_file = tmp_path / "song.mp3"
    pc_file.write_bytes(b"music")
    existing_ithmb = artwork_dir / f"F{REQUIRED_FMT}_1.ithmb"
    existing_ithmb.write_bytes(b"OLD!")

    monkeypatch.setattr(aw, "read_existing_artwork", lambda *_args, **_kwargs: _existing_art_entry(existing_ithmb))
    monkeypatch.setattr(aw, "get_artwork_format_definitions", lambda _ipod_path: {})
    monkeypatch.setattr(aw, "expected_size_bytes", lambda *_args, **_kwargs: 4)
    monkeypatch.setattr(aw, "extract_art_with_folder", lambda _path: None)

    result = aw.write_artworkdb(
        str(ipod_root),
        [_make_track(1)],
        pc_file_paths={1: str(pc_file)},
        artwork_formats={REQUIRED_FMT: (1, 1)},
    )

    assert result == {}
    assert existing_ithmb.exists()
    assert existing_ithmb.read_bytes() == b"OLD!"


def test_write_artworkdb_clear_art_warns_for_unknown_and_leaves_file_alone(
    monkeypatch,
    tmp_path: Path,
    caplog,
) -> None:
    ipod_root, artwork_dir = _make_ipod_root(tmp_path)
    unknown_ithmb = artwork_dir / f"F{UNKNOWN_FMT}_1.ithmb"
    unknown_ithmb.write_bytes(b"UNKN")

    monkeypatch.setattr(
        aw,
        "read_existing_artwork",
        lambda *_args, **_kwargs: {
            42: {
                "song_id": 1,
                "src_img_size": 99,
                "formats": {
                    UNKNOWN_FMT: _format_ref(unknown_ithmb),
                },
            },
        },
    )
    monkeypatch.setattr(aw, "get_artwork_format_definitions", lambda _ipod_path: {})

    with caplog.at_level(logging.WARNING):
        result = aw.write_artworkdb(
            str(ipod_root),
            [_make_track(1, hint="clear_art")],
            pc_file_paths={},
            artwork_formats={REQUIRED_FMT: (1, 1)},
        )

    assert result == {}
    assert unknown_ithmb.read_bytes() == b"UNKN"
    assert f"unknown artwork format {UNKNOWN_FMT} at {unknown_ithmb}" in caplog.text


def test_write_artworkdb_preserves_existing_art_when_source_is_missing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    ipod_root, artwork_dir = _make_ipod_root(tmp_path)
    missing_pc_file = tmp_path / "missing.mp3"
    existing_ithmb = artwork_dir / f"F{REQUIRED_FMT}_1.ithmb"
    existing_ithmb.write_bytes(b"OLD!")

    monkeypatch.setattr(aw, "read_existing_artwork", lambda *_args, **_kwargs: _existing_art_entry(existing_ithmb))
    monkeypatch.setattr(aw, "get_artwork_format_definitions", lambda _ipod_path: {})
    monkeypatch.setattr(aw, "expected_size_bytes", lambda *_args, **_kwargs: 4)

    result = aw.write_artworkdb(
        str(ipod_root),
        [_make_track(1)],
        pc_file_paths={1: str(missing_pc_file)},
        artwork_formats={REQUIRED_FMT: (1, 1)},
    )

    assert result[1] == (100, 99)
    assert existing_ithmb.exists()
    assert existing_ithmb.read_bytes() == b"OLD!"


def test_write_artworkdb_salvages_existing_art_when_only_partial_formats_exist(
    monkeypatch,
    tmp_path: Path,
) -> None:
    ipod_root, artwork_dir = _make_ipod_root(tmp_path)
    existing_ithmb = artwork_dir / f"F{EXTRA_KNOWN_FMT}_1.ithmb"
    existing_ithmb.write_bytes(b"OLD!")

    monkeypatch.setattr(
        aw,
        "read_existing_artwork",
        lambda *_args, **_kwargs: {
            42: {
                "song_id": 1,
                "src_img_size": 99,
                "formats": {
                    EXTRA_KNOWN_FMT: _format_ref(existing_ithmb),
                },
            },
        },
    )
    monkeypatch.setattr(aw, "get_artwork_format_definitions", lambda _ipod_path: {})
    monkeypatch.setattr(aw, "expected_size_bytes", lambda *_args, **_kwargs: 4)
    monkeypatch.setattr(
        aw,
        "_decode_preserved_frame",
        lambda *_args, **_kwargs: Image.new("RGB", (1, 1), (1, 2, 3)),
    )
    monkeypatch.setattr(
        aw,
        "encode_image_for_format",
        lambda _img, fmt_id, *_args, **_kwargs: aw.EncodedFormatPayload(
            data=bytes([fmt_id % 256]) * 4,
            width=1,
            height=1,
            size=4,
            stride_pixels=1,
        ),
    )

    result = aw.write_artworkdb(
        str(ipod_root),
        [_make_track(1)],
        pc_file_paths={},
        artwork_formats={REQUIRED_FMT: (1, 1)},
    )

    assert result[1] == (100, 99)
    assert (artwork_dir / f"F{EXTRA_KNOWN_FMT}_1.ithmb").exists()
    assert (artwork_dir / f"F{REQUIRED_FMT}_1.ithmb").exists()
    assert (artwork_dir / f"F{REQUIRED_FMT}_1.ithmb").read_bytes() == bytes([REQUIRED_FMT % 256]) * 4


def test_write_artworkdb_drops_preserved_art_when_required_formats_cannot_be_salvaged(
    monkeypatch,
    tmp_path: Path,
) -> None:
    ipod_root, artwork_dir = _make_ipod_root(tmp_path)
    existing_ithmb = artwork_dir / f"F{EXTRA_KNOWN_FMT}_1.ithmb"
    existing_ithmb.write_bytes(b"OLD!")

    monkeypatch.setattr(
        aw,
        "read_existing_artwork",
        lambda *_args, **_kwargs: {
            42: {
                "song_id": 1,
                "src_img_size": 99,
                "formats": {
                    EXTRA_KNOWN_FMT: _format_ref(existing_ithmb),
                },
            },
        },
    )
    monkeypatch.setattr(aw, "get_artwork_format_definitions", lambda _ipod_path: {})
    monkeypatch.setattr(aw, "expected_size_bytes", lambda *_args, **_kwargs: 4)
    monkeypatch.setattr(aw, "_decode_preserved_frame", lambda *_args, **_kwargs: None)

    result = aw.write_artworkdb(
        str(ipod_root),
        [_make_track(1)],
        pc_file_paths={},
        artwork_formats={REQUIRED_FMT: (1, 1)},
    )

    assert result == {}
    assert existing_ithmb.exists()
    assert not (artwork_dir / f"F{REQUIRED_FMT}_1.ithmb").exists()


def test_write_artworkdb_zero_art_case_preserves_existing_ithmbs(
    monkeypatch,
    tmp_path: Path,
) -> None:
    ipod_root, artwork_dir = _make_ipod_root(tmp_path)
    stale_ithmb = artwork_dir / f"F{REQUIRED_FMT}_1.ithmb"
    stale_ithmb.write_bytes(b"OLD!")
    predictable_temp = artwork_dir / "ArtworkDB.tmp"
    predictable_temp.write_bytes(b"do-not-truncate")

    monkeypatch.setattr(aw, "read_existing_artwork", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(aw, "get_artwork_format_definitions", lambda _ipod_path: {})

    result = aw.write_artworkdb(
        str(ipod_root),
        [],
        pc_file_paths={},
        artwork_formats={REQUIRED_FMT: (1, 1)},
    )

    assert result == {}
    assert stale_ithmb.exists()
    assert stale_ithmb.read_bytes() == b"OLD!"
    assert predictable_temp.read_bytes() == b"do-not-truncate"
    assert (artwork_dir / "ArtworkDB").exists()


def test_write_artworkdb_cleans_exclusive_ithmb_temp_when_flush_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    ipod_root, artwork_dir = _make_ipod_root(tmp_path)
    source = tmp_path / "song.mp3"
    source.write_bytes(b"music")
    callbacks: list[str] = []

    monkeypatch.setattr(aw, "read_existing_artwork", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(aw, "get_artwork_format_definitions", lambda _ipod_path: {})
    monkeypatch.setattr(aw, "extract_art_with_folder", lambda _path: b"image")
    monkeypatch.setattr(
        aw,
        "image_from_bytes",
        lambda _bytes, **_kwargs: Image.new("RGB", (1, 1), (9, 8, 7)),
    )
    monkeypatch.setattr(
        aw,
        "encode_image_for_format",
        lambda *_args, **_kwargs: aw.EncodedFormatPayload(
            data=b"NEW!",
            width=1,
            height=1,
            size=4,
            stride_pixels=1,
        ),
    )
    monkeypatch.setattr(
        aw,
        "flush_written_file",
        lambda _file: (_ for _ in ()).throw(OSError("device flush failed")),
    )

    with pytest.raises(OSError, match="device flush failed"):
        aw.write_artworkdb(
            str(ipod_root),
            [_make_track(1)],
            pc_file_paths={1: str(source)},
            artwork_formats={REQUIRED_FMT: (1, 1)},
            before_device_mutation=lambda: callbacks.append("revalidate"),
        )

    assert callbacks
    assert list(artwork_dir.glob(".iop-*.tmp")) == []
    assert not (artwork_dir / f"F{REQUIRED_FMT}_1.ithmb").exists()


def test_write_artworkdb_reencodes_existing_extra_known_formats_for_new_art(
    monkeypatch,
    tmp_path: Path,
) -> None:
    ipod_root, artwork_dir = _make_ipod_root(tmp_path)
    pc_file = tmp_path / "song.mp3"
    pc_file.write_bytes(b"music")
    existing_required = artwork_dir / f"F{REQUIRED_FMT}_1.ithmb"
    existing_extra = artwork_dir / f"F{EXTRA_KNOWN_FMT}_1.ithmb"
    existing_required.write_bytes(b"OLDR")
    existing_extra.write_bytes(b"OLDE")

    parse_written_artworkdb = aw.read_existing_artwork
    monkeypatch.setattr(
        aw,
        "read_existing_artwork",
        lambda *_args, **_kwargs: {
            42: {
                "song_id": 1,
                "src_img_size": 99,
                "formats": {
                    REQUIRED_FMT: _format_ref(existing_required),
                    EXTRA_KNOWN_FMT: _format_ref(existing_extra),
                },
            },
        },
    )
    monkeypatch.setattr(aw, "get_artwork_format_definitions", lambda _ipod_path: {})
    monkeypatch.setattr(aw, "extract_art_with_folder", lambda _path: b"art")
    monkeypatch.setattr(aw, "image_from_bytes", lambda _bytes: Image.new("RGB", (1, 1), (9, 8, 7)))

    seen_format_ids: list[int] = []

    def _encode(_img, fmt_id, *_args, **_kwargs):
        seen_format_ids.append(fmt_id)
        return aw.EncodedFormatPayload(
            data=bytes([fmt_id % 256]) * 4,
            width=1,
            height=1,
            size=4,
            stride_pixels=1,
        )

    monkeypatch.setattr(aw, "encode_image_for_format", _encode)

    result = aw.write_artworkdb(
        str(ipod_root),
        [_make_track(1)],
        pc_file_paths={1: str(pc_file)},
        artwork_formats={REQUIRED_FMT: (1, 1)},
    )

    assert result[1] == (100, 3)
    assert seen_format_ids == [REQUIRED_FMT, EXTRA_KNOWN_FMT]
    assert existing_required.read_bytes() == bytes([REQUIRED_FMT % 256]) * 4
    assert existing_extra.read_bytes() == bytes([EXTRA_KNOWN_FMT % 256]) * 4
    assert not (artwork_dir / f"F{REQUIRED_FMT}_2.ithmb").exists()
    assert not (artwork_dir / f"F{EXTRA_KNOWN_FMT}_2.ithmb").exists()

    rewritten = parse_written_artworkdb(
        str(artwork_dir / "ArtworkDB"),
        str(artwork_dir),
    )
    refs = next(iter(rewritten.values()))["formats"]
    assert refs[REQUIRED_FMT].ithmb_filename == f"F{REQUIRED_FMT}_1.ithmb"
    assert refs[EXTRA_KNOWN_FMT].ithmb_filename == f"F{EXTRA_KNOWN_FMT}_1.ithmb"


def test_write_artworkdb_incremental_sync_preserves_video_5g_existing_art(
    monkeypatch,
    tmp_path: Path,
) -> None:
    ipod_root, artwork_dir = _make_ipod_root(tmp_path)
    video_formats = {
        VIDEO_SMALL_FMT: (1, 1),
        VIDEO_LARGE_FMT: (2, 2),
    }
    tracks = [_make_track(1), _make_track(2)]
    pc_paths: dict[int, str] = {}
    for track in tracks:
        pc_file = tmp_path / f"song-{track.db_track_id}.mp3"
        pc_file.write_bytes(b"music")
        pc_paths[track.db_track_id] = str(pc_file)

    monkeypatch.setattr(aw, "get_artwork_format_definitions", lambda _ipod_path: {})
    monkeypatch.setattr(aw, "extract_art_with_folder", lambda path: f"art:{path}".encode())
    monkeypatch.setattr(aw, "image_from_bytes", lambda _bytes: Image.new("RGB", (2, 2), (9, 8, 7)))

    def _encode(_img, fmt_id, *_args, **_kwargs):
        width, height = video_formats[fmt_id]
        data = bytes([fmt_id % 256]) * (width * height * 2)
        return aw.EncodedFormatPayload(
            data=data,
            width=width,
            height=height,
            size=len(data),
            stride_pixels=width,
        )

    monkeypatch.setattr(aw, "encode_image_for_format", _encode)

    first_result = aw.write_artworkdb(
        str(ipod_root),
        tracks,
        pc_file_paths=pc_paths,
        artwork_formats=video_formats,
    )
    for track in tracks:
        img_id, src_size = first_result[track.db_track_id]
        track.mhii_link = img_id
        track.artwork_count = 1
        track.artwork_size = src_size
    old_img_links = {track.db_track_id: track.mhii_link for track in tracks}

    new_track = _make_track(3)
    new_pc_file = tmp_path / "song-3.mp3"
    new_pc_file.write_bytes(b"music")

    second_result = aw.write_artworkdb(
        str(ipod_root),
        [*tracks, new_track],
        pc_file_paths={3: str(new_pc_file)},
        artwork_formats=video_formats,
        start_img_id=500,
    )

    assert set(second_result) == {1, 2, 3}
    assert old_img_links == {1: 100, 2: 101}
    assert {db_track_id: info[0] for db_track_id, info in second_result.items()} == {
        1: 500,
        2: 501,
        3: 502,
    }
    assert all(
        second_result[db_track_id][0] != old_img_links[db_track_id]
        for db_track_id in old_img_links
    )

    for track in [*tracks, new_track]:
        img_id, src_size = second_result[track.db_track_id]
        track.mhii_link = img_id
        track.artwork_count = 1
        track.artwork_size = src_size
    assert {track.db_track_id: track.mhii_link for track in [*tracks, new_track]} == {
        1: 500,
        2: 501,
        3: 502,
    }

    rewritten = aw.read_existing_artwork(str(artwork_dir / "ArtworkDB"), str(artwork_dir))
    assert set(rewritten) == {500, 501, 502}
    assert {entry["song_id"]: img_id for img_id, entry in rewritten.items()} == {
        1: 500,
        2: 501,
        3: 502,
    }
    for entry in rewritten.values():
        assert set(entry["formats"]) == {VIDEO_SMALL_FMT, VIDEO_LARGE_FMT}
    assert (artwork_dir / f"F{VIDEO_SMALL_FMT}_1.ithmb").stat().st_size > 0
    assert (artwork_dir / f"F{VIDEO_LARGE_FMT}_1.ithmb").stat().st_size > 0


def test_write_artworkdb_warns_for_unknown_formats_and_leaves_file_alone(
    monkeypatch,
    tmp_path: Path,
    caplog,
) -> None:
    ipod_root, artwork_dir = _make_ipod_root(tmp_path)
    known_ithmb = artwork_dir / f"F{REQUIRED_FMT}_1.ithmb"
    unknown_ithmb = artwork_dir / f"F{UNKNOWN_FMT}_1.ithmb"
    known_ithmb.write_bytes(b"KNOWN")
    unknown_ithmb.write_bytes(b"UNKN")

    parse_written_artworkdb = aw.read_existing_artwork
    read_state = {"calls": 0}

    def read_existing_artwork_once_then_parse(*args, **kwargs):
        if read_state["calls"] == 0:
            read_state["calls"] += 1
            return {
                42: {
                    "song_id": 1,
                    "src_img_size": 99,
                    "formats": {
                        REQUIRED_FMT: _format_ref(known_ithmb),
                        UNKNOWN_FMT: _format_ref(unknown_ithmb),
                    },
                },
            }
        return parse_written_artworkdb(*args, **kwargs)

    monkeypatch.setattr(
        aw,
        "read_existing_artwork",
        read_existing_artwork_once_then_parse,
    )
    monkeypatch.setattr(aw, "get_artwork_format_definitions", lambda _ipod_path: {})
    monkeypatch.setattr(aw, "expected_size_bytes", lambda *_args, **_kwargs: 4)

    with caplog.at_level(logging.WARNING):
        result = aw.write_artworkdb(
            str(ipod_root),
            [_make_track(1)],
            pc_file_paths={},
            artwork_formats={REQUIRED_FMT: (1, 1)},
        )

    assert result[1] == (100, 99)
    assert unknown_ithmb.read_bytes() == b"UNKN"
    rewritten = aw.read_existing_artwork(str(artwork_dir / "ArtworkDB"), str(artwork_dir))
    assert rewritten[100]["formats"][UNKNOWN_FMT].path == str(unknown_ithmb)
    assert f"unknown artwork format {UNKNOWN_FMT}" in caplog.text


def test_read_existing_artwork_uses_mhni_filename_for_numbered_ithmb(
    tmp_path: Path,
) -> None:
    _ipod_root, artwork_dir = _make_ipod_root(tmp_path)
    ithmb_path = artwork_dir / f"F{REQUIRED_FMT}_2.ithmb"
    ithmb_path.write_bytes(b"JUNKDATA")
    entry = aw.ArtworkEntry(
        100,
        1,
        None,
        4,
        {
            REQUIRED_FMT: aw.EncodedFormatPayload(
                data=b"DATA",
                width=1,
                height=1,
                size=4,
                stride_pixels=1,
            ),
        },
    )
    artdb_data = aw.build_artworkdb(
        [entry],
        {100: {REQUIRED_FMT: aw.IthmbLocation(f"F{REQUIRED_FMT}_2.ithmb", 4)}},
        [REQUIRED_FMT],
        {REQUIRED_FMT: 4},
        101,
    )
    artdb_path = artwork_dir / "ArtworkDB"
    artdb_path.write_bytes(artdb_data)

    parsed = aw.read_existing_artwork(str(artdb_path), str(artwork_dir))

    ref = parsed[100]["formats"][REQUIRED_FMT]
    assert ref.path == str(ithmb_path)
    assert ref.ithmb_filename == f"F{REQUIRED_FMT}_2.ithmb"
    assert ref.ithmb_offset == 4


def test_ithmb_shard_budget_limits_mutable_tail_rewrite_size() -> None:
    assert aw.ITHMB_MAX_SIZE_BYTES == 32 * 1000 * 1000


def test_write_artworkdb_rolls_owned_formats_to_next_numbered_ithmb(
    monkeypatch,
    tmp_path: Path,
) -> None:
    ipod_root, artwork_dir = _make_ipod_root(tmp_path)
    tracks = [_make_track(1), _make_track(2), _make_track(3)]
    pc_paths = {}
    for track in tracks:
        pc_file = tmp_path / f"song-{track.db_track_id}.mp3"
        pc_file.write_bytes(b"music")
        pc_paths[track.db_track_id] = str(pc_file)

    monkeypatch.setattr(aw, "ITHMB_MAX_SIZE_BYTES", 8)
    monkeypatch.setattr(aw, "get_artwork_format_definitions", lambda _ipod_path: {})
    monkeypatch.setattr(
        aw,
        "extract_art_with_folder",
        lambda path: Path(path).name.encode("ascii"),
    )
    monkeypatch.setattr(
        aw,
        "image_from_bytes",
        lambda data: Image.new("RGB", (1, 1), (data[0], 0, 0)),
    )
    monkeypatch.setattr(
        aw,
        "encode_image_for_format",
        lambda _img, fmt_id, *_args, **_kwargs: aw.EncodedFormatPayload(
            data=bytes([fmt_id % 256]) * 4,
            width=1,
            height=1,
            size=4,
            stride_pixels=1,
        ),
    )

    result = aw.write_artworkdb(
        str(ipod_root),
        tracks,
        pc_file_paths=pc_paths,
        artwork_formats={REQUIRED_FMT: (1, 1)},
    )

    assert set(result) == {1, 2, 3}
    assert (artwork_dir / f"F{REQUIRED_FMT}_1.ithmb").read_bytes() == bytes([REQUIRED_FMT % 256]) * 8
    assert (artwork_dir / f"F{REQUIRED_FMT}_2.ithmb").read_bytes() == bytes([REQUIRED_FMT % 256]) * 4

    parsed = aw.read_existing_artwork(str(artwork_dir / "ArtworkDB"), str(artwork_dir))
    refs_by_song_id = {
        entry["song_id"]: entry["formats"][REQUIRED_FMT]
        for entry in parsed.values()
    }
    assert refs_by_song_id[1].ithmb_filename == f"F{REQUIRED_FMT}_1.ithmb"
    assert refs_by_song_id[1].ithmb_offset == 0
    assert refs_by_song_id[2].ithmb_filename == f"F{REQUIRED_FMT}_1.ithmb"
    assert refs_by_song_id[2].ithmb_offset == 4
    assert refs_by_song_id[3].ithmb_filename == f"F{REQUIRED_FMT}_2.ithmb"
    assert refs_by_song_id[3].ithmb_offset == 0


def test_read_existing_artwork_rejects_truncated_tail(
    tmp_path: Path,
) -> None:
    _ipod_root, artwork_dir = _make_ipod_root(tmp_path)
    ithmb_path = artwork_dir / f"F{REQUIRED_FMT}_1.ithmb"
    ithmb_path.write_bytes(b"DATA")
    entry = aw.ArtworkEntry(
        100,
        1,
        None,
        4,
        {
            REQUIRED_FMT: aw.EncodedFormatPayload(
                data=b"DATA",
                width=1,
                height=1,
                size=4,
                stride_pixels=1,
            ),
        },
    )
    artdb_data = aw.build_artworkdb(
        [entry],
        {100: {REQUIRED_FMT: 0}},
        [REQUIRED_FMT],
        {REQUIRED_FMT: 4},
        101,
    )
    artdb_path = artwork_dir / "ArtworkDB"
    artdb_path.write_bytes(artdb_data[:-10])

    with pytest.raises(
        DeviceWriteSafetyError,
        match="ArtworkDB is malformed or truncated",
    ):
        aw.read_existing_artwork(str(artdb_path), str(artwork_dir))
