"""Sidecar projection, publication, staleness and recovery on virtual devices."""

import plistlib
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from threading import Event

import pytest
from tests.iOpenPod.app.services.test_library_resources import build_device
from tests.iPodDB.library.test_writing import library
from tests.iPodDB.sidecars.test_sidecar_readers import counts, otg, stats

from iOpenPod.app.library_write import (
    LibraryPreparationRequest,
    LibraryReview,
    LibrarySaveResult,
    WriteProgress,
)
from iOpenPod.app.models.device import ActiveIPod, DeviceCandidateIssueCode
from iOpenPod.app.services.device_coordinator import (
    DeviceCoordinationError,
    DeviceLibraryLoadError,
    SyncRecoveryRequiredError,
)
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhip import MhipHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import MhsdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import MhypHeader
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB
from iPodDB.library import (
    IPodLibrary,
    SmartField,
    SmartOperator,
    SmartPlaylist,
    SmartRule,
    SmartRuleGroup,
    WriteResources,
    _write_preparation,
)
from iPodDB.library._playlist_writing import position_item
from iPodDB.library._smart_writing import smart_chunks
from iPodDB.shared.chunk import DatabaseDocument, chunk_as
from storage import DevicePath, FilesystemSession


def _saved_smart_playlists(
    mismatch: str, *, canonical_members: tuple[int, ...] | None = None
) -> bytes:
    source = library(mirrored=True, conflicting=mismatch == "name")
    document = parse_iTunesDB(source.serialize().itunes)
    smart = SmartPlaylist(
        rules=SmartRuleGroup(
            rules=(SmartRule(SmartField.PLAY_COUNT, SmartOperator.GREATER_THAN, 0),)
        )
    )
    for dataset in document.find_chunks(MhsdHeader):
        for row in dataset.find_chunks(MhypHeader):
            if row.chunk.header.master_flag:
                continue
            children = row.chunk.children
            kind = dataset.chunk.header.dataset_type
            if canonical_members is not None and kind == 3:
                children = tuple(
                    child
                    for child in children
                    if not isinstance(child.header, MhipHeader)
                    or child.header.track_id in canonical_members
                )
                if canonical_members == (1,):
                    # Keep one occurrence even though the source has duplicates.
                    children = children[:2]
            if mismatch == "membership" and kind == 2:
                # Retain a different saved occurrence list in the flat dataset.
                first_entry = next(
                    index
                    for index, child in enumerate(children)
                    if isinstance(child.header, MhipHeader)
                )
                children = children[:first_entry] + children[first_entry + 1 :]
            if mismatch == "missing_member" and kind == 2:
                children = tuple(
                    child
                    for child in children
                    if not isinstance(child.header, MhipHeader)
                    or child.header.track_id != 1
                )
            definition = (
                replace(
                    smart,
                    rules=SmartRuleGroup(
                        rules=(SmartRule(SmartField.PLAY_COUNT, SmartOperator.IS, 0),)
                    ),
                )
                if mismatch == "rules" and kind == 2
                else smart
            )
            children = tuple(
                position_item(chunk_as(child, MhipHeader), index - 1)
                if isinstance(child.header, MhipHeader)
                else child
                for index, child in enumerate(children)
            )
            document = document.replace_chunk(
                row,
                replace(row.chunk, children=(*smart_chunks(definition, ()), *children)),
            )
    return write_iTunesDB(document)


def _smart_metadata_bytes(data: bytes) -> tuple[tuple[bytes, ...], ...]:
    document = parse_iTunesDB(data)
    return tuple(
        tuple(
            data[
                child.offset : child.offset + child.generic_header.length_or_child_count
            ]
            for child in row.chunk.children
            if not isinstance(child.header, MhipHeader)
        )
        for row in document.find_chunks(MhypHeader)
        if row.chunk.header.playlist_id == 10
    )


def test_stale_smart_copy_stays_byte_exact_without_refresh_intent() -> None:
    original = _saved_smart_playlists("membership", canonical_members=(1,))
    source = IPodLibrary(original)
    result = source.prepare(source.analyze(source.begin_draft()))
    assert result.prepared is not None, result.issues
    assert result.prepared.itunes == original


@pytest.mark.parametrize("identities", [(10, 10), (-1,), (1000,)])
def test_invalid_smart_refresh_intent_cannot_bypass_validation(
    identities: tuple[int, ...],
) -> None:
    source = IPodLibrary(_saved_smart_playlists("membership"))
    result = source.prepare(
        source.analyze(source.begin_draft(refresh_smart_playlists=identities))
    )
    assert result.prepared is None
    assert any(i.code == "draft.invalid_smart_refresh" for i in result.issues)


