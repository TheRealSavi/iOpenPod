# Podcast database behavior: primary-source comparison

Research date: **2026-10-18**. This note compares the Original iOpenPod,
libgpod, and Apple manuals with the questions raised by the user-supplied
`Podcast Research` captures. The captures are imperfect producer evidence, not a
new authoring specification. Their measured contents belong in the separate
capture investigation; this note does not claim physical firmware validation.

## Evidence and scope

The Original baseline inspected here is `origin/1.x` at
`a20242428b93b672d14b37230772dbad75139c69`. The libgpod source is pinned to
`7982c5554f78dde47fd006afbeff659201d6db3d`. These are implementations of an
undocumented format, not Apple format specifications. Original's grouped writer
explicitly follows libgpod, so agreement between them is implementation lineage,
not two independent discoveries. [Original grouped writer][original-groups].

Apple manuals establish intended user-visible behavior. They do not specify
MHIP relationships, artwork field meanings, or the exact representation needed by
each firmware. Current Apple Podcasts documentation describes the modern app and
publishing service; it does not promise equivalent Finder output for older iPods.
[Classic manual, page 33][apple-classic], [current chapters documentation][apple-chapters].

## Native Podcast grouping

libgpod distinguishes the ordinary Playlist dataset 2 from optional dataset 3,
which contains the special grouped Podcasts Playlist. Its writer groups episodes
by album, emits a group before its episodes, and includes both kinds of MHIP in
the MHYP item count. [Dataset reader][gpod-datasets],
[group writer][gpod-groups].

The Original writer gives the precise authored relationship below. The offsets
come from its shared MHIP definitions; they are relative to each MHIP header.
[Original writer][original-groups], [shared definitions][original-mhip].

| Field | Show group | Episode occurrence |
| --- | --- | --- |
| `0x10`, u16, Podcast group flag | `0x0100` | `0` |
| `0x14`, u32, group/item ID | Unique nonzero group ID | Unique nonzero occurrence ID |
| `0x18`, u32, Track ID | `0` | Referenced MHIT Track ID |
| `0x20`, u32, group reference | `0` | Parent show's group ID |
| Child MHOD | Type 1, album/show title | Type 100, position equal to this occurrence's own ID |

The episode position is therefore not an ordinary zero-based display index in
this representation. Group identity and Track identity are different concepts.
Grouping uses album text, rather than RSS URL or the TV-show field. The Original
Podcast import path sets the album from the feed title, making that relationship
explicit. [Original group builder][original-groups],
[Podcast import adapter][original-import].

Preserve the separate u16 at `0x12`. The Original definitions record nonzero
`0x8000`/`0x8001` values there in an earlier Classic 6.5 capture, alongside the
`0x0100` group flag. They also retain a separate group-level u64 at `0x24` without
claiming its exact meaning. These fields must not be collapsed into one invented
32-bit flag or discarded when a group survives an edit.
[Original shared definitions][original-mhip].

### The reported Root entry

The user reports one `Root` entry on the Classic 6.5. The parallel capture
inspection found zero episode parent references on all four models, while show
headers, episode IDs, and title metadata were present. It found no literal `Root`
in the Playlist titles. These are capture findings, not claims made by the external
sources.

**Hypothesis:** missing explicit parent references may expose a firmware-specific
fallback on the Classic. This is worth testing because established writers supply
those references. It is not a proven cause: the other three devices share the
zero-reference pattern without the reported symptom, and no inspected primary
source identifies `Root` as this firmware's zero-reference fallback.
[Original authoring relationship][original-groups], [libgpod writer][gpod-groups].

A useful controlled comparison changes only the resolvable parent links, keeping
Track IDs, group IDs, group order, labels, media, and playback state fixed. Record
the Classic's show list and episode membership before and after. A successful
result would validate that repair for the tested firmware; it would not establish
that zero is universally invalid in all iTunesDB versions.

## Track metadata is independent of Playlist membership

libgpod describes media type as a bitfield: Podcast is `0x04`, audio is `0x01`,
and video is `0x02`. An audio-plus-Podcast value of `0x05` must therefore not be
rejected by a reader that expects exact equality with `0x04`. Playlist membership,
media classification, and the Podcast Now Playing marker remain distinct.
[libgpod media types][gpod-track].

The same source documents Now Playing values `1` and `2`, shuffle exclusion,
remembered playback position, and played/unplayed markers. Value `2` for the
artwork-presence field means absent, despite being nonzero. Artwork count or size
alone cannot establish a usable ArtworkDB relationship.
[libgpod Track documentation][gpod-track].

The Original definitions place release time at `0x8C`, artwork presence at
`0xA4`, shuffle exclusion at `0xA5`, resume at `0xA6`, the Podcast Now Playing
marker at `0xA7`, and media type at `0xD0` when the header contains that extension.
Readers must respect the actual header layout. [Original MHIT definitions][original-mhit].

libgpod names MHOD 15 and 16 as enclosure and feed URLs with direct UTF-8/ASCII
bodies, without the usual UTF-16 string subheader. The local Finder captures
establish that MHOD 15 actually contains Podcast GUIDs, also mirrored in SQLite;
ADR-0149 adopts that meaning while retaining the wire encoding. MHOD 14 carries
description text and MHOD 17 is separate chapter data.
[libgpod MHOD declarations][gpod-mhod].

Existing [ADR-0092][adr-playback] already chooses the application's required
Podcast playback flags and preserves recognized retained Now Playing values.
The new captures do not justify normalizing unrelated raw fields during parsing.

## Artwork and chapters: what Apple actually documents

