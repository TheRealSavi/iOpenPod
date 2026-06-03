"""Friendly podcast network error descriptions."""

from __future__ import annotations

from dataclasses import dataclass

import requests


@dataclass(frozen=True)
class PodcastErrorInfo:
    title: str
    message: str
    code: str = ""


class PodcastNetworkError(RuntimeError):
    """Network failure with a user-facing title/message/code."""

    def __init__(self, info: PodcastErrorInfo):
        super().__init__(info.message)
        self.info = info


def describe_podcast_error(error: BaseException, *, action: str = "load podcasts") -> PodcastErrorInfo:
    """Return short, user-facing copy for podcast network/feed errors."""
    if isinstance(error, PodcastNetworkError):
        return error.info

    if isinstance(error, requests.Timeout):
        return PodcastErrorInfo(
            title="The connection timed out",
            message="The podcast service took too long to answer. Try again in a moment.",
        )

    if isinstance(error, requests.ConnectionError):
        return PodcastErrorInfo(
            title="No internet connection",
            message="iOpenPod could not reach the podcast service. Check your connection and try again.",
        )

    if isinstance(error, requests.HTTPError):
        response = getattr(error, "response", None)
        status_code = getattr(response, "status_code", None)
        if isinstance(status_code, int):
            code = f"HTTP {status_code}"
            if 400 <= status_code < 500:
                return PodcastErrorInfo(
                    title="This podcast link did not work",
                    message=(
                        "The podcast service rejected the request or the feed may have moved. "
                        "The code below can help identify the issue."
                    ),
                    code=code,
                )
            if 500 <= status_code < 600:
                return PodcastErrorInfo(
                    title="The podcast service is having trouble",
                    message=(
                        "The server answered with an error. This usually clears up after a little while."
                    ),
                    code=code,
                )
            return PodcastErrorInfo(
                title="The podcast service could not finish the request",
                message="The code below can help identify what happened.",
                code=code,
            )

    if isinstance(error, requests.RequestException):
        return PodcastErrorInfo(
            title=f"Could not {action}",
            message="iOpenPod could not reach the podcast service. Check your connection and try again.",
        )

    if isinstance(error, ValueError):
        return PodcastErrorInfo(
            title="This feed could not be read",
            message="The podcast feed answered, but it did not look like a valid podcast feed.",
        )

    return PodcastErrorInfo(
        title=f"Could not {action}",
        message=str(error) or "Something went wrong while loading podcasts.",
    )


def podcast_network_error(error: BaseException, *, action: str = "load podcasts") -> PodcastNetworkError:
    return PodcastNetworkError(describe_podcast_error(error, action=action))
