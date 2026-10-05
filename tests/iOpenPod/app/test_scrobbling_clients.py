"""Service protocol vectors use mocked HTTP; no account or network is needed."""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import replace
from threading import Event
from urllib.parse import parse_qs, urlsplit

import pytest

from iOpenPod.app.core.version import get_version
from iOpenPod.app.scrobbling.clients import (
    LASTFM_URL,
    LISTENBRAINZ_URL,
    LastFmClient,
    ListenBrainzClient,
    Response,
    wait_between_batches,
)
from iOpenPod.app.scrobbling.models import (
    Account,
    Credentials,
    Listen,
    ScrobbleError,
    Service,
)
from iOpenPod.app.scrobbling.reporting import rejection_report


class TransportStub:
    def __init__(self, *responses: dict[str, object]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, bytes | None, Mapping[str, str]]] = []

    def request(
        self, url: str, data: bytes | None, headers: Mapping[str, str]
    ) -> Response:
        self.calls.append((url, data, headers))
        return Response(self.responses.pop(0))


LISTEN = Listen("Björk", "Jóga", "Homogenic", 1_790_000_000, 305)
CREDENTIALS = Credentials("listener", "session", "api-key", "shared-secret")


def acknowledgement(listen: Listen, code: int, message: str = "") -> dict[str, object]:
    return {
        "artist": {"#text": listen.artist, "corrected": "0"},
        "track": {"#text": listen.title, "corrected": "0"},
        "timestamp": str(listen.timestamp),
        "ignoredMessage": {"code": str(code), "#text": message},
    }


def test_lastfm_matches_lexically_ordered_acknowledgements_to_the_submitted_listens() -> (
    None
):
    entries = tuple(
        replace(LISTEN, timestamp=LISTEN.timestamp + index * 305) for index in range(12)
    )
    replies = [
        acknowledgement(entries[index], 0 if index == 11 else 1)
        for index in sorted(range(12), key=str)
    ]
    result = LastFmClient(TransportStub({"scrobbles": {"scrobble": replies}})).submit(
        entries, CREDENTIALS
    )
    assert result.accepted == (False,) * 11 + (True,)
    assert {item.listen.timestamp for item in result.rejections} == {
        entry.timestamp for entry in entries[:-1]
    }


@pytest.mark.parametrize("change", ["timestamp", "artist", "duplicate", "ambiguous"])
def test_lastfm_does_not_guess_when_acknowledgements_cannot_be_matched(
    change: str,
) -> None:
    second = replace(LISTEN, title="Other song")
    first_reply = acknowledgement(LISTEN, 0)
    second_reply = acknowledgement(second, 0)
    if change == "timestamp":
        first_reply["timestamp"] = str(LISTEN.timestamp + 1)
    elif change == "artist":
        first_reply["artist"] = {"#text": "Wrong artist", "corrected": "0"}
    elif change == "duplicate":
        second_reply = first_reply
    else:
        first_reply["track"] = {"#text": "Corrected title", "corrected": "1"}
    client = LastFmClient(
        TransportStub({"scrobbles": {"scrobble": [first_reply, second_reply]}})
    )
    with pytest.raises(ScrobbleError, match="matched unambiguously"):
        client.submit((LISTEN, second), CREDENTIALS)


def test_lastfm_empty_code_one_reports_age_without_blame_or_repeated_boilerplate() -> (
    None
):
    entries = (
        LISTEN,
        replace(LISTEN, title="Recent song", timestamp=LISTEN.timestamp + 30 * 86400),
    )
    result = LastFmClient(
        TransportStub(
            {
                "scrobbles": {
                    "scrobble": [acknowledgement(entry, 1) for entry in entries]
                }
            }
        )
    ).submit(entries, CREDENTIALS)
    report = rejection_report(
        Account(Service.LASTFM, "listener"),
        list(result.rejections),
        now=entries[1].timestamp,
    )
    assert "1 listen is more than 14 days old" in report
    assert "Listen ignored (code 1): 2 listens" in report
    assert "does not establish that the artist metadata is wrong" in report
    assert report.count("supplied no further explanation") == 1


