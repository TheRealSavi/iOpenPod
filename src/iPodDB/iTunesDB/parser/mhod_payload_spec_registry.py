"""Parser functions selected by shared iTunesDB MHOD definitions."""

from collections.abc import Mapping
from types import MappingProxyType

from iPodDB.iTunesDB.parser.mhod_parsers.chapter_data_mhod import (
    parse_chapter_data_payload,
)
from iPodDB.iTunesDB.parser.mhod_parsers.contextual_100_mhod import (
    parse_playlist_position_payload,
)
from iPodDB.iTunesDB.parser.mhod_parsers.library_index_mhod import (
    parse_library_index_payload,
)
from iPodDB.iTunesDB.parser.mhod_parsers.library_jump_table_mhod import (
    parse_library_jump_table_payload,
)
from iPodDB.iTunesDB.parser.mhod_parsers.opaque_mhod import parse_opaque_payload
from iPodDB.iTunesDB.parser.mhod_parsers.plist_mhod import parse_plist_payload
from iPodDB.iTunesDB.parser.mhod_parsers.settings_mhod import parse_settings_payload
from iPodDB.iTunesDB.parser.mhod_parsers.smart_prefs_mhod import (
    parse_smart_prefs_payload,
)
from iPodDB.iTunesDB.parser.mhod_parsers.smart_rules_mhod import (
    parse_smart_rules_payload,
)
from iPodDB.iTunesDB.parser.mhod_parsers.string_mhod import parse_string_payload
from iPodDB.iTunesDB.parser.mhod_parsers.url_mhod import parse_url_payload
from iPodDB.iTunesDB.parser.mhod_parsers.video_details_mhod import (
    parse_video_details_payload,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.contextual_100_mhod import (
    MhodPlaylistPositionPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.library_index_mhod import (
    MhodLibraryIndexPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.library_jump_table_mhod import (
    MhodLibraryJumpTablePrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.smart_prefs_mhod import (
    MhodSmartPrefsPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.smart_rules_mhod import (
    MhodSmartRulesPrefix,
)
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.string_mhod import MhodStringPrefix
from iPodDB.iTunesDB.shared.constants import MhodPayloadKind
from iPodDB.iTunesDB.shared.mhod_payload_spec_registry import MHOD_DEFINITIONS
from iPodDB.shared.types import (
    ContextualMhodPayloadSpec,
    MhodPayloadSpec,
    MhodPayloadSpecSelectionContext,
    contextual_mhod_payload_spec,
    prefixed_mhod_payload_spec,
    unprefixed_mhod_payload_spec,
)

OPAQUE_SPEC = unprefixed_mhod_payload_spec(parse_opaque_payload)
URL_SPEC = unprefixed_mhod_payload_spec(parse_url_payload)
CHAPTER_DATA_SPEC = unprefixed_mhod_payload_spec(parse_chapter_data_payload)
VIDEO_DETAILS_SPEC = unprefixed_mhod_payload_spec(parse_video_details_payload)
PLIST_SPEC = unprefixed_mhod_payload_spec(parse_plist_payload)
SETTINGS_SPEC = unprefixed_mhod_payload_spec(parse_settings_payload)

STRING_SPEC = prefixed_mhod_payload_spec(MhodStringPrefix, parse_string_payload)
SMART_PREFS_SPEC = prefixed_mhod_payload_spec(
    MhodSmartPrefsPrefix,
    parse_smart_prefs_payload,
)
SMART_RULES_SPEC = prefixed_mhod_payload_spec(
    MhodSmartRulesPrefix,
    parse_smart_rules_payload,
)
LIBRARY_INDEX_SPEC = prefixed_mhod_payload_spec(
    MhodLibraryIndexPrefix,
    parse_library_index_payload,
)
LIBRARY_JUMP_TABLE_SPEC = prefixed_mhod_payload_spec(
    MhodLibraryJumpTablePrefix,
    parse_library_jump_table_payload,
)
PLAYLIST_POSITION_SPEC = prefixed_mhod_payload_spec(
    MhodPlaylistPositionPrefix,
    parse_playlist_position_payload,
)


def _resolve_contextual_100(
    context: MhodPayloadSpecSelectionContext,
) -> MhodPayloadSpec:
    definition = MHOD_DEFINITIONS[int(context.mhod_type)]
    parent_marker = (
        context.ancestors[-1].generic_header.header_marker
        if context.ancestors
        else None
    )
    payload_kind = definition.payload_kind_for_parent(parent_marker)
    payload_spec = MHOD_PAYLOAD_SPECS[payload_kind]
    if isinstance(payload_spec, ContextualMhodPayloadSpec):
        raise ValueError(
            f"MHOD type {int(context.mhod_type)} resolved to another contextual layout"
        )
    return payload_spec


CONTEXTUAL_100_SPEC = contextual_mhod_payload_spec(_resolve_contextual_100)

MHOD_PAYLOAD_SPECS: Mapping[
    MhodPayloadKind,
    MhodPayloadSpec | ContextualMhodPayloadSpec,
] = MappingProxyType(
    {
        MhodPayloadKind.OPAQUE: OPAQUE_SPEC,
        MhodPayloadKind.STRING: STRING_SPEC,
        MhodPayloadKind.URL: URL_SPEC,
        MhodPayloadKind.CHAPTER_DATA: CHAPTER_DATA_SPEC,
        MhodPayloadKind.SMART_PREFS: SMART_PREFS_SPEC,
        MhodPayloadKind.VIDEO_DETAILS: VIDEO_DETAILS_SPEC,
        MhodPayloadKind.SMART_RULES: SMART_RULES_SPEC,
        MhodPayloadKind.LIBRARY_INDEX: LIBRARY_INDEX_SPEC,
        MhodPayloadKind.LIBRARY_JUMP_TABLE: LIBRARY_JUMP_TABLE_SPEC,
        MhodPayloadKind.PLIST: PLIST_SPEC,
        MhodPayloadKind.CONTEXTUAL_100: CONTEXTUAL_100_SPEC,
        MhodPayloadKind.PLAYLIST_POSITION: PLAYLIST_POSITION_SPEC,
        MhodPayloadKind.SETTINGS: SETTINGS_SPEC,
    }
)
