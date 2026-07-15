from pathlib import Path

from iopenpod.application.jobs import ChapterSplitWorker
from iopenpod.itunesdb_writer.mhit_writer import TrackInfo
from iopenpod.sync.contracts import SyncAction, SyncItem, SyncPlan
from iopenpod.sync.fingerprint_diff_engine import FingerprintDiffEngine
from iopenpod.sync.mapping import MappingFile
from iopenpod.sync.pc_library import PCTrack
from iopenpod.sync.sync_executor import SyncExecutor, _SyncContext
from iopenpod.sync.transcoder import TranscodeOptions


def _track(
    path: Path,
    *,
    title: str,
    album: str = "Album",
    track_number: int = 1,
    duration_ms: int = 1000,
) -> PCTrack:
    path.write_bytes((title or "track").encode("utf-8"))
    stat = path.stat()
    return PCTrack(
        path=str(path),
        relative_path=path.name,
        filename=path.name,
        extension=path.suffix,
        mtime=stat.st_mtime,
        size=stat.st_size,
        title=title,
        artist="Artist",
        album=album,
        album_artist="Artist",
        genre=None,
        year=None,
        track_number=track_number,
        track_total=2,
        disc_number=1,
        disc_total=1,
        duration_ms=duration_ms,
        bitrate=None,
        sample_rate=None,
        rating=None,
    )


def _engine() -> FingerprintDiffEngine:
    engine = FingerprintDiffEngine.__new__(FingerprintDiffEngine)
    engine.transcode_options = TranscodeOptions()
    return engine


def _source_row(engine: FingerprintDiffEngine, pc_track: PCTrack, fp: str, index: int) -> dict:
    chapter = {
        "startpos": (index - 1) * 1000,
        "endpos": index * 1000,
    }
    return engine._contained_source_from_pc_track(pc_track, fp, chapter, index)


def _mapping_with_aggregate(
    engine: FingerprintDiffEngine,
    tracks_by_fp: dict[str, PCTrack],
) -> MappingFile:
    mapping = MappingFile()
    contains_sources = [
        _source_row(engine, pc_track, fp, index)
        for index, (fp, pc_track) in enumerate(tracks_by_fp.items(), start=1)
    ]
    mapping.add_track(
        fingerprint="agg-fp",
        db_track_id=42,
        source_format="m4a",
        ipod_format="m4a",
        source_size=1234,
        source_mtime=10.0,
        was_transcoded=False,
        aggregate_kind="chaptered_album",
        contains_fingerprints=tuple(tracks_by_fp),
        contains_sources=contains_sources,
    )
    return mapping


def test_mapping_writes_contains_fingerprints_only_for_aggregates() -> None:
    mapping = MappingFile()
    mapping.add_track(
        fingerprint="ordinary-fp",
        db_track_id=1,
        source_format="mp3",
        ipod_format="mp3",
        source_size=10,
        source_mtime=1.0,
        was_transcoded=False,
    )
    mapping.add_track(
        fingerprint="agg-fp",
        db_track_id=2,
        source_format="m4a",
        ipod_format="m4a",
        source_size=20,
        source_mtime=2.0,
        was_transcoded=False,
        aggregate_kind="chaptered_album",
        contains_fingerprints=("one", "two"),
        contains_sources=({"fingerprint": "one"}, {"fingerprint": "two"}),
    )

    data = mapping.to_dict()

    ordinary = data["tracks"]["ordinary-fp"][0]
    aggregate = data["tracks"]["agg-fp"][0]
    assert "containsFingerprints" not in ordinary
    assert aggregate["containsFingerprints"] == ["one", "two"]
    assert aggregate["containsSources"] == [{"fingerprint": "one"}, {"fingerprint": "two"}]

    loaded = MappingFile.from_dict(data)
    _fp, entry = loaded.aggregate_entries()[0]
    assert entry.contains_fingerprints == ["one", "two"]
    assert entry.contains_sources == [{"fingerprint": "one"}, {"fingerprint": "two"}]


def test_chaptered_aggregate_represents_contained_tracks(tmp_path) -> None:
    engine = _engine()
    first = _track(tmp_path / "one.mp3", title="One", track_number=1)
    second = _track(tmp_path / "two.mp3", title="Two", track_number=2)
    mapping = _mapping_with_aggregate(engine, {"fp-one": first, "fp-two": second})
    plan = SyncPlan()

    represented, detached, claimed = engine._plan_chaptered_aggregate_updates(
        plan,
        mapping,
        {"fp-one": [first], "fp-two": [second]},
        {
            42: {
                "db_track_id": 42,
                "Title": "Album",
                "Location": ":iPod_Control:Music:F00:Album.m4a",
                "chapter_data": {
                    "chapters": [
                        {"startpos": 0, "title": "01. One"},
                        {"startpos": 1000, "title": "02. Two"},
                    ]
                },
            }
        },
        {"fp-one", "fp-two"},
    )

    assert represented == {"fp-one": mapping.get_entries("agg-fp")[0], "fp-two": mapping.get_entries("agg-fp")[0]}
    assert detached == set()
    assert claimed == {42}
    assert not plan.has_changes


