from __future__ import annotations

import json
from pathlib import Path

from SyncEngine.fingerprint_diff_engine import SyncAction, SyncItem, SyncPlan
from SyncEngine.mapping import MappingFile
from SyncEngine.pc_library import PCTrack
from SyncEngine.scrobbler import (
    IMPORT_SERVICE,
    RateLimitInfo,
    ScrobbleAborted,
    ScrobbleEntry,
    ScrobbleResult,
    _build_listen_payload,
    build_scrobble_entries,
    get_latest_import,
    scrobble_listenbrainz,
    set_latest_import,
)
from SyncEngine.sync_executor import SyncExecutor, _SyncContext


def _build_scrobble_context(*, progress_log: list | None = None) -> _SyncContext:
    plan = SyncPlan(
        to_sync_playcount=[
            SyncItem(
                action=SyncAction.SYNC_PLAYCOUNT,
                play_count_delta=1,
                description="+1 play: Artist - Song",
            )
        ]
    )
    return _SyncContext(
        plan=plan,
        mapping=MappingFile(),
        progress_callback=(progress_log.append if progress_log is not None else None),
        dry_run=False,
        write_back_to_pc=False,
        _is_cancelled=None,
        scrobble_on_sync=True,
        listenbrainz_token="token",
        listenbrainz_username="TheRealSavi",
    )


def test_build_scrobble_entries_use_playback_start_time() -> None:
    item = SyncItem(
        action=SyncAction.SYNC_PLAYCOUNT,
        play_count_delta=2,
        pc_track=PCTrack(
            path="/tmp/track.mp3",
            relative_path="track.mp3",
            filename="track.mp3",
            extension=".mp3",
            mtime=0.0,
            size=1234,
            artist="Artist",
            title="Track",
            album="Album",
            album_artist="Album Artist",
            genre="Rock",
            year=None,
            track_number=3,
            track_total=None,
            disc_number=1,
            disc_total=None,
            duration_ms=240_000,
            bitrate=None,
            sample_rate=None,
            rating=None,
        ),
        ipod_track={"last_played": 1_700_000_000},
    )

    entries = build_scrobble_entries([item])

    assert [entry.timestamp for entry in entries] == [
        1_700_000_000 - 480,
        1_700_000_000 - 240,
    ]


