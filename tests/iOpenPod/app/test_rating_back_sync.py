"""Ratings return only to the paired Host file after a verified Sync."""

from __future__ import annotations

import base64
import io
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO, cast

import pytest
from mutagen.id3 import POPM, TIT2
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4FreeForm

from iOpenPod.app.media.ratings import rewrite_rating_stream
from iOpenPod.app.media.tags import read_tag_values
from storage.media_processing import find_media_tool

if TYPE_CHECKING:
    from collections.abc import Callable

    from iOpenPod.app.library_write import WriteProgress
    from storage.host_input import LocalHostFile

FIXTURES = Path(__file__).parents[2] / "fixtures" / "media"


def _load_media(stream: BinaryIO | Path, suffix: str) -> Any:
    factory: Any = MP3 if suffix == "mp3" else MP4
    return factory(stream)


@pytest.mark.parametrize("suffix", ["mp3", "m4a"])
def test_rating_round_trip_preserves_other_tags_and_payload(suffix: str) -> None:
    data = base64.b64decode((FIXTURES / f"tone.{suffix}.b64").read_bytes())
    stream = io.BytesIO(data)
    if suffix == "mp3":
        audio = _load_media(stream, suffix)
        if audio.tags is None:
            audio.add_tags()
        audio.tags.add(cast("Any", TIT2)(encoding=3, text=["Keep title"]))
        audio.tags.add(cast("Any", POPM)(email="existing", rating=64, count=17))
        audio.save(stream)
    else:
        audio = _load_media(stream, suffix)
        audio["©nam"] = ["Keep title"]
        audio["----:com.apple.iTunes:PRIVATE"] = [cast("Any", MP4FreeForm)(b"retain")]
        audio.save(stream)
    stream.seek(0)
    before = stream.getvalue()
    rewrite_rating_stream(stream, f"track.{suffix}", 80)
    stream.seek(0)
    checked = _load_media(stream, suffix)
    tags = {tag.name: tag.value for tag in read_tag_values(checked.tags)}
    assert tags["rating"] == "80"
    assert tags["title"] == "Keep title"
    if suffix == "mp3":
        assert checked.tags.getall("POPM")[0].count == 17
        assert (
            before[before.index(b"\xff\xfb") :]
            == stream.getvalue()[stream.getvalue().index(b"\xff\xfb") :]
        )
    else:
        assert checked.tags["----:com.apple.iTunes:PRIVATE"] == [b"retain"]

        def payload(data: bytes) -> bytes:
            start = data.index(b"mdat") - 4
            size = int.from_bytes(data[start : start + 4], "big")
            return data[start + 8 : start + size]

        assert payload(before) == payload(stream.getvalue())
    written = stream.getvalue()
    rewrite_rating_stream(stream, f"track.{suffix}", 80)
    assert stream.getvalue() == written


@pytest.mark.parametrize("rating", [-1, 21, 101])
def test_invalid_rating_is_rejected(rating: int) -> None:
    with pytest.raises(ValueError):
        rewrite_rating_stream(io.BytesIO(b"unchanged"), "track.mp3", rating)


@pytest.mark.parametrize(
    "host,ipod,baseline_host,baseline_ipod,expected",
    [
        (60, 60, 60, 60, False),
        (60, 80, 60, 60, True),
        (60, 20, 60, 60, True),
        (60, 0, 60, 60, True),
        (100, 80, 60, 60, False),
        (60, 80, None, None, False),
        (60, 80, 60, 80, False),
    ],
)
def test_rating_back_sync_requires_changed_known_baselines(
    host: int,
    ipod: int,
    baseline_host: int | None,
    baseline_ipod: int | None,
    expected: bool,
) -> None:
    from iOpenPod.app.back_sync import review_rating
    from iOpenPod.app.library_sync_helper import SyncDetails

    sync = SyncDetails(
        "2026-11-13",
        "track.mp3",
        1,
        1,
        "mp3",
        "mp3",
        False,
        host_rating=baseline_host,
        ipod_rating=baseline_ipod,
    )
    decision = review_rating(host, ipod, sync, "host")
    assert (decision is not None and decision.host_target is not None) is expected