def test_refresh_retains_each_counterparts_own_surviving_occurrence() -> None:
    original = _saved_smart_playlists("membership", canonical_members=(1,))
    source = IPodLibrary(original)
    result = source.prepare(
        source.analyze(source.begin_draft(refresh_smart_playlists=(10,))),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is not None, result.issues
    before = parse_iTunesDB(original)
    after = parse_iTunesDB(result.prepared.itunes)
    for kind in (2, 3):
        source_dataset = next(
            row
            for row in before.find_chunks(MhsdHeader)
            if row.chunk.header.dataset_type == kind
        )
        target_dataset = next(
            row
            for row in after.find_chunks(MhsdHeader)
            if row.chunk.header.dataset_type == kind
        )
        previous = next(
            item.chunk
            for item in source_dataset.find_chunks(MhipHeader)
            if item.chunk.header.track_id == 1
        )
        current = target_dataset.find_chunks(MhipHeader)
        assert len(current) == 1
        assert current[0].chunk.header == previous.header
    assert _smart_metadata_bytes(result.prepared.itunes) == _smart_metadata_bytes(
        original
    )
    assert source.serialize().itunes == original


def test_verification_rejects_stale_counterpart_after_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = _saved_smart_playlists("membership", canonical_members=(1,))
    source = IPodLibrary(original)
    flat = (
        next(
            row
            for row in parse_iTunesDB(original).find_chunks(MhsdHeader)
            if row.chunk.header.dataset_type == 2
        )
        .find_chunks(MhypHeader)[1]
        .chunk
    )

    def corrupt(document: DatabaseDocument[MhbdHeader]) -> bytes:
        dataset = next(
            row
            for row in document.find_chunks(MhsdHeader)
            if row.chunk.header.dataset_type == 2
        )
        selection = dataset.find_chunks(MhypHeader)[1]
        return write_iTunesDB(document.replace_chunk(selection, flat))

    monkeypatch.setattr(_write_preparation, "write_iTunesDB", corrupt)
    result = source.prepare(
        source.analyze(source.begin_draft(refresh_smart_playlists=(10,))),
        WriteResources(pending_playback_sidecars=False),
    )
    assert result.prepared is None
    assert any(i.code == "verification.playlist_mirror" for i in result.issues)
    assert source.serialize().itunes == original


@pytest.mark.parametrize("mismatch", ["none", "membership", "missing_member"])
@pytest.mark.parametrize("sidecar", ["Play Counts", "OTGPlaylistInfo"])
@pytest.mark.parametrize("canonical_current", [False, True])
def test_selection_refreshes_smart_playlists_with_stale_counterpart_membership(
    tmp_path: Path, mismatch: str, sidecar: str, canonical_current: bool
) -> None:
    device = build_device(tmp_path, model="MA450")
    directory = device.root / "iPod_Control/iTunes"
    expected = (1,) if sidecar == "Play Counts" else ()
    original = _saved_smart_playlists(
        mismatch, canonical_members=expected if canonical_current else None
    )
    evidence = counts() if sidecar == "Play Counts" else b""
    try:
        (directory / "iTunesDB").write_bytes(original)
        (directory / sidecar).write_bytes(evidence)
        selected = device.coordinator.select_device(device.active.candidate.id)
        assert selected.library.tracks[0].play_count == (
            3 if sidecar == "Play Counts" else 0
        )
        assert selected.library.playlists[0].track_ids == expected
        committed = (directory / "iTunesDB").read_bytes()
        native = parse_iTunesDB(committed)
        copies = tuple(
            row
            for row in native.find_chunks(MhypHeader)
            if row.chunk.header.playlist_id == 10
        )
        assert len(copies) == 2
        for row in copies:
            assert (
                tuple(
                    item.chunk.header.track_id for item in row.find_chunks(MhipHeader)
                )
                == expected
            )
        assert _smart_metadata_bytes(committed) == _smart_metadata_bytes(original)
        assert (directory / (sidecar + ".bak")).read_bytes() == evidence
        assert not (directory / sidecar).exists()

        reloaded = device.coordinator.select_device(selected.candidate.id)
        assert reloaded.library == selected.library
        assert (directory / "iTunesDB").read_bytes() == committed

        # Ordinary saves continue to refresh and accept the now-current copies.
        review = device.prepare(replace(reloaded.library, device_name="Refreshed"))
        assert review.result.prepared is not None, review.result.issues
        assert review.result.prepared.snapshot.playlists[0].track_ids == expected
        assert (directory / "iTunesDB").read_bytes() == committed
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("mismatch", ["none", "membership"])
def test_selection_refreshes_smart_playlists_and_adds_otg(
    tmp_path: Path, mismatch: str
) -> None:
    device = build_device(tmp_path, model="MA450")
    directory = device.root / "iPod_Control/iTunes"
    original = _saved_smart_playlists(mismatch)
    files = {"Play Counts": counts(), "OTGPlaylistInfo": otg((1, 0, 1))}
    try:
        (directory / "iTunesDB").write_bytes(original)
        for name, data in files.items():
            (directory / name).write_bytes(data)
        selected = device.coordinator.select_device(device.active.candidate.id)
        assert selected.library.tracks[0].play_count == 3
        saved, added = selected.library.playlists
        assert saved.track_ids == (1,)
        assert added.track_ids == (2, 1, 2)
        committed = (directory / "iTunesDB").read_bytes()
        assert _smart_metadata_bytes(committed) == _smart_metadata_bytes(original)
        for name, data in files.items():
            assert (directory / (name + ".bak")).read_bytes() == data
            assert not (directory / name).exists()
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("mismatch", ["name", "rules"])
def test_selection_blocks_conflicting_smart_definitions_without_consuming_evidence(
    tmp_path: Path, mismatch: str
) -> None:
    device = build_device(tmp_path, model="MA450")
    directory = device.root / "iPod_Control/iTunes"
    original = _saved_smart_playlists(mismatch)
    files = {"Play Counts": counts(), "OTGPlaylistInfo": otg((1, 0, 1))}
    try:
        (directory / "iTunesDB").write_bytes(original)
        for name, data in files.items():
            (directory / name).write_bytes(data)
        candidate_id = device.active.candidate.id
        with pytest.raises(
            DeviceLibraryLoadError, match="dataset disagrees"
        ) as failure:
            device.coordinator.select_device(candidate_id)
        assert (
            f"different source fields: {'smart' if mismatch == 'rules' else 'name'}"
            in str(failure.value)
        )
        assert device.coordinator.active_ipod is None
        assert (directory / "iTunesDB").read_bytes() == original
        for name, data in files.items():
            assert (directory / name).read_bytes() == data
            assert not (directory / (name + ".bak")).exists()
    finally:
        device.coordinator.close()


def test_discovery_is_read_only_and_selection_commits_history_and_otg_once(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    directory = device.root / "iPod_Control/iTunes"
    files = {
        "Play Counts": counts(),
        "OTGPlaylistInfo": otg((1, 0, 1)),
        "OTGPlaylistInfo_2": otg((0,)),
    }
    try:
        for name, data in files.items():
            (directory / name).write_bytes(data)
        candidate = device.coordinator.discover_devices().candidates[0]
        device.assert_original()
        for name, data in files.items():
            assert (directory / name).read_bytes() == data
        selected = device.coordinator.select_device(candidate.id)
        assert selected is device.active
        snapshot = device.active.library
        assert snapshot.tracks[0].play_count == 3
        assert snapshot.playlists[-2].track_ids == (
            snapshot.tracks[1].track_id,
            snapshot.tracks[0].track_id,
            snapshot.tracks[1].track_id,
        )
        for name, data in files.items():
            assert not (directory / name).exists()
            assert (directory / (name + ".bak")).read_bytes() == data
        persisted = IPodLibrary((directory / "iTunesDB").read_bytes())
        assert persisted.snapshot.tracks[0].play_count == 3
        assert persisted.snapshot.playlists == snapshot.playlists
        assert not tuple(
            (device.root / ".iopenpod-recovery").glob("*/transaction.json")
        )
        committed = (directory / "iTunesDB").read_bytes()
        reloaded = device.coordinator.select_device(device.active.candidate.id)
        assert reloaded.library.tracks[0].play_count == 3
        assert len(reloaded.library.playlists) == len(snapshot.playlists)
        assert (directory / "iTunesDB").read_bytes() == committed
        # A later ordinary save cannot import the retired delta or playlists again.
        review = device.prepare(replace(reloaded.library, device_name="Sidecar test"))
        assert review.result.prepared is not None, review.result.issues
        saved = device.save(review)
        assert saved.active is not None, saved.issues
        assert saved.active.library.tracks[0].play_count == 3
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("numbered_playlists", [False, True])
def test_selection_consumes_empty_otg_semaphore_and_numbered_playlists_once(
    tmp_path: Path, numbered_playlists: bool
) -> None:
    device = build_device(tmp_path)
    directory = device.root / "iPod_Control/iTunes"
    original = device.active.library
    files = {"OTGPlaylistInfo": b""}
    if numbered_playlists:
        # A numeric gap and reverse creation order must not alter import order.
        files.update(
            {
                "OTGPlaylistInfo_10": otg((0, 0)),
                "OTGPlaylistInfo_2": otg((1, 0, 1)),
            }
        )
    try:
        for name, data in files.items():
            (directory / name).write_bytes(data)
        selected = device.coordinator.select_device(device.active.candidate.id)
        assert selected is device.active
        snapshot = selected.library
        assert snapshot.tracks == original.tracks
        if numbered_playlists:
            assert len(snapshot.playlists) == len(original.playlists) + 2
            added = snapshot.playlists[-2:]
            assert tuple(p.name for p in added) == ("On-The-Go 3", "On-The-Go 11")
            first, second = snapshot.tracks
            assert added[0].track_ids == (
                second.track_id,
                first.track_id,
                second.track_id,
            )
            assert added[1].track_ids == (first.track_id, first.track_id)
        else:
            assert snapshot.playlists == original.playlists
            device.assert_original()
        for name, data in files.items():
            assert not (directory / name).exists()
            assert (directory / (name + ".bak")).read_bytes() == data
        committed = (directory / "iTunesDB").read_bytes()
        persisted = IPodLibrary(committed)
        assert persisted.snapshot.playlists == snapshot.playlists
        assert not tuple(
            (device.root / ".iopenpod-recovery").glob("*/transaction.json")
        )
        reloaded = device.coordinator.select_device(selected.candidate.id)
        assert reloaded.library.playlists == snapshot.playlists
        assert (directory / "iTunesDB").read_bytes() == committed
        for name, data in files.items():
            assert not (directory / name).exists()
            assert (directory / (name + ".bak")).read_bytes() == data
    finally:
        device.coordinator.close()


def test_empty_numbered_otg_blocks_selection_without_consuming_empty_semaphore(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    directory = device.root / "iPod_Control/iTunes"
    files = {
        "OTGPlaylistInfo": b"",
        "OTGPlaylistInfo_1": otg((0,)),
        "OTGPlaylistInfo_2": b"",
    }
    try:
        for name, data in files.items():
            (directory / name).write_bytes(data)
        with pytest.raises(DeviceLibraryLoadError, match="OTGPlaylistInfo_2"):
            device.coordinator.select_device(device.active.candidate.id)
        assert device.coordinator.active_ipod is None
        device.assert_original()
        for name, data in files.items():
            assert (directory / name).read_bytes() == data
            assert not (directory / (name + ".bak")).exists()
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("kind", ["stats24", "stats32", "plist"])
def test_other_playback_formats_publish_through_the_same_transaction(
    tmp_path: Path, kind: str
) -> None:
    device = build_device(tmp_path)
    directory = device.root / "iPod_Control/iTunes"
    try:
        track = device.active.library.tracks[1]
        assert track.ipod is not None
        if kind == "plist":
            name = "PlayCounts.plist"
            data = plistlib.dumps(
                {"tracks": [{"persistentID": track.ipod.db_track_id, "playCount": 5}]},
                fmt=plistlib.FMT_BINARY,
            )
        else:
            name = "iTunesStats"
            data = stats(3 if kind == "stats24" else 4)
        (directory / name).write_bytes(data)
        device.coordinator.select_device(device.active.candidate.id)
        assert device.active.library.tracks[1].play_count == 5
        persisted = IPodLibrary((directory / "iTunesDB").read_bytes())
        assert persisted.snapshot.tracks[1].play_count == 5
        assert (directory / (name + ".bak")).read_bytes() == data
        assert not (directory / name).exists()
    finally:
        device.coordinator.close()


@pytest.mark.parametrize(
    "phase", ["before_review", "after_review", "save.storage.prepared"]
)
@pytest.mark.parametrize("mutation", ["change", "delete", "new_file"])
def test_changed_loaded_evidence_never_publishes_stale_totals(
    tmp_path: Path, phase: str, mutation: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = build_device(tmp_path)
    directory = device.root / "iPod_Control/iTunes"
    path = directory / "Play Counts"
    try:
        path.write_bytes(counts())

        def mutate() -> None:
            if mutation == "change":
                path.write_bytes(counts(((7, 0, 0),), width=12))
            elif mutation == "delete":
                path.unlink()
            else:
                (directory / "PlayCounts.plist").write_bytes(
                    plistlib.dumps({"tracks": []})
                )

        prepare = device.coordinator.prepare_library
        save = device.coordinator.save_library

        def prepare_with_mutation(
            request: LibraryPreparationRequest,
            progress: Callable[[WriteProgress], None],
            cancelled: Event,
        ) -> LibraryReview:
            if phase == "before_review":
                mutate()
            review = prepare(request, progress, cancelled)
            if phase == "after_review":
                mutate()
            return review

        def save_with_mutation(
            review: LibraryReview,
            expected: ActiveIPod,
            progress: Callable[[WriteProgress], None],
            cancelled: Event,
        ) -> LibrarySaveResult:
            def observed(event: WriteProgress) -> None:
                progress(event)
                if event.phase == phase:
                    mutate()

            return save(review, expected, observed, cancelled)

        monkeypatch.setattr(
            device.coordinator, "prepare_library", prepare_with_mutation
        )
        monkeypatch.setattr(device.coordinator, "save_library", save_with_mutation)
        with pytest.raises((DeviceLibraryLoadError, SyncRecoveryRequiredError)):
            device.coordinator.select_device(device.active.candidate.id)
        assert device.coordinator.active_ipod is None
        assert device.coordinator.discovery.active_candidate_id is None
        device.assert_original()
        assert not (directory / "Play Counts.bak").exists()
    finally:
        device.coordinator.close()


def test_cleanup_failure_keeps_committed_selection_and_recovery_restores_all_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    device = build_device(tmp_path)
    directory = device.root / "iPod_Control/iTunes"
    data = counts()
    try:
        (directory / "Play Counts").write_bytes(data)
        (directory / "Play Counts.bak").write_bytes(b"previous backup")

        def fail_cleanup(_session: FilesystemSession, _path: DevicePath) -> None:
            raise OSError("Recovery files are temporarily unavailable")

        with monkeypatch.context() as fault:
            fault.setattr(
                FilesystemSession, "finalize_committed_transaction", fail_cleanup
            )
            selected = device.coordinator.select_device(device.active.candidate.id)
        assert selected.library.tracks[0].play_count == 3
        assert any(
            issue.code is DeviceCandidateIssueCode.TRANSACTION_CLEANUP_PENDING
            for issue in selected.candidate.issues
        )
        recovered = device.coordinator.recover_sync_journal(
            device.coordinator.sync_cleanup_path
        )
        device.assert_original()
        assert recovered.library.tracks[0].play_count == 0
        assert (directory / "Play Counts").read_bytes() == data
        assert (directory / "Play Counts.bak").read_bytes() == b"previous backup"
    finally:
        device.coordinator.close()


def test_malformed_sidecar_blocks_selection_without_committing_other_valid_sidecars(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    path = device.root / "iPod_Control/iTunes/Play Counts"
    try:
        path.write_bytes(b"malformed history")
        otg_path = path.with_name("OTGPlaylistInfo")
        otg_path.write_bytes(otg((0,)))
        with pytest.raises(DeviceLibraryLoadError, match="Play Counts"):
            device.coordinator.select_device(device.active.candidate.id)
        assert device.coordinator.active_ipod is None
        assert path.read_bytes() == b"malformed history"
        assert otg_path.read_bytes() == otg((0,))
        assert not otg_path.with_suffix(".bak").exists()
        device.assert_original()
    finally:
        device.coordinator.close()


def test_track_removal_commits_correct_history_and_otg_membership(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    directory = device.root / "iPod_Control/iTunes"
    try:
        (directory / "Play Counts").write_bytes(
            counts(((3, 0, 0), (8, 0, 0)), width=12)
        )
        (directory / "OTGPlaylistInfo").write_bytes(otg((1, 0, 1)))
        device.coordinator.select_device(device.active.candidate.id)
        # Any later edit and restoration now starts from the committed history.
        for relative in device.original:
            device.original[relative] = (device.root / relative).read_bytes()
        snapshot = device.active.library
        survivor = snapshot.tracks[1]
        desired = replace(
            snapshot,
            tracks=(survivor,),
            playlists=tuple(
                replace(
                    p,
                    entries=tuple(
                        e for e in p.entries if e.track_id == survivor.track_id
                    ),
                )
                for p in snapshot.playlists
            ),
        )
        review = device.prepare(desired, delete=True)
        assert review.result.prepared is not None, review.result.issues
        saved = device.save(review)
        assert saved.active is not None, saved.issues
        assert saved.active.library.tracks[0].play_count == 8
        assert saved.active.library.playlists[-1].track_ids == (survivor.track_id,) * 2
        assert not (directory / "Play Counts").exists()
        assert not (directory / "OTGPlaylistInfo").exists()
        device.restore(saved.recovery_path)
        assert not (directory / "Play Counts").exists()
        assert not (directory / "OTGPlaylistInfo").exists()
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("choice", ["restore", "keep", "disconnect_restore"])
def test_interrupted_selection_requires_recovery_and_does_not_reconsume_on_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, choice: str
) -> None:
    device = build_device(tmp_path)
    directory = device.root / "iPod_Control/iTunes"
    try:
        (directory / "Play Counts").write_bytes(counts())
        save = device.coordinator.save_library

        def interrupted_save(
            review: LibraryReview,
            expected: ActiveIPod,
            progress: Callable[[WriteProgress], None],
            cancelled: Event,
        ) -> LibrarySaveResult:
            def observed(event: WriteProgress) -> None:
                progress(event)
                if (
                    event.phase == "save.storage.publishing"
                    and event.current_item == "iPod_Control/iTunes/iTunesDB"
                ):
                    if choice == "disconnect_restore":
                        device.platform.disconnect(device.root)
                    else:
                        raise OSError(
                            "Publication interrupted after database replacement"
                        )

            return save(review, expected, observed, cancelled)

        with monkeypatch.context() as fault:
            fault.setattr(device.coordinator, "save_library", interrupted_save)
            with pytest.raises(SyncRecoveryRequiredError) as failure:
                device.coordinator.select_device(device.active.candidate.id)
        assert device.coordinator.active_ipod is None
        assert device.coordinator.discovery.active_candidate_id is None
        assert (directory / "Play Counts").read_bytes() == counts()
        assert (
            IPodLibrary((directory / "iTunesDB").read_bytes())
            .snapshot.tracks[0]
            .play_count
            == 3
        )
        if choice == "disconnect_restore":
            device.platform.reconnect(device.root)
        if choice == "keep":
            recovered = device.coordinator.keep_sync_contents(
                failure.value.recovery_path
            )
            assert recovered.library.tracks[0].play_count == 3
        else:
            recovered = device.coordinator.recover_sync_journal(
                failure.value.recovery_path
            )
            device.assert_original()
            assert recovered.library.tracks[0].play_count == 0
        assert (directory / "Play Counts").read_bytes() == counts()
    finally:
        device.coordinator.close()


def test_read_only_device_with_pending_history_cannot_publish_a_pending_library(
    tmp_path: Path,
) -> None:
    device = build_device(tmp_path)
    path = device.root / "iPod_Control/iTunes/Play Counts"
    try:
        path.write_bytes(counts())
        device.platform.set_writable(device.root, False)
        candidate = device.coordinator.discover_devices().candidates[0]
        with pytest.raises(DeviceCoordinationError):
            device.coordinator.select_device(candidate.id)
        assert device.coordinator.active_ipod is None
        device.assert_original()
        assert path.read_bytes() == counts()
    finally:
        device.coordinator.close()


@pytest.mark.parametrize("kind", ["absent", "orphan", "unknown", "empty_otg"])
def test_selection_preserves_database_without_known_changes(
    tmp_path: Path, kind: str
) -> None:
    device = build_device(tmp_path)
    directory = device.root / "iPod_Control/iTunes"
    files = {
        "orphan": ("OTGPlaylistInfo_2", otg((0,))),
        "unknown": ("On-The-Go-future", b"unrecognized firmware data"),
        "empty_otg": ("OTGPlaylistInfo", otg(())),
    }
    try:
        if kind in files:
            name, data = files[kind]
            (directory / name).write_bytes(data)
        selected = device.coordinator.select_device(device.active.candidate.id)
        device.assert_original()
        assert selected.library.tracks[0].play_count == 0
        if kind in files:
            name, data = files[kind]
            if kind == "empty_otg":
                assert not (directory / name).exists()
                assert (directory / (name + ".bak")).read_bytes() == data
            else:
                assert (directory / name).read_bytes() == data
    finally:
        device.coordinator.close()