| Model | Documented Podcast behavior | Evidence limit |
| --- | --- | --- |
| Mini 2 | Show/episode/chapter organization, resume, and an information screen. [Apple guide, page 30][apple-mini]. | This passage does not promise native artwork display. iOpenPod's application-only artwork policy is separate. |
| Nano 2 | Podcast artwork may change during playback; chapter navigation is described. [Apple Features Guide, pages 29–30][apple-nano2]. | The Apple-authored guide was read through a third-party mirror; Apple's current model page did not provide the guide. |
| Classic 6.5 / 120 GB | Podcast artwork, changing pictures, and next/previous chapter navigation. [Apple guide, page 33][apple-classic]. | No binary field or format-ID prescription. |
| Nano 5 | Show/episode/chapter organization, resume, changing artwork, and chapter navigation. [Apple guide, pages 47–48][apple-nano5]. | No guarantee that modern Finder supplies these structures. |

The Nano 2 source is the Apple manual identified as `019-0969 4/2007`, including
its Apple copyright statement, rather than commentary by the hosting site.
[Mirrored original manual][apple-nano2].

The absence of visible artwork on Mini 2 must not be combined with the color-screen
models into one firmware defect. The current project explicitly distinguishes
non-cover devices from native cover-capable profiles and can store artwork for
iOpenPod's own browser. [ADR-0118][adr-app-artwork].

An episode needs real image content and the target's artwork representation to
display artwork. A changed `has_artwork` flag cannot manufacture missing pixels.
Chapter navigation and timed artwork are also separate outputs: libgpod builds
MHOD 17 using a `sean` tree, per-chapter `chap`/`name` atoms, and a terminal
28-byte `hedr`. That blob does not contain chapter image pixels.
[Chapter serializer][gpod-chapters].

The project has already compared those chapter bytes against Original fixtures
and separately adopted Classic chapter-image layouts. Reuse those contracts rather
than inventing new layouts from captures that contain neither chapter data nor
ArtworkDB. Hardware results still require a controlled playback check.
[Chapter compatibility investigation][chapter-investigation],
[ADR-0139][adr-timed-artwork].

### Modern app chapters need not be embedded

Apple's current publishing documentation accepts chapter titles/times in episode
descriptions, an RSS `podcast:chapters` link, or media-file metadata. It also
describes automatically generated chapters. Thus a chapter visible in Apple
Podcasts is not proof that the downloaded media contains an embedded chapter track,
or that Finder authored MHOD 17. Those are separate observations to inspect.
[Apple chapter sources][apple-chapters].

The same distinction applies when evaluating a missing chapter image: first identify
where the publisher supplied it, then inspect whether the downloaded content,
native database, and artwork shards represent it. Do not generate invented chapter
titles or timing from an empty native record.

## Implications for bounded implementation

These are recommendations derived from the comparison, not new accepted decisions:

1. Keep unchanged database round trips byte-exact, including zero parent references,
   unknown group fields, and contradictory artwork hints.
2. For an affected dataset-3 Podcast edit, author explicit parent references when
   ownership is uniquely supported by the retained group and Track album. Reject
   ambiguous ownership rather than moving an episode to an arbitrary show.
3. Do not infer a new grouping capability merely because Podcast Tracks exist.
   Keep the dataset ownership and counterpart policies in [ADR-0024][adr-datasets].
4. Test compound media types, retained nonzero flags, show renames, episode deletion,
   repeated occurrences, and mismatched/duplicate group labels using synthetic
   fixtures. Compare semantic reads and native output relationships separately.
5. Treat absent chapter/artwork resources as a missing-input or missing-output
   investigation. Publish valid artwork/chapter structures through existing
   iPodDB preparation and Storage transactions when actual inputs are available.
6. Separate binary verification from firmware acceptance. The `Root` hypothesis and
   timed artwork behavior require model/firmware-specific observations.

[original-groups]: https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/itunesdb_writer/mhyp_writer.py#L416-L472
[original-mhip]: https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/itunesdb_shared/mhip_defs.py
[original-mhit]: https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/itunesdb_shared/mhit_defs.py
[original-import]: https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/podcasts/podcast_sync.py
[gpod-datasets]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_itunesdb.c#L3127-L3137
[gpod-groups]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_itunesdb.c#L5343-L5447
[gpod-mhod]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_itunesdb.c#L164-L186
[gpod-chapters]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_itunesdb.c#L4414-L4465
[gpod-track]: https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb.h
[apple-classic]: https://cdsassets.apple.com/live/6GJYWVAV/user/ma630_ipod_classic_120gb_en.pdf#page=33
[apple-mini]: https://cdsassets.apple.com/live/6GJYWVAV/user/ma96_ipod_mini_2nd_gen_userguide.pdf#page=30
[apple-nano2]: https://manualmachine.com/apple/ipodnano2ndgeneration/1975565-owners-manual/
[apple-nano5]: https://cdsassets.apple.com/live/6GJYWVAV/user/ma1194_ipod_nano_5th_gen_userguide.pdf#page=47
[apple-chapters]: https://podcasters.apple.com/support/5482-using-chapters-on-apple-podcasts
[adr-datasets]: ../adr/0024-reconcile-and-verify-playlists-by-dataset.md
[adr-playback]: ../adr/0092-enforce-podcast-and-video-playback-options.md
[adr-app-artwork]: ../adr/0118-write-application-artwork-for-non-cover-devices.md
[adr-timed-artwork]: ../adr/0139-complete-timed-artwork-formats-and-counts.md
[chapter-investigation]: chapter-data-issue-257.md
