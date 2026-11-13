"""Safe, user-facing failures from Podcast network and credential adapters."""

from enum import StrEnum

from iOpenPod.app.display_text import source_text


class PodcastFeedError(ValueError):
    """A Podcast resource could not be obtained or interpreted safely."""


class PodcastAccessFailure(StrEnum):
    REQUIRED = "required"
    REJECTED = "rejected"
    DENIED = "denied"
    UNSUPPORTED = "unsupported"
    DIFFERENT_SERVER = "different_server"


class PodcastAccessError(PodcastFeedError):
    def __init__(self, reason: PodcastAccessFailure) -> None:
        self.reason = reason
        super().__init__(
            {
                PodcastAccessFailure.REQUIRED: source_text(
                    "This Podcast requires a username and password."
                ),
                PodcastAccessFailure.REJECTED: source_text(
                    "The Podcast server rejected the login. Check your username and password."
                ),
                PodcastAccessFailure.DENIED: source_text(
                    "The Podcast server denied access. Check that your subscription is active."
                ),
                PodcastAccessFailure.UNSUPPORTED: source_text(
                    "The Podcast server requires an unsupported login method. HTTP Basic authentication is supported."
                ),
                PodcastAccessFailure.DIFFERENT_SERVER: source_text(
                    "This Podcast resource requires a login on a different server. Your feed password was not shared with it."
                ),
            }[reason]
        )
