"""Exact Photo copies retain independent identities through verified Sync writes."""

from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.test_library_resources import Device, build_device

# Reuse the execution fixtures while keeping their test-only API private.
from tests.iOpenPod.app.test_sync_execution import (
    _Executor,  # pyright: ignore[reportPrivateUsage]
    _ipod,  # pyright: ignore[reportPrivateUsage]
    _photo_host,  # pyright: ignore[reportPrivateUsage]
)

from iOpenPod.app.host_media_library import HostMediaLibrary
from iOpenPod.app.models.sync_selection import SyncSelection
from iOpenPod.app.sync_execution import (
    SyncExecutionRequest,
    SyncExecutionResult,
    SyncExecutionStatus,
)
from iOpenPod.app.sync_plan import (
    SyncDuplicatePair,
    SyncDuplicateResolution,
    SyncPlanAction,
    SyncPlanMediaKind,
    prepare_sync_plan,
)
from iPodDB.library import PhotoLibrary, PhotoRepresentationKind


def _duplicate_photos(tmp_path: Path) -> HostMediaLibrary:
    original_directory = tmp_path / "original"
    copied_directory = tmp_path / "copied"
    original_directory.mkdir()
    copied_directory.mkdir()
    first, second = _photo_host(original_directory), _photo_host(copied_directory)
    assert first.snapshot.photos is not None and second.snapshot.photos is not None
    assert first.sources[0].content_sha256 == second.sources[0].content_sha256
    return replace(
        first,
        snapshot=replace(
            first.snapshot,
            photos=PhotoLibrary(
                photos=(
                    first.snapshot.photos.photos[0],
                    replace(second.snapshot.photos.photos[0], photo_id=2),
                )
            ),
        ),
        sources=(*first.sources, *second.sources),
    )


def _publish_photos(
    device: Device, host: HostMediaLibrary, count: int = 2
) -> SyncExecutionResult:
    ipod = _ipod(device)
    selection = SyncSelection()
    comparison = prepare_sync_plan(host, ipod, device.active.library)
    selection.reset(host, comparison)
    (group,) = comparison.duplicate_groups
    assert group.media_kind is SyncPlanMediaKind.PHOTO
    assert not group.requires_resolution
    assert selection.selected_plan.count(SyncPlanAction.ADD) == 0
    selection.set_photos_checked(range(1, count + 1), True)
    assert selection.selected_plan.count(SyncPlanAction.ADD) == count
    result = _Executor(device.coordinator).execute(
        SyncExecutionRequest(selection.selected_plan, host, ipod, device.active, 1, 1),
        lambda _: None,
        Event(),
    )
    assert result.status is SyncExecutionStatus.SUCCESS, result.issues
    return result


