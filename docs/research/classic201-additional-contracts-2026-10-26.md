# Further Classic import and Smart rule corrections

Research date: **2026-10-26**. This pass compares the existing firmware research
with iOpenPod's actual projections, authors and refresh paths. It extends
[the field report](classic201-itunesdb-semantics-2026-10-26.md) and
[the clock report](classic201-clock-semantics-2026-10-26.md);
[ADR-0198](../adr/0198-adopt-native-rule-operands-and-import-markers.md) records
the product decisions.

## Evidence and scope

The firmware remains Classic 120GB RetailOS 2.0.1, updater family 33. Normalized
OSOS is 10,513,984 bytes with SHA-256
`220913cb8569af0538a7e828f1aaa08d9313bf9a5c2b0a7a7e6e2dc0bee5f16e`.
The osos-lab baseline is `d2c8e357d58591bdaa70bb6be9da191f489554a6`;
DRAM maps runtime `0x08000000` to image offset `0xb65c`.

Existing reports establish the importer and comparator behavior. An additional
read-only Ghidra export resolves the boolean operand getter at `0x08032fd8`:
its entire 112-byte body matches the pinned image. The export verified all three
initialized program regions; an independent instruction-byte check also passed.
This is static evidence, not execution or recovered Apple source. Product tests
use synthetic data and do not require firmware binaries or a connected iPod.

## Podcast group discrimination

Playlist importer `0x08072f30`, at `0x08073770..0x08073778`, loads byte MHIP
`+0x11` and compares it with zero. Every nonzero byte takes the group branch.
MHIP `+0x10` is a different input: its nonzero value can set shared Track unchecked
state in the firmware. The two bytes must not be collapsed into one boolean.

iPodDB initially retained them together as the raw u16 `podcast_group_flag`. Testing only
`value & 0x0100` misclassified `0x0200` and `0x8000` as ordinary occurrences.
When such a group carried an ID matching a Track, it could leak into projected
membership; different consumers could also flatten or verify it incorrectly.

The initial correction made the shared derived predicate test `value & 0xff00`.
The [2026-10-28 follow-up](../../../ipod-firmware-lab/notes/itunesdb/mhip-control-bytes.md)
replaces the combined field with actual u8 `unchecked_override` and `group_marker`
fields; the predicate now tests `bool(group_marker)`. All relevant consumers
use that predicate. New groups still use marker byte `1`; retained noncanonical
markers and the independent low byte survive understood edits. Deleting a Track
also leaves hidden groups intact when their unused Track-ID word happens to match
the deleted identity. The MHYP
`playlist_kind_flags & 0x0100` Folder test is a separate field and stays unchanged.
This does not adopt the firmware's unresolved-parent dropping or other permissive
import behavior. See the [hierarchy investigation][hierarchy].

## Boolean rules compare an operand

Track rule evaluator `0x08049778` obtains the right-hand boolean operand through
`0x08032fd8` before calling comparison logic at `0x080237bc`. The getter:

1. Requires a numeric criterion with a nonnull payload and length `0x44`.
2. Copies the first eight payload bytes into a native 64-bit value.
3. Writes false for zero, true for any nonzero value, including high-word-only
   values. It does not merely inspect the low byte.

The comparator's equality action `0x00000001` compares those booleans; action
`0x02000001` negates that comparison. Two fields in the examined Track switch
establish the following relationship:

| Smart field | Native input | Host meaning | Canonical right operand |
| --- | --- | --- | --- |
| `0x1d` | Unchecked flag | Checked is the inverse | `0` |
| `0x1f` | Compilation flag | Compilation follows the flag | `1` |

With these canonical operands, equality authors `IS_TRUE` and inequality authors
`IS_FALSE`. Imported rules can use the opposite operand/action combination for
the same meaning, and any nonzero 64-bit operand means true. Projection now
accounts for both pieces; unchanged encodings remain retained.

Previously both fields used operand zero, while projection inferred truth solely
from the action. Checked happened to be correct for that canonical operand, but
Compilation was reversed. For example, Compilation/equality/zero means
"not a compilation" to the inspected firmware. Naming it true on the Host and
refreshing membership from that name changes the rule's effect.

These are suitable analyst names for the recovered operations:
`ReadNumericRuleBooleanOperand` (`0x08032fd8`) and `CompareRuleBooleans`
(`0x080237bc`). They are documentation proposals, not Apple symbols or a claim
that all boolean rule fields use this Track path. Artwork and Purchased retain
their existing interpretation pending separate evidence.

## Signed numeric bounds and malformed text

Comparator `0x08023928` uses signed 64-bit ordering. The former Host numeric
domain allowed values through `0xffffffffffffffff`, which Python compares as
positive integers. A play-count condition "less than `0x8000000000000000`"
therefore selected ordinary counts on the Host even though that firmware bound
is the most negative signed value.

