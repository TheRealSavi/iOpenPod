# Artwork count and Classic timed artwork

Research date: **2026-10-11**. This follow-up addresses a user report that an image
assigned at 15 seconds did not replace the cover on a physical iPod Classic 6.5G,
while MHIT `artwork_count` remained one. The tracks were initially described as
probably ALAC. Subsequent [read-only inspection][readback] confirmed ALAC sample
entries in all 15 affected files and recorded the firmware metadata's provenance.
The user observed the failure in normal Now Playing; expanded artwork was not
tested. This is a failed playback observation, not proof that the count caused it.

## What the count evidence establishes

The strongest producer evidence is foo_dop's import path. It passes the track's
chapter list to `add_artwork_v3`, then writes `artwork_count = 1`, `artwork_flag = 1`
and the ordinary source-image size. It does not increase the count for each
temporal image or each generated size in this path. This is concrete evidence
that a chapter-artwork producer uses one, although the code alone cannot prove
successful playback on every device. [foo_dop import][foo-import].

libgpod's thumbnail setter describes this field as the number of images embedded
in MP3 tags and assigns one when a source image is supplied. Its comment expresses
an implementation interpretation; it is not an Apple specification or evidence
that an ArtworkDB temporal-group count belongs here. Its public track description
more generally calls it the number of associated album-artwork items.
[libgpod setter][gpod-track], [track documentation][gpod-track-doc].

There is also a measured counterexample to a universal requirement for a count
greater than one. The successful [Video 5G timing experiment][timing] used count
one. A fresh byte check of the retained `timed-10000-ab` iTunesDB finds:

| Property | Value |
| --- | --- |
| MHIT file offset | 432 bytes |
| MHIT header size | 328 bytes (`0x148`) |
| Little-endian u16 at MHIT `0x7C` | 1 |
| iTunesDB SHA-256 | `2ceaecf905f99a6a8598902df4297ed88ff353a48ca82af0c3b948de078164aa` |

That experiment used Apple `iPod_20.1.3`, F1028/F1029 and synthetic MP3 playback in
an emulator. It establishes neither the Classic's behavior nor ALAC support.
The firmware analysis associated with that experiment followed MHNI selection
keys; it did not establish all uses of MHIT `artwork_count`.

**Current conclusion:** count one is consistent with existing producer behavior
and the tested firmware path. There is no evidence here that changing it to the
number of timeline entries will repair this physical-device failure.

## Classic chapter formats differ from ordinary covers

libgpod's pinned fallback tables distinguish the Classic's chapter images from
ordinary album covers:

| Role in that implementation | Format IDs and nominal dimensions |
| --- | --- |
| Ordinary Classic cover | 1061 (56×56, explicitly marked uncertain), 1055 (128×128), 1068 (128×128), 1060 (320×320) |
| Classic chapter image | 1055 (128×128), 1029 (200×200) |

The fallback is assigned to its Classic 1/2/3 generations and nano 3. If extended
device metadata exists, its getter uses that metadata instead of the fallback;
the chapter-support predicate checks whether that resulting list is nonempty.
These are libgpod's historical capability rules, not direct measurements of the
connected device. In particular, a missing fallback entry cannot establish lack
of support: the same table supplies no chapter list for Video, despite the
positive emulator experiment. [Fallback tables][gpod-formats],
[metadata precedence][gpod-getter], [support predicate][gpod-support].

foo_dop likewise stores ordinary and chapter formats separately. Its metadata
parser accepts `ChapterImageSpecs2` or `ChapterImageSpecs`, alongside the separate
`AlbumArt2`/`AlbumArt` list, and reads per-format `AssociatedFormat` and
`ExcludedFormats`. [Metadata parser][foo-plist].

Its chapter writer loops over the chapter list's formats, filtering them by the
track's media-type bits. The ordinary-cover loop uses its own list and the same
filtering mechanism. Chapter positions become MHNI display times; chapter
position one is normalized to zero, and that case puts the ordinary cover at
`0xFFFFFFFF`. These producer conventions make chapter format selection and
ordinary-cover separation stronger investigation leads than the count alone.
They do not prove which convention the connected firmware requires.
[Artwork producer][foo-artwork].

The saved groups already contain F1055, which overlaps the historical chapter
set. Consequently, missing F1029 alone is not an established explanation for
normal Now Playing failing to refresh. The broader unanswered question is which
chapter-artwork selection and refresh path this firmware uses for these tracks.

The connected device's initial inspection found no chapter-format list in its
captured SysInfoExtended, but its separate authority record identifies that file
as generated from iOpenPod's Device Registry. **This is not native-device evidence
that chapter formats are absent.** Physical inspection is recorded separately;
the fallback table must not silently be substituted for measured capabilities.

## ALAC, media kind, and chapters remain distinct questions

Apple's Classic 120GB user guide explicitly describes artwork changing during a
podcast episode. It does not document MHIT count semantics, ArtworkDB format IDs,
or guarantee changing artwork for arbitrary Music tracks. This is strong evidence
that the model family supports some form of changing artwork, with a narrower
documented use case than the editor's general timeline. [Apple guide, page 33][apple].

foo_dop extracts chapter data in its MP4/M4A extension branch and serializes that
chapter metadata separately. The inspected chapter-artwork filter tests media
kind, not an ALAC codec flag. Neither fact demonstrates that an ALAC Music track
without chapter metadata must switch images on Classic firmware. Conversely,
these sources do not establish an ALAC-specific prohibition.
[Import branch][foo-extraction], [artwork filter][foo-artwork].

