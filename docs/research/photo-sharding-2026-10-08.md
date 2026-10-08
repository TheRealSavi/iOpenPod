# PhotosDB and shared iTHMB shard research

## Scope and provenance

Sources were retrieved on 2026-10-08 to investigate Sync allocating one iTHMB file
per Photo and format. This complements the [artwork loss
investigation](artwork-sync-loss-2026-10-08.md), [PhotosDB grammar](photosdb-format.md),
and [Photo raster research](ithmb-uyvy-format.md). Shared Chunk definitions do not
make all ArtworkDB and PhotosDB field meanings interchangeable.

The investigation distinguishes executable source, independent device observations,
and the iOpenPod policy chosen in [ADR-0135](../adr/0135-pack-photos-into-bounded-shared-shards.md).
Context7 returned unrelated libgpiod results for libgpod; direct upstream sources
were inspected instead. Several files in one project are one source family.

| Source | Pinned revision or retrieval | Contribution and limits |
| --- | --- | --- |
| [libgpod thumbnail writer](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/ithumb-writer.c) | `7982c5554f78dde47fd006afbeff659201d6db3d` | Per-format writers, filenames, byte offsets, rollover policy, raster allocation. |
| [libgpod database writer](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/db-artwork-writer.c) | Same revision | Photo-specific branches, MHIF declarations, counts, dates; not independent confirmation of its thumbnail writer. |
| [ipod-sharp PhotoDatabase](https://github.com/mono/ipod-sharp/blob/69165d82bff44065436bfe9f7ebccd692b4874fc/src/PhotoDatabase.cs) | `69165d82bff44065436bfe9f7ebccd692b4874fc` | Independent shared-file writer and full-resolution containers; only the first shard is addressed. |
| [Keith's iPod Photo Reader](https://github.com/kebwi/Keiths_iPod_Photo_Reader/blob/c15481b7abeb5750d6264ba9d1800787977294d8/README.txt) | `c15481b7abeb5750d6264ba9d1800787977294d8` | Independent device observations of concatenated images, sequential files, and raster variants. |
| [foo_dop Photo/artwork structures](https://github.com/reupen/ipod_manager/blob/08e0657b5ee09bd05cdb60273e1a139205d4d3f6/foo_dop/photodb.cpp) | `08e0657b5ee09bd05cdb60273e1a139205d4d3f6` | Separate MHNI data and allocation fields; album-art authoring is not proof of every Photo format. |
| [Apple iTunes photo synchronization](https://support.apple.com/guide/itunes/sync-photos-itns3102/windows) | Retrieved 2026-10-08 | Full-resolution copies are an additional option for iPod classic and iPod nano. |
| [Original iOpenPod Photo workflow](https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/sync/photos.py) | `a20242428b93b672d14b37230772dbad75139c69`, local `origin/1.x` | Behavioral baseline packs by format; not independent verification of this project's format assumptions. |

## Shared files and the compatibility bound

libgpod creates one writer per Photo format and feeds all Photos through those
writers. `get_ithmb_filename` produces `:Thumbs:F<format>_<index>.ithmb` for Photos,
versus `:F<format>_<index>.ithmb` for covers. The physical Photo path is under
`Photos/Thumbs/`. Each MHNI receives the writer's current byte offset.
Its `ITHUMB_MAX_SIZE` is decimal **256,000,000 bytes**. The comment attributes the
reduction from 500 MB to slow iPod interface reports. Its rollover checks the
existing offset before writing, so one allocation can cross the threshold.
This establishes a historical compatibility policy, not a hard firmware maximum.
[libgpod writer](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/ithumb-writer.c)

ipod-sharp's `SaveThumbnails` independently groups records by format, appends new
representations, and records their offsets. Its use of `F<format>_1.ithmb` does not
establish rollover behavior. [ipod-sharp implementation](https://github.com/mono/ipod-sharp/blob/69165d82bff44065436bfe9f7ebccd692b4874fc/src/PhotoDatabase.cs)
Keith's reader describes large concatenated Photo collections continuing in
sequentially numbered files. [Independent observations](https://github.com/kebwi/Keiths_iPod_Photo_Reader/blob/c15481b7abeb5750d6264ba9d1800787977294d8/README.txt)

The iOpenPod inference is to use 256,000,000 as a bounded output default and roll
before `current_length + next_allocation` would exceed it. Fill each format's
available capacity independently; a Photo's different representations need not
share a suffix. Never split one representation across files. A lower applicable
filesystem limit also constrains publication. Existing larger files are not proven
corrupt merely because they exceed the new-output policy.

## Byte ranges, allocations, and retained data

MHNI `0x14` is a byte offset; `0x18` describes image bytes. libgpod authors the
primary size while leaving the secondary field zero. That is established output,
not proof of corruption. [libgpod MHNI writer](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/db-artwork-writer.c)
foo_dop separately serializes `file_size` at `0x18` and `file_size_2` at `0x28`;
its allocation behavior underlies the distinctions already documented in the
artwork investigation. Carry that evidence into shared structural validation
without inventing new Photo codec rules. [foo_dop source](https://github.com/reupen/ipod_manager/blob/08e0657b5ee09bd05cdb60273e1a139205d4d3f6/foo_dop/photodb.cpp)

libgpod advances offsets through format padding and aligned raster rows. Its I420
packing allocates two bytes per physical pixel, although the planar image occupies
less. [Allocation implementation](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/ithumb-writer.c)
The existing [connected-iPod F1067 evidence](ithmb-uyvy-format.md#connected-ipod-experiment)
also records meaningful auxiliary bytes beyond the conventional planar raster.
Those bytes must not be discarded as expendable padding. Physical Device Profile
geometry determines decode layout before applying visible-region cropping.

For iOpenPod append eligibility, validate the complete captured file and every
retained reference, using nonzero secondary allocation sizes where present and
primary sizes where secondary sizes are unspecified. Prove positive, bounded
extents and supported raster geometry. Exact shared ranges may have multiple
owners; partial overlaps are not valid allocation evidence. Retain raw MHNI fields,
including legacy zero sizes, rather than normalizing them during an unrelated add.

Append after the captured file length, preserving its entire prefix byte for byte.
Do not choose an offset from only the last visible representation: unreferenced
ranges, auxiliary bytes, and trailing Unknown Data may follow it. Missing,
truncated, unreadable, or uncertain shards remain reserved destinations and receive
no append. Their failure does not prevent preparing valid incoming Photos into
fresh shards. This is preservation policy, not a claim that every old shard can be
decoded or reconstructed automatically.

## Database declarations and Photo-specific identities

libgpod emits one MHIF per device Photo format, with an image-size declaration.
MHLF therefore counts format records, not physical shards. Its fixed `width *
height * 2` formula is historical implementation behavior, not a universal codec
formula. MHLI counts Photo MHII records; each MHII counts its actual MHOD children.
Its Photo `song_id` branch uses `image_id + 2`, illustrating why Music Track-link
semantics cannot simply be applied to Photos. [libgpod database writer](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/db-artwork-writer.c)

ipod-sharp independently keys MHIF entries by format and writes MHII child count
from its representation list, including an optional full-resolution container.
[Independent structure implementation](https://github.com/mono/ipod-sharp/blob/69165d82bff44065436bfe9f7ebccd692b4874fc/src/PhotoDatabase.cs)
Packing must leave Photo IDs, Photo Album memberships, ratings, and untouched
headers unchanged. MHIF remains a per-frame declaration when its shard grows.
Neither the Music Track `artwork_count = 1` rule nor sparse cover ownership repairs
are Photo MHII count rules.

## Full-resolution exception and timestamp disagreement

Apple documents full-resolution transfer as an additional option.
[Apple instructions](https://support.apple.com/guide/itunes/sync-photos-itns3102/windows)
ipod-sharp writes its original-image reference through MHOD type 5 and copies that
image separately from its type-2 thumbnail representations.
[Full-resolution handling](https://github.com/mono/ipod-sharp/blob/69165d82bff44065436bfe9f7ebccd692b4874fc/src/PhotoDatabase.cs)
Preserve that separation: a full-resolution Photo remains a standalone image file,
not a frame in a shared iTHMB shard, and retains whole-file verification.

The [older PhotosDB notes](photosdb-format.md#photo-specific-meanings) describe
Original iOpenPod authoring Unix seconds at MHII `0x28` and `0x2C`. Both libgpod and
ipod-sharp convert these Photo dates to Mac epoch fields.
[libgpod date authoring](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/db-artwork-writer.c),
[ipod-sharp date conversion](https://github.com/mono/ipod-sharp/blob/69165d82bff44065436bfe9f7ebccd692b4874fc/src/PhotoDatabase.cs)
This is a documented disagreement with the historical baseline. Current 2.0 policy
already uses captured local Mac conversion under [ADR-0098](../adr/0098-capture-device-time-context-for-library-dates.md).
Shard packing neither changes that decision nor migrates retained timestamps.

## Excluded inferences and verification targets

The newer [Ithmb-Codec-CSharp README](https://github.com/B67687/Ithmb-Codec-CSharp/blob/main/README.md),
retrieved 2026-10-08, describes a 32 MB input guard for its own memory protection.
It derives format profiles from iOpenPod and primarily validates single-image
T-prefix cache files. That guard is not independent firmware-limit evidence.
Host Photo Cache organization must not be substituted for on-device F-prefix
shards. No exact universal firmware maximum was established by this investigation.

Required tests follow the chosen policy: batch sharing, independent format
rollover, exact-capacity boundaries, nonzero offsets, successive Sync append,
padded retained allocations, and unchanged Unknown Data. Exercise shared-owner
replacement/removal, last-owner cleanup, malformed or case-colliding names,
unavailable shards, changed captured prefixes, and Storage rollback restoring both
the shared files and PhotosDB. Native firmware testing is still needed to validate
performance and display behavior across supported devices.
