# ArtworkDB binary format notes

## Scope and evidence

These notes translate ArtworkDB knowledge from the Original iOpenPod into the
iOpenPod 2.0 format layer. The primary local evidence is:

- `src/iopenpod/artworkdb_parser/` for the original Chunk traversal and field reads
- `src/iopenpod/artworkdb_shared/` for header sizes, MHOD kinds, and string encoding
- `src/iopenpod/artworkdb_writer/artworkdb_chunks.py` for album-art serialization
- `src/iopenpod/sync/photos.py` for the more complete photo-album and file-list paths
- `tests/test_artwork_writer.py` and `tests/test_photo_path_safety.py` for exercised
  behavior

The Original iOpenPod is evidence rather than a runtime dependency. The iOpenPod
2.0 implementation translates this knowledge into shared Chunk definitions, parser
behavior, writer behavior, and tests.

## Chunk tree

The observed database shape is:

```text
mhfd
├── mhsd type 1
│   └── mhli
│       └── mhii ...
│           └── mhod type 2, 5, or 6
│               └── mhni
│                   └── mhod type 3 (image or ITHMB path)
├── mhsd type 2
│   └── mhla
│       └── mhba ...
│           ├── mhod type 1 (album name)
│           └── mhia ... (image membership)
└── mhsd type 3
    └── mhlf
        └── mhif ...
            └── optional mhod type 3 (file path)
```

Every Chunk starts with a 12-byte generic header:

| Offset | Encoding | Meaning |
| --- | --- | --- |
| `0x00` | 4 raw bytes | Header Marker |
| `0x04` | little-endian `u32` | Header length |
| `0x08` | little-endian `u32` | Total Chunk length, or child count for a list Chunk |

`mhli`, `mhla`, and `mhlf` use the third word as a child count. Other known Chunks
use it as their total byte length.

## Observed header sizes

| Chunk | Header size | Purpose |
| --- | ---: | --- |
| `mhfd` | 132 | ArtworkDB root |
| `mhsd` | 96 | Dataset wrapper |
| `mhli` | 92 | Image list |
| `mhla` | 92 | Photo album list |
| `mhlf` | 92 | Artwork file-format list |
| `mhii` | 152 | Image item |
| `mhod` | 24 | Typed data object |
| `mhni` | 76 | Image location and dimensions |
| `mhba` | 148 | Photo album |
| `mhia` | 40 | Photo album membership item |
| `mhif` | 124 | Artwork file-format item |

These are observed writer defaults, not permission to discard a different retained
header length. Parsed header bytes remain authoritative for unchanged round trips.

## Known fields

### `mhfd`

The root declares its dataset count at `0x14` and the next image item ID at `0x1C`.
The Original iOpenPod reads additional values through `0x40`, but does not establish
stable meanings for them. They remain explicitly named by offset.

The value at `0x10` is especially uncertain. Older parser comments describe values
1 and 2; Original iOpenPod's current album-art and photo writers use 6, also found
in the local Nano 5 and Nano 7 captures. It is not a settled database version.
Known Device Profiles now supply creation value 6 without requiring existing files.
The builder still takes the root value and next image ID explicitly. Library
preparation starts fresh identities at 100 and preserves existing root variants.
See [ADR-0033](../adr/0033-create-artworkdb-from-catalog-capabilities.md).

### `mhsd`

Dataset kinds are:

| Value | Child list |
| ---: | --- |
| 1 | `mhli` image list |
| 2 | `mhla` photo album list |
| 3 | `mhlf` artwork file-format list |

The dedicated ArtworkDB parser reads the dataset kind at `0x0C` as `u16` and cites
the libgpod structure. The later photo workflow reads and writes `u32`. iOpenPod 2.0
uses the evidenced `u16` value and retains the upper two bytes at `0x0E` as Unknown
Data rather than silently choosing a meaning.

### `mhii`

Known fields include the MHOD child count, image ID, linked iTunesDB Track ID,
rating, two timestamps used by the photo path, and original source-image size. The
album-art path normally links the 64-bit value at `0x14` to an iTunesDB Track's
`db_track_id`.