The historical iPodLinux iTunesDB page could not be retrieved during this check.
libgpod acknowledges it as a source for many field descriptions, so its comments
must not be counted as an independent confirmation of an inaccessible wiki claim.
[libgpod attribution][gpod-attribution].

## Discriminating next checks

The [physical readback][readback] completed the saved-data and codec inspection;
playback comparisons below remain unexecuted.

1. Preserve the inspected MHII/MHNI keys, format IDs, ordering, paths, offsets and
   payload lengths as the failed-playback baseline. Distinct zero and 15,000-ms
   images survived Save and reload.
2. Retain model, firmware provenance, codec/container, media kind and chapter
   metadata with each comparison. Distinguish device-origin capability metadata
   from generated files, and normal Now Playing from expanded artwork.
3. On a controlled fixture, compare ordinary-cover formats against complete
   chapter-format groups, keeping pixels, timing, track metadata and count fixed.
   Missing F1029 is a hypothesis worth testing, not a sufficient diagnosis.
4. Separately test chapter metadata/media kind and ordinary-cover placement if
   needed. A known-good iTunes-authored enhanced podcast on the same firmware
   would provide a valuable reference.
5. A count-one/count-two comparison can test the count hypothesis, but must change
   only that field. It should not accompany a speculative production count change.

No production code or connected-device data was changed by this source review.

## Subsequent authoring decision

After reviewing the physical readback, the user requested both the missing chapter
representation and a count matching the number of image times for a new device
test. [ADR-0139](../../adr/0139-complete-timed-artwork-formats-and-counts.md)
records that policy. It does not change the count-one source and emulator evidence
above, or establish that the new combination fixes physical playback.

## After chapter navigation was fixed

The user reports that chapters now work after the terminal `hedr` fix, but the
second artwork image still does not appear. The Tracks remain classified as
**Music**, and only **normal Now Playing** has been tested. This rules out
missing usable chapter navigation as a sufficient explanation of the artwork
failure in that reported setup. It does not establish the behavior of the
expanded artwork view. [Chapter investigation](classic-chapter-encoding.md).

There is still no demonstrated rule restricting timed artwork to Podcasts or
Audiobooks. Apple's manual documents changing podcast artwork; it does not state
that other media kinds are prohibited. foo_dop filters each chapter format using
the device's `AssociatedFormat` and `ExcludedFormats` values, rather than a
single hardcoded podcast/audiobook-only rule. Its associated-format translation
can include ordinary audio, podcast, and audiobook bits; a zero association
accepts every media bit before exclusions. This permits a media-kind restriction
in device metadata but does not prove one for this Classic. The captured
SysInfoExtended was generated by iOpenPod and cannot settle the native masks.
[Apple guide][apple], [filter][foo-artwork], [association translation][foo-association].

The most useful next comparisons, in order, are:

1. Replay the same Music/ALAC Track and examine expanded artwork after 15 seconds.
   If that view changes while the normal view stays fixed, the remaining issue
   is specific to view selection or refresh for that setup.
2. If both views fail, compare the same chapter/artwork/media bytes under Music,
   Podcast, and Audiobook classifications in a controlled fixture. Audit native
   metadata changes and browse the corresponding device category. Classification
   workflows may also change flags or playlist placement, so success would first
   establish a difference between those prepared states, not one magic bit.
3. Separately compare the producer's ordinary-cover/chapter separation: foo_dop
   uses the chapter formats for chapter images and can put the ordinary cover at
   `0xFFFFFFFF`. Current explicit timelines emit the cover/chapter union at each
   time. That difference remains a candidate even with F1029 present; do not
   change it together with media kind in the same test.

These are proposed experiments. No classification change, artwork rewrite, or
new physical test was performed during this follow-up. The successful earlier
emulator fixture used **Video 5G firmware `iPod_20.1.3`**, not Classic firmware;
the emulator also supporting 5.5G does not change that run's provenance.

[foo-import]: https://github.com/reupen/ipod_manager/blob/08e0657b5ee09bd05cdb60273e1a139205d4d3f6/foo_dop/file_adder.cpp#L906-L918
[foo-association]: https://github.com/reupen/ipod_manager/blob/08e0657b5ee09bd05cdb60273e1a139205d4d3f6/foo_dop/photodb.cpp#L52-L92
[gpod-track]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_track.c#L413-L428
[gpod-track-doc]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb.h#L1420-L1427
[timing]: artwork-timing-experiments.md
[readback]: classic-timed-artwork-readback.md
[gpod-formats]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_device.c#L560-L620
[gpod-getter]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_device.c#L1344-L1365
[gpod-support]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_device.c#L1812-L1829
[foo-plist]: https://github.com/reupen/ipod_manager/blob/08e0657b5ee09bd05cdb60273e1a139205d4d3f6/foo_dop/plist.cpp#L371-L417
[foo-artwork]: https://github.com/reupen/ipod_manager/blob/08e0657b5ee09bd05cdb60273e1a139205d4d3f6/foo_dop/photodb.cpp#L780-L822
[apple]: https://cdsassets.apple.com/live/6GJYWVAV/user/ma630_ipod_classic_120gb_en.pdf#page=33
[foo-extraction]: https://github.com/reupen/ipod_manager/blob/08e0657b5ee09bd05cdb60273e1a139205d4d3f6/foo_dop/file_adder.cpp#L558-L573
[gpod-attribution]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb.h#L1581-L1588
