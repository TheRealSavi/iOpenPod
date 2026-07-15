"""Shared text matching for user-facing searches."""

from __future__ import annotations

import difflib
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SearchText:
    """Reusable normalized and alphanumeric forms of searchable text."""

    normalized: str
    alphanumeric: str


def _normalized_text(value: str) -> str:
    return unicodedata.normalize("NFC", value).casefold()


def _alphanumeric_text(value: str) -> str:
    return "".join(char for char in value if char.isalnum() or char.isspace())


def prepare_search_text(value: str) -> SearchText:
    """Prepare reusable forms of text searched repeatedly by the UI."""
    normalized = _normalized_text(value)
    compatibility_text = unicodedata.normalize("NFKC", value).casefold()
    return SearchText(
        normalized=normalized,
        alphanumeric=_alphanumeric_text(compatibility_text),
    )


def _allows_alphanumeric_fallback(query: SearchText) -> bool:
    """Keep punctuation-only and one-character searches precise."""
    return sum(char.isalnum() for char in query.normalized) >= 2


def _query_matches(query: str, text: str, *, match_all_terms: bool) -> bool:
    if match_all_terms:
        return all(term in text for term in query.split())
    return query in text


def matches_search(
    query: str,
    text: str | SearchText,
    *,
    match_all_terms: bool = False,
) -> bool:
    """Return whether *text* contains the exact or symbol-free *query*."""
    prepared_query = prepare_search_text(query)
    prepared_text = text if isinstance(text, SearchText) else prepare_search_text(text)
    if _query_matches(
        prepared_query.normalized,
        prepared_text.normalized,
        match_all_terms=match_all_terms,
    ):
        return True
    return _allows_alphanumeric_fallback(prepared_query) and _query_matches(
        prepared_query.alphanumeric,
        prepared_text.alphanumeric,
        match_all_terms=match_all_terms,
    )


def _word_matches(
    term: str,
    word: str,
    *,
    fuzzy_min_length: int | None,
    fuzzy_threshold: float,
) -> bool:
    if term in word:
        return True
    if (
        fuzzy_min_length is None
        or len(term) < fuzzy_min_length
        or len(word) < fuzzy_min_length
    ):
        return False
    return (
        difflib.SequenceMatcher(None, term, word, autojunk=False).ratio()
        >= fuzzy_threshold
    )


def _terms_match_words(
    terms: tuple[str, ...],
    words: tuple[str, ...],
    *,
    fuzzy_min_length: int | None,
    fuzzy_threshold: float,
) -> bool:
    return all(
        any(
            _word_matches(
                term,
                word,
                fuzzy_min_length=fuzzy_min_length,
                fuzzy_threshold=fuzzy_threshold,
            )
            for word in words
        )
        for term in terms
    )


def matches_search_words(
    query: str,
    words: tuple[str | SearchText, ...],
    *,
    fuzzy_min_length: int | None = None,
    fuzzy_threshold: float = 1.0,
) -> bool:
    """Return whether every query term matches one of the supplied words."""
    prepared_query = prepare_search_text(query)
    prepared_words = tuple(
        word if isinstance(word, SearchText) else prepare_search_text(word)
        for word in words
    )
    if _terms_match_words(
        tuple(prepared_query.normalized.split()),
        tuple(word.normalized for word in prepared_words),
        fuzzy_min_length=fuzzy_min_length,
        fuzzy_threshold=fuzzy_threshold,
    ):
        return True

    return _allows_alphanumeric_fallback(prepared_query) and _terms_match_words(
        tuple(prepared_query.alphanumeric.split()),
        tuple(word.alphanumeric for word in prepared_words),
        fuzzy_min_length=fuzzy_min_length,
        fuzzy_threshold=fuzzy_threshold,
    )