def test_execute_scrobble_reports_listenbrainz_errors(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import SyncEngine.scrobbler as scrobbler

    progress_log = []
    ctx = _build_scrobble_context(progress_log=progress_log)
    executor = SyncExecutor(tmp_path)

    def fake_scrobble_plays(*args, **kwargs):
        return [ScrobbleResult(errors=["HTTP 400: invalid payload"])]

    monkeypatch.setattr(scrobbler, "scrobble_plays", fake_scrobble_plays)

    ok = executor._execute_scrobble(ctx)

    assert ok is False
    assert ctx.result.scrobbles_submitted == 0
    assert ctx.result.errors == [
        ("scrobble", "listenbrainz: HTTP 400: invalid payload")
    ]
    assert progress_log[-1].stage == "scrobble"
    assert progress_log[-1].message == (
        "ListenBrainz did not accept any plays from this sync."
    )


def test_build_listen_payload_omits_music_service_for_local_collection() -> None:
    payload = _build_listen_payload(
        ScrobbleEntry(
            artist="Artist",
            track="Track",
            album="Album",
            duration_secs=240,
            timestamp=1_700_000_000,
        )
    )

    additional_info = payload["track_metadata"]["additional_info"]
    assert "music_service_name" not in additional_info
    assert additional_info["submission_client"] == "iOpenPod"
    assert additional_info["media_player"] == "iPod"


def test_latest_import_requests_are_scoped_to_iopenpod(monkeypatch) -> None:
    requests: list[tuple[str, str, dict | None, bytes | None]] = []

    def fake_make_request(method, path, token="", body=None, params=None, **kwargs):
        requests.append((method, path, params, body))
        if method == "GET":
            return {"latest_import": 123}, RateLimitInfo()
        return {"status": "ok"}, RateLimitInfo()

    monkeypatch.setattr("SyncEngine.scrobbler._make_request", fake_make_request)

    assert get_latest_import("TheRealSavi", "token") == 123
    assert set_latest_import(456, "token") is True

    assert requests[0] == (
        "GET",
        "/1/latest-import",
        {"user_name": "TheRealSavi", "service": IMPORT_SERVICE},
        None,
    )
    assert requests[1][0:2] == ("POST", "/1/latest-import")
    assert requests[1][2] is None
    assert requests[1][3] == b'{"ts": 456, "service": "iopenpod"}'


def test_scrobble_listenbrainz_skips_entries_covered_by_latest_import(
    monkeypatch,
) -> None:
    submitted_payloads: list[list[dict]] = []
    latest_import = 1_700_000_000

    def fake_get_latest_import(
        username,
        token="",
        service=IMPORT_SERVICE,
        **kwargs,
    ):
        assert username == "TheRealSavi"
        assert service == IMPORT_SERVICE
        return latest_import

    def fake_set_latest_import(ts, token, service=IMPORT_SERVICE, **kwargs):
        assert ts == latest_import + 100
        assert service == IMPORT_SERVICE
        return True

    def fake_make_request(method, path, token="", body=None, params=None, **kwargs):
        assert method == "POST"
        assert path == "/1/submit-listens"
        assert body is not None
        submitted_payloads.append(json.loads(body.decode("utf-8"))["payload"])
        return {"status": "ok"}, RateLimitInfo(remaining=10, reset_in=0.0)

    monkeypatch.setattr("SyncEngine.scrobbler.get_latest_import", fake_get_latest_import)
    monkeypatch.setattr("SyncEngine.scrobbler.set_latest_import", fake_set_latest_import)
    monkeypatch.setattr("SyncEngine.scrobbler._make_request", fake_make_request)

    result = scrobble_listenbrainz(
        [
            ScrobbleEntry("Artist", "Old", "Album", 240, latest_import),
            ScrobbleEntry("Artist", "New", "Album", 240, latest_import + 100),
        ],
        "token",
        listenbrainz_username="TheRealSavi",
    )

    assert result.submitted == 1
    assert result.accepted == 1
    assert result.ignored == 1
    assert len(submitted_payloads) == 1
    assert [listen["track_metadata"]["track_name"] for listen in submitted_payloads[0]] == ["New"]


def test_scrobble_listenbrainz_returns_user_gave_up_when_latest_import_aborts(
    monkeypatch,
) -> None:
    def fake_get_latest_import(*args, **kwargs):
        raise ScrobbleAborted("User gave up while connecting to ListenBrainz")

    monkeypatch.setattr("SyncEngine.scrobbler.get_latest_import", fake_get_latest_import)

    result = scrobble_listenbrainz(
        [ScrobbleEntry("Artist", "Track", "Album", 240, 1_700_000_100)],
        "token",
        listenbrainz_username="TheRealSavi",
    )

    assert result.submitted == 0
    assert result.accepted == 0
    assert result.errors == ["User gave up while connecting to ListenBrainz"]


def test_scrobble_listenbrainz_reports_latest_import_update_failure(
    monkeypatch,
) -> None:
    def fake_make_request(method, path, token="", body=None, params=None, **kwargs):
        assert method == "POST"
        assert path == "/1/submit-listens"
        return {"status": "ok"}, RateLimitInfo(remaining=10, reset_in=0.0)

    monkeypatch.setattr("SyncEngine.scrobbler._make_request", fake_make_request)
    monkeypatch.setattr("SyncEngine.scrobbler.set_latest_import", lambda *args, **kwargs: False)

    result = scrobble_listenbrainz(
        [ScrobbleEntry("Artist", "Track", "Album", 240, 1_700_000_100)],
        "token",
    )

    assert result.submitted == 1
    assert result.accepted == 1
    assert result.errors == [
        "Latest-import timestamp could not be updated; future duplicate protection may be affected"
    ]


def test_write_finalize_scrobbles_before_deleting_playcounts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import SyncEngine.sync_executor as sync_executor

    order: list[str] = []
    ctx = _build_scrobble_context()
    executor = SyncExecutor(tmp_path)

    monkeypatch.setattr(executor, "_write_database", lambda *args, **kwargs: True)
    monkeypatch.setattr(executor, "_backpatch_new_tracks", lambda ctx: None)
    monkeypatch.setattr(executor.mapping_manager, "save", lambda mapping: None)
    monkeypatch.setattr(executor, "_update_podcast_subscriptions", lambda ctx: None)
    monkeypatch.setattr(executor, "_clear_gui_cache", lambda ctx: None)
    monkeypatch.setattr(executor, "_apply_itunes_protections", lambda ctx, tracks: None)
    monkeypatch.setattr(executor, "_build_and_evaluate_playlists", lambda ctx, tracks: ("iPod", [], []))
    monkeypatch.setattr(sync_executor, "read_photo_db", lambda path: None)
    monkeypatch.setattr(executor, "_execute_scrobble", lambda ctx: order.append("scrobble") or True)
    monkeypatch.setattr(executor, "_delete_playcounts_file", lambda: order.append("delete"))

    executor._execute_write_and_finalize(ctx)

    assert order == ["scrobble", "delete"]
