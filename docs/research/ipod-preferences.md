# iPod Preferences format evidence

Investigated 2026-09-30 for the pure iPodDB preference codecs. Two different binary
artifacts are involved: `iPod_Control/Device/Preferences` stores device settings,
while `iPod_Control/iTunes/iTunesPrefs` stores iTunes settings. The companion
`iTunesPrefs.plist` is a separate artifact; its schema is outside this increment.
Neither binary file is an application settings file or a general Apple property
list. See the API contract in [ipod-preferences.md](../ipod-preferences.md).

## Established timezone layouts

[libgpod's timezone reader](https://github.com/gtkpod/libgpod/blob/main/src/itdb_tzinfo.c#L249)
selects these exact lengths, then reads a signed little-endian 16-bit value:

| Bytes | Offset | Source's device examples | Encoding |
| --- | --- | --- | --- |
| 2,892 | `0xB10` | Fourth generation | Zone/DST code |
| 2,924 | `0xB22` | Video | Minute-based code |
| 2,952 | `0xB70` | nano 3 / Classic | City ID |
| 2,956 | `0xB70` | Classic | City ID |
| 2,960 | `0xB70` | nano 4 | City ID |

For fourth generation, validate `0 <= raw <= 48`, subtract 25, then compute
`((adjusted >> 1) + (adjusted & 1)) * 3600`. Testing parity before subtraction is
incorrect. The Original iOpenPod does that and differs by one hour. For Video,
compute `raw * 60 - 28800`; the primary reader accepts offsets within ±12 hours.
See [the conversion functions](https://github.com/gtkpod/libgpod/blob/main/src/itdb_tzinfo.c#L117).

The source has no model parameter, signature check, or Preferences writer. Its
fallback to the Host offset is an application policy that this codec does not adopt.

[A Classic owner's tested patch](https://sourceforge.net/p/gtkpod/mailman/message/27578577/)
confirms city values at `0xB70` and shows that another file length was needed for
the same broad model family. That report read 32 bits; libgpod consumes 16. The
codec models only the two evidenced bytes and preserves the following two.

The existing iPodDB city catalog was checked against all 204 entries of
[libgpod's city table](https://github.com/gtkpod/libgpod/blob/main/src/itdb_tzinfo_data.h)
and matches exactly. It has no entry for city zero. The catalog is now owned by the
Preferences module and re-exported from its former device-time location.

## Other documented Device/Preferences fields

The [preserved iPodLinux format research](https://github.com/raleighlittles/iTunesDB-Parser/blob/main/itunesdb_docs/README.md#L18945)
supplies these additional byte fields:

| Offset | Field | Documented interpretation | Evidence scope |
| --- | --- | --- | --- |
| `0xAF8` (2808) | Language | English = 0 | Model unspecified |
| `0x6BC` (1724) | DST adjustment | Off = 0; on = 60 | nano 3 |
| `0xB50` (2896) | Volume limit | Range 0–64 | Video/nano firmware 1.1.1 |

Language is exposed as a retained code in known layouts. A later parser's author
[reports testing language choices on an iPod](https://github.com/raleighlittles/iTunesDB-Parser/blob/main/parser/src/preferences.rs#L24),
but does not identify its exact model. Its mapping aliases several Portuguese and
Chinese codes and also treats 1 as English. That evidence does not establish a
complete, generation-independent language enumeration.

The DST and volume fields require explicit model/firmware interpretation beyond
the length-selected timezone layout. A file length alone cannot establish these
settings' availability. In particular, zero is an observed volume-limit value;
there is no established rule that it means the limit is disabled. The independent
DST byte must not automatically be added to the city-based timezone conversion.

The historical wiki's city example for Zurich disagrees with libgpod's table.
Use the latter for the existing catalog rather than combining incompatible maps.
The [later parser's constants](https://github.com/raleighlittles/iTunesDB-Parser/blob/main/parser/src/constants/preferences_constants.rs#L9)
also change the timezone offset without selecting a layout, and its
[decoder acknowledges incorrect results](https://github.com/raleighlittles/iTunesDB-Parser/blob/main/parser/src/preferences.rs#L15).
That implementation does not override libgpod's model-specific timezone evidence.

## Documented binary iTunesPrefs fields

The [historical iTunesPrefs table](https://github.com/raleighlittles/iTunesDB-Parser/blob/main/itunesdb_docs/README.md#L16864)
describes an `frpd` marker and the following settings. Offsets are decimal; entries
are one byte unless noted. Boolean settings use 0/1; modes use manual = 0,
automatic = 1; selections use all = 1, selected = 2.

| Offset | Field |
| --- | --- |
| 8 | Setup completed |
| 9 | Open iTunes on attachment |
| 10 / 11 | Music sync mode / selection |
| 12 | Linked library identifier, 8 bytes |
| 31 | Disk use |
| 34 | Checked tracks only |
| 49 | Show artwork |
| 52 / 55 | Sync photos / retain originals |
| 72 / 73 | Transcode / retain source-list entry |
| 89 / 90 | Podcast selection / sync mode |
| 96 | Second library identifier, 8 bytes |
| 124 | Sound Check |

Transcoding, source-list visibility, and Sound Check were documented in a Shuffle
context. Exposing retained binary settings does not establish their effect on
every Device Profile. The two identifiers remain separate stored values: although
the source describes a repeated identifier, a codec must not silently repair a
mismatch.

The source describes a 236-byte file, which provides the historical minimum for
this codec's common layout, not a universal exact length. Bytes 4–7 are labeled
unknown in the source; retain them without inventing a version contract. The
two-byte fields at offsets 104 and 106 have only tentative Shuffle capacity
interpretations. Their units and formulas remain unresolved; keep them as Unknown
Data rather than presenting track counts or byte capacities.

[foo_dop's reader](https://github.com/reupen/ipod_manager/blob/main/foo_dop/reader.cpp#L502)
reads byte `0xF9` (249) as VoiceOver enabled when nonzero. Its
[iTunesSD writer](https://github.com/reupen/ipod_manager/blob/main/foo_dop/writer_itunessd.cpp)
uses that value for a Shuffle database header. This supports an explicit Shuffle
interpretation when the byte exists, not a universal extension inferred merely
from a file being longer than 236 bytes.

## Local file observations

The following user-supplied files were read, without modification:

| File context | Length | LE16 at `0xB70` | Catalog interpretation |
| --- | --- | --- | --- |
| `ipods/nano5/iPod_Control/Device/Preferences` | 2,960 | `0x1D` | New York |
| `ipods/orig_nano7/iPod_Control/Device/Preferences` | 2,960 | `0x00` | Unknown |
| Connected `D:/iPod_Control/Device/Preferences` | 2,956 | `0x21` | Detroit |

These are observations of captured bytes, not independent verification of each
device's displayed setting. The nano 7 observation does not establish whether that
firmware uses another setting source or treats zero specially. It must not be
interpreted as proof of UTC. No personal captures are committed as fixtures.

All three files have zero at the documented language, DST, and volume-limit byte
offsets. The first four bytes represent little-endian 61 in the 2,956-byte file
and 62 in the two 2,960-byte files. These observations do not establish a header
version contract or independently validate the meanings of all setting offsets.

The sibling `iPod_Control/iTunes/iTunesPrefs` files in all three locations are
1,232 bytes, beginning `66 72 70 64 01 00 19 00`. The documented common flag values
fit their known ranges and the two library identifiers match in each file. This
is evidence to preserve longer files, not proof of a complete 1,232-byte schema.
No usernames, hostnames, library identifiers, or other personal capture contents
are committed to the repository.

## Unresolved formats and writer limits

A [first-hand nano 6 filesystem listing](https://gist.github.com/uroboro/9557b5535f1685cb4151b67e5c24026f)
shows a 2,960-byte Preferences alongside `iPodSettings.xml`; file length alone does
not identify a model or prove which artifact controls its clock. An
[older device report](https://bugzilla.gnome.org/show_bug.cgi?id=358029) also contains
a 2,912-byte Preferences outside the supported set. Neither observation supplies
enough field evidence to add another decoded layout.

The Original iOpenPod's `src/iopenpod/sync/itunes_prefs.py`, inspected at local
revision `a20242428b93b672d14b37230772dbad75139c69`,
[parses 128-byte history records starting at byte 384](https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/sync/itunes_prefs.py#L206).
Its [writer also claims those records prevent macOS reinitialization](https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/sync/itunes_prefs.py#L554).
Neither the record schema nor that behavioral claim was independently corroborated
in this investigation. They must not become trusted typed fields or automatic
mutations in iOpenPod 2.0. Keep this tail opaque.

No complete firmware schema, whole-file checksum contract, or verified on-device
write procedure was established for these binary artifacts. Their inverse writers
overlay supported fields on retained bytes, preserving original size, unknown
codes, header bytes, and tails. They do not synthesize factory defaults, infer
missing model capabilities, or claim hardware acceptance. Unknown
Device/Preferences lengths remain opaque, with explicit layout assertions
available when the caller has additional evidence. Codec serialization does not
publish files: persistence remains an Application Layer and Storage workflow.
