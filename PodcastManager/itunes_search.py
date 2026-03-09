"""iTunes Search API client for podcast discovery.

Uses the public iTunes Search API which requires no authentication.
https://developer.apple.com/library/archive/documentation/AudioVideo/
Conceptual/iTuneSearchAPI/Searching.html
"""

from __future__ import annotations

import logging

import requests

from .models import SearchResult

log = logging.getLogger(__name__)

_SEARCH_URL = "https://itunes.apple.com/search"
_LOOKUP_URL = "https://itunes.apple.com/lookup"
_TIMEOUT = 15  # seconds


def search_podcasts(
    query: str,
    limit: int = 25,
    country: str = "US",
) -> list[SearchResult]:
    """Search for podcasts by name.

    Args:
        query: Search term (e.g. "Serial", "Joe Rogan").
        limit: Maximum results to return (1–200).
        country: ISO 3166-1 alpha-2 country code for store region.

    Returns:
        List of SearchResult objects.  Empty list on error.
    """
    if not query.strip():
        return []

    params = {
        "term": query,
        "media": "podcast",
        "entity": "podcast",
        "limit": min(limit, 200),
        "country": country,
    }

    try:
        resp = requests.get(_SEARCH_URL, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        log.warning("iTunes Search API error: %s", exc)
        return []
    except ValueError as exc:
        log.warning("iTunes Search API JSON decode error: %s", exc)
        return []

    results: list[SearchResult] = []
    for entry in data.get("results", []):
        # Skip entries without a feed URL (can't subscribe)
        if not entry.get("feedUrl"):
            continue
        results.append(SearchResult.from_itunes(entry))
    return results


def lookup_podcast(collection_id: int) -> SearchResult | None:
    """Look up a single podcast by its iTunes collection ID.

    This can be used to resolve a podcast from a shared link.
    """
    try:
        resp = requests.get(
            _LOOKUP_URL,
            params={"id": collection_id, "entity": "podcast"},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        log.warning("iTunes Lookup API error: %s", exc)
        return None

    entries = data.get("results", [])
    if entries and entries[0].get("feedUrl"):
        return SearchResult.from_itunes(entries[0])
    return None