@pytest.mark.parametrize("count", (1, 2))
def test_identical_host_photos_can_be_selected_and_committed_separately(
    tmp_path: Path, count: int
) -> None:
    device = build_device(tmp_path)
    try:
        host = _duplicate_photos(tmp_path)
        originals = {
            Path(source.path): Path(source.path).read_bytes() for source in host.sources
        }
        result = _publish_photos(device, host, count)
        assert result.active is not None and result.active.library.photos is not None
        assert result.helper is not None
        photos = result.active.library.photos.photos
        assert len(photos) == count
        assert len({photo.photo_id for photo in photos}) == count
        paths = tuple(
            representation.relative_path
            for photo in photos
            for representation in photo.representations
            if representation.kind is PhotoRepresentationKind.FULL_RESOLUTION
        )
        assert len(set(paths)) == count
        assert all(
            (device.root / path).read_bytes() == next(iter(originals.values()))
            for path in paths
        )
        assert all(path.read_bytes() == data for path, data in originals.items())
        assert len(result.helper.images) == count
        assert {
            image.sync.host_path_hint
            for image in result.helper.images
            if image.sync is not None
        } == {str(source.path) for source in host.sources[:count]}
        reloaded = device.coordinator.scan_ipod_media(
            result.active, lambda _: None, Event()
        )
        repeated = prepare_sync_plan(host, reloaded, result.active.library)
        assert repeated.count(SyncPlanAction.UNCHANGED) == count
        assert repeated.count(SyncPlanAction.ADD) == 2 - count
        assert repeated.attention_count == 0
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("remove_extra", (False, True))
@pytest.mark.parametrize("prior_claims", (False, True))
def test_explicit_photo_choice_persists_identity_and_only_removes_opted_in_copy(
    tmp_path: Path,
    remove_extra: bool,
    prior_claims: bool,
) -> None:
    device = build_device(tmp_path)
    try:
        duplicates = _duplicate_photos(tmp_path)
        first_result = _publish_photos(device, duplicates)
        assert (
            first_result.active is not None
            and first_result.active.library.photos is not None
        )
        assert first_result.helper is not None
        assert duplicates.snapshot.photos is not None
        host = replace(
            duplicates,
            sources=(duplicates.sources[0],),
            snapshot=replace(
                duplicates.snapshot,
                photos=PhotoLibrary(photos=(duplicates.snapshot.photos.photos[0],)),
            ),
        )
        prior = first_result.helper.images[0].sync if prior_claims else None
        ipod = replace(
            first_result.helper,
            images=tuple(
                replace(image, sync=prior) for image in first_result.helper.images
            ),
        )
        old_photos = {
            photo.photo_id: photo for photo in first_result.active.library.photos.photos
        }
        untouched, chosen = ipod.images
        old_untouched_bytes = (device.root / str(untouched.path)).read_bytes()
        old_source_bytes = Path(host.sources[0].path).read_bytes()
        comparison = prepare_sync_plan(host, ipod, device.active.library)
        selection = SyncSelection()
        selection.reset(host, comparison)
        (group,) = comparison.duplicate_groups
        assert group.requires_resolution
        selection.set_duplicate_resolution(
            SyncDuplicateResolution(
                group.group_id,
                pairs=(SyncDuplicatePair(str(host.sources[0].path), chosen.image_id),),
                removed_ipod_ids=frozenset({untouched.image_id})
                if remove_extra
                else frozenset(),
            )
        )
        assert selection.selected_plan.count(SyncPlanAction.UPDATE) == 1
        assert selection.selected_plan.count(SyncPlanAction.REMOVE) == int(remove_extra)
        result = _Executor(device.coordinator).execute(
            SyncExecutionRequest(
                selection.selected_plan, host, ipod, device.active, 1, 1
            ),
            lambda _: None,
            Event(),
        )
        assert result.status is SyncExecutionStatus.SUCCESS, result.issues
        assert result.active is not None and result.active.library.photos is not None
        assert result.helper is not None
        photos = {
            photo.photo_id: photo for photo in result.active.library.photos.photos
        }
        assert set(photos) == ({chosen.image_id} if remove_extra else set(old_photos))
        assert chosen.image_id in photos
        if remove_extra:
            assert not (device.root / str(untouched.path)).exists()
            assert all(
                untouched.image_id not in album.photo_ids
                for album in result.active.library.photos.albums
            )
        else:
            assert photos[untouched.image_id] == old_photos[untouched.image_id]
            assert (
                device.root / str(untouched.path)
            ).read_bytes() == old_untouched_bytes
            retained = next(
                image
                for image in result.helper.images
                if image.image_id == untouched.image_id
            )
            if prior_claims:
                assert retained.sync is not None and retained.sync.host_path_hint == ""
            else:
                assert retained.sync is None
        assert Path(host.sources[0].path).read_bytes() == old_source_bytes
        recorded = next(
            image for image in result.helper.images if image.image_id == chosen.image_id
        )
        assert recorded.sync is not None
        assert recorded.sync.host_path_hint == str(host.sources[0].path)
        reloaded = device.coordinator.scan_ipod_media(
            result.active, lambda _: None, Event()
        )
        repeated = prepare_sync_plan(host, reloaded, result.active.library)
        (pair,) = tuple(item for item in repeated.items if item.host_path)
        assert pair.ipod_id == chosen.image_id
        assert pair.action is SyncPlanAction.UNCHANGED
        assert repeated.attention_count == 0
        selection.reset(host, repeated)
        assert selection.selected_plan.count(SyncPlanAction.REMOVE) == 0
    finally:
        device.coordinator.close()
