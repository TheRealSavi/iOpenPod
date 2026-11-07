# MHII unknown words and the inherited rating name

Research date: 2026-10-28. The [firmware report][report] traces Classic 120GB
RetailOS 2.0.1 image imports, endian conversion and candidate consumers. Its
instruction-byte audit binds the results to the pinned normalized OSOS image.
These are static findings, not new physical-device observations.

| Serialized offset | Finding | iOpenPod consequence |
| --- | --- | --- |
| `+0x1C` | Ignored by the built-in Classic 2.0.1 import/display/API paths: discarded with the temporary header and not subsequently reread. | Preserve `unk_mhii_0x1c`; do not add behavior or force zero. Other firmware has not been verified. |
| `+0x20` | Also ignored by those native paths. | Retain the existing Host `rating` API, but identify its name as inherited; it has no native rating effect on these paths. |
| `+0x24` | Ascending unsigned primary key for the ordered image enumeration index. Ties compare unsigned image ID, then native pointer address. | Define `image_order_key` as an actual u32 field, retaining its zero default and every imported value. |

The Photos loader passes `Photos\Photo Database` through `0x080369D4` and
`0x080427E4` to the same image reader `0x0805E54C`. The import observations
therefore apply to ordinary ArtworkDB and PhotosDB loads in this firmware.
This does not establish every other consumer or every iPod model.

The [header-lifetime analysis][lifetime] closes the temporary buffer's lifetime.
The subsequent native image, SImage, thumbnail backlink and thumbnail wrapper
traces close the possible later reread through stored Image `+0x18`. The raster
loader uses Thumbnail `+0x18/+0x1C` for iTHMB reads, not the parent image's MHII
file position. This is an ignored-field result for these built-in paths, rather
than stopping at an unidentified consumer. It is not a claim about arbitrary
third-party code or other firmware releases.

Apparent reads of `+0x1C` on a thumbnail or an ImageLibrary cache are not reads of
the parent image member. In particular, thumbnail byte counts and cache-entry
counts do not describe MHII `+0x24`. Its positive consumer is comparator
`0x0809C104`, used by the third image index at library `+0x9D8` (`0x08030BFC`).
That index reaches ordered image enumeration API `0x082A0574` through
`0x0811C1C4`. This establishes an ordering key, not a timestamp or a promise
that every gallery and Photo Album uses this order.

PhotosDB shares `MhiiHeader`; Photo projection and editing currently expose
`rating` as a raw integer. Existing image updates retain the unknown words through
header replacement, and existing Nano 6 tests cover `+0x24` preservation. This
investigation replaces the former `unk_mhii_0x24` member with `image_order_key`
in the shared binary definition and updates its preservation tests. Literal
fixtures exercise zero, one and high unsigned values, both supported header
lengths, and independent edits without altering adjacent metadata. No synthetic
range restriction, sorting policy or guessed Boolean conversion is introduced.

Earlier [Video 5G emulator probes][emulator] found no visual difference when each
unknown word was set to 1 in a plain-MP3 workload. Those observations neither
prove non-use in PhotosDB nor supply Classic field semantics.

[report]: ../../../ipod-firmware-lab/notes/itunesdb/mhii-unknown-image-fields.md
[emulator]: ithmb/database-field-experiments.md
[lifetime]: ../../../ipod-firmware-lab/notes/itunesdb/mhii-header-lifetime.md
