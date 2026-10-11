# Classic chapter records after the ALAC artwork test

## Observed result and provenance

After a 6.5th-generation Classic received the F1029 representations and
`artwork_count = 2`, the user reported that its normal Now Playing screen still
did not switch artwork at 15 seconds. The user then created chapters at 0 and
15,000 ms through **Metadata Editor → Chapters** on the same ALAC Tracks and
reported that chapters were not visible on the iPod either. These are
first-person playback observations, not a controlled firmware trace.

A subsequent read-only capture of the connected device is stored privately in
`.scratch/diagnostics/timed-artwork-physical-20261011T152709Z/`. The captured
ArtworkDB SHA-256 is
`2e9597ace82f412f67591f0281c75068dd19713b52bb6f1236abcf76fef87ad2`,
matching the F1029/count-two publication. The captured iTunesDB SHA-256 is
`1feb43d1ebb8d6f94998f24f9e79afb23576ec8cd08ae86f2bc759ffd83842bf`;
its chapter records are summarized in the private `chapter-inspection.json`.
The capture was taken after the user's chapter edits, so it establishes saved
database bytes rather than the display behavior that produced the report.

| Captured Track group | Tracks | Media type | `sean` field at `+8` | Child count | Terminal `hedr` | Chapter starts |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| Existing chaptered Tracks | 13 | 64, TV show | 1 | chapter count + 1 | present | includes 0 |
| Existing chaptered Track | 1 | 2, video | 1 | 16 | present | includes 0 |
| Newly edited ALAC Tracks | 15 | 1, ordinary audio | 0 | 2 | **absent** | 0 and 15,000 ms |

The existing Tracks' terminal 28-byte `hedr` atoms have big-endian fields
`(1, 0, 0, 0, 1)` after the atom type. The new Tracks
have two `chap` children and no `hedr`. This is an observed difference within
one device. It does not prove that the media type, `sean` field, or omitted atom
is the reason the Classic hid the chapters.

## Producer comparison

Two pinned third-party implementations always append `hedr` when writing
MHOD 17 chapter data and set the `sean` child count to chapter count plus one.
[libgpod's writer][libgpod-writer] emits a 28-byte `hedr` with fields
`(1, 0, 0, 0, 1)`, matching the captured existing Tracks.
[foo_dop's writer][foo-writer] also appends `hedr`, though its final data words
come from its chapter list and may differ. The [libgpod reader][libgpod-reader]
subtracts one from `sean`'s child count to determine the chapter count, on the
assumption that the final child is `hedr`. These implementations are producer
and parser evidence; neither is a specification for every Apple firmware.

The implementations disagree on `sean`'s field at `+8`: libgpod writes 1,
foo_dop writes 0. The current iOpenPod writer uses 0, so that field alone
cannot be labeled invalid. The existing captured Tracks start at 0 ms,
so a first-chapter position of 0 cannot be ruled out from this case either.

The Metadata Editor writes an iTunesDB MHOD 17 record. It does not add
chapters to the ALAC file's MP4 container. The earlier bounded `moov` captures
of these 15 media files each found only a `soun` handler and an `alac` sample
entry; none contained the literal markers `chpl`, `chap`, or `tref`. That is a
limited inspection of an earlier media snapshot, not a fresh full-container
audit. [foo_dop's import flow][foo-import] *reads* chapter data from MP4 and
then serializes database chapter data; that does not establish whether firmware
requires both representations. The current readback also cannot show whether
ordinary-audio ALAC Tracks are chapter eligible in this firmware. All 14
preexisting chaptered Tracks observed on the device are TV show or video
media types. An earlier version of this note incorrectly labeled raw codes 64
and 2 as podcast and audiobook; those codes are 4 and 8 respectively. This
correction does not change the captured chapter bytes or the missing-atom finding.

The earlier [Video 5G emulator timing test](artwork-timing-experiments.md)
switched an MP3's artwork without MHOD 17 chapter data. That result is scoped
to its emulated firmware and codec, but it means a missing `hedr` cannot yet
be claimed as the cause of this Classic's timed-artwork failure. It is a
separate, concrete explanation to test for the missing chapter navigation.

## Implementation and remaining test

The Library writer's new-chapter branch omitted `hedr`. It now writes the
locally observed/libgpod-shaped terminal atom; the encoder derives the
`sean` child count from the emitted children. An explicit chapter edit also
repairs the simple hedrless shape produced by the earlier iOpenPod branch,
provided there are no opaque chapter atoms or trailing bytes. Unchanged
database records and unfamiliar chapter extensions remain byte-exact.
Regression tests cover creation on an existing ordinary-audio Track and a
subsequent edit of an earlier app-authored hedrless record.

The connected device was **not modified** during this investigation. A useful
next physical comparison is to edit a chapter title on one affected Track with
the corrected application, save, read back that one Track's MHOD 17, and replay
past 15 seconds. Observe chapter navigation and the normal/expanded artwork
views separately. This changes the chapter record while keeping its timing,
artwork representations, count, media classification, and ALAC content fixed.
Visible chapter navigation would support the chapter-encoding hypothesis for
that device. Whether the artwork switches remains a separate observation.
Failure would leave media classification, embedded MP4 chapters, firmware
behavior, and artwork refresh as distinct possibilities.

## Subsequent physical result

The user subsequently reported: **chapters now work, but the later artwork still
does not appear**. This supports the chapter-record fix on the tested device and
shows that visible chapters alone did not resolve timed artwork in this case.
It is a first-person playback result; no fresh database capture accompanies this
report. The user confirmed that the Tracks are **still Music** and only normal
Now Playing was tested. This is evidence for working chapter navigation on that
Music setup, not for artwork refresh in every view. See the updated
[media-kind investigation](artwork-count-and-classic-timing.md#after-chapter-navigation-was-fixed).

[libgpod-writer]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_itunesdb.c#L4415-L4466
[libgpod-reader]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_itunesdb.c#L1669-L1721
[foo-writer]: https://github.com/reupen/ipod_manager/blob/08e0657b5ee09bd05cdb60273e1a139205d4d3f6/foo_dop/chapter.h#L179-L200
[foo-import]: https://github.com/reupen/ipod_manager/blob/08e0657b5ee09bd05cdb60273e1a139205d4d3f6/foo_dop/file_adder.cpp#L555-L577
