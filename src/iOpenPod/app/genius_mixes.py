"""Genre proposals and ownership-aware native Genius Mix rotation policy."""

from __future__ import annotations

import json
import math
import random
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast
from uuid import uuid4

from device_registry import FeatureSupport
from iOpenPod.app.core.settings.definitions import SettingDefinition
from iPodDB.library import MediaKind, is_video_track
from iPodDB.library.genius import GeniusCollectionKind, GeniusMix

if TYPE_CHECKING:
    from collections.abc import Mapping

    from device_registry import DeviceProfile
    from iOpenPod.app.genius_audio import GeniusAudioProfile
    from iPodDB.library import LibrarySnapshot, Track
    from iPodDB.library.genius import GeniusBrowse


@dataclass(frozen=True, slots=True)
class MixDefinition:
    key: str
    name: str
    genres: tuple[str, ...]
    kind: Literal["genre", "mood"] = "genre"


# Product catalog, inspired by broad iTunes-era genre families. Stable keys and
# normalized aliases are independent of display language and native identities.
MIX_CATALOG = (
    MixDefinition("rock", "Rock Mix", ("rock", "classic rock", "arena rock")),
    MixDefinition(
        "alternative",
        "Alternative Mix",
        ("alternative", "alternative rock", "indie", "indie rock", "indie pop"),
    ),
    MixDefinition(
        "pop", "Pop Mix", ("pop", "pop rock", "dance pop", "synthpop", "synth pop")
    ),
    MixDefinition("hard-rock", "Hard Rock Mix", ("hard rock", "grunge")),
    MixDefinition(
        "metal",
        "Metal Mix",
        ("metal", "heavy metal", "progressive metal", "death metal", "thrash metal"),
    ),
    MixDefinition("punk", "Punk Mix", ("punk", "punk rock", "pop punk", "post punk")),
    MixDefinition(
        "electronic",
        "Electronic Mix",
        ("electronic", "electronica", "ambient", "downtempo", "trip hop"),
    ),
    MixDefinition(
        "dance", "Dance Mix", ("dance", "house", "techno", "trance", "edm", "disco")
    ),
    MixDefinition("hip-hop", "Hip-Hop Mix", ("hip hop", "hip hop rap", "rap")),
    MixDefinition(
        "soul",
        "R&B and Soul Mix",
        ("r&b", "r&b soul", "rhythm and blues", "soul", "neo soul", "funk"),
    ),
    MixDefinition(
        "jazz", "Jazz Mix", ("jazz", "vocal jazz", "smooth jazz", "bebop", "swing")
    ),
    MixDefinition("blues", "Blues Mix", ("blues", "blues rock", "electric blues")),
    MixDefinition(
        "country",
        "Country Mix",
        ("country", "country rock", "alt country", "bluegrass", "americana"),
    ),
    MixDefinition(
        "folk",
        "Folk and Acoustic Mix",
        ("folk", "folk rock", "acoustic", "singer songwriter"),
    ),
    MixDefinition(
        "classical",
        "Classical Mix",
        ("classical", "opera", "orchestral", "chamber music", "baroque"),
    ),
    MixDefinition("reggae", "Reggae Mix", ("reggae", "dub", "ska", "dancehall")),
    MixDefinition(
        "latin", "Latin Mix", ("latin", "latin pop", "salsa", "reggaeton", "bossa nova")
    ),
    MixDefinition(
        "soundtracks",
        "Soundtrack Mix",
        ("soundtrack", "soundtracks", "score", "film score", "musical"),
    ),
    MixDefinition("focus", "Focus Mix", (), "mood"),
    MixDefinition("love", "Love Mix", (), "mood"),
    MixDefinition("energy", "Energy Mix", (), "mood"),
    MixDefinition("relax", "Relax Mix", (), "mood"),
)
MIN_MIX_TRACKS = 10


@dataclass(frozen=True, slots=True)
class MixPolicy:
    count: int = 0
    expiry_days: int = 30

    def __post_init__(self) -> None:
        if type(self.count) is not int or not 0 <= self.count <= len(MIX_CATALOG):
            raise ValueError("Invalid automatic Genius Mix count")
        if type(self.expiry_days) is not int or not 1 <= self.expiry_days <= 3650:
            raise ValueError("Invalid Genius Mix expiry")

    def encode(self) -> str:
        return json.dumps({"count": self.count, "expiry_days": self.expiry_days})

    @classmethod
    def decode(cls, value: str) -> MixPolicy:
        payload: object = json.loads(value)
        if not isinstance(payload, dict):
            raise ValueError("Invalid Genius Mix settings")
        fields = cast("dict[str, object]", payload)
        count, expiry = fields.get("count"), fields.get("expiry_days")
        if type(count) is not int or type(expiry) is not int:
            raise ValueError("Invalid Genius Mix settings")
        return cls(count, expiry)


