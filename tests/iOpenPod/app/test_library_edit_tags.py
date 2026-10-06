"""Ordinary Library saves keep Rockbox file tags in step with reviewed edits."""

import io
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal

import pytest
from mutagen.mp4 import MP4
from PIL import Image
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iOpenPod.app.test_library_write_controller import manual_settings, wait_for
from tests.iOpenPod.app.test_media_lyrics import fixture, media_payload
from tests.iPodDB.library.test_write_artwork import BLUE, RED
from tests.iPodDB.library.test_writing import library

from iOpenPod.app.core.settings.definitions import (
    DRAFT_ALL_CHANGES,
    ROCKBOX_METADATA_SUPPORT,
)
from iOpenPod.app.device_controller import DeviceController
from iOpenPod.app.export_tagging import ExportMediaTagger
from iOpenPod.app.library_workspace import (
    LibraryWorkspace,
    TrackArtworkEdit,
    TrackUpdate,
)
from iOpenPod.app.library_write_controller import (
    LibraryWriteController,
    PreparationState,
)
from iOpenPod.app.models.track_table_model import TrackTableModel
from iPodDB.library import TrackFieldEdit


@pytest.mark.parametrize("rockbox", [False, True])
@pytest.mark.parametrize("automatic", [False, True])
@pytest.mark.parametrize("model", ["MB565", "M9802"])
@pytest.mark.parametrize(
    "change", ["metadata", "replace", "remove", "lyrics", "combined"]
)
def test_edits_update_retained_file_tags(
    tmp_path: Path,
    rockbox: bool,
    automatic: bool,
    model: str,
    change: Literal["metadata", "replace", "remove", "lyrics", "combined"],
) -> None:
    original = ExportMediaTagger().prepare_bytes(
        fixture("tone.m4a"), "tone.m4a", library().snapshot.tracks[0], RED.pixels
    )
    device = build_device(tmp_path, media_payload=original, model=model)
    settings = manual_settings()
    settings.set_global(ROCKBOX_METADATA_SUPPORT, rockbox)
    settings.set_global(DRAFT_ALL_CHANGES, not automatic)
    devices = DeviceController(device.coordinator, TrackTableModel(), settings)
    workspace = LibraryWorkspace()
    workspace.load(device.active.library)
    controller = LibraryWriteController(
        device.coordinator, workspace, devices, settings
    )
    first = workspace.tracks[0]
    path = device.root / first.metadata.location
    before = path.read_bytes()
    other = device.root / workspace.tracks[1].metadata.location
    other_before = other.read_bytes()
    original_artwork = {
        p.name: p.read_bytes() for p in (device.root / "iPod_Control/Artwork").iterdir()
    }
    reader: Any = MP4
    prior: Any = reader(io.BytesIO(before))
    try:
        fields: list[TrackFieldEdit] = []
        if change in ("metadata", "combined"):
            fields.append(TrackFieldEdit("title", "Edited in iOpenPod"))
        if change in ("lyrics", "combined"):
            fields.append(TrackFieldEdit("metadata.lyrics", "Edited lyrics"))
        artwork = (
            TrackArtworkEdit(BLUE.pixels)
            if change in ("replace", "combined")
            else TrackArtworkEdit(None)
            if change == "remove"
            else None
        )
        workspace.apply_track_edits(
            (TrackUpdate(first.track_id, tuple(fields)),),
            workspace.edit_revision,
            artwork=artwork,
        )
        if automatic:
            wait_for(
                lambda: (
                    controller.state
                    in (
                        PreparationState.SAVED,
                        PreparationState.FAILED,
                        PreparationState.BLOCKED,
                    )
                )
            )
        else:
            controller.prepare()
            wait_for(lambda: controller.state is not PreparationState.PREPARING)
            assert controller.review is not None
            assert controller.can_save, controller.review.result.issues
            assert path.read_bytes() == before
            controller.save()
            wait_for(lambda: controller.state is not PreparationState.SAVING)
        assert controller.state is PreparationState.SAVED, controller.save_result
        tagged: Any = reader(io.BytesIO(path.read_bytes()))
        assert tagged["\u00a9nam"] == (
            ["Edited in iOpenPod"]
            if rockbox and change in ("metadata", "combined")
            else prior["\u00a9nam"]
        )
        if change in ("lyrics", "combined"):
            assert tagged["\u00a9lyr"] == ["Edited lyrics"]
        if rockbox and change in ("replace", "combined"):
            with Image.open(io.BytesIO(tagged["covr"][0])) as image:
                assert image.size == ((120, 120) if model == "M9802" else (4, 4))
                assert image.mode == ("L" if model == "M9802" else "RGB")
            assert list((device.root / "iPod_Control/Artwork").glob("*.ithmb"))
        elif rockbox and change == "remove":
            assert "covr" not in tagged
        else:
            assert tagged["covr"] == prior["covr"]
        if change in ("metadata", "lyrics"):
            assert original_artwork == {
                p.name: p.read_bytes()
                for p in (device.root / "iPod_Control/Artwork").iterdir()
            }
        assert media_payload(path.read_bytes(), ".m4a") == media_payload(before, ".m4a")
        assert other.read_bytes() == other_before
        assert device.active.library.tracks[0].size_bytes == path.stat().st_size
        if not rockbox and change not in ("lyrics", "combined"):
            assert path.read_bytes() == before
    finally:
        controller.shutdown()
        devices.shutdown()


