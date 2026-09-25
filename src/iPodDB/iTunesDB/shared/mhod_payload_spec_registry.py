"""Known iTunesDB MHOD meanings shared by parsing and writing."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from iPodDB.iTunesDB.shared.constants import MhodPayloadKind, MhodType


@dataclass(frozen=True, slots=True)
class MhodDefinition:
    mhod_type: int
    name: str
    payload_kind: MhodPayloadKind

    def payload_kind_for_parent(
        self,
        parent_marker: bytes | None,
    ) -> MhodPayloadKind:
        del parent_marker
        return self.payload_kind


@dataclass(frozen=True, slots=True)
class ContextualMhodDefinition:
    """MHOD meaning whose concrete payload is selected by its parent Chunk."""

    mhod_type: int
    name: str
    parent_payload_kinds: Mapping[bytes, MhodPayloadKind]

    def __post_init__(self) -> None:
        if not self.parent_payload_kinds:
            raise ValueError("a contextual MHOD definition requires parent layouts")
        for marker, payload_kind in self.parent_payload_kinds.items():
            if len(marker) != 4:
                raise ValueError("MHOD parent markers must contain exactly four bytes")
            if payload_kind == MhodPayloadKind.CONTEXTUAL_100:
                raise ValueError("a contextual MHOD parent layout must be concrete")

    @property
    def payload_kind(self) -> MhodPayloadKind:
        return MhodPayloadKind.CONTEXTUAL_100

    def payload_kind_for_parent(
        self,
        parent_marker: bytes | None,
    ) -> MhodPayloadKind:
        payload_kind = (
            None
            if parent_marker is None
            else self.parent_payload_kinds.get(parent_marker)
        )
        if payload_kind is not None:
            return payload_kind

        expected = " or ".join(
            marker.decode("ascii").upper() for marker in self.parent_payload_kinds
        )
        raise ValueError(f"MHOD type {self.mhod_type} requires an {expected} parent")


type MhodDefinitionSpec = MhodDefinition | ContextualMhodDefinition


def _mhod(
    mhod_type: int,
    name: str,
    payload_kind: MhodPayloadKind,
) -> tuple[int, MhodDefinition]:
    return mhod_type, MhodDefinition(mhod_type, name, payload_kind)


def _contextual_mhod(
    mhod_type: int,
    name: str,
    parent_payload_kinds: Mapping[bytes, MhodPayloadKind],
) -> tuple[int, ContextualMhodDefinition]:
    return mhod_type, ContextualMhodDefinition(
        mhod_type,
        name,
        parent_payload_kinds,
    )


MHOD_DEFINITIONS: Mapping[int, MhodDefinitionSpec] = MappingProxyType(
    dict(
        (
            _mhod(1, "Title", MhodPayloadKind.STRING),
            _mhod(2, "Location", MhodPayloadKind.STRING),
            _mhod(3, "Album", MhodPayloadKind.STRING),
            _mhod(4, "Artist", MhodPayloadKind.STRING),
            _mhod(5, "Genre", MhodPayloadKind.STRING),
            _mhod(6, "Filetype", MhodPayloadKind.STRING),
            _mhod(7, "EQ Setting", MhodPayloadKind.STRING),
            _mhod(8, "Comment", MhodPayloadKind.STRING),
            _mhod(9, "Category", MhodPayloadKind.STRING),
            _mhod(10, "Lyrics", MhodPayloadKind.STRING),
            _mhod(11, "Unknown (MHOD 11)", MhodPayloadKind.OPAQUE),
            _mhod(12, "Composer", MhodPayloadKind.STRING),
            _mhod(13, "Grouping", MhodPayloadKind.STRING),
            _mhod(14, "Description", MhodPayloadKind.STRING),
            _mhod(15, "Podcast Enclosure URL", MhodPayloadKind.URL),
            _mhod(16, "Podcast RSS URL", MhodPayloadKind.URL),
            _mhod(17, "Chapter Data", MhodPayloadKind.CHAPTER_DATA),
            _mhod(18, "Subtitle", MhodPayloadKind.STRING),
            _mhod(19, "Show", MhodPayloadKind.STRING),
            _mhod(20, "Episode", MhodPayloadKind.STRING),
            _mhod(21, "TV Network", MhodPayloadKind.STRING),
            _mhod(22, "Album Artist", MhodPayloadKind.STRING),
            _mhod(23, "Sort Artist", MhodPayloadKind.STRING),
            _mhod(24, "Track Keywords", MhodPayloadKind.STRING),
            _mhod(25, "Show Locale", MhodPayloadKind.STRING),
            _mhod(26, "iTunes Store Asset Info", MhodPayloadKind.STRING),
            _mhod(27, "Sort Title", MhodPayloadKind.STRING),
            _mhod(28, "Sort Album", MhodPayloadKind.STRING),
            _mhod(29, "Sort Album Artist", MhodPayloadKind.STRING),
            _mhod(30, "Sort Composer", MhodPayloadKind.STRING),
            _mhod(31, "Sort Show", MhodPayloadKind.STRING),
            _mhod(32, "Video Track Data", MhodPayloadKind.VIDEO_DETAILS),
            _mhod(33, "Unknown (MHOD 33)", MhodPayloadKind.OPAQUE),
            _mhod(34, "Unknown (MHOD 34)", MhodPayloadKind.OPAQUE),
            _mhod(35, "Unknown (MHOD 35)", MhodPayloadKind.OPAQUE),
            _mhod(36, "Unknown (MHOD 36)", MhodPayloadKind.OPAQUE),
            _mhod(37, "Content Provider", MhodPayloadKind.STRING),
            _mhod(38, "Unknown (MHOD 38)", MhodPayloadKind.OPAQUE),
            _mhod(39, "Copyright", MhodPayloadKind.STRING),
            _mhod(40, "Unknown (MHOD 40)", MhodPayloadKind.OPAQUE),
            _mhod(41, "Unknown (MHOD 41)", MhodPayloadKind.OPAQUE),
            _mhod(42, "Encoding Quality Descriptor", MhodPayloadKind.STRING),
            _mhod(43, "Purchase Account", MhodPayloadKind.STRING),
            _mhod(44, "Purchaser Name", MhodPayloadKind.STRING),
            _mhod(50, "Smart Playlist Preferences", MhodPayloadKind.SMART_PREFS),
            _mhod(51, "Smart Playlist Rules", MhodPayloadKind.SMART_RULES),
            _mhod(52, "Library Playlist Index", MhodPayloadKind.LIBRARY_INDEX),
            _mhod(
                53,
                "Library Playlist Jump Table",
                MhodPayloadKind.LIBRARY_JUMP_TABLE,
            ),
            _mhod(55, "Playlist Property Plist", MhodPayloadKind.PLIST),
            _contextual_mhod(
                100,
                "Column Size or Playlist Order",
                MappingProxyType(
                    {
                        b"mhip": MhodPayloadKind.PLAYLIST_POSITION,
                        b"mhyp": MhodPayloadKind.OPAQUE,
                    }
                ),
            ),
            _mhod(101, "Unknown (MHOD 101)", MhodPayloadKind.OPAQUE),
            _mhod(102, "Playlist Settings Binary", MhodPayloadKind.SETTINGS),
            _mhod(200, "Album (Album Item)", MhodPayloadKind.STRING),
            _mhod(201, "Artist (Album Item)", MhodPayloadKind.STRING),
            _mhod(202, "Sort Artist (Album Item)", MhodPayloadKind.STRING),
            _mhod(203, "Podcast URL (Album Item)", MhodPayloadKind.STRING),
            _mhod(204, "Show (Album Item)", MhodPayloadKind.STRING),
            _mhod(300, "Artist (Artist Item)", MhodPayloadKind.STRING),
        )
    )
)

if frozenset(MHOD_DEFINITIONS) != frozenset(MhodType):
    raise RuntimeError("every known iTunesDB MHOD type must have one definition")
