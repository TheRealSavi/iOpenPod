"""Explicit firmware Genius intent, separate from the semantic Library Snapshot.

Track references use Library Track IDs; preparation assigns persistent identities.
Updates replace the complete known graph. ``mixes=None`` preserves retained native
Mixes; an explicit tuple replaces them, including an empty tuple to clear them.
Recommendation policy belongs to the caller. Omitting an update preserves retained
Genius state. With ``mixes=None``, ``mix_additions`` and ``mix_removals`` provide
selective collection edits while preserving every unmentioned native Mix.
"""

from iPodDB.genius import (
    GeniusConfig,
    GeniusMetadata,
    GeniusSimilarities,
    GeniusSpacingRule,
    make_no_rule_genius_config,
)
from iPodDB.library._genius_reconciliation import reconcile_genius_playlists
from iPodDB.library.genius_browse import (
    GeniusBrowse,
    GeniusBrowseIssue,
    GeniusCollection,
    GeniusCollectionKind,
    project_genius_browse,
)
from iPodDB.SQLiteDB.genius import (
    GeniusConfigRow,
    GeniusData,
    GeniusDatabase,
    GeniusMetadataRow,
    GeniusSimilaritiesRow,
    parse_genius_database,
    serialize_genius_database,
)
from iPodDB.SQLiteDB.genius_projection import read_sqlite_genius_state
from iPodDB.SQLiteDB.inputs import (
    SQLiteGeniusMix as GeniusMix,
)
from iPodDB.SQLiteDB.inputs import (
    SQLiteGeniusTrack as GeniusTrack,
)
from iPodDB.SQLiteDB.inputs import (
    SQLiteGeniusUpdate as GeniusUpdate,
)

__all__ = [
    "GeniusBrowse",
    "GeniusBrowseIssue",
    "GeniusCollection",
    "GeniusCollectionKind",
    "GeniusConfig",
    "GeniusConfigRow",
    "GeniusData",
    "GeniusDatabase",
    "GeniusMetadata",
    "GeniusMetadataRow",
    "GeniusMix",
    "GeniusSimilarities",
    "GeniusSimilaritiesRow",
    "GeniusSpacingRule",
    "GeniusTrack",
    "GeniusUpdate",
    "make_no_rule_genius_config",
    "parse_genius_database",
    "project_genius_browse",
    "read_sqlite_genius_state",
    "reconcile_genius_playlists",
    "serialize_genius_database",
]