@pytest.mark.skipif(
    any(find_media_tool(tool) is None for tool in ("ffmpeg", "ffprobe")),
    reason="Real Sync integration requires FFmpeg and FFprobe",
)
@pytest.mark.parametrize("suffix", ["mp3", "m4a"])
@pytest.mark.parametrize(
    "case",
    [
        "success",
        "partial_star",
        "excluded",
        "write_failure",
        "device_failure",
        "cancelled",
        "cancel_after_commit",
        "zero",
        "conflict",
        "legacy",
        "preview_helper",
        "corrupt_rating_state",
        "host_only",
        "conflict_ipod",
        "conflict_average",
        "same",
        "optout",
        "average_retry",
        "average_retry_without_helper",
        "average_retry_after_host_write",
        "same_facts",
        "unreadable",
    ],
)
def test_sync_writes_changed_rating_to_paired_host_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, suffix: str, case: str
) -> None:
    from dataclasses import replace
    from threading import Event

    from tests.iOpenPod.app.services.test_first_artwork_save import bare_device

    from iOpenPod.app import back_sync
    from iOpenPod.app.host_media_folders import create_host_media_folder
    from iOpenPod.app.host_media_library import HostMediaLibrary, HostMediaScanner
    from iOpenPod.app.library_sync_helper import (
        LIBRARY_SYNC_HELPER_PATH,
        RATING_SYNC_PATH,
        IPodMediaCacheStats,
        IPodMediaLibrary,
        _decode_helper,  # pyright: ignore[reportPrivateUsage]
        _encode_helper,  # pyright: ignore[reportPrivateUsage]
    )
    from iOpenPod.app.sync_execution import (
        SyncExecutionRequest,
        SyncExecutionStatus,
        SyncExecutor,
    )
    from iOpenPod.app.sync_plan import (
        SyncPlanAction,
        host_path_identity,
        prepare_sync_plan,
        select_sync_plan,
    )
    from storage import AtomicHostFile, DevicePath, FilesystemSession
    from storage.host_replacement import replace_host_file

    average_retry = case.startswith("average_retry")
    host_already_written = case == "average_retry_after_host_write"
    policy = (
        None
        if case == "optout"
        else "ipod"
        if case == "conflict_ipod"
        else "average"
        if case == "conflict_average" or average_retry
        else "host"
    )
    monkeypatch.setattr(
        "iOpenPod.app.host_media_fingerprint.FpcalcFingerprinter.fingerprint",
        lambda *args, **kwargs: "1,2,3",
    )
    folder = tmp_path / "host"
    folder.mkdir()
    path = folder / f"track.{suffix}"
    stream = io.BytesIO(
        base64.b64decode((FIXTURES / f"tone.{suffix}.b64").read_bytes())
    )
    rewrite_rating_stream(stream, path.name, 60)
    path.write_bytes(stream.getvalue())
    scanner = HostMediaScanner(AtomicHostFile(tmp_path / "cache.json"))

    def scan() -> HostMediaLibrary:
        pending = scanner.scan(
            (create_host_media_folder(folder),), checkpoint=lambda: None
        )
        return scanner.complete(pending, frozenset(), checkpoint=lambda: None)

    device = bare_device(tmp_path, model_number="M9802")
    try:
        active = device.active
        ipod = IPodMediaLibrary((), (), (), IPodMediaCacheStats(), None, False)
        host = scan()
        executor = SyncExecutor(device.coordinator)
        plan = select_sync_plan(
            prepare_sync_plan(
                host, ipod, active.library, rating_conflict_policy=policy
            ),
            selected_host_paths=frozenset({host_path_identity(str(path))}),
            selected_ipod_removals=frozenset(),
        )
        assert any(item.action is SyncPlanAction.ADD for item in plan.items)
        result = executor.execute(
            SyncExecutionRequest(
                plan,
                host,
                ipod,
                active,
                1,
                1,
            ),
            lambda _: None,
            Event(),
        )
        assert result.status is SyncExecutionStatus.SUCCESS, [
            (i.code, i.message, i.detail) for i in result.issues
        ]
        assert result.active is not None and result.helper is not None
        active, ipod = result.active, result.helper
        persisted = _decode_helper(
            (device.root / str(LIBRARY_SYNC_HELPER_PATH)).read_bytes()
        )
        assert not persisted.inline_ratings
        stored = next(
            record.sync for record in persisted.tracks if record.sync is not None
        )
        assert stored.host_rating is None and stored.ipod_rating is None
        ipod = device.coordinator.scan_ipod_media(active, lambda _: None, Event())
        baseline = next(
            record.sync for record in ipod.tracks if record.sync is not None
        )
        assert baseline.host_rating == 60 and baseline.ipod_rating == 60
        track = next(
            t for t in active.library.tracks if t.metadata.location.endswith(suffix)
        )
        assert track.rating == 60
        if case == "legacy":
            (device.root / str(RATING_SYNC_PATH)).unlink()
            ipod = device.coordinator.scan_ipod_media(active, lambda _: None, Event())
            assert (
                ipod.tracks[0].sync is not None
                and ipod.tracks[0].sync.host_rating is None
            )
        if case == "preview_helper":
            (device.root / str(RATING_SYNC_PATH)).unlink()
            (device.root / str(LIBRARY_SYNC_HELPER_PATH)).write_bytes(
                _encode_helper(
                    ipod.tracks,
                    ipod.images,
                    persisted.library_sha256,
                    updated_at=persisted.updated_at,
                    include_inline_ratings=True,
                )
            )
            ipod = device.coordinator.scan_ipod_media(active, lambda _: None, Event())
            assert (
                ipod.tracks[0].sync is not None
                and ipod.tracks[0].sync.host_rating == 60
            )
        if case == "corrupt_rating_state":
            (device.root / str(RATING_SYNC_PATH)).write_bytes(b"damaged")
            ipod = device.coordinator.scan_ipod_media(active, lambda _: None, Event())
            assert not ipod.ratings_available and ipod.tracks[0].sync is not None
        changed = replace(
            track, rating={"zero": 0, "host_only": 60, "partial_star": 75}.get(case, 80)
        )
        if case not in {"host_only", "unreadable"}:
            review = device.prepare(
                replace(
                    active.library,
                    tracks=tuple(
                        changed if t.track_id == track.track_id else t
                        for t in active.library.tracks
                    ),
                )
            )
            saved = device.coordinator.save_library(
                review, active, lambda _: None, Event()
            )
            assert saved.active is not None
            active = saved.active
        if average_retry or case in {
            "zero",
            "conflict",
            "host_only",
            "conflict_ipod",
            "conflict_average",
            "same",
            "optout",
            "cancel_after_commit",
        }:
            with path.open("r+b") as writable:
                if average_retry or case in {
                    "conflict",
                    "host_only",
                    "conflict_ipod",
                    "conflict_average",
                    "same",
                }:
                    rewrite_rating_stream(
                        writable,
                        path.name,
                        80
                        if case == "same"
                        else 20
                        if case == "conflict_average" or average_retry
                        else 100,
                    )
                writable.seek(0)
                tagged = _load_media(writable, suffix)
                if suffix == "mp3":
                    tagged.tags.add(
                        cast("Any", TIT2)(encoding=3, text=["Updated Host title"])
                    )
                else:
                    tagged["©nam"] = ["Updated Host title"]
                tagged.save(writable)
        host = scan()
        plan = select_sync_plan(
            prepare_sync_plan(
                host, ipod, active.library, rating_conflict_policy=policy
            ),
            selected_host_paths=frozenset({host_path_identity(str(path))}),
            selected_ipod_removals=frozenset(),
        )
        if case == "corrupt_rating_state":
            assert not plan.change_count
            assert (device.root / str(RATING_SYNC_PATH)).read_bytes() == b"damaged"
            return
        if case == "unreadable":
            host = replace(
                host,
                sources=tuple(
                    replace(source, metadata_complete=False) for source in host.sources
                ),
                snapshot=replace(
                    host.snapshot, tracks=(replace(host.snapshot.tracks[0], rating=0),)
                ),
            )
            assert not prepare_sync_plan(
                host, ipod, active.library, rating_conflict_policy=policy
            ).change_count
            return
        assert any(item.action is SyncPlanAction.UPDATE for item in plan.items)
        if case in {"conflict_average", "legacy", "partial_star"} or average_retry:
            decision = next(
                item.rating for item in plan.items if item.ipod_id == track.track_id
            )
            assert decision is not None
            if case == "legacy":
                assert (
                    decision.host_rating,
                    decision.ipod_target,
                    decision.host_target,
                ) == (60, 80, None)
            elif case == "partial_star":
                assert (decision.ipod_target, decision.host_target) == (75, 80)
            else:
                assert (decision.ipod_target, decision.host_target) == (60, 60)
        original = path.read_bytes()
        if case == "excluded":
            plan = replace(plan, items=())
        if case == "same_facts":

            def replace_at_same_mtime(
                observed: LocalHostFile,
                transform: Callable[[BinaryIO], object],
                *,
                checkpoint: Callable[[], None],
            ) -> LocalHostFile:
                def collide(staged: BinaryIO) -> None:
                    transform(staged)
                    staged.flush()
                    staged_path = next(path.parent.glob(f".{path.name}.*.tmp"))
                    assert staged_path.stat().st_size == observed.size_bytes
                    os.utime(
                        staged_path, ns=(observed.modified_ns, observed.modified_ns)
                    )

                updated = replace_host_file(observed, collide, checkpoint=checkpoint)
                assert updated.size_bytes == observed.size_bytes
                assert updated.modified_ns != observed.modified_ns
                return updated

            monkeypatch.setattr(back_sync, "replace_host_file", replace_at_same_mtime)
        if case == "write_failure" or (average_retry and not host_already_written):

            def fail_write(*args: object, **kwargs: object) -> None:
                raise OSError("Host file is read-only")

            monkeypatch.setattr("iOpenPod.app.back_sync.replace_host_file", fail_write)
        publish_sync_success = device.coordinator.publish_sync_success
        if case == "average_retry_without_helper":

            def fail_helper(*args: object, **kwargs: object) -> None:
                raise OSError("The Sync helper could not be published")

            monkeypatch.setattr(device.coordinator, "publish_sync_success", fail_helper)
        atomic_write = FilesystemSession.atomic_write
        if host_already_written:

            def fail_helper_write(
                session: FilesystemSession,
                target: DevicePath,
                data: bytes,
                **kwargs: Any,
            ) -> Any:
                if target == LIBRARY_SYNC_HELPER_PATH:
                    raise OSError("The Sync helper could not be published")
                return atomic_write(session, target, data, **kwargs)

            monkeypatch.setattr(FilesystemSession, "atomic_write", fail_helper_write)
        if case == "device_failure":

            def fail_save(*args: object, **kwargs: object) -> None:
                raise OSError("Device publication failed")

            monkeypatch.setattr(device.coordinator, "save_library", fail_save)
        cancelled = Event()
        if case == "cancelled":
            cancelled.set()

        def progress(value: WriteProgress) -> None:
            if case == "cancel_after_commit" and value.phase == "sync.helper":
                cancelled.set()

        result = executor.execute(
            SyncExecutionRequest(
                plan,
                host,
                ipod,
                active,
                1,
                1,
            ),
            progress,
            cancelled,
        )
        if average_retry:
            assert result.status is SyncExecutionStatus.PARTIAL, result.issues
            assert result.active is not None
            assert (result.helper is None) == (
                case == "average_retry_without_helper" or host_already_written
            )
            assert (
                next(
                    t.rating
                    for t in result.active.library.tracks
                    if t.track_id == track.track_id
                )
                == 60
            )
            if host_already_written:

                def unexpected_replacement(*args: object, **kwargs: object) -> None:
                    pytest.fail(
                        "Retry rewrote a Host file already at the reviewed target"
                    )

                monkeypatch.setattr(
                    back_sync, "replace_host_file", unexpected_replacement
                )
                monkeypatch.setattr(FilesystemSession, "atomic_write", atomic_write)
            else:
                monkeypatch.setattr(back_sync, "replace_host_file", replace_host_file)
            monkeypatch.setattr(
                device.coordinator, "publish_sync_success", publish_sync_success
            )
            retry_host = scan()
            retry_ipod = device.coordinator.scan_ipod_media(
                result.active, lambda _: None, Event()
            )
            baseline = next(
                record.sync for record in retry_ipod.tracks if record.sync is not None
            )
            assert baseline.pending_rating is not None
            retry_plan = select_sync_plan(
                prepare_sync_plan(
                    retry_host,
                    retry_ipod,
                    result.active.library,
                    rating_conflict_policy=policy,
                ),
                selected_host_paths=frozenset({host_path_identity(str(path))}),
                selected_ipod_removals=frozenset(),
            )
            retry = executor.execute(
                SyncExecutionRequest(
                    retry_plan,
                    retry_host,
                    retry_ipod,
                    result.active,
                    1,
                    1,
                ),
                lambda _: None,
                Event(),
            )
            assert retry.status is SyncExecutionStatus.SUCCESS, retry.issues
            assert retry.active is not None and retry.helper is not None
            baseline = next(
                record.sync for record in retry.helper.tracks if record.sync is not None
            )
            assert (
                baseline.host_rating,
                baseline.ipod_rating,
                baseline.pending_rating,
            ) == (60, 60, None)
            assert (
                next(
                    t.rating
                    for t in retry.active.library.tracks
                    if t.track_id == track.track_id
                )
                == 60
            )
            assert {
                tag.name: tag.value
                for tag in read_tag_values(_load_media(path, suffix).tags)
            }["rating"] == "60"
            return
        if case in {
            "excluded",
            "write_failure",
            "device_failure",
            "cancelled",
            "cancel_after_commit",
        }:
            assert path.read_bytes() == original
            assert (
                result.status
                is {
                    "excluded": SyncExecutionStatus.SUCCESS,
                    "write_failure": SyncExecutionStatus.PARTIAL,
                    "device_failure": SyncExecutionStatus.FAILED,
                    "cancelled": SyncExecutionStatus.CANCELLED,
                    "cancel_after_commit": SyncExecutionStatus.PARTIAL,
                }[case]
            ), result.issues
            if case in {"write_failure", "cancel_after_commit"}:
                assert result.active is not None and result.helper is not None
                retry_comparison = prepare_sync_plan(
                    scan(),
                    result.helper,
                    result.active.library,
                    rating_conflict_policy=policy,
                )
                assert any(
                    i.action is SyncPlanAction.UPDATE for i in retry_comparison.items
                )
            return
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None and result.helper is not None
        audio = _load_media(path, suffix)
        assert {tag.name: tag.value for tag in read_tag_values(audio.tags)}[
            "rating"
        ] == (
            "100"
            if case in {"conflict", "host_only"}
            else "0"
            if case == "zero"
            else "60"
            if case in {"legacy", "optout", "conflict_average"}
            else "80"
        )
        if case in {"legacy", "optout"}:
            assert path.read_bytes() == original
        if case == "legacy":
            seeded = next(
                record.sync
                for record in result.helper.tracks
                if record.sync is not None
            )
            assert (seeded.host_rating, seeded.ipod_rating) == (60, 80)
        if case == "preview_helper":
            upgraded = _decode_helper(
                (device.root / str(LIBRARY_SYNC_HELPER_PATH)).read_bytes()
            )
            assert not upgraded.inline_ratings
            assert (device.root / str(RATING_SYNC_PATH)).is_file()
        if case not in {"legacy", "optout"}:
            final_track = next(
                t for t in result.active.library.tracks if t.track_id == track.track_id
            )
            expected = (
                100
                if case in {"host_only", "conflict"}
                else 60
                if case == "conflict_average" or average_retry
                else 0
                if case == "zero"
                else 75
                if case == "partial_star"
                else 80
            )
            assert final_track.rating == expected
        after = path.read_bytes()
        scanner = HostMediaScanner(AtomicHostFile(tmp_path / "cache.json"))
        plan = prepare_sync_plan(
            scan(), result.helper, result.active.library, rating_conflict_policy=policy
        )
        if case != "optout":
            assert all(item.action is not SyncPlanAction.UPDATE for item in plan.items)
        assert path.read_bytes() == after
    finally:
        device.coordinator.close()