def test_lastfm_browser_auth_and_utf8_signed_post() -> None:
    transport = TransportStub(
        {"token": "temporary"},
        {"session": {"name": "listener", "key": "session"}},
        {"scrobbles": {"scrobble": acknowledgement(LISTEN, 0)}},
    )
    client = LastFmClient(transport)
    token, url = client.begin_auth("api-key", "shared-secret")
    assert token == "temporary"
    assert url.startswith("https://www.last.fm/api/auth/?")
    assert parse_qs(urlsplit(url).query) == {
        "api_key": ["api-key"],
        "token": ["temporary"],
    }
    credentials = client.finish_auth("api-key", "shared-secret", token)
    assert credentials == CREDENTIALS
    assert client.submit((LISTEN,), credentials).accepted == (True,)
    endpoint, body, headers = transport.calls[-1]
    assert endpoint == LASTFM_URL and body is not None
    params = {k: v[0] for k, v in parse_qs(body.decode()).items()}
    signature = params.pop("api_sig")
    assert params.pop("format") == "json"
    assert params["artist[0]"] == "Björk"
    assert params["timestamp[0]"] == "1790000000"
    assert (
        signature
        == hashlib.md5(
            ("".join(k + params[k] for k in sorted(params)) + "shared-secret").encode()
        ).hexdigest()
    )
    assert headers["Content-Type"] == "application/x-www-form-urlencoded"
    assert "session" not in repr(credentials)
    assert "shared-secret" not in repr(credentials)


def test_lastfm_acknowledges_each_listen_in_partial_response() -> None:
    transport = TransportStub(
        {
            "scrobbles": {
                "scrobble": [
                    acknowledgement(LISTEN, 0),
                    acknowledgement(LISTEN, 3, "Timestamp is too old"),
                ]
            }
        }
    )
    result = LastFmClient(transport).submit((LISTEN, LISTEN), CREDENTIALS)
    assert result.accepted == (True, False)
    assert len(result.rejections) == 1
    assert result.rejections[0].listen == LISTEN
    assert result.rejections[0].code == 3
    assert result.rejections[0].message == "Timestamp is too old"


def test_lastfm_rejection_preserves_submitted_metadata_and_service_explanation() -> (
    None
):
    rejected = replace(LISTEN, artist="Unknown Artist", title="Unidentified song")
    transport = TransportStub(
        {
            "scrobbles": {
                "scrobble": [
                    acknowledgement(LISTEN, 0),
                    {
                        **acknowledgement(
                            rejected, 1, "Artist name failed filter: Unknown Artist"
                        ),
                        "artist": {"#text": "Corrected artist", "corrected": "1"},
                    },
                ]
            }
        }
    )
    result = LastFmClient(transport).submit((LISTEN, rejected), CREDENTIALS)
    assert result.accepted == (True, False)
    assert len(result.rejections) == 1
    assert result.rejections[0].listen == rejected
    assert result.rejections[0].code == 1
    assert result.rejections[0].message == "Artist name failed filter: Unknown Artist"
    report = rejection_report(
        Account(Service.LASTFM, "listener"), list(result.rejections)
    )
    assert 'Title: "Unidentified song"' in report
    assert LISTEN.title not in report


@pytest.mark.parametrize(
    ("code", "reason", "advice"),
    [
        (2, "Track title ignored", "Check the title metadata"),
        (4, "Timestamp too new", "Check the iPod clock"),
        (5, "Daily scrobble limit reached", "Retry after Last.fm's daily limit resets"),
    ],
)
def test_lastfm_report_explains_other_rejection_codes(
    code: int, reason: str, advice: str
) -> None:
    result = LastFmClient(
        TransportStub({"scrobbles": {"scrobble": acknowledgement(LISTEN, code)}})
    ).submit((LISTEN,), CREDENTIALS)
    report = rejection_report(
        Account(Service.LASTFM, "listener"), list(result.rejections)
    )
    assert f"{reason} (code {code}): 1 listen" in report
    assert advice in report
    assert "supplied no further explanation" in report


