from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from iopenpod.itunesdb_writer.mhit_writer import TrackInfo
from iopenpod.sync.fingerprint_diff_engine import SyncAction, SyncItem, SyncPlan
from iopenpod.sync.lastfm_scrobbler import (
    ScrobbleEntry as LastFmScrobbleEntry,
)
from iopenpod.sync.lastfm_scrobbler import (
    ScrobbleResult as LastFmScrobbleResult,
)
from iopenpod.sync.lastfm_scrobbler import (
    _build_scrobble_batch_params,
    _make_lastfm_request,
    scrobble_lastfm,
)
from iopenpod.sync.lb_scrobbler import (
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
from iopenpod.sync.mapping import MappingFile
from iopenpod.sync.pc_library import PCTrack
from iopenpod.sync.sync_executor import SyncExecutor, _SyncContext


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
    import iopenpod.sync.lb_scrobbler as lb_scrobbler

    progress_log = []
    ctx = _build_scrobble_context(progress_log=progress_log)
    executor = SyncExecutor(tmp_path)

    def fake_scrobble_plays(*args, **kwargs):
        return [ScrobbleResult(errors=["HTTP 400: invalid payload"])]

    monkeypatch.setattr(lb_scrobbler, "scrobble_plays", fake_scrobble_plays)

    ok = executor._execute_scrobble(ctx)

    assert ok is False
    assert ctx.result.scrobbles_submitted == 0
    assert ctx.result.errors == [
        ("listenbrainz", "HTTP 400: invalid payload")
    ]
    assert progress_log[-1].stage == "scrobble_listenbrainz"
    assert progress_log[-1].message == (
        "ListenBrainz did not accept any plays from this sync."
    )


def test_execute_scrobble_reports_lastfm_errors(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import iopenpod.sync.lastfm_scrobbler as lastfm_scrobbler

    progress_log = []
    ctx = _build_scrobble_context(progress_log=progress_log)
    ctx.listenbrainz_token = ""
    ctx.listenbrainz_username = ""
    ctx.lastfm_api_key = "api-key"
    ctx.lastfm_api_secret = "api-secret"
    ctx.lastfm_session_key = "session-key"
    ctx.lastfm_username = "TheRealSavi"
    executor = SyncExecutor(tmp_path)

    def fake_scrobble_plays(*args, **kwargs):
        return [LastFmScrobbleResult(errors=["Invalid session key"])]

    monkeypatch.setattr(lastfm_scrobbler, "scrobble_plays", fake_scrobble_plays)

    ok = executor._execute_scrobble(ctx)

    assert ok is False
    assert ctx.result.scrobbles_submitted == 0
    assert ctx.result.errors == [("lastfm", "Invalid session key")]
    assert progress_log[-1].stage == "scrobble_lastfm"
    assert progress_log[-1].message == (
        "Last.fm did not accept any plays from this sync."
    )


def test_execute_scrobble_ignores_disconnected_lastfm_saved_api_keys(
    tmp_path: Path,
) -> None:
    progress_log = []
    ctx = _build_scrobble_context(progress_log=progress_log)
    ctx.listenbrainz_token = ""
    ctx.listenbrainz_username = ""
    ctx.lastfm_api_key = "api-key"
    ctx.lastfm_api_secret = "api-secret"
    ctx.lastfm_session_key = ""
    executor = SyncExecutor(tmp_path)

    ok = executor._execute_scrobble(ctx)

    assert ok is True
    assert ctx.result.errors == []
    assert progress_log == []


def test_each_scrobble_service_gets_original_playcount_delta(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import iopenpod.sync.lastfm_scrobbler as lastfm_scrobbler
    import iopenpod.sync.lb_scrobbler as lb_scrobbler

    ctx = _build_scrobble_context()
    ctx.plan.to_sync_playcount[0].play_count_delta = 2
    ctx.plan.to_sync_playcount[0].ipod_track = {"play_count_2": 2}
    ctx.lastfm_api_key = "api-key"
    ctx.lastfm_api_secret = "api-secret"
    ctx.lastfm_session_key = "session-key"
    executor = SyncExecutor(tmp_path)

    seen: list[tuple[str, int]] = []

    def fake_listenbrainz(playcount_items, **_kwargs):
        seen.append(("listenbrainz", playcount_items[0].play_count_delta))
        playcount_items[0].play_count_delta = 0
        playcount_items[0].ipod_track["play_count_2"] = 0
        return [SimpleNamespace(accepted=2, errors=[])]

    def fake_lastfm(playcount_items, **_kwargs):
        seen.append(("lastfm", playcount_items[0].play_count_delta))
        return [SimpleNamespace(accepted=2, errors=[])]

    monkeypatch.setattr(lb_scrobbler, "scrobble_plays", fake_listenbrainz)
    monkeypatch.setattr(lastfm_scrobbler, "scrobble_plays", fake_lastfm)

    ok = executor._execute_scrobble(ctx)

    assert ok is True
    assert seen == [("listenbrainz", 2), ("lastfm", 2)]
    assert ctx.plan.to_sync_playcount[0].play_count_delta == 2
    assert ctx.plan.to_sync_playcount[0].ipod_track["play_count_2"] == 2


def test_lastfm_request_reports_json_api_errors(monkeypatch) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"error": 9, "message": "Invalid session key"}'

    monkeypatch.setattr(
        "iopenpod.sync.lastfm_scrobbler.urllib.request.urlopen",
        lambda *_args, **_kwargs: FakeResponse(),
    )

    with pytest.raises(RuntimeError, match="Last.fm API 9: Invalid session key"):
        _make_lastfm_request(
            {"method": "user.getInfo", "api_key": "api-key", "sk": "bad-session"},
            api_secret="api-secret",
            method="GET",
        )


def test_lastfm_request_retries_json_temporary_api_errors(monkeypatch) -> None:
    class FakeResponse:
        def __init__(self, body: bytes):
            self._body = body

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return self._body

    responses = [
        FakeResponse(b'{"error": 16, "message": "Temporary error"}'),
        FakeResponse(b'{"user": {"name": "TheRealSavi"}}'),
    ]
    waits: list[float] = []

    def fake_urlopen(*_args, **_kwargs):
        return responses.pop(0)

    monkeypatch.setattr(
        "iopenpod.sync.lastfm_scrobbler.urllib.request.urlopen",
        fake_urlopen,
    )
    monkeypatch.setattr(
        "iopenpod.sync.lastfm_scrobbler._sleep_with_abort",
        lambda seconds, should_abort=None: waits.append(seconds),
    )

    data = _make_lastfm_request(
        {"method": "user.getInfo", "api_key": "api-key", "sk": "session-key"},
        api_secret="api-secret",
        method="GET",
    )

    assert data == {"user": {"name": "TheRealSavi"}}
    assert waits == [5.0]


def test_lastfm_scrobble_params_include_duration() -> None:
    params = _build_scrobble_batch_params(
        [
            LastFmScrobbleEntry(
                "Artist",
                "Track",
                "Album",
                240,
                1_700_000_100,
                track_number=7,
                album_artist="Album Artist",
            )
        ],
        "api-key",
        "session-key",
    )

    assert params["duration[0]"] == "240"
    assert params["albumArtist[0]"] == "Album Artist"
    assert params["trackNumber[0]"] == "7"


def test_scrobble_lastfm_reports_json_api_errors(monkeypatch) -> None:
    def fake_make_request(*_args, **_kwargs):
        raise RuntimeError("Last.fm API 9: Invalid session key")

    monkeypatch.setattr(
        "iopenpod.sync.lastfm_scrobbler._make_lastfm_request",
        fake_make_request,
    )

    result = scrobble_lastfm(
        [LastFmScrobbleEntry("Artist", "Track", "Album", 240, 1_700_000_100)],
        "api-key",
        "api-secret",
        "bad-session",
    )

    assert result.submitted == 1
    assert result.accepted == 0
    assert result.errors == ["Batch at index 0: Last.fm API 9: Invalid session key"]


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

    monkeypatch.setattr("iopenpod.sync.lb_scrobbler._make_request", fake_make_request)

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

    monkeypatch.setattr("iopenpod.sync.lb_scrobbler.get_latest_import", fake_get_latest_import)
    monkeypatch.setattr("iopenpod.sync.lb_scrobbler.set_latest_import", fake_set_latest_import)
    monkeypatch.setattr("iopenpod.sync.lb_scrobbler._make_request", fake_make_request)

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

    monkeypatch.setattr("iopenpod.sync.lb_scrobbler.get_latest_import", fake_get_latest_import)

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

    monkeypatch.setattr("iopenpod.sync.lb_scrobbler._make_request", fake_make_request)
    monkeypatch.setattr("iopenpod.sync.lb_scrobbler.set_latest_import", lambda *args, **kwargs: False)

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
    import iopenpod.sync.sync_executor as sync_executor

    order: list[str] = []
    ctx = _build_scrobble_context()
    executor = SyncExecutor(tmp_path)

    monkeypatch.setattr(
        sync_executor,
        "write_database_commit",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(executor, "_backpatch_new_tracks", lambda ctx: None)
    monkeypatch.setattr(executor.mapping_manager, "save", lambda mapping: None)
    monkeypatch.setattr(executor, "_update_podcast_subscriptions", lambda ctx: None)
    monkeypatch.setattr(executor, "_clear_gui_cache", lambda ctx: None)
    monkeypatch.setattr(
        sync_executor,
        "apply_itunes_protections_from_tracks",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        executor,
        "_build_and_evaluate_playlists",
        lambda ctx, tracks: ("iPod", None, [], "iPod", None, [], []),
    )
    monkeypatch.setattr(sync_executor, "read_photo_db", lambda path: None)
    monkeypatch.setattr(executor, "_execute_scrobble", lambda ctx: order.append("scrobble") or True)
    monkeypatch.setattr(executor, "_delete_playcounts_file", lambda: order.append("delete"))

    executor._execute_write_and_finalize(ctx)

    assert order == ["scrobble", "delete"]


def test_write_finalize_clears_playcount_after_scrobble_before_database_write(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import iopenpod.sync.sync_executor as sync_executor

    ctx = _build_scrobble_context()
    ctx.plan.to_sync_playcount[0].db_track_id = 123
    ctx.plan.to_sync_playcount[0].ipod_track = {
        "play_count_2": 3,
        "recent_playcount": 3,
    }
    track = TrackInfo(title="Song", location=":iPod_Control:Music:F00:ABCD.mp3")
    track.db_track_id = 123
    track.play_count_2 = 3
    ctx.tracks_by_db_track_id[123] = track
    executor = SyncExecutor(tmp_path)
    order: list[str] = []

    def fake_scrobble(scrobble_ctx):
        order.append("scrobble")
        assert track.play_count_2 == 3
        assert scrobble_ctx.plan.to_sync_playcount[0].ipod_track["play_count_2"] == 3
        return True

    def fake_write_database_commit(_ipod_path, payload, **_kwargs):
        order.append("write")
        assert payload.all_tracks[0].play_count_2 == 0
        return True

    monkeypatch.setattr(sync_executor, "write_database_commit", fake_write_database_commit)
    monkeypatch.setattr(executor, "_backpatch_new_tracks", lambda ctx: None)
    monkeypatch.setattr(executor.mapping_manager, "save", lambda mapping: None)
    monkeypatch.setattr(executor, "_update_podcast_subscriptions", lambda ctx: None)
    monkeypatch.setattr(executor, "_clear_gui_cache", lambda ctx: None)
    monkeypatch.setattr(
        sync_executor,
        "apply_itunes_protections_from_tracks",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        executor,
        "_build_and_evaluate_playlists",
        lambda ctx, tracks: ("iPod", None, [], "iPod", None, [], []),
    )
    monkeypatch.setattr(sync_executor, "read_photo_db", lambda path: None)
    monkeypatch.setattr(executor, "_execute_scrobble", fake_scrobble)
    monkeypatch.setattr(executor, "_delete_playcounts_file", lambda: order.append("delete"))

    executor._execute_write_and_finalize(ctx)

    assert order == ["scrobble", "write", "delete"]
    assert track.play_count_2 == 0
    assert ctx.plan.to_sync_playcount[0].play_count_delta == 1
    assert ctx.plan.to_sync_playcount[0].ipod_track["play_count_2"] == 0
