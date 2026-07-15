from __future__ import annotations

import pytest
import requests

from iopenpod.podcasts.itunes_search import search_podcasts
from iopenpod.podcasts.network_errors import PodcastNetworkError, describe_podcast_error


def test_describe_http_500_includes_simple_code() -> None:
    response = requests.Response()
    response.status_code = 500
    error = requests.HTTPError("server error", response=response)

    info = describe_podcast_error(error, action="search podcasts")

    assert info.title == "The podcast service is having trouble"
    assert info.code == "HTTP 500"
    assert "server" in info.message.lower()


def test_describe_connection_error_is_plain_language() -> None:
    info = describe_podcast_error(
        requests.ConnectionError("name resolution failed"),
        action="search podcasts",
    )

    assert info.title == "No internet connection"
    assert "Check your connection" in info.message
    assert info.code == ""


def test_search_podcasts_can_raise_ui_friendly_network_error(monkeypatch) -> None:
    def fail_get(*_args, **_kwargs):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr("iopenpod.podcasts.itunes_search.requests.get", fail_get)

    with pytest.raises(PodcastNetworkError) as exc_info:
        search_podcasts("example", raise_on_error=True)

    assert exc_info.value.info.title == "No internet connection"