def test_chapter_title_change_plans_metadata_update(tmp_path) -> None:
    engine = _engine()
    first = _track(tmp_path / "one.mp3", title="New One", track_number=1)
    second = _track(tmp_path / "two.mp3", title="Two", track_number=2)
    mapping = _mapping_with_aggregate(engine, {"fp-one": first, "fp-two": second})
    plan = SyncPlan()

    engine._plan_chaptered_aggregate_updates(
        plan,
        mapping,
        {"fp-one": [first], "fp-two": [second]},
        {
            42: {
                "db_track_id": 42,
                "Title": "Album",
                "Location": ":iPod_Control:Music:F00:Album.m4a",
                "chapter_data": {
                    "chapters": [
                        {"startpos": 0, "title": "01. Old One"},
                        {"startpos": 1000, "title": "02. Two"},
                    ]
                },
            }
        },
        {"fp-one", "fp-two"},
    )

    assert len(plan.to_update_metadata) == 1
    update = plan.to_update_metadata[0]
    assert update.action is SyncAction.UPDATE_METADATA
    assert update.aggregate_kind == "chaptered_album"
    assert update.metadata_changes["chapter_data"][0]["chapters"][0]["title"] == "01. New One"


def test_chapter_title_tag_edit_does_not_plan_file_rebuild(tmp_path) -> None:
    engine = _engine()
    first = _track(tmp_path / "one.mp3", title="One", track_number=1)
    second = _track(tmp_path / "two.mp3", title="Two", track_number=2)
    mapping = _mapping_with_aggregate(engine, {"fp-one": first, "fp-two": second})
    first.title = "New One"
    first.size += 128
    first.mtime += 10
    plan = SyncPlan()

    engine._plan_chaptered_aggregate_updates(
        plan,
        mapping,
        {"fp-one": [first], "fp-two": [second]},
        {
            42: {
                "db_track_id": 42,
                "Title": "Album",
                "Location": ":iPod_Control:Music:F00:Album.m4a",
                "chapter_data": {
                    "chapters": [
                        {"startpos": 0, "title": "01. One"},
                        {"startpos": 1000, "title": "02. Two"},
                    ]
                },
            }
        },
        {"fp-one", "fp-two"},
    )

    assert plan.to_update_file == []
    assert len(plan.to_update_metadata) == 1
    update = plan.to_update_metadata[0]
    assert update.description == "Update chapter titles: Album"
    assert update.metadata_changes["chapter_data"][0]["chapters"][0]["title"] == "01. New One"


def test_missing_contained_source_plans_partial_aggregate_rebuild(tmp_path) -> None:
    engine = _engine()
    first = _track(tmp_path / "one.mp3", title="One", track_number=1)
    second = _track(tmp_path / "two.mp3", title="Two", track_number=2)
    third = _track(tmp_path / "three.mp3", title="Three", track_number=3)
    mapping = _mapping_with_aggregate(
        engine,
        {"fp-one": first, "fp-two": second, "fp-three": third},
    )
    plan = SyncPlan()

    engine._plan_chaptered_aggregate_updates(
        plan,
        mapping,
        {"fp-one": [first], "fp-three": [third]},
        {
            42: {
                "db_track_id": 42,
                "Title": "Album",
                "Location": ":iPod_Control:Music:F00:Album.m4a",
                "size": 999,
                "chapter_data": {
                    "chapters": [
                        {"startpos": 0, "title": "01. One"},
                        {"startpos": 1000, "title": "02. Two"},
                        {"startpos": 2000, "title": "03. Three"},
                    ]
                },
            }
        },
        {"fp-one", "fp-three"},
    )

    assert len(plan.to_remove) == 1
    removal = plan.to_remove[0]
    assert removal.action is SyncAction.REMOVE_FROM_IPOD
    assert removal.aggregate_kind == "chaptered_album"
    assert removal.aggregate_contains_fingerprints == ("fp-one", "fp-three")
    assert [track.title for track in removal.aggregate_rebuild_pc_tracks] == ["One", "Three"]
    assert plan.storage.bytes_to_remove == 0


def test_one_remaining_source_removes_aggregate_and_detaches_track(tmp_path) -> None:
    engine = _engine()
    first = _track(tmp_path / "one.mp3", title="One", track_number=1)
    second = _track(tmp_path / "two.mp3", title="Two", track_number=2)
    mapping = _mapping_with_aggregate(engine, {"fp-one": first, "fp-two": second})
    plan = SyncPlan()

    _represented, detached, _claimed = engine._plan_chaptered_aggregate_updates(
        plan,
        mapping,
        {"fp-one": [first]},
        {
            42: {
                "db_track_id": 42,
                "Title": "Album",
                "Location": ":iPod_Control:Music:F00:Album.m4a",
                "size": 999,
            }
        },
        {"fp-one"},
    )

    assert detached == {"fp-one"}
    assert len(plan.to_remove) == 1
    assert plan.to_remove[0].aggregate_rebuild_pc_tracks == ()
    assert plan.storage.bytes_to_remove == 999