def test_rejected_out_of_range_timestamp_still_has_a_readable_report() -> None:
    listen = replace(LISTEN, timestamp=2**63)
    result = LastFmClient(
        TransportStub({"scrobbles": {"scrobble": acknowledgement(listen, 4)}})
    ).submit((listen,), CREDENTIALS)
    report = rejection_report(
        Account(Service.LASTFM, "listener"), list(result.rejections)
    )
    assert "Timestamp too new" in report
    assert f"UNIX timestamp {listen.timestamp}" in report


def test_lastfm_rejection_message_is_bounded_plain_text_with_credentials_redacted() -> (
    None
):
    message = "\n".join(
        (
            CREDENTIALS.token,
            CREDENTIALS.api_key,
            CREDENTIALS.api_secret,
            "\x00" + "x" * 1000,
        )
    )
    result = LastFmClient(
        TransportStub({"scrobbles": {"scrobble": acknowledgement(LISTEN, 1, message)}})
    ).submit((LISTEN,), CREDENTIALS)
    detail = result.rejections[0].message
    for secret in (CREDENTIALS.token, CREDENTIALS.api_key, CREDENTIALS.api_secret):
        assert secret not in detail
    assert "[redacted]" in detail
    assert "\n" not in detail and "\x00" not in detail
    assert len(detail) <= 500


@pytest.mark.parametrize(
    "response",
    [
        {"scrobbles": {"@attr": {"accepted": "1", "ignored": "0"}}},
        {"scrobbles": {"scrobble": {"ignoredMessage": {"code": "unexpected"}}}},
        {"scrobbles": []},
        {"scrobbles": {"scrobble": [None]}},
        {"scrobbles": {"scrobble": {"ignoredMessage": []}}},
        {"error": 9, "message": "session secret"},
    ],
)
def test_lastfm_unacknowledged_or_unauthorized_listens_are_not_success(
    response: dict[str, object],
) -> None:
    with pytest.raises(ScrobbleError) as caught:
        LastFmClient(TransportStub(response)).submit((LISTEN,), CREDENTIALS)
    assert "session secret" not in str(caught.value)


def test_listenbrainz_header_auth_and_import_contract() -> None:
    transport = TransportStub(
        {"valid": True, "user_name": "listener"}, {"status": "ok"}
    )
    client = ListenBrainzClient(transport)
    credentials = client.validate_token("user-token")
    assert credentials == Credentials("listener", "user-token")
    assert transport.calls[0] == (
        LISTENBRAINZ_URL + "validate-token",
        None,
        {"Authorization": "Token user-token"},
    )
    assert client.submit((LISTEN,), credentials).accepted == (True,)
    endpoint, body, headers = transport.calls[-1]
    assert endpoint == LISTENBRAINZ_URL + "submit-listens"
    assert headers["Authorization"] == "Token user-token"
    assert body is not None
    payload = json.loads(body)
    assert payload["listen_type"] == "import"
    assert payload["payload"][0]["listened_at"] == LISTEN.timestamp
    assert payload["payload"][0]["track_metadata"]["artist_name"] == LISTEN.artist
    assert (
        payload["payload"][0]["track_metadata"]["additional_info"]["submission_client"]
        == "iOpenPod"
    )
    assert (
        payload["payload"][0]["track_metadata"]["additional_info"][
            "submission_client_version"
        ]
        == get_version()
    )


def test_listenbrainz_invalid_token_and_unacknowledged_import() -> None:
    with pytest.raises(ScrobbleError, match="rejected"):
        ListenBrainzClient(TransportStub({"valid": False})).validate_token("bad")
    with pytest.raises(ScrobbleError, match="acknowledge"):
        ListenBrainzClient(TransportStub({"status": "error"})).submit(
            (LISTEN,), CREDENTIALS
        )


def test_rate_limit_wait_is_cancellable_and_long_pauses_stop_the_run() -> None:
    client = ListenBrainzClient(TransportStub())
    client.retry_after = 5
    cancelled = Event()
    cancelled.set()
    assert not wait_between_batches(client, cancelled, lambda: None)
    client.retry_after = 61
    with pytest.raises(ScrobbleError, match="longer pause"):
        wait_between_batches(client, Event(), lambda: None)
