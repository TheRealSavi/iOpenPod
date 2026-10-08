"""Retained Photo shard eligibility uses all raw names and allocation ranges."""

from pathlib import Path

import pytest
from tests.iOpenPod.app.media.test_photo_sync import (
    _asset,  # pyright: ignore[reportPrivateUsage]
)
from tests.iOpenPod.app.services.test_library_resources import build_device

from iOpenPod.app.services.photo_shard_resources import capture_and_pack
from iPodDB.library import RetainedArtworkFile, read_content
from storage import DevicePath, FileFingerprint, FilesystemSession
from storage.content_workspace import ContentWorkspace, StagedContent, content_workspace


@pytest.mark.parametrize(
    "case", ["truncated-alias", "overlap", "zero-range", "duplicate"]
)
def test_all_retained_allocation_evidence_controls_prefix_eligibility(
    tmp_path: Path, case: str
) -> None:
    device = build_device(tmp_path)
    try:
        path = device.root / "Photos/Thumbs/F1024_1.ithmb"
        path.parent.mkdir(parents=True)
        prefix = bytes(128)
        path.write_bytes(prefix)
        second_range = {
            "truncated-alias": (64, 128),
            "overlap": (32, 64),
            "zero-range": (0, 0),
            "duplicate": (0, 64),
        }[case]
        retained = (
            RetainedArtworkFile("Photos/Thumbs/F1024_1.ithmb", ((0, 64),)),
            RetainedArtworkFile("photos/thumbs/f1024_1.ITHMB", (second_range,)),
        )
        with (
            device.coordinator.sync_session(device.active) as session,
            content_workspace(memory_budget=0, checkpoint=lambda: None) as workspace,
        ):
            result = capture_and_pack(
                session,
                (_asset(),),
                retained,
                None,
                workspace,
                lambda: None,
                max_file_bytes=256,
            )[0]
            thumbnail = result.photo.representations[1]
            if case == "duplicate":
                assert thumbnail.relative_path.endswith("F1024_1.ithmb")
                assert thumbnail.offset == len(prefix)
                assert read_content(result.files[1].data, 0, len(prefix)) == prefix
            else:
                assert thumbnail.relative_path.endswith("F1024_2.ithmb")
                assert thumbnail.offset == 0
                assert not result.file_prefixes
        assert path.read_bytes() == prefix
    finally:
        device.coordinator.close()


def test_only_last_eligible_partial_shard_is_captured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = build_device(tmp_path)
    try:
        thumbnails = device.root / "Photos/Thumbs"
        thumbnails.mkdir(parents=True)
        retained = tuple(
            RetainedArtworkFile(f"Photos/Thumbs/F1024_{number}.ithmb", ((0, 64),))
            for number in (1, 2)
        )
        for file in retained:
            (device.root / file.file_name).write_bytes(bytes(64))
        captured: list[str] = []
        original = ContentWorkspace.capture_device_snapshot

        def capture(
            workspace: ContentWorkspace, session: FilesystemSession, path: DevicePath
        ) -> tuple[bytes | StagedContent, FileFingerprint]:
            captured.append(str(path))
            return original(workspace, session, path)

        monkeypatch.setattr(ContentWorkspace, "capture_device_snapshot", capture)
        with (
            device.coordinator.sync_session(device.active) as session,
            content_workspace(memory_budget=0, checkpoint=lambda: None) as workspace,
        ):
            result = capture_and_pack(
                session,
                (_asset(),),
                retained,
                None,
                workspace,
                lambda: None,
                max_file_bytes=256,
            )[0]
            assert result.photo.representations[1].relative_path.endswith(
                "F1024_2.ithmb"
            )
        assert captured == ["Photos/Thumbs/F1024_2.ithmb"]
    finally:
        device.coordinator.close()