def test_chapter_split_pairs_segments_to_aggregate_source_rows(tmp_path) -> None:
    engine = _engine()
    first = _track(tmp_path / "one.mp3", title="One", track_number=1)
    second = _track(tmp_path / "two.mp3", title="Two", track_number=2)
    mapping = _mapping_with_aggregate(engine, {"fp-one": first, "fp-two": second})
    aggregate_mapping = mapping.get_by_db_track_id(42)

    rows = ChapterSplitWorker._aggregate_source_rows_for_split(
        aggregate_mapping,
        segment_count=2,
    )

    assert [row["fingerprint"] for row in rows] == ["fp-one", "fp-two"]
    assert rows[0]["source_size"] == first.size
    assert rows[1]["source_mtime"] == second.mtime


def test_backpatch_split_track_uses_original_source_mapping_without_aggregate_fields(tmp_path) -> None:
    generated = _track(tmp_path / "generated.mp3", title="Generated", track_number=1)
    ipod_dest = tmp_path / "iPod_Control" / "Music" / "F00" / "Generated.mp3"
    ipod_dest.parent.mkdir(parents=True)
    ipod_dest.write_bytes(b"generated")
    track_info = TrackInfo(
        title="Generated",
        location=":iPod_Control:Music:F00:Generated.mp3",
        db_track_id=77,
    )
    add_item = SyncItem(
        action=SyncAction.ADD_TO_IPOD,
        fingerprint="fp-one",
        pc_track=generated,
        conversion_source_fingerprints=("should-not-be-contained",),
        mapping_source_metadata={
            "fingerprint": "fp-one",
            "source_path_hint": "Album/01 One.flac",
            "source_size": 12345,
            "source_mtime": 99.5,
            "source_hash": "source-hash",
        },
    )
    progress_stages: list[tuple[str, int, int]] = []
    ctx = _SyncContext(
        plan=SyncPlan(),
        mapping=MappingFile(),
        progress_callback=lambda progress: progress_stages.append(
            (progress.stage, progress.current, progress.total)
        ),
        dry_run=False,
        write_back_to_pc=False,
        _is_cancelled=None,
    )
    ctx.new_tracks.append(track_info)
    ctx.new_track_fingerprints[id(track_info)] = "fp-one"
    ctx.new_track_info[id(track_info)] = (generated, ipod_dest, False, add_item)

    SyncExecutor(tmp_path)._backpatch_new_tracks(ctx)

    entry = ctx.mapping.get_entries("fp-one")[0]
    assert entry.db_track_id == 77
    assert entry.source_format == "flac"
    assert entry.source_size == 12345
    assert entry.source_mtime == 99.5
    assert entry.source_path_hint == "Album/01 One.flac"
    assert entry.source_hash == "source-hash"
    assert entry.aggregate_kind is None
    assert entry.contains_fingerprints is None
    assert "containsFingerprints" not in entry.to_dict()
    assert progress_stages == [("backpatch", 0, 1), ("backpatch", 1, 1)]


def test_backpatch_split_track_does_not_use_generated_hash_for_original_source(tmp_path) -> None:
    generated = _track(tmp_path / "generated.mp3", title="Generated", track_number=1)
    ipod_dest = tmp_path / "iPod_Control" / "Music" / "F00" / "Generated.mp3"
    ipod_dest.parent.mkdir(parents=True)
    ipod_dest.write_bytes(b"generated")
    track_info = TrackInfo(
        title="Generated",
        location=":iPod_Control:Music:F00:Generated.mp3",
        db_track_id=78,
    )
    add_item = SyncItem(
        action=SyncAction.ADD_TO_IPOD,
        fingerprint="fp-one",
        pc_track=generated,
        mapping_source_metadata={
            "fingerprint": "fp-one",
            "source_path_hint": "Album/01 One.flac",
            "source_size": 12345,
            "source_mtime": 99.5,
        },
    )
    ctx = _SyncContext(
        plan=SyncPlan(),
        mapping=MappingFile(),
        progress_callback=None,
        dry_run=False,
        write_back_to_pc=False,
        _is_cancelled=None,
    )
    ctx.new_tracks.append(track_info)
    ctx.new_track_fingerprints[id(track_info)] = "fp-one"
    ctx.new_track_info[id(track_info)] = (generated, ipod_dest, False, add_item)

    SyncExecutor(tmp_path)._backpatch_new_tracks(ctx)

    entry = ctx.mapping.get_entries("fp-one")[0]
    assert entry.source_hash is None