def test_v14_mp4_cache_refreshes_previously_unread_rating(tmp_path: Path) -> None:
    import hashlib
    import json

    from iOpenPod.app.host_media_folders import create_host_media_folder
    from iOpenPod.app.host_media_library import HostMediaScanner
    from storage import AtomicHostFile

    stream = io.BytesIO(base64.b64decode((FIXTURES / "tone.m4a.b64").read_bytes()))
    rewrite_rating_stream(stream, "track.m4a", 80)
    (tmp_path / "track.m4a").write_bytes(stream.getvalue())
    cache = AtomicHostFile(tmp_path / "cache.json")
    folder = create_host_media_folder(tmp_path)
    HostMediaScanner(cache).scan((folder,), checkpoint=lambda: None)
    document = json.loads(cache.path.read_bytes())
    document["version"] = 14
    # Simulate the genuine old reader's cached tag projection, with no RATING.
    document["entries"][0]["metadata"]["tag_values"] = [
        tag
        for tag in document["entries"][0]["metadata"]["tag_values"]
        if tag["name"] != "rating"
    ]
    document["catalog_sha256"] = hashlib.sha256(
        json.dumps(
            document["entries"],
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    cache.replace_bytes(json.dumps(document).encode())
    scanner = HostMediaScanner(cache)
    pending = scanner.scan((folder,), checkpoint=lambda: None)
    assert pending.cache.inspected == 1
    library = scanner.complete(pending, frozenset(), checkpoint=lambda: None)
    assert library.snapshot.tracks[0].rating == 80


@pytest.mark.parametrize("version", [3, 4])
def test_rating_edit_retains_id3_version(version: int) -> None:
    stream = io.BytesIO(base64.b64decode((FIXTURES / "tone.mp3.b64").read_bytes()))
    audio = _load_media(stream, "mp3")
    audio.save(stream, v2_version=version)
    rewrite_rating_stream(stream, "track.mp3", 80)
    stream.seek(0)
    assert _load_media(stream, "mp3").tags.version[:2] == (2, version)


def test_native_rating_is_rechecked_before_editing() -> None:
    stream = io.BytesIO(base64.b64decode((FIXTURES / "tone.m4a.b64").read_bytes()))
    rewrite_rating_stream(stream, "track.m4a", 60)
    original = stream.getvalue()
    with pytest.raises(ValueError, match="Host rating changed"):
        rewrite_rating_stream(stream, "track.m4a", 80, expected_rating=20)
    assert stream.getvalue() == original


@pytest.mark.parametrize("rating", [0, 20, 40, 60, 80, 100])
def test_flac_rating_round_trip_preserves_audio(rating: int) -> None:
    from mutagen.flac import FLAC

    stream = io.BytesIO(base64.b64decode((FIXTURES / "surround.flac.b64").read_bytes()))
    audio = cast("Any", FLAC)(stream)
    original_audio = audio.info.md5_signature
    rewrite_rating_stream(stream, "surround.flac", rating)
    stream.seek(0)
    checked = cast("Any", FLAC)(stream)
    assert checked.info.md5_signature == original_audio
    assert {t.name: t.value for t in read_tag_values(checked.tags)}.get(
        "rating", "0"
    ) == str(rating)


@pytest.mark.parametrize(
    "host,ipod,bh,bi,policy,expected",
    [
        (60, 80, None, None, "ipod", 80),
        (0, 60, 0, 60, "host", 60),
        (100, 60, 60, 60, "ipod", 100),
        (60, 0, 60, 60, "host", 0),
        (20, 80, 60, 60, "host", 20),
        (20, 80, 60, 60, "ipod", 80),
        (20, 80, 60, 60, "average", 60),
        (80, 80, 60, 60, "average", 80),
    ],
)
def test_rating_resolution(
    host: int, ipod: int, bh: int | None, bi: int | None, policy: str, expected: int
) -> None:
    from iOpenPod.app.back_sync import resolved_rating

    assert resolved_rating(host, ipod, bh, bi, policy) == expected


@pytest.mark.parametrize(
    "suffix,codec",
    [("ogg", "vorbis"), ("oga", "vorbis"), ("opus", "libopus"), ("ogg", "libopus")],
)
def test_ogg_rating_transform_round_trip(suffix: str, codec: str) -> None:
    import shutil
    import subprocess

    if shutil.which("ffmpeg") is None:
        pytest.skip("FFmpeg is needed to author the Ogg fixture")
    source = base64.b64decode((FIXTURES / "surround.flac.b64").read_bytes())
    encoded = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            "pipe:0",
            "-ac",
            "2",
            "-c:a",
            codec,
            "-strict",
            "experimental",
            "-f",
            "ogg",
            "pipe:1",
        ],
        input=source,
        capture_output=True,
        check=True,
    ).stdout
    stream = io.BytesIO(encoded)
    rewrite_rating_stream(stream, f"track.{suffix}", 80)
    rewrite_rating_stream(stream, f"track.{suffix}", 0, expected_rating=80)
    from mutagen.oggopus import OggOpus
    from mutagen.oggvorbis import OggVorbis

    stream.seek(0)
    factory: Any = OggVorbis if codec == "vorbis" else OggOpus
    assert {t.name: t.value for t in read_tag_values(factory(stream).tags)}[
        "rating"
    ] == "0"
