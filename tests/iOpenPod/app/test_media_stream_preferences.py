"""Durable choices and successful preparation receipts have separate lifetimes."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iOpenPod.app.test_media_stream_selection import (
    multiple_streams as multiple_streams,
)
from tests.iOpenPod.app.test_sync_execution import (
    _request,  # pyright: ignore[reportPrivateUsage]
)
from tests.iOpenPod.app.test_sync_stream_selection import host_library
from tests.iOpenPod.app.test_video_preparation import (
    _FFmpeg,  # pyright: ignore[reportPrivateUsage]
)
from tests.iOpenPod.app.test_video_preparation import captioned_video as captioned_video
from tests.iOpenPod.app.test_video_preparation import ffmpeg as ffmpeg
from tests.iOpenPod.app.test_video_preparation import video as video

from iOpenPod.app import media_stream_preferences as preferences_module
from iOpenPod.app.host_media_library import HostMediaFileKind
from iOpenPod.app.media import MediaInspector
from iOpenPod.app.media.models import StreamKind
from iOpenPod.app.media.stream_selection import MediaStreamSelection, is_caption
from iOpenPod.app.media.stream_selection_codec import (
    selection_digest,
    selection_document,
    selection_from_document,
)
from iOpenPod.app.media_stream_preferences import MediaStreamPreferences
from iOpenPod.app.models.sync_selection import SyncSelection
from iOpenPod.app.sync_execution import (
    SyncExecutionStatus,
    SyncExecutor,
    _validate_plan,  # pyright: ignore[reportPrivateUsage]
)
from iOpenPod.app.sync_plan import (
    SyncPlan,
    SyncPlanAction,
    SyncPlanBasis,
    SyncPlanItem,
    SyncPlanMediaKind,
    prepare_sync_plan,
    with_stream_selection,
)
from iPodDB.library import MediaType
from storage import AtomicHostFile, HostPath


@pytest.mark.parametrize("codec", ("ass", "subrip", "webvtt", "mov_text"))
@pytest.mark.parametrize("previous_revision", (None, 1))
def test_saved_text_conversion_requests_compatibility_repair_only_once(
    multiple_streams: Path, codec: str, previous_revision: int | None
) -> None:
    observed = MediaInspector().scan_metadata(
        HostPath(multiple_streams), checkpoint=lambda: None
    )
    subtitle = next(
        s
        for s in observed.streams
        if s.kind is StreamKind.SUBTITLE and not is_caption(s)
    )
    choice = MediaStreamSelection(
        observed.video_streams[0],
        observed.audio_streams[0],
        (replace(subtitle, codec=codec),),
    )
    # Both pre-layout receipts and layout-only receipts need the movie-clock fix.
    document = selection_document(choice)
    if codec != "mov_text" and previous_revision is not None:
        document["text_subtitle_layout"] = previous_revision
    old_receipt = hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    original = SyncPlanItem(
        SyncPlanAction.UNCHANGED,
        SyncPlanMediaKind.TRACK,
        SyncPlanBasis.HOST_FACTS_MATCH,
        "Episode",
        host_path=str(multiple_streams),
        ipod_id=7,
        ipod_path="iPod_Control/Music/F00/AAAA.m4v",
        applied_stream_selection_sha256=old_receipt,
    )
    planned = with_stream_selection(original, choice)
    assert planned.action is (
        SyncPlanAction.UNCHANGED if codec == "mov_text" else SyncPlanAction.UPDATE
    )
    assert planned.audio_payload_changed is (codec != "mov_text")
    repaired = replace(
        original, applied_stream_selection_sha256=selection_digest(choice)
    )
    assert with_stream_selection(repaired, choice).action is SyncPlanAction.UNCHANGED


def test_subtitle_compatibility_revision_preserves_other_receipts(
    multiple_streams: Path,
) -> None:
    observed = MediaInspector().scan_metadata(
        HostPath(multiple_streams), checkpoint=lambda: None
    )
    video, audio = observed.video_streams[0], observed.audio_streams[0]
    native_text = tuple(
        s
        for s in observed.streams
        if s.kind is StreamKind.SUBTITLE and not is_caption(s)
    )
    captions = tuple(s for s in observed.streams if is_caption(s))
    assert selection_digest(None) is None
    for choice in (
        MediaStreamSelection(None, audio),
        MediaStreamSelection(video, audio),
        MediaStreamSelection(video, audio, native_text, captions),
    ):
        document = selection_document(choice)
        assert document["version"] == 1 and "text_subtitle_layout" not in document
        assert set(document) == {"version", "video", "audio", "subtitles", "captions"}
        previous = hashlib.sha256(
            json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        assert selection_digest(choice) == previous


@pytest.mark.parametrize("with_alternate", (False, True))
def test_all_four_stream_kinds_round_trip_without_losing_facts(
    tmp_path: Path, multiple_streams: Path, with_alternate: bool
) -> None:
    metadata = MediaInspector().scan_metadata(
        HostPath(multiple_streams), checkpoint=lambda: None
    )
    subtitles = tuple(s for s in metadata.streams if s.kind is StreamKind.SUBTITLE)
    choice = MediaStreamSelection(
        metadata.video_streams[1],
        metadata.audio_streams[1],
        tuple(s for s in subtitles if not is_caption(s)),
        tuple(s for s in subtitles if is_caption(s)),
        metadata.audio_streams[0] if with_alternate else None,
    )
    file = AtomicHostFile(tmp_path / "choices.json")
    MediaStreamPreferences(file).set(str(multiple_streams), choice)
    (restored,) = MediaStreamPreferences(file).load().values()
    assert restored == choice
    assert (
        restored.video is not None
        and restored.audio is not None
        and restored.subtitles
        and restored.captions
    )
    assert selection_digest(restored) == selection_digest(choice)
    assert selection_document(restored)["version"] == (2 if with_alternate else 1)


@pytest.mark.parametrize(
    "invalid",
    (
        "unknown_version",
        "boolean_version",
        "float_version",
        "v1_with_alternate",
        "missing_alternate",
        "null_alternate",
        "wrong_kind",
        "duplicate_audio",
        "no_video",
        "no_primary",
        "extra_field",
    ),
)
def test_saved_alternate_audio_rejects_invalid_versions_and_choices(
    multiple_streams: Path, invalid: str
) -> None:
    metadata = MediaInspector().scan_metadata(
        HostPath(multiple_streams), checkpoint=lambda: None
    )
    choice = MediaStreamSelection(
        metadata.video_streams[0],
        metadata.audio_streams[0],
        alternate_audio=metadata.audio_streams[1],
    )
    # JSON reproduces the durable array representation for immutable stream facts.
    document = json.loads(json.dumps(selection_document(choice)))
    if invalid == "missing_alternate":
        del document["alternate_audio"]
    elif invalid == "null_alternate":
        document["alternate_audio"] = None
    elif invalid == "wrong_kind":
        document["alternate_audio"] = document["video"]
    elif invalid == "duplicate_audio":
        document["alternate_audio"] = document["audio"]
    elif invalid == "no_video":
        document["video"] = None
    elif invalid == "no_primary":
        document["audio"] = None
    elif invalid == "extra_field":
        document["unexpected"] = None
    else:
        document["version"] = {
            "unknown_version": 3,
            "boolean_version": True,
            "float_version": 2.0,
            "v1_with_alternate": 1,
        }[invalid]
    with pytest.raises(ValueError):
        selection_from_document(document)


def test_adding_or_changing_alternate_audio_changes_the_receipt(
    multiple_streams: Path,
) -> None:
    metadata = MediaInspector().scan_metadata(
        HostPath(multiple_streams), checkpoint=lambda: None
    )
    primary, alternate = metadata.audio_streams
    old = MediaStreamSelection(metadata.video_streams[0], primary)
    chosen = replace(old, alternate_audio=alternate)
    swapped = replace(chosen, audio=alternate, alternate_audio=primary)
    assert (
        len(
            {selection_digest(old), selection_digest(chosen), selection_digest(swapped)}
        )
        == 3
    )
    assert selection_digest(replace(chosen, alternate_audio=None)) == selection_digest(
        old
    )


def test_preferences_survive_restart_clear_and_missing_sources(
    tmp_path: Path, video: Path
) -> None:
    file = AtomicHostFile(tmp_path / "choices.json")
    host = host_library(video)
    metadata = MediaInspector().scan_metadata(HostPath(video), checkpoint=lambda: None)
    choice = MediaStreamSelection(metadata.video_streams[0], None)
    first = SyncSelection(stream_preferences=MediaStreamPreferences(file))
    first.reset(host, SyncPlan(()))
    first.set_stream_selection(100, choice)
    first.clear()
    second = SyncSelection(stream_preferences=MediaStreamPreferences(file))
    second.reset(
        replace(host, snapshot=replace(host.snapshot, tracks=()), sources=()),
        SyncPlan(()),
    )
    second.reset(host, SyncPlan(()))
    assert second.stream_selection(100) == choice
    second.set_stream_selection(100, None)
    assert MediaStreamPreferences(file).load() == {}


def test_failed_save_preserves_durable_and_staged_choices(
    tmp_path: Path, video: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = AtomicHostFile(tmp_path / "choices.json")
    observed = MediaInspector().scan_metadata(HostPath(video), checkpoint=lambda: None)
    choice = MediaStreamSelection(observed.video_streams[0], None)
    model = SyncSelection(stream_preferences=MediaStreamPreferences(file))
    model.reset(host_library(video), SyncPlan(()))
    model.set_stream_selection(100, choice)
    previous = file.read_bytes()

    def fail(_self: AtomicHostFile, _data: bytes) -> None:
        raise OSError("Disk full")

    monkeypatch.setattr(AtomicHostFile, "replace_bytes", fail)
    with pytest.raises(OSError, match="Disk full"):
        model.set_stream_selection(100, None)
    assert model.stream_selection(100) == choice
    assert file.read_bytes() == previous


def test_oversized_save_keeps_the_previous_readable_preferences(
    tmp_path: Path, video: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = AtomicHostFile(tmp_path / "choices.json")
    metadata = MediaInspector().scan_metadata(HostPath(video), checkpoint=lambda: None)
    silent = MediaStreamSelection(metadata.video_streams[0], None)
    audible = MediaStreamSelection(metadata.video_streams[0], metadata.audio_streams[0])
    store = MediaStreamPreferences(file)
    store.set(str(video), silent)
    previous = file.read_bytes()
    assert previous is not None
    monkeypatch.setattr(preferences_module, "_MAX_FILE_BYTES", len(previous) + 20)
    with pytest.raises(ValueError, match="supported size"):
        store.set(str(video), audible)
    assert file.read_bytes() == previous
    assert tuple(store.load().values()) == (silent,)


@pytest.mark.parametrize(
    "payload",
    [
        b"invalid",
        b'{"version":2,"choices":{}}',
        b'{"version":1,"choices":{"C:/movie.mp4":{}}}',
    ],
)
def test_corrupt_preferences_are_preserved(
    tmp_path: Path, video: Path, payload: bytes
) -> None:
    file = AtomicHostFile(tmp_path / "choices.json")
    file.replace_bytes(payload)
    store = MediaStreamPreferences(file)
    model = SyncSelection(stream_preferences=store)
    model.reset(host_library(video), SyncPlan(()))
    assert model.preference_error
    with pytest.raises(ValueError):
        store.set(str(video), None)
    assert file.read_bytes() == payload


@pytest.mark.parametrize(
    ("media_type", "text_subtitles"),
    [
        (MediaType.VIDEO, False),
        (MediaType.TV_SHOW, False),
        (MediaType.MUSIC_VIDEO, False),
        (MediaType.VIDEO_PODCAST, False),
        (MediaType.AUDIO_VIDEO, False),
        (MediaType.VIDEO, True),
    ],
)
def test_video_choice_sync_rescan_restart_and_restore_automatic(
    tmp_path: Path,
    video: Path,
    ffmpeg: _FFmpeg,
    media_type: MediaType,
    text_subtitles: bool,
) -> None:
    if text_subtitles:
        text = tmp_path / "dialogue.srt"
        text.write_text(
            "1\n00:00:00,400 --> 00:00:02,800\nRetain this subtitle choice.\n",
            encoding="utf-8",
        )
        source = tmp_path / "subtitled.mkv"
        ffmpeg(
            "-i",
            str(video),
            "-i",
            str(text),
            "-map",
            "0",
            "-map",
            "1:s",
            "-c",
            "copy",
            str(source),
        )
        video = source
    host = host_library(video)
    host = replace(
        host,
        snapshot=replace(
            host.snapshot,
            tracks=(replace(host.snapshot.tracks[0], media_types=(media_type,)),),
        ),
        sources=(replace(host.sources[0], kind=HostMediaFileKind.VIDEO),),
    )
    observed = MediaInspector().scan_metadata(HostPath(video), checkpoint=lambda: None)
    choice = MediaStreamSelection(
        observed.video_streams[0],
        None,
        tuple(s for s in observed.streams if s.kind is StreamKind.SUBTITLE),
    )
    file = AtomicHostFile(tmp_path / "choices.json")
    model = SyncSelection(stream_preferences=MediaStreamPreferences(file))
    device = build_device(tmp_path)
    try:
        request = _request(device, host)
        model.reset(host, request.plan)
        model.set_stream_selection(100, choice)
        model.set_tracks_checked((100,), True)
        request = replace(request, plan=model.selected_plan)
        result = SyncExecutor(device.coordinator).execute(
            request, lambda _: None, Event()
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None and result.helper is not None
        receipt = next(
            entry
            for entry in result.helper.tracks
            if entry.sync and entry.sync.host_path_hint == str(video)
        )
        assert (
            receipt.sync is not None
            and receipt.sync.stream_selection_sha256 == selection_digest(choice)
        )
        output = MediaInspector().scan_metadata(
            HostPath(device.root / str(receipt.path)), checkpoint=lambda: None
        )
        assert output.video_streams and not output.audio_streams
        assert any(s.codec_tag == "tx3g" for s in output.streams) is text_subtitles
        restarted = SyncSelection(stream_preferences=MediaStreamPreferences(file))
        comparison = prepare_sync_plan(host, result.helper, result.active.library)
        restarted.reset(host, comparison)
        (retained,) = restarted.selected_plan.items
        assert retained.action is SyncPlanAction.UNCHANGED
        assert retained.stream_selection == choice
        restarted.set_tracks_checked((100,), False)
        assert restarted.selected_plan.items[0].action is SyncPlanAction.REMOVE
        _validate_plan(
            replace(
                request,
                source=result.active,
                ipod=result.helper,
                plan=restarted.selected_plan,
            )
        )
        restarted.set_tracks_checked((100,), True)
        _validate_plan(
            replace(
                request,
                source=result.active,
                ipod=result.helper,
                plan=restarted.selected_plan,
            )
        )
        if media_type is MediaType.VIDEO:
            # Updating metadata must retain the selected silent media and its receipt.
            host = replace(
                host,
                snapshot=replace(
                    host.snapshot,
                    tracks=(replace(host.snapshot.tracks[0], title="Retitled movie"),),
                ),
            )
            restarted.reset(
                host, prepare_sync_plan(host, result.helper, result.active.library)
            )
            (tags,) = restarted.selected_plan.items
            assert tags.metadata_changed and not tags.audio_payload_changed
            request = replace(
                request,
                host=host,
                source=result.active,
                ipod=result.helper,
                plan=restarted.selected_plan,
            )
            result = SyncExecutor(device.coordinator).execute(
                request, lambda _: None, Event()
            )
            assert result.status is SyncExecutionStatus.SUCCESS, result.issues
            assert result.active is not None and result.helper is not None
            tagged = next(
                entry
                for entry in result.helper.tracks
                if entry.track_id == receipt.track_id
            )
            assert tagged.path == receipt.path
            assert (
                tagged.sync is not None
                and tagged.sync.stream_selection_sha256 == selection_digest(choice)
            )
            restarted.reset(
                host, prepare_sync_plan(host, result.helper, result.active.library)
            )
            assert restarted.selected_plan.change_count == 0
        restarted.set_stream_selection(100, None)
        (automatic,) = restarted.selected_plan.items
        assert (
            automatic.action is SyncPlanAction.UPDATE
            and automatic.stream_selection_changed
        )
        assert result.active is not None and result.helper is not None
        reset_request = replace(
            request,
            source=result.active,
            ipod=result.helper,
            plan=restarted.selected_plan,
        )
        restored = SyncExecutor(device.coordinator).execute(
            reset_request, lambda _: None, Event()
        )
        assert restored.status is SyncExecutionStatus.SUCCESS, restored.issues
        assert restored.active is not None and restored.helper is not None
        new_receipt = next(
            entry
            for entry in restored.helper.tracks
            if entry.track_id == receipt.track_id
        )
        assert (
            new_receipt.sync is not None
            and new_receipt.sync.stream_selection_sha256 is None
        )
        output = MediaInspector().scan_metadata(
            HostPath(device.root / str(new_receipt.path)), checkpoint=lambda: None
        )
        assert output.video_streams and output.audio_streams
        restarted.reset(
            host, prepare_sync_plan(host, restored.helper, restored.active.library)
        )
        assert restarted.selected_plan.change_count == 0
        assert json.loads(file.read_bytes() or b"{}")["choices"] == {}
    finally:
        device.coordinator.close()
