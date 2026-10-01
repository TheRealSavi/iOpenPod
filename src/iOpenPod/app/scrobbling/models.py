"""Typed scrobbling requests and service outcomes."""

from dataclasses import dataclass, field
from enum import StrEnum

LASTFM_MAX_AGE = 14 * 86400


class Service(StrEnum):
    LASTFM = "lastfm"
    LISTENBRAINZ = "listenbrainz"

    @property
    def label(self) -> str:
        return "Last.fm" if self is Service.LASTFM else "ListenBrainz"


class ScrobbleError(Exception):
    """Safe, credential-free diagnostic suitable for presentation."""


@dataclass(frozen=True, slots=True)
class Credentials:
    username: str
    token: str = field(repr=False)
    api_key: str = field(default="", repr=False)
    api_secret: str = field(default="", repr=False)


@dataclass(frozen=True, slots=True)
class Account:
    service: Service
    username: str

    @property
    def identity(self) -> str:
        return f"{self.service.value}:{self.username.casefold()}"


@dataclass(frozen=True, slots=True)
class Listen:
    artist: str
    title: str
    album: str
    timestamp: int
    duration: int
    album_artist: str = ""
    track_number: int = 0


@dataclass(frozen=True, slots=True)
class RejectedListen:
    listen: Listen
    code: int
    message: str = ""


@dataclass(frozen=True, slots=True)
class Submission:
    accepted: tuple[bool, ...]
    rejections: tuple[RejectedListen, ...] = ()


@dataclass(frozen=True, slots=True)
class ScrobbleResult:
    accepted: int = 0
    pending: int = 0
    skipped: int = 0
    issues: tuple[str, ...] = ()
    cancelled: bool = False
    adjusted: int = 0
    notices: tuple[str, ...] = ()

    @property
    def summary(self) -> str:
        adjusted = f", {self.adjusted} dates adjusted" if self.adjusted else ""
        return (
            f"Scrobbling: {self.accepted} accepted, {self.pending} pending, "
            f"{self.skipped} Tracks skipped{adjusted}."
        )
