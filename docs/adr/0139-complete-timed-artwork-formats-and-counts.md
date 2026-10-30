# ADR-0139: Complete timed artwork formats and counts

- Status: Accepted
- Date: 2026-10-11
- Extends: ADR-0138
- Extended by: ADR-0202 for explicit chapter-artwork flag coordination

## Context

The first timed-artwork implementation reused each Device Profile's ordinary
cover formats and wrote MHIT `artwork_count` as a presence flag. A physical Classic
6.5G readback confirmed distinct saved images at zero and 15 seconds, but the user
reported that normal Now Playing did not switch. Historical producers distinguish
Classic chapter formats F1055/F1029 from its cover formats. The existing writer
supplied F1055 but omitted F1029. See the [readback](../research/ithmb/classic-timed-artwork-readback.md)
and [source comparison](../research/ithmb/artwork-count-and-classic-timing.md).

The user requested both the additional format and a count matching the artwork
sequence for another device test. This is an explicit authoring-policy decision;
it does not establish that either change is required by Apple firmware. The
successful Video emulator fixture and foo_dop both use count one with timed images.

## Decision

Device Registry describes chapter formats separately from ordinary cover formats.
The Classic family uses the source-supported F1055/F1029 set, reusing existing
pixel layouts. Nano 5 uses F1073, reusing its existing 240-by-240 cover layout
with the Chapter artwork role. Its RetailOS 1.0.2 capability emitter and native
Chapter flag reader are independently verified in the
[nano 5 investigation](../research/nano5-chapter-artwork-contract.md). Other
profiles are not assigned inferred chapter sets. The
Application Layer supplies these layouts to iPodDB independently of cover layouts
and includes them when reading artwork. Existing cover definitions and shard caps
remain unchanged.

An explicitly authored timed sequence supplies the union of cover and chapter
formats at each ordinary display time. Duplicate IDs with identical layouts are
encoded once; conflicting layouts are rejected. Retained groups preserve their
existing representations and Unknown Data. Missing target representations are
generated from the largest decodable retained representation using captured
source bytes. Failure to decode a required source blocks preparation. Retained
special time `0xFFFFFFFF` is not augmented. An ordinary new cover uses cover
formats only. Replacing a cover also refreshes known chapter representations
already present at zero, so that they cannot retain the previous image. An
untouched Library remains byte-exact.

For changed artwork relationships, MHIT `artwork_count` is the number of distinct
saved Artwork Display Time groups, including a retained special group. Multiple
thumbnail sizes at one time count as one image; zero/15,000-ms groups count as two.
Removal writes zero, and a count beyond the native u16 range rejects preparation.
The count is an authoring policy, not a new editable application field. Verification
checks it against the serialized groups independently of the presence flag.

## Consequences

Existing edited sequences can acquire missing chapter representations without
replacing their original pixels or thumbnail references. This may require capture
of a full source shard even when that shard is not an append candidate. New
representations follow the existing bounded allocation and verified Storage save
workflow; device signing requirements remain in force.

Testing both changes together can establish whether their combination works on
the tested device. It cannot establish which change mattered. MHOD17 chapter
metadata, sentinel placement, media classification, and media files are not changed
by this decision. Firmware playback success must be recorded separately from
successful database preparation and publication.

Nano 5 adoption enables the existing explicit-timeline Chapter flag coordination
in both CDB and Extras. F1073 is shared between cover and Chapter roles, so this
capability correction does not add pixels or alter the ordinary cover layouts.
Virtual-device regressions verify saved flags, retained unknown bits, identical
pixel bytes, and ordinary-cover flag preservation. Physical display acceptance
remains separate from the verified native flag gates.