### `mhni`

Known fields include the child count, artwork format ID, byte offset in an ITHMB
file, image byte size, signed vertical and horizontal padding, visible height and
width, and a second image-size field observed in later databases.

The format ID is also called a correlation ID in older Original iOpenPod code. The
canonical implementation uses `format_id` because the same value selects device
artwork format behavior.

### `mhba` and `mhia`

`mhba` separately counts MHOD metadata children and MHIA membership children. Known
album fields include the album ID, slideshow flags, slide and transition durations,
a 64-bit Track reference, and the previous album ID. `mhia` identifies one member by
image ID at `0x10`.

### `mhif`

Known fields are a child count, artwork format ID, and image size. Some photo
databases may append an MHOD type 3 path child; album-art databases commonly use no
child.

## ArtworkDB MHOD layouts

The MHOD type is a little-endian `u16` at `0x0C`. Byte `0x0F` records string padding
in Original iOpenPod output. Known types are:

| Type | Observed meaning | Payload shape |
| ---: | --- | --- |
| 1 | Album name | String |
| 2 | Thumbnail image | MHNI container, except for the MHBA firmware bug below |
| 3 | File name or path | String |
| 4 | Unknown | Opaque |
| 5 | Full-resolution image | MHNI container |
| 6 | Auxiliary image data | MHNI container or opaque body, including MHAF |

Unknown MHOD types are expected Unknown Data and retain their payload bytes.

### String body

The ArtworkDB string layout differs from the iTunesDB string layout:

| Standard-header offset | Payload-relative offset | Encoding | Meaning |
| --- | --- | --- | --- |
| `0x18` | `0x00` | `u32` | Encoded byte length |
| `0x1C` | `0x04` | `u8` | Encoding indicator: 1 for UTF-8, 2 for UTF-16 little-endian |
| `0x1D` | `0x05` | 3 raw bytes | Unknown Data |
| `0x20` | `0x08` | `u32` | Unknown Data |
| `0x24` | `0x0C` | variable | Encoded string followed by retained padding |

The prefix begins at the MHOD's declared header end. The standard 24-byte header
places it at the chunk-relative offsets shown above, while a longer retained header
moves the prefix without changing its payload-relative layout.

Original iOpenPod writes type 3 strings as UTF-16 little-endian and other string
types as UTF-8.

### Contextual type 2 behavior

The Original iOpenPod records an iPod firmware bug: an MHOD type 2 beneath `mhba`
can contain a string instead of an `mhni` container. The payload registry therefore
selects the type 2 layout from parent context, mirroring the contextual MHOD design
already used by iTunesDB.

## Unknown Data and writing

`mhaf` is recognized by the Original parser but has no established body layout.
A standalone structurally valid MHAF remains an opaque Chunk. Captured type-6 MHOD
bodies instead begin with `mhaf`, then the words 96 and 60: treating those as a
generic header length and total length would be invalid. That entire body is
preserved as opaque MHOD data bounded by its enclosing record. New image records
include the evidenced 96-byte empty body from Original iOpenPod. Unknown MHOD types
are also opaque. An otherwise
unknown Header Marker can be retained as an opaque leaf when its generic header
supplies a structurally valid total length; an unknown list/container encoding with
no discoverable length remains malformed rather than being guessed.

Parsed Chunks retain their original header, body, and trailing bytes. The writer
patches known fields through the same `chunk_field` definitions used by the parser,
recalculates lengths and child counts, and carries untouched bytes forward. This
supports byte-exact unchanged round trips while allowing explicit structured edits
without normalizing unrelated data.

ArtworkDB parsing and serialization operate only on bytes. The adjacent iTHMB codec
also accepts only caller-supplied bytes and an explicit pixel layout; it is not part
of the ArtworkDB parser or writer and performs no I/O. Device capability selection,
filesystem persistence, request scheduling, and presentation remain outside the
iPodDB boundary.
