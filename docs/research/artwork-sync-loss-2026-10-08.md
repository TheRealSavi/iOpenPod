# Artwork loss during Sync: format and recovery research

## Scope and confidence

Research retrieved on 2026-10-08. This is a source investigation and repair design
input, not a diagnosis of the reported physical iPod. No before/after database,
device model, firmware version, or transaction log accompanied the report.

The relevant unit of correctness is the complete association: Track, artwork
identity, ArtworkDB representation, named iTHMB range, and device format. A valid
binary tree alone cannot establish that firmware will display the right cover.
The findings below distinguish observed implementation behavior, reported hardware
observations, and proposed iOpenPod policy.

Repository context consulted: `CONTEXT.md`, `GLOSSARY.md`,
`docs/source_architecture.md`, existing ArtworkDB and UYVY research, and ADR-0033,
ADR-0111, ADR-0121, ADR-0124, ADR-0125, and ADR-0131. The Original iOpenPod reference
was also inspected at local `origin/1.x`, commit
`a20242428b93b672d14b37230772dbad75139c69`.

## Source coverage and provenance

The investigation examined more than twenty primary source files, developer
documents, and first-hand reports across the following projects. Multiple libgpod
files, mirrors, and applications using libgpod are not independent confirmations
of a format rule.

| Source family | Revision or date | Evidence and limitations |
| --- | --- | --- |
| [libgpod](https://github.com/gtkpod/libgpod/tree/7982c5554f78dde47fd006afbeff659201d6db3d) | `7982c555`, 2012-05-04 | Mature parser, writer, device tables, codecs, and SQLite projection; important historical limitations remain. |
| [foo_dop](https://github.com/reupen/ipod_manager/tree/08e0657b5ee09bd05cdb60273e1a139205d4d3f6) | `08e0657b`, 2021-04-13 | Independent C++ writer with sparse artwork and distinct allocation sizes. |
| [GNUpod source](https://www.apt-browse.com/browse/debian/wheezy/main/all/gnupod-tools/0.99.8-2.1/file/usr/share/perl5/GNUpod/ArtworkDB.pm) | Debian 0.99.8-2.1 | Published original Perl source, hosted by a package archive; independent implementation, not independent device testing of every constant. |
| [GNUpod manual](https://www.blinkenlights.ch/gnupod/gnupod.html) | Retrieved 2026-10-08 | Maintainer documentation of interoperability with iTunes. |
| [ipod-sharp](https://github.com/mono/ipod-sharp/tree/69165d82bff44065436bfe9f7ebccd692b4874fc) | `69165d82` | Independent managed reader/writer; historical format coverage is narrower than current iOpenPod. |
| [rePear](https://github.com/worstje/repear/tree/7ca8bbd704ee247e15cf9bccdb85a94b1d53d768) | `7ca8bbd7`, 2010-09-17 | Independent Python writer; related to KeyJ's earlier work. |
| [KeyJ development diary](https://keyj.emphy.de/an-ipod-hackers-diary/) | 2006-07-09 | First-hand nano experiments, including a whole-library artwork rejection caused by an incorrect count. |
| [Keith's iPod Photo Reader](https://github.com/kebwi/Keiths_iPod_Photo_Reader/tree/c15481b7abeb5750d6264ba9d1800787977294d8) | `c15481b7`, 2016-05-30 | Independent observed-device raster decoding; primarily Photos rather than album-art associations. |
| [podkit investigation](https://github.com/jvgomg/podkit/blob/abaf519a02d8dab100da627c2f4a3a3791aa760e/docs/adr/adr-013-ipod-artwork-corruption-diagnosis-and-repair.md) | `abaf519a`, ADR dated 2026-03-21 | Recent first-hand corruption measurements; writer behavior comes from libgpod and the interruption trigger remains a hypothesis. |
| [JakPod changelog](https://www.jakpod.de/changelog) | Retrieved 2026-10-08 | Maintainer reports of artwork reorganization bugs and repairs; no accompanying binary capture examined. |
| [gtkpod developer discussion](https://sourceforge.net/p/gtkpod/mailman/gtkpod-questions/thread/s2qd45479531005071657qd2a00702p900f2991bc1c81d1%40mail.gmail.com/) | 2010-05 | Distinguishes failure to transfer new covers from corruption of existing covers; shares libgpod implementation. |
| [Rockbox album-art source](https://github.com/Rockbox/rockbox/blob/master/apps/recorder/albumart.c) | Retrieved 2026-10-08 | Different firmware artwork lookup; useful to separate symptom classes, not an ArtworkDB specification. |
| [Apple TN2307](https://developer.apple.com/library/archive/technotes/tn2307/_index.html) | Retrieved 2026-10-08 | Primary YCbCr component semantics, not an iPod database specification. |
| [Microsoft YUV documentation](https://learn.microsoft.com/en-us/windows/win32/medfound/recommended-8-bit-yuv-formats-for-video-rendering) | Retrieved 2026-10-08 | Independent authoritative pixel-order and conversion reference. |

GitHub repository heads were fetched through its public API before pinning source
links. The historical iPodLinux wiki, its `ipodlinux.wiki` mirror, and an Internet
Archive snapshot were attempted but unavailable through the browser. They are
therefore not cited as freshly verified evidence. The accessible implementations
above often acknowledge that common historical reference.

Two newer search results require particular care. [libopod's own
documentation](https://docs.rs/libopod-rs/latest/libopod/) explicitly derives its
format knowledge from iOpenPod; it cannot independently validate iOpenPod's
assumptions. [ithmb-core's synthetic
builder](https://docs.rs/ithmb-core/latest/ithmb_core/photodb/builder/fn.try_build_photodb.html)
documents a reduced MHFD/MHSD/MHNI fixture structure with inline pixels. Such a
fixture does not demonstrate compatibility with the complete firmware ArtworkDB
tree and external iTHMB files.

## Findings that affect the whole lifecycle

### Track flags count source images, not thumbnail representations

libgpod sets MHIT `artwork_count` to one for a newly supplied source image and
documents it as the number of images in the media tags. It sets `has_artwork` to
one; removing artwork uses count zero, size zero, link zero, and `has_artwork` two.
This is not the number of generated MHNI sizes. Its `artwork_size` tracks source
image bytes, not the sum of packed rasters. [libgpod Track
implementation](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_track.c#L413-L428)

foo_dop independently writes count one, flag one, and encoded source size when
adding artwork, including when several device representations are generated or
an existing sparse cover is reused. This is strong evidence for authoring count
one for iOpenPod's single-cover operation. Existing counts greater than one may
describe legitimate embedded images and should not be indiscriminately normalized.
[foo_dop addition
path](https://github.com/reupen/ipod_manager/blob/08e0657b5ee09bd05cdb60273e1a139205d4d3f6/foo_dop/file_adder.cpp#L867-L929)

There is an unresolved historical size discrepancy: libgpod adds `artwork_count`
to the MHII source-size value, while foo_dop stores the original image size
directly. This does not justify a universal plus-one repair. Preserve retained
values unless the requested operation supplies a new authoritative source.
[libgpod Track
implementation](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_track.c#L413-L428),
[foo_dop image
creation](https://github.com/reupen/ipod_manager/blob/08e0657b5ee09bd05cdb60273e1a139205d4d3f6/foo_dop/photodb.cpp#L748-L775)

### Both association schemes must survive edits

libgpod explicitly recognizes the older `MHII.song_id -> Track.dbid` association
and the later `Track.mhii_link -> MHII.image_id` association. It first resolves
legacy references and then applies nonzero explicit links. Sparse artwork can
have several Tracks referencing one image identity. Its parser clears Track
artwork when a nonzero explicit link cannot resolve. That clearing is historical
behavior, not a suitable lossless-repair policy for iOpenPod. [libgpod association
code](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/db-artwork-parser.c#L464-L561)

libgpod's writer updates identities and Track links together; sparse and
non-sparse devices follow different identity-sharing paths. Therefore, changing
an image ID or deleting its apparent owner without following every incoming
Track reference is a possible library-wide failure mechanism. [libgpod ID
assignment](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/db-artwork-writer.c#L913-L1005)

For late devices the graph includes SQLite. libgpod projects the artwork flag
into `item.artwork_status`, the image identity into `item.artwork_cache_id`, and
selects a covered Track for `album.artwork_item_pid`. ArtworkDB and iTunesDB can
both parse while this companion projection is stale. [libgpod SQLite
projection](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_sqlite.c#L962-L970)

### Sparse reference metadata has evidence, but uncertain necessity

foo_dop writes MHII reference count at `0x38` and a flag at `0x3C`. Its addition
path increments the count and sets the flag to one for its sixth-generation
format. GNUpod writes one at both offsets. These offsets are distinct from
`0x1C`, which libgpod calls unknown, and `0x28`/`0x2C`, which it treats as dates.
[foo_dop MHII
writer](https://github.com/reupen/ipod_manager/blob/08e0657b5ee09bd05cdb60273e1a139205d4d3f6/foo_dop/photodb.cpp#L1176-L1200),
[GNUpod MHII
writer](https://www.apt-browse.com/browse/debian/wheezy/main/all/gnupod-tools/0.99.8-2.1/file/usr/share/perl5/GNUpod/iTunesDB.pm),
[libgpod header
definition](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/db-itunes-parser.h#L556-L570)

libgpod and the inspected Original iOpenPod writer do not author these extended
fields. Thus zero is not, by itself, proven corruption. Modeling these fields and
preserving their meaning when sharing changes is reasonable future work; treating
every zero as the explanation for the reported disappearance is not supported.

### Count and filename mistakes can hide every cover

KeyJ's nano experiments are unusually valuable because they distinguish an
observed failure from a plausible theory. Artwork vanished when the image-list
count described unique bitmap sources rather than all written MHII records.
Correcting the count restored display, including shared physical pixel ranges.
The same experiment found that arbitrary thumbnail filenames failed even though
the database referenced existing valid image data; the device expected its
format-specific `F1027` and `F1031` naming. Those observations establish these
rules for the tested nano, not every later firmware. [KeyJ's first-hand
report](https://keyj.emphy.de/an-ipod-hackers-diary/)

ipod-sharp independently writes MHLI's third word as image-item count and uses
format-derived `:F<id>_1.ithmb` paths for album art, versus
`:Thumbs:F<id>_1.ithmb` for Photos. Count fields and byte lengths are not
interchangeable. [ipod-sharp database
implementation](https://github.com/mono/ipod-sharp/blob/69165d82bff44065436bfe9f7ebccd692b4874fc/src/PhotoDatabase.cs#L404-L458)

### Raster bytes, allocated bytes, and visible bounds differ

**A zero secondary MHNI size is established legacy output.** libgpod's header
initializer clears the entire 76-byte MHNI header, and `write_mhni` writes the
primary size at `0x18` but never writes `0x28`. ipod-sharp likewise writes its
36-byte known header followed by zero padding. Requiring the secondary field to
equal the primary would reject these writers' normal output. For validated fixed
rasters, interpreting a zero secondary size as an unspecified allocation with the
primary size as its bound is supported by this evidence; the retained zero need
not be rewritten. [libgpod MHNI
writer](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/db-artwork-writer.c#L363-L416),
[ipod-sharp MHNI
writer](https://github.com/mono/ipod-sharp/blob/69165d82bff44065436bfe9f7ebccd692b4874fc/src/PhotoDatabase.cs#L651-L670)

foo_dop records data size in MHNI `0x18` and padded allocation size in `0x28`.
It writes width/height as right/bottom coordinates and padding as left/top
coordinates. It also changes MHIF's size to a thumbnail file's end position
during truncation. Consequently, unequal MHNI sizes or an MHIF value matching a
whole file do not independently prove damage. The existing ADR-0111, ADR-0124,
and ADR-0131 compatibility rules address these distinctions.
[foo_dop allocation and geometry
code](https://github.com/reupen/ipod_manager/blob/08e0657b5ee09bd05cdb60273e1a139205d4d3f6/foo_dop/photodb.cpp#L141-L197)

GNUpod independently describes Classic/Nano 3 F1061 as 56 by 56 pixels with
`drop=112`, removing one 112-byte row. That produces 6,160 stored bytes rather
than 6,272. This supports the existence of the 55-row variant already handled in
iOpenPod; it does not establish that every mixed allocation is valid.
[GNUpod format
profiles](https://www.apt-browse.com/browse/debian/wheezy/main/all/gnupod-tools/0.99.8-2.1/file/usr/share/perl5/GNUpod/ArtworkDB.pm)

libgpod computes packed row width using byte alignment before computing frame
size. Its read path seeks to MHNI's byte offset and reads the recorded size.
Therefore, a visible width or a file's quotient by a nominal frame size cannot
replace the recorded layout and range. [libgpod packed
encoder](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/ithumb-writer.c#L85-L129),
[libgpod raster
reader](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_artwork.c#L631-L688)

### Pixel formats need device and representation context

libgpod's device tables and SysInfo parser distinguish RGB565, RGB555 variants,
rotation, row alignment, and YUV layouts. A format number is useful only with its
device/layout evidence. [Device format
tables](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_device.c),
[SysInfo format
mapping](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_sysinfo_extended_parser.c)

The recursive RGB555 variant stores quadrants top-left, bottom-left, top-right,
bottom-right, recursively; ordinary row-major RGB555 has different byte order.
libgpod's encoder and decoder agree on that traversal. A round trip through two
equally mistaken codecs would miss the error, so a small independent pixel-order
vector is necessary. No current static iOpenPod Device Profile selects this
format; finding a codec defect alone does not identify this user's loss cause.
[libgpod recursive
decoder](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_artwork.c#L368-L441),
[libgpod recursive
encoder](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/ithumb-writer.c#L368-L430)

F1019 uses two field-contiguous halves of UYVY rows; F1067 uses planar I420 with a
larger allocated record than its conventional 12-bit planes. Keith's independently
observed Photo formats corroborate that raw iTHMB interpretation depends on model
and format. These are principally Photo/TV-output findings; they should not be
applied indiscriminately to album-cover formats. See the repository's
[detailed UYVY research](ithmb-uyvy-format.md).
[Keith's format
observations](https://github.com/kebwi/Keiths_iPod_Photo_Reader/blob/c15481b7abeb5750d6264ba9d1800787977294d8/README.txt),
[libgpod pixel
decoder](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_artwork.c#L525-L629)

Apple documents limited-range YCbCr conventions; Microsoft independently documents
UYVY order and conversion. These corroborate color interpretation, not iPod field
ordering, chunk structure, or firmware acceptance. [Apple
TN2307](https://developer.apple.com/library/archive/technotes/tn2307/_index.html),
[Microsoft YUV
reference](https://learn.microsoft.com/en-us/windows/win32/medfound/recommended-8-bit-yuv-formats-for-video-rendering)

### Publication can break a correct candidate

libgpod compacts existing iTHMB files in place, updates offsets, truncates, and
appends new thumbnails. Its own comments assume equal thumbnail sizes for
compaction. Copying this algorithm into a system that accepts mixed rasters would
discard that assumption and introduce risk. iOpenPod's retained-original Storage
Transactions and append-oriented preparation should remain the foundation.
[libgpod thumbnail
rearrangement](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/ithumb-writer.c#L1390-L1524)

podkit reports a concrete autopsy: 2,289 referenced unique slots but only 246
physical slots in both expected iPod Video formats. That proves missing ranges in
that capture. Its proposed FAT32 write-order/interruption explanation remains a
primary hypothesis; its own report says compaction was not shown to scramble the
in-bounds data. The broader claim that only a complete rebuild can repair any
artwork corruption is not justified by that example. Surviving validated covers
can be preserved while affected representations are regenerated.
[podkit autopsy and
hypotheses](https://github.com/jvgomg/podkit/blob/abaf519a02d8dab100da627c2f4a3a3791aa760e/docs/adr/adr-013-ipod-artwork-corruption-diagnosis-and-repair.md)

JakPod's changelog also records a 2008 reorganization bug that mixed up album art,
followed by a fix and an iTunes-compatible iTHMB creation option. This is an
independent warning about compaction and interoperability, not evidence that
iOpenPod has the same defect. [JakPod
history](https://www.jakpod.de/changelog)

The local audit also reproduced a separate durability defect in ordinary Storage
Transactions: an unsuccessful pre-commit Volume flush still allowed a COMMITTED
journal. A later reconnect and successful flush could then authorize automatic
terminal cleanup of the originals, even if an interrupted write had not survived.
The journal now records whether the result crossed a successful durability
barrier. Unconfirmed and legacy terminal journals require a later successful flush
and fresh result verification before cleanup. Confirmed transactions retain the
existing cleanup path. Restoration establishes its own confirmation. A failed
final journal-marker flush does not erase an already successful content barrier.
[Storage durability regressions](../../tests/storage/test_transaction_durability.py),
[updated cleanup decision](../adr/0134-verify-unconfirmed-durability-before-recovery-cleanup.md)

Making Volume flushes mandatory for ordinary publication would introduce a Windows
regression. Microsoft explicitly requires administrative privileges for flushing
a writable Volume handle. Individual writes already call `fsync`, which Python
implements through Windows `_commit`; that does not justify treating a denied
Volume flush as successful. Publication therefore preserves its warning behavior
and cleanup retains originals while durability is unconfirmed. [Microsoft Volume
flush requirements](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-flushfilebuffers),
[Python fsync](https://docs.python.org/3.12/library/os.html#os.fsync),
[Microsoft _commit](https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/commit)

This fix preserves recovery evidence; it does not change restoration's existing
concurrent-edit protection. A current file that matches neither its prior nor
its proposed content is not automatically overwritten, even when truncation
after a disconnect is a plausible explanation.

### Missing source artwork is not the same as missing device artwork

GNUpod documents that artwork can disappear after iTunes processes media without
the corresponding embedded tags. Thus a Host preview, device thumbnail, and
embedded cover are distinct representations with different consumers.
[GNUpod interoperability
note](https://www.blinkenlights.ch/gnupod/gnupod.html)

gtkpod's developer discussion shows a report initially understood as corruption
that actually concerned covers never copied to newly added Tracks. Establish
whether the symptom is old-cover loss, new-cover omission, wrong-cover display,
or failure of one view before naming the cause. [gtkpod
discussion](https://sourceforge.net/p/gtkpod/mailman/gtkpod-questions/thread/s2qd45479531005071657qd2a00702p900f2991bc1c81d1%40mail.gmail.com/)

Rockbox searches conventional external image filenames in Track/Album directories
and its own artwork directory. Stock firmware ArtworkDB behavior must not be
inferred from a Rockbox screenshot alone. [Rockbox image
lookup](https://github.com/Rockbox/rockbox/blob/master/apps/recorder/albumart.c)

## Proposed repair policy for iOpenPod

These are engineering recommendations derived from the evidence, not additional
accepted ADRs or a claim that every repair is implemented.

1. **Keep decoding failure separate from absence.** A missing Host source, an
   unsupported representation, and a missing device range are three different
   facts. None alone authorizes clearing a retained cover association.
2. **Repair the smallest provable defect.** Correct a stale declared count or
   size when bounded children or validated rasters uniquely establish its value.
   Repair a broken explicit association from a unique persistent Track reference
   only when the association is unambiguous. Record what changed and why.
3. **Use alternate surviving evidence.** If one representation is unreadable,
   try other validated representations of that same artwork identity. Re-encode
   required device sizes from an available Host source or decoded surviving cover.
   Recovering from a thumbnail is useful but does not recover original resolution.
4. **Isolate affected artwork.** A damaged unrelated representation should not
   force deletion of healthy art or prevent all other covers from being written.
   Allocate a fresh, correctly named shard when an existing shard cannot be safely
   extended. Preserve the old file and its retained references.
5. **Preserve Unknown Data and ambiguous evidence.** Ordinary parsing and
   unchanged serialization remain byte-exact. A repair candidate is an explicit
   transformed document with original bytes available for recovery. Raw marker
   searching must not turn arbitrary pixel bytes into trusted database records.
6. **Verify the complete candidate graph.** Reparse output and independently
   resolve Track links, represented formats, filenames, offsets, data sizes,
   allocations, and companion SQLite associations. Check aliasing globally:
   identical shared ranges are valid; overlapping incompatible ranges are not.
7. **Publish one recoverable generation.** iTHMB data, ArtworkDB, iTunesDB/CDB,
   and relevant companions belong in one Storage Transaction. Verify staged and
   published bytes, retain originals, and test recovery at each publish boundary.
8. **Do not accept unexplained coverage loss.** Compare old and new coverage by
   stable Track identity. Every newly uncovered retained Track needs an explicit
   removal intent, a documented unresolved defect retained without further loss,
   or a failed/deferred item outcome. A successful generic parse is insufficient.

The maximum recovery available depends on surviving information. Without original
images, intact thumbnails, a usable database association, or a previous retained
generation, pixel ownership cannot be proved from arbitrary RGB565 bytes. The
correct response is to retain those bytes and explain the missing evidence while
repairing every association and representation that can be established.

## Regression matrix suggested by the sources

| Scenario | Required observation |
| --- | --- |
| One source cover generates two, three, or four formats | New MHIT count remains one; every required MHNI is present. |
| Legacy-only, explicit-link-only, and shared sparse covers | Unrelated metadata edits retain each Track's displayed identity. |
| Delete one Track sharing artwork | Other referring Tracks retain their cover and pixel ranges. |
| Stale MHLI count with uniquely bounded MHII children | Repair candidate corrects the count; unchanged source serialization remains exact. |
| MHIF contains shard length; MHNI describes sound frames | Evidence-backed size correction preserves all existing frames. |
| Legacy MHNI has primary size but zero secondary size | Validate the primary bounded raster; preserve the zero and allow unrelated/new covers. |
| F1061 6,160/6,272-byte rasters and padded allocations | Each retained raster uses its own bounds; new output follows accepted policy. |
| One bad format and another valid format for the same cover | Valid representation remains available; repair does not clear the whole cover. |
| One missing shard among otherwise valid artwork | Healthy shards and associations survive; affected work has a specific outcome. |
| Host extraction fails or cover source is temporarily unavailable | Existing device cover is retained and the intended cover change can retry. |
| Variable-size or unknown representation | Preserve bytes; do not infer fixed slots from neighboring records. |
| Late-device database companions | Binary and SQLite image/Track references agree after commit. |
| Disconnect at each file-publication boundary | Recovery restores a mutually consistent prior or verified new generation. |
| Volume flush fails before commit or restoration completes | Ordinary publication reports the warning; unconfirmed cleanup requires a successful later barrier and fresh verification before deleting originals. |
| Repeated Sync after a successful repair | No repeated repair, re-encoding, or unrelated thumbnail changes. |

Physical firmware tests remain necessary for newly supported encodings and sparse
metadata policies. Synthetic fixtures establish software behavior; they cannot
prove how every iPod generation interprets a newly authored layout.