def _valid_policy(value: str) -> bool:
    try:
        MixPolicy.decode(value)
    except ValueError:
        return False
    return True


GENIUS_MIX_POLICY = SettingDefinition[str](
    "genius/mix-policy",
    str,
    MixPolicy().encode(),
    device_overridable=True,
    validator=_valid_policy,
)


@dataclass(frozen=True, slots=True)
class ManagedMix:
    container_id: int
    definition_key: str
    # None means manually added and never eligible for automatic removal.
    added_at: int | None = None


@dataclass(frozen=True, slots=True)
class MixState:
    entries: tuple[ManagedMix, ...] = ()
    error: str = ""


@dataclass(frozen=True, slots=True)
class MixProposal:
    definition: MixDefinition
    track_ids: tuple[int, ...]
    pending_analysis: bool = False

    @property
    def eligible(self) -> bool:
        return len(self.track_ids) >= MIN_MIX_TRACKS


@dataclass(frozen=True, slots=True)
class MixPlan:
    additions: tuple[GeniusMix, ...]
    removals: tuple[int, ...]
    state: MixState


def supports_mix_creation(profile: DeviceProfile) -> bool:
    capabilities = profile.capabilities
    return (
        capabilities.genius.mixes is FeatureSupport.SUPPORTED
        and capabilities.genius.playlists is FeatureSupport.SUPPORTED
        and capabilities.database.uses_sqlite_database
    )


def _genre(value: str) -> str:
    return re.sub(r"[\s\-_/]+", " ", value.casefold()).strip()


_LOVE_CUE = re.compile(r"\b(?:love|lover|loving|romance|romantic|amor|amour)\b", re.I)


def _mood_matches(key: str, track: Track, profile: GeniusAudioProfile) -> bool:
    """Conservative, explainable acoustic rules; these are seed suggestions."""
    from iOpenPod.app.genius_audio import GENIUS_AUDIO_FEATURE_COUNT

    if len(profile.body) != GENIUS_AUDIO_FEATURE_COUNT or not all(
        math.isfinite(value) for value in profile.body
    ):
        return False
    tempo, centroid, centroid_variance = profile.body[:3]
    if centroid <= 200 or centroid_variance < 0 or tempo < 0:
        return False
    texture_change = centroid_variance / max(centroid * centroid, 1.0)
    if key == "focus":
        return (
            (tempo == 0 or 60 <= tempo <= 145)
            and centroid <= 2800
            and texture_change <= 0.8
        )
    if key == "energy":
        return tempo >= 105 and centroid >= 1200 and (tempo >= 125 or centroid >= 2400)
    if key == "relax":
        return (
            (tempo == 0 or 50 <= tempo <= 110)
            and centroid <= 2200
            and texture_change <= 1.0
        )
    if key == "love":
        return (
            bool(_LOVE_CUE.search(f"{track.title} {track.album}"))
            and (tempo == 0 or 50 <= tempo <= 140)
            and centroid <= 3000
        )
    return False


def propose_mixes(
    snapshot: LibrarySnapshot,
    *,
    profiles: Mapping[int, GeniusAudioProfile] | None = None,
    preview: bool = False,
) -> tuple[MixProposal, ...]:
    groups: dict[str, list[int]] = {}
    music: list[Track] = []
    for track in snapshot.tracks:
        if (
            track.media_kind is MediaKind.MUSIC
            and not track.metadata.podcast
            and not is_video_track(track)
        ):
            music.append(track)
            groups.setdefault(_genre(track.genre), []).append(track.track_id)
    proposals: list[MixProposal] = []
    for definition in MIX_CATALOG:
        if definition.kind == "genre":
            ids = tuple(
                dict.fromkeys(
                    track_id
                    for genre in definition.genres
                    for track_id in groups.get(genre, ())
                )
            )
            proposals.append(MixProposal(definition, ids))
            continue
        if profiles is None:
            ids = (
                tuple(
                    track.track_id
                    for track in music
                    if definition.key != "love"
                    or _LOVE_CUE.search(f"{track.title} {track.album}")
                )
                if preview
                else ()
            )
            proposals.append(MixProposal(definition, ids, pending_analysis=preview))
            continue
        ids = tuple(
            track.track_id
            for track in music
            if (profile := profiles.get(track.track_id)) is not None
            and _mood_matches(definition.key, track, profile)
        )
        proposals.append(MixProposal(definition, ids))
    return tuple(proposals)