@pytest.mark.parametrize("model", ["MB565", "M9802"])
@pytest.mark.parametrize("stale_cover", [False, True])
def test_reusing_library_artwork_embeds_verified_thumbnail(
    tmp_path: Path, model: str, stale_cover: bool
) -> None:
    device = build_device(tmp_path, media_payload=fixture("tone.m4a"), model=model)
    first, second = device.active.library.tracks
    initial = device.prepare(
        replace(
            device.active.library,
            tracks=(replace(first, artwork_id=BLUE.artwork_id), second),
        ),
        cover=True,
    )
    assert device.save(initial).active is not None
    settings = manual_settings()
    settings.set_global(ROCKBOX_METADATA_SUPPORT, True)
    devices = DeviceController(device.coordinator, TrackTableModel(), settings)
    workspace = LibraryWorkspace()
    workspace.load(device.active.library)
    controller = LibraryWriteController(
        device.coordinator, workspace, devices, settings
    )
    first, second = workspace.tracks
    path = device.root / second.metadata.location
    original = path.read_bytes()
    database = device.root / "iPod_Control/iTunes/iTunesDB"
    original_database = database.read_bytes()
    try:
        workspace.apply_track_edits(
            tuple(TrackUpdate(t.track_id, ()) for t in workspace.tracks),
            workspace.edit_revision,
            artwork=TrackArtworkEdit(None, source_artwork_id=first.artwork_id),
        )
        controller.prepare()
        wait_for(lambda: controller.state is not PreparationState.PREPARING)
        assert controller.review is not None
        assert controller.can_save, controller.review.result.issues
        assert controller.review.plan is not None
        assert controller.review.plan.required_lyrics == (second.track_id,)
        if stale_cover:
            for thumbnail in (device.root / "iPod_Control/Artwork").glob("*.ithmb"):
                thumbnail.write_bytes(thumbnail.read_bytes() + b"external edit")
        controller.save()
        wait_for(lambda: controller.state is not PreparationState.SAVING)
        if stale_cover:
            assert controller.state is PreparationState.SAVE_FAILED
            assert path.read_bytes() == original
            assert database.read_bytes() == original_database
        else:
            assert controller.state is PreparationState.SAVED, controller.save_result
            reader: Any = MP4
            tagged: Any = reader(io.BytesIO(path.read_bytes()))
            with Image.open(io.BytesIO(tagged["covr"][0])) as cover:
                assert cover.size == ((120, 120) if model == "M9802" else (320, 320))
                assert cover.mode == ("L" if model == "M9802" else "RGB")
                if model == "M9802":
                    assert max(cover.tobytes()) < 40
                else:
                    assert min(cover.tobytes()[2::3]) > 240
            assert media_payload(path.read_bytes(), ".m4a") == media_payload(
                original, ".m4a"
            )
    finally:
        controller.shutdown()
        devices.shutdown()


@pytest.mark.parametrize("enabled", [False, True])
def test_rockbox_preference_change_retires_prepared_edit(
    tmp_path: Path, enabled: bool
) -> None:
    device = build_device(tmp_path, media_payload=fixture("tone.m4a"))
    settings = manual_settings()
    settings.set_global(ROCKBOX_METADATA_SUPPORT, not enabled)
    devices = DeviceController(device.coordinator, TrackTableModel(), settings)
    workspace = LibraryWorkspace()
    workspace.load(device.active.library)
    controller = LibraryWriteController(
        device.coordinator, workspace, devices, settings
    )
    first = workspace.tracks[0]
    try:
        workspace.apply_track_edits(
            (TrackUpdate(first.track_id, (TrackFieldEdit("title", "Edited"),)),),
            workspace.edit_revision,
        )
        controller.prepare()
        wait_for(lambda: controller.state is PreparationState.READY)
        settings.set_global(ROCKBOX_METADATA_SUPPORT, enabled)
        assert controller.state is PreparationState.STALE
        assert not controller.can_save and controller.can_prepare
        controller.prepare()
        wait_for(lambda: controller.state is PreparationState.READY)
        controller.save()
        wait_for(lambda: controller.state is not PreparationState.SAVING)
        assert controller.save_result is not None
        assert controller.save_result.active is not None, controller.save_result.issues
        reader: Any = MP4
        tagged: Any = reader(str(device.root / first.metadata.location))
        assert tagged["\u00a9nam"] == (["Edited"] if enabled else ["Inspection tone"])
    finally:
        controller.shutdown()
        devices.shutdown()


def test_unwritable_rockbox_tags_block_database_only_save(tmp_path: Path) -> None:
    device = build_device(tmp_path, media_payload=b"invalid media")
    settings = manual_settings()
    settings.set_global(ROCKBOX_METADATA_SUPPORT, True)
    devices = DeviceController(device.coordinator, TrackTableModel(), settings)
    workspace = LibraryWorkspace()
    workspace.load(device.active.library)
    controller = LibraryWriteController(
        device.coordinator, workspace, devices, settings
    )
    first = workspace.tracks[0]
    try:
        workspace.apply_track_edits(
            (TrackUpdate(first.track_id, (TrackFieldEdit("title", "Edited"),)),),
            workspace.edit_revision,
        )
        controller.prepare()
        wait_for(lambda: controller.state is not PreparationState.PREPARING)
        assert controller.state is PreparationState.BLOCKED
        assert not controller.can_save
        assert controller.review is not None
        assert any(
            first.metadata.location in issue.detail
            for issue in controller.review.result.issues
        )
        device.assert_original()
    finally:
        controller.shutdown()
        devices.shutdown()
