"""Older iTunes left duplicate native browse records; additions must still write."""

from tests.iPodDB.library.test_artist_browse_case import add_track, artist_source

from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhii import MhiiHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.library.writing import IssueSeverity


def test_addition_keeps_the_native_artist_record_owning_most_members() -> None:
    # Two native artist rows carry one name and each owns a Track: the shape
    # older iTunes leaves behind when a rename left the old record in place.
    source = artist_source(names=("DJ OKAWARI", "DJ OKAWARI"))
    result = add_track(source, "DJ OKAWARI")

    assert result.prepared is not None, result.issues
    checked = parse_iTunesDB(result.prepared.itunes)
    refs = {s.chunk.header.artist_id_ref for s in checked.find_chunks(MhitHeader)}
    assert len(refs) == 1, refs
    assert refs <= {6, 9}, refs
    warnings = [
        issue for issue in result.issues if issue.code == "library.ambiguous_group"
    ]
    assert warnings, result.issues
    assert all(issue.severity is IssueSeverity.WARNING for issue in warnings)


def test_addition_never_invents_a_third_artist_record() -> None:
    source = artist_source(names=("DJ OKAWARI", "DJ OKAWARI"))
    result = add_track(source, "DJ OKAWARI")

    assert result.prepared is not None, result.issues
    checked = parse_iTunesDB(result.prepared.itunes)
    assert len(checked.find_chunks(MhiiHeader)) == 2
