# Lyrics firmware findings adopted by iOpenPod

Target: Classic 120GB RetailOS 2.0.1. Normalized OSOS SHA-256:
`220913cb8569af0538a7e828f1aaa08d9313bf9a5c2b0a7a7e6e2dc0bee5f16e`.
Main-image mapping is runtime address minus `0x08000000` plus `0xB65C`.
Proposed names are analyst annotations, not recovered Apple source.

The [lyrics research overview](https://ipod-firmware-wiki.lightrhea20.chatgpt.site/#/reports/lyrics-overview)
links the metadata, display and Host compatibility reports. Byte audits and raw
exports remain in the companion firmware lab; production and tests require no
firmware image or connected iPod.

## Native contract and application changes

| Evidence | Consequence |
| --- | --- |
| Importer `0x08073BB8`; getter `0x0827C6A4` | Project only MHIT `+0xB0` bit zero. Raw `0x02` is false, while `0x03` is true; preserve untouched bytes. |
| ID3 reader `0x08166074` | A maximum of `0x2800` / 10,240 frame-body bytes is read, including encoding/language/descriptor overhead. |
| Decoder `0x080586BC` | Handle encoding zero as byte widening, one as BOM-sensitive UTF-16, and three as UTF-8. Encoding two has no text assignment branch. |
| Frame readers `0x080E391C`, `0x081CEA04` | A v2.4 size `00 00 01 00` means 128 by the standard but 256 to the traced native path. Validate actual traversed sizes rather than trusting the major version. |
| MP4 reader `0x0812A700` | Require one `data` child filling `©lyr`; text payload has a 10,240-byte cap. Datatype/locale words do not choose this decoder. |
| Suffix predicate `0x0827B04C` | `.m4a`, `.m4b`, `.m4p` select direct UTF-8 in the traced player. `.mp4`, `.m4v`, `.mov` do not. Successful Host tag parsing cannot prove native lyrics display for them. |
| Player service `0x081578C0` | Retrieval success can coexist with empty decoded text. Publication must compare complete decoded text, not just a success flag. |
| ExtraInfo eligibility `0x081D40F8` and item getter `0x0827AB34` | Podcast/audiobook ExtraInfo uses MHOD 14 description before the embedded-lyrics service. Keep fields separate and explain that precedence during lyrics preparation. |

The final verifier is an application authoring check, not a complete emulation
of every unsafe or permissive firmware read. It rejects ambiguous or unsupported
structures rather than claiming that Host parsing proves physical display.
WAVE/AIFF embedded ID3 inspection establishes the same tag contract, not complete
proof of all native container-reader routes. Encrypted-media support is unchanged.

## Preservation and authoring policy

New ID3 tags retain the existing v2.3 UTF-16 policy. Existing v2.3/v2.4 tags keep
their version, with unknown and unrelated frames retained by focused edits.
When an explicit native preparation finds equal text in an incompatible encoding,
it may reauthor only the lyrics frame using that version's supported encoding.
If a frame-size or byte-bound mismatch remains, publication is blocked with a
specific explanation. Full text is never silently shortened.

Mutagen documents that conversion with `update_to_v23()` can remove v2.4-only
frames. That tradeoff is why native verification does not automatically downgrade
the whole tag.
[Mutagen ID3 version guidance](https://mutagen.readthedocs.io/en/latest/user/id3.html)

Classic preparation checks the final output after focused lyrics edits and after
optional full metadata/artwork edits. The device path, final hash, database flag
and file bytes still publish through the existing reviewed Storage transaction.
Untouched retained Tracks are not scanned or rewritten by this change.

## Evidence limits

The retained `MhodType.LYRICS = 10` mapping is not established by this firmware
work. A [separate provenance review](mhod-10-provenance.md) traces it to an
unsupported application interpretation. The [firmware and capture follow-up](../../../ipod-firmware-lab/notes/itunesdb/mhod10-identity.md)
confirms Classic skips type 10 and the current captured payloads contain podcast
description HTML. Native verification of media tags does not make that legacy
database mapping correct. Removing it requires preserving unclassified records
and distinguishing any application-authored cache from other data.

The low-bit database interpretation is verified for the shared Classic format.
The native authoring gate applies to Classic Device Profiles; other families keep
their previous behavior until their contracts are established. Existing broad
Host readers continue to display standards-compliant lyrics that the Classic
may not support. They are useful for reading and repairing source files.

Physical Unicode rendering, duplicate frame selection, scrolling and exact
loading latency remain unverified. This change does not flatten SYLT timestamps,
claim karaoke support, or imitate native retry timers in the Host player.
See [ADR-0206](../adr/0206-validate-native-lyrics-publication.md).