def plan_mixes(
    snapshot: LibrarySnapshot,
    browse: GeniusBrowse,
    state: MixState,
    *,
    manual_keys: tuple[str, ...] = (),
    remove_ids: tuple[int, ...] = (),
    policy: MixPolicy | None = None,
    profiles: Mapping[int, GeniusAudioProfile] | None = None,
    now: int,
    rng: random.Random | None = None,
) -> MixPlan:
    """Rotation removes only owned automatic Mixes; explicit removals may be external."""
    if state.error:
        raise ValueError(state.error)
    if now < 0:
        raise ValueError("Genius Mix time cannot be negative")
    native_ids = {
        item.native_playlist_id
        for item in browse.collections
        if item.kind is GeniusCollectionKind.MIX
    }
    # Missing external containers never cause deletion of an unrelated collection.
    entries = [entry for entry in state.entries if entry.container_id in native_ids]
    occupied = {entry.definition_key for entry in entries}
    proposals = {
        proposal.definition.key: proposal
        for proposal in propose_mixes(snapshot, profiles=profiles)
    }
    additions: list[GeniusMix] = []
    removals: list[int] = []
    used_ids = native_ids | {playlist.playlist_id for playlist in snapshot.playlists}
    choose = rng if rng is not None else random.SystemRandom()

    if len(set(remove_ids)) != len(remove_ids) or not set(remove_ids) <= native_ids:
        raise ValueError("A selected Genius Mix is no longer on this iPod.")
    for identity in remove_ids:
        entry = next((item for item in entries if item.container_id == identity), None)
        if entry is not None:
            entries.remove(entry)
            occupied.remove(entry.definition_key)
        removals.append(identity)

    def add(key: str, added_at: int | None) -> None:
        proposal = proposals[key]
        identity = uuid4().int & ((1 << 64) - 1)
        while not identity or identity in used_ids:
            identity = uuid4().int & ((1 << 64) - 1)
        used_ids.add(identity)
        additions.append(
            GeniusMix(identity, proposal.definition.name, proposal.track_ids)
        )
        entries.append(ManagedMix(identity, key, added_at))
        occupied.add(key)

    for key in dict.fromkeys(manual_keys):
        if key not in proposals or not proposals[key].eligible:
            if key in proposals and proposals[key].definition.kind == "mood":
                raise ValueError(
                    "This mood Mix needs at least 10 analyzed matching music Tracks."
                )
            raise ValueError(
                "This Genius Mix no longer has enough matching music. Reopen Add Mixes."
            )
        existing = next(
            (entry for entry in entries if entry.definition_key == key), None
        )
        if existing is not None:
            entries[entries.index(existing)] = ManagedMix(existing.container_id, key)
        else:
            add(key, None)

    if policy is not None:
        automatic = sorted(
            (entry for entry in entries if entry.added_at is not None),
            key=lambda entry: (entry.added_at, entry.container_id),
        )
        excess = max(0, len(automatic) - policy.count)
        for entry in automatic[:excess]:
            entries.remove(entry)
            occupied.remove(entry.definition_key)
            removals.append(entry.container_id)
        for entry in automatic[excess:]:
            assert entry.added_at is not None
            if now - entry.added_at <= policy.expiry_days * 86400:
                continue
            choices = [
                key
                for key, proposal in proposals.items()
                if proposal.eligible and key not in occupied
            ]
            if not choices:
                continue
            key = choose.choice(choices)
            entries.remove(entry)
            occupied.remove(entry.definition_key)
            removals.append(entry.container_id)
            add(key, now)
        while sum(entry.added_at is not None for entry in entries) < policy.count:
            choices = [
                key
                for key, proposal in proposals.items()
                if proposal.eligible and key not in occupied
            ]
            if not choices:
                break
            add(choose.choice(choices), now)
    return MixPlan(tuple(additions), tuple(removals), MixState(tuple(entries)))