The editable nonnegative domain now ends at `0x7fffffffffffffff`. Imported
active numeric operands outside that domain remain Unsupported Smart Rules; an
unused upper operand does not restrict a single-bound operator. The Host
does not guess a new signed intent or reevaluate their membership. This limit
does not apply to boolean nonzero tests or reinterpret signed relative-date
displacement slots. The [operator investigation][operators] explains the native
comparison domain.

Malformed UTF-16 rule text was another projection loss: decoding with replacement
could invent U+FFFD and expose an editable rule that automatic refresh would then
evaluate. Such inputs now remain unsupported with their native data and saved
membership retained. Valid supplementary Unicode text remains distinct from
unpaired surrogate units. This is a Host preservation decision; it does not
claim complete compatibility with firmware collation or malformed-text handling.

## City identity corrections

The [verified Classic city table][timezones] has 205 rows and independently
resolved base offsets. Offset agreement alone cannot identify a geographical
zone. The corrections below additionally use city labels from a
[pinned libgpod table][city-labels] and geographical coverage in pinned IANA data.
Historical IANA interpretation remains Host policy, not a claim of firmware DST
parity.

| City ID and label | Previous mapping | Corrected mapping | Firmware base minutes |
| --- | --- | --- | --- |
| `0x18` San Jose | `PST8PDT` / Los Angeles | `America/Costa_Rica` | `-360` |
| `0x36` San Juan | `America/Argentina/San_Juan` | `America/Puerto_Rico` | `-240` |
| `0x41` Rio de Janeiro | `Africa/Casablanca` | `America/Sao_Paulo` | `-180` |
| `0x95` Victoria | Missing | `Indian/Mahe` | `+240` |

IANA's [North America source][northamerica] ties the first two names to their
geographical zones. Its [South America source][southamerica] includes Rio de
Janeiro in the Sao Paulo region. [Backzone][backzone] identifies Victoria in the
Mahe entry, corroborated by the Seychelles row in [zone.tab][zone-tab]. These
labels and offsets distinguish similarly named cities on other continents.

City `0x26` remains different: the inherited label is Manchester with a London
mapping, but this Classic image resolves its base offset to `-300` minutes.
The evidence does not justify inventing a replacement city identity. The qualified
Classic profile preserves the city word and withholds the contradictory name.
Generic profiles retain their existing policy. The existing valid MHBD fallback
remains available and visibly reports the unresolved-city reason; it is a fixed
offset and does not recover historical DST.

No saved Preferences bytes or retained database date words are changed by these
interpretation corrections. A newly requested date write uses the corrected
context, subject to ordinary range/fold validation. Historical intent behind
dates written with a previously wrong zone cannot be reconstructed automatically.

## Remaining research-to-product work

These findings do not exhaust the research. The following seams remain explicit:

- **Native date write intent:** consuming ambiguous local dates or semantic-zero
  collisions safely would need a native-date contract through resolution,
  preparation and verification. The current whole-sidecar rejection preserves
  evidence instead of guessing an instant.
- **Firmware Smart calendar windows:** cached day-based endpoints differ from
  Host rolling durations. Adopting them needs an explicit evaluation context and
  cross-model policy; endpoint preservation alone does not establish parity.
- **Text encodings and collation:** the encoding-2 counted-string mismatch and
  byte/unit limits are established statically, but an authentic producer and
  controlled execution remain missing. Keep lossless retained strings and avoid
  claiming that ordinary UTF-8 authoring reproduces that native contract.
- **Hierarchy order and shared occurrence state:** forward parents, unresolved
  group references and MHIP unchecked/date-added effects have additional native
  behavior. Host hierarchy repair and generated Podcast structure remain explicit
  policies rather than a complete firmware importer emulation.
- **Extended numeric rule payloads:** the boolean getter requires exactly
  `0x44` bytes, while the Host retains numeric payload suffixes. Their native
  meaning still needs a separate compatibility decision.

The application preserves its Storage boundaries, shared Chunk definitions and
byte-exact unchanged round trips. Cross-model application of the shared rule and
group corrections is an inference consistent with ADR-0195; this pass supplies no
new physical-device or cross-firmware execution result.

[hierarchy]: https://ipod-firmware-reference.lightrhea20.chatgpt.site/#/reports/playlist-hierarchy-and-occurrences
[operators]: https://ipod-firmware-reference.lightrhea20.chatgpt.site/#/reports/smart-reevaluation
[timezones]: https://ipod-firmware-reference.lightrhea20.chatgpt.site/#/reports/timezone-and-dst-settings
[city-labels]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_tzinfo_data.h
[northamerica]: https://github.com/eggert/tz/blob/682cbf0af7d53870c7f8fe1658aa9200ec74b7ee/northamerica
[southamerica]: https://github.com/eggert/tz/blob/682cbf0af7d53870c7f8fe1658aa9200ec74b7ee/southamerica
[backzone]: https://github.com/eggert/tz/blob/682cbf0af7d53870c7f8fe1658aa9200ec74b7ee/backzone
[zone-tab]: https://github.com/eggert/tz/blob/682cbf0af7d53870c7f8fe1658aa9200ec74b7ee/zone.tab
