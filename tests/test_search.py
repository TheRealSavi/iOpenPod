from iopenpod.search import matches_search, matches_search_words, prepare_search_text


def test_search_matches_equivalent_text_after_removing_symbols() -> None:
    assert matches_search("don't", "Don’t Stop")


def test_symbol_free_search_matches_text_that_contains_symbols() -> None:
    assert matches_search("dont", "Don’t Stop")
    assert matches_search("acdc", "AC/DC")
    assert matches_search("pnk", "P!nk")


def test_symbol_only_search_remains_exact() -> None:
    assert matches_search("!!!", "!!!")
    assert not matches_search("!!!", "Greatest Hits")
    assert matches_search("™", "™")
    assert not matches_search("™", "TM")


def test_single_character_symbol_free_search_remains_exact() -> None:
    assert matches_search("C#", "Learn C#")
    assert not matches_search("C#", "C Programming")


def test_search_can_match_all_terms_across_metadata() -> None:
    metadata = "Second Song\nGuns N’ Roses\nJazz"

    assert matches_search("second jazz", metadata, match_all_terms=True)
    assert matches_search("guns n' roses", metadata, match_all_terms=True)


def test_prepared_search_text_can_be_reused() -> None:
    searchable = prepare_search_text("Don’t Stop")

    assert matches_search("don't", searchable)
    assert matches_search("stop", searchable)


def test_word_search_matches_symbol_free_terms() -> None:
    assert matches_search_words("i'm", ("i’m",))


def test_word_search_can_preserve_existing_fuzzy_matching() -> None:
    assert matches_search_words(
        "ablum",
        ("album",),
        fuzzy_min_length=3,
        fuzzy_threshold=0.78,
    )
