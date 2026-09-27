"""Versioned JSON documents for on-device podcast state."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

from iOpenPod.app.podcasts.models import (
    ListeningRecord,
    PodcastClearAge,
    PodcastClearMethod,
    PodcastFillMode,
    PodcastSubscription,
    PodcastSyncSettings,
    SubscriptionSource,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

_SUBSCRIPTIONS_SCHEMA = "iopenpod.podcast-subscriptions"
_HISTORY_SCHEMA = "iopenpod.podcast-listening-history"
_VERSION = 1
_HISTORY_VERSION = 2
_HISTORY_FIELDS = frozenset(
    (
        "subscription_id",
        "episode_id",
        "guid",
        "enclosure_url",
        "title",
        "listened_override",
        "observed_play_count",
        "last_played",
        "published_at",
        "episode_number",
        "automatically_cleared",
    )
)
# Keep the established path, but older apps must reject documents whose retention
# choices they cannot preserve. Version 1 loads with Original iOpenPod defaults.
_SUBSCRIPTIONS_VERSION = 2
_MAX_SUBSCRIPTIONS = 500
_MAX_HISTORY_RECORDS = 250_000


class PodcastDocumentError(ValueError):
    """An existing Podcast state file is malformed or unsupported."""


def encode_subscriptions(subscriptions: Sequence[PodcastSubscription]) -> bytes:
    document: dict[str, object] = {
        "schema": _SUBSCRIPTIONS_SCHEMA,
        "version": _SUBSCRIPTIONS_VERSION,
        "subscriptions": [
            {
                "id": item.subscription_id,
                "feed_url": item.feed_url,
                "title": item.title,
                "source": item.source.value,
                "author": item.author,
                "description": item.description,
                "artwork_url": item.artwork_url,
                "category": item.category,
                "language": item.language,
                "last_refreshed": item.last_refreshed,
                "sync_settings": {
                    "episode_slots": item.sync_settings.episode_slots,
                    "fill_mode": item.sync_settings.fill_mode.value,
                    "clear_when_listened": item.sync_settings.clear_when_listened,
                    "clear_older_than": item.sync_settings.clear_older_than.value,
                    "clear_method": item.sync_settings.clear_method.value,
                },
            }
            for item in subscriptions
        ],
    }
    return _encode(document)


def decode_subscriptions(payload: bytes) -> tuple[PodcastSubscription, ...]:
    root = _root(payload, _SUBSCRIPTIONS_SCHEMA, versions=(1, _SUBSCRIPTIONS_VERSION))
    rows = _sequence(root.get("subscriptions", ()), "subscriptions")
    if len(rows) > _MAX_SUBSCRIPTIONS:
        raise PodcastDocumentError("The subscriptions file contains too many shows")
    subscriptions: list[PodcastSubscription] = []
    for index, value in enumerate(rows):
        row = _mapping(value, f"subscriptions[{index}]")
        try:
            source = SubscriptionSource(_text(row, "source", required=True))
            subscriptions.append(
                PodcastSubscription(
                    _text(row, "id", required=True),
                    _text(row, "feed_url"),
                    _text(row, "title", required=True),
                    source,
                    author=_text(row, "author"),
                    description=_text(row, "description"),
                    artwork_url=_text(row, "artwork_url"),
                    category=_text(row, "category"),
                    language=_text(row, "language"),
                    last_refreshed=_integer(row, "last_refreshed"),
                    sync_settings=(
                        _decode_settings(row.get("sync_settings"))
                        if root.get("version") == _SUBSCRIPTIONS_VERSION
                        else PodcastSyncSettings()
                    ),
                )
            )
        except (TypeError, ValueError) as error:
            raise PodcastDocumentError(
                f"subscriptions[{index}] is invalid: {error}"
            ) from error
    try:
        # Reuse snapshot-level uniqueness invariants without persisting GUI state.
        ids = tuple(item.subscription_id for item in subscriptions)
        if len(ids) != len(set(ids)):
            raise ValueError("subscription IDs are repeated")
    except ValueError as error:
        raise PodcastDocumentError(str(error)) from error
    return tuple(subscriptions)


def encode_history(records: Sequence[ListeningRecord]) -> bytes:
    document: dict[str, object] = {
        "schema": _HISTORY_SCHEMA,
        "version": _HISTORY_VERSION,
        "records": [
            {
                "subscription_id": item.subscription_id,
                "episode_id": item.episode_id,
                "guid": item.guid,
                "enclosure_url": item.enclosure_url,
                "title": item.title,
                "listened_override": item.listened_override,
                "observed_play_count": item.observed_play_count,
                "last_played": item.last_played,
                "published_at": item.published_at,
                "episode_number": item.episode_number,
                "automatically_cleared": item.automatically_cleared,
            }
            for item in records
        ],
    }
    return _encode(document)


def decode_history(payload: bytes) -> tuple[ListeningRecord, ...]:
    root = _root(payload, _HISTORY_SCHEMA, versions=(1, _HISTORY_VERSION))
    rows = _sequence(root.get("records", ()), "records")
    if len(rows) > _MAX_HISTORY_RECORDS:
        raise PodcastDocumentError("The listening-history file is too large")
    records: list[ListeningRecord] = []
    for index, value in enumerate(rows):
        row = _mapping(value, f"records[{index}]")
        version_two = root.get("version") == _HISTORY_VERSION
        if version_two and frozenset(row) != _HISTORY_FIELDS:
            raise PodcastDocumentError(
                f"records[{index}] must contain exactly the version 2 history fields"
            )
        override = row.get("listened_override")
        if override is not None and not isinstance(override, bool):
            raise PodcastDocumentError(
                f"records[{index}].listened_override must be true, false, or null"
            )
        try:
            records.append(
                ListeningRecord(
                    _text(row, "subscription_id", required=True),
                    _text(row, "episode_id", required=True),
                    guid=_text(row, "guid"),
                    enclosure_url=_text(row, "enclosure_url"),
                    title=_text(row, "title"),
                    listened_override=override,
                    observed_play_count=_integer(row, "observed_play_count"),
                    last_played=_integer(row, "last_played"),
                    published_at=_integer(row, "published_at") if version_two else 0,
                    episode_number=(
                        _optional_integer(row, "episode_number")
                        if version_two
                        else None
                    ),
                    automatically_cleared=(
                        _boolean(row, "automatically_cleared") if version_two else False
                    ),
                )
            )
        except (TypeError, ValueError) as error:
            raise PodcastDocumentError(
                f"records[{index}] is invalid: {error}"
            ) from error
    identities = tuple((item.subscription_id, item.episode_id) for item in records)
    if len(identities) != len(set(identities)):
        raise PodcastDocumentError("Listening-history identities are repeated")
    return tuple(records)


def _decode_settings(value: object) -> PodcastSyncSettings:
    row = _mapping(value, "sync_settings")
    listened = row.get("clear_when_listened")
    if not isinstance(listened, bool):
        raise PodcastDocumentError("clear_when_listened must be true or false")
    return PodcastSyncSettings(
        episode_slots=_integer(row, "episode_slots"),
        fill_mode=PodcastFillMode(_text(row, "fill_mode", required=True)),
        clear_when_listened=listened,
        clear_older_than=PodcastClearAge(_text(row, "clear_older_than", required=True)),
        clear_method=PodcastClearMethod(_text(row, "clear_method", required=True)),
    )


def _root(
    payload: bytes,
    expected_schema: str,
    *,
    versions: tuple[int, ...] = (_VERSION,),
) -> Mapping[str, object]:
    try:
        value: object = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PodcastDocumentError(
            f"The file is not valid UTF-8 JSON: {error}"
        ) from error
    root = _mapping(value, "document")
    if root.get("schema") != expected_schema:
        raise PodcastDocumentError("The file has an unexpected schema identifier")
    version = root.get("version")
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version not in versions
    ):
        raise PodcastDocumentError("The file uses an unsupported schema version")
    return root


def _mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise PodcastDocumentError(f"{path} must be a JSON object")
    mapping = cast("dict[object, object]", value)
    if any(not isinstance(key, str) for key in mapping):
        raise PodcastDocumentError(f"{path} must use text object keys")
    return cast("Mapping[str, object]", mapping)


def _sequence(value: object, path: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise PodcastDocumentError(f"{path} must be a JSON array")
    return cast("Sequence[object]", value)


def _text(row: Mapping[str, object], name: str, *, required: bool = False) -> str:
    value = row.get(name, "")
    if not isinstance(value, str):
        raise PodcastDocumentError(f"{name} must be text")
    result = value.strip()
    if required and not result:
        raise PodcastDocumentError(f"{name} must not be empty")
    return result


def _integer(row: Mapping[str, object], name: str) -> int:
    value = row.get(name, 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PodcastDocumentError(f"{name} must be a non-negative integer")
    return value


def _optional_integer(row: Mapping[str, object], name: str) -> int | None:
    return None if row.get(name) is None else _integer(row, name)


def _boolean(row: Mapping[str, object], name: str) -> bool:
    value = row.get(name)
    if not isinstance(value, bool):
        raise PodcastDocumentError(f"{name} must be true or false")
    return value


def _encode(value: Mapping[str, object]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


__all__ = [
    "PodcastDocumentError",
    "decode_history",
    "decode_subscriptions",
    "encode_history",
    "encode_subscriptions",
]
