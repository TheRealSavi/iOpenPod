# iTunesCDB Internals — How libgpod Handles Compressed Databases

> **Audience:** iOpenPod developers, iPod reverse-engineering community.
> **Last updated:** 2025-07-12
> **Primary sources:** libgpod `itdb_itunesdb.c`, `itdb_zlib.c`,
> `itdb_device.c`, `db-itunes-parser.h`, plus empirical analysis of a
> real Nano 6G (`iTunesCDB`, version `0x6F`).

---

## Table of Contents

1. [What Is iTunesCDB?](#1-what-is-itunescdb)
2. [Which Devices Use It?](#2-which-devices-use-it)
3. [On-Disk Format](#3-on-disk-format)
4. [Read Path — Decompression](#4-read-path--decompression)
5. [Write Path — Compression & Signing](#5-write-path--compression--signing)
6. [MHBD Header Deep-Dive](#6-mhbd-header-deep-dive)
7. [MHSD Dataset Types](#7-mhsd-dataset-types)
8. [Playlist Handling (Type 2 vs Type 3)](#8-playlist-handling-type-2-vs-type-3)
9. [Checksum / Signing](#9-checksum--signing)
10. [Comparison: libgpod vs iOpenPod](#10-comparison-libgpod-vs-iopenpod)
11. [Comparison: libgpod vs GNUpod](#11-comparison-libgpod-vs-gnupod)
12. [Key Differences & Gotchas](#12-key-differences--gotchas)
13. [References](#13-references)

---

## 1. What Is iTunesCDB?

Starting with iPod firmware 2.0.1 on the Nano 5G (late 2009), Apple added a
**compressed database** format alongside the traditional `iTunesDB`. The file
is named `iTunesCDB` (the "C" stands for "Compressed") and lives in the same
`/iPod_Control/iTunes/` directory.

The format is straightforward: the standard `mhbd` header is stored
**uncompressed**, and the remainder of the file (all `mhsd` children) is
wrapped in a single **zlib** stream. The firmware reads `iTunesCDB` in
preference to `iTunesDB` when both are present.

### Why?

On flash-based iPods (Nano 5G+), storage I/O dominates boot time. Compressing
the database reduces its size by ~80 % (e.g. 972 KB → 173 KB for a 522-track
library), which cuts read time significantly.

---

## 2. Which Devices Use It?

libgpod ties compressed-DB support to `itdb_device_supports_sqlite_db()`.
Despite the name, this function is used for **both** SQLite and CDB support
detection.

### `itdb_device_supports_compressed_itunesdb()`

```c
/* itdb_device.c */
gboolean itdb_device_supports_compressed_itunesdb (Itdb_Device *device)
{
    return itdb_device_supports_sqlite_db (device);
}
```

### Device Matrix

| Device Family | Generation | Compressed DB | Checksum |
|---------------|------------|:-------------:|----------|
| iPod (classic form factor) | 1G – 5.5G | No | NONE |
| iPod Classic | 1G – 3G | No | HASH58 |
| iPod Mini | 1G – 2G | No | NONE |
| iPod Nano | 1G – 2G | No | NONE |
| iPod Nano | 3G – 4G | No | HASH58 |
| **iPod Nano** | **5G** | **Yes** | HASH72 |
| **iPod Nano** | **6G** | **Yes** | HASHAB |
| **iPod Nano** | **7G** | **Yes** | HASHAB |
| iPod Shuffle | 1G – 4G | No | NONE |
| iPod Touch | 1G – 4G | Yes* | HASH72/HASHAB |
| iPhone | 1G – 4 | Yes* | HASH72/HASHAB |
| iPad | 1G | Yes* | HASHAB |

\* iPod Touch / iPhone / iPad also use a **SQLite** database (`iTunesDB`
in proprietary SQLite format). libgpod can generate this via
`itdb_sqlite_generate_itdbs()`, but it's separate from CDB.

**For classic iPods (with click-wheel), the devices that use iTunesCDB are
the Nano 5G, 6G, and 7G only.** All other click-wheel iPods use uncompressed
`iTunesDB`.

---

## 3. On-Disk Format

```
┌─────────────────────────────────────────────────────────┐
│ Offset 0x00                                              │
│ ┌───────────────────────────────────────────────────────┐│
│ │  mhbd header  (uncompressed, ≥ 0xA9 / 169 bytes)    ││
│ │  • total_length at +0x08 = compressed file size       ││
│ │  • unk_0xA8 = 1 (compressed flag)                     ││
│ │  • header_length at +0x04 = typically 244 (0xF4)      ││
│ └───────────────────────────────────────────────────────┘│
│                                                          │
│ Offset header_length                                     │
│ ┌───────────────────────────────────────────────────────┐│
│ │  zlib stream  (deflate, all mhsd children)            ││
│ │  first byte is 0x78 (zlib magic)                      ││
│ │  compressed with level 1 (Z_BEST_SPEED) by libgpod    ││
│ └───────────────────────────────────────────────────────┘│
│                                                          │
│ EOF = header_length + len(compressed_payload)            │
└─────────────────────────────────────────────────────────┘
```

### Key invariants

| Field | CDB Value | Normal iTunesDB Value |
|-------|-----------|----------------------|
| `total_length` (+0x08) | Compressed file size | Uncompressed file size |
| `unk_0x0C` (+0x0C) | 2 | 1 |
| `unk_0xA8` (+0xA8) | 1 (set by compressor) | 0 |
| First byte after header | 0x78 (zlib magic) | `m` (start of "mhsd") |

---

## 4. Read Path — Decompression

### libgpod (`itdb_itunesdb.c` + `itdb_zlib.c`)

#### Step 1: File Selection

```c
/* itdb_parse() in itdb_itunesdb.c */
filename = itdb_get_itunescdb_path(mp);    // Try iTunesCDB first
if (!filename) {
    filename = itdb_get_itunesdb_path(mp); // Fall back to iTunesDB
} else {
    compressed = TRUE;
}
```

libgpod always prefers `iTunesCDB` if it exists on disk. The `compressed`
flag is passed down to `parse_fimp()`.

#### Step 2: Decompression (`itdb_zlib_check_decompress_fimp`)

```c
/* itdb_zlib.c – simplified pseudocode */
void itdb_zlib_check_decompress_fimp(FImport *fimp)
{
    FContents *cts = fimp->fcontents;
    guint32 headerSize   = get32lint(cts, 4);   // mhbd header length
    guint32 compressedSz = get32lint(cts, 8);   // total_length (= file size)

    /* Guard: header must be at least 0xA9 bytes to contain the
       compression flag field */
    if (headerSize < 0xA9) return;

    guint16 flag = get16lint(cts, 0xA8);
    if (flag != 1) return;   // not compressed

    /* --- Two-pass zlib inflate --- */
    /* Pass 1: determine uncompressed size */
    gchar *payload = cts->contents + headerSize;
    gulong payloadLen = compressedSz - headerSize;
    gulong uncompressedLen = zlib_inflate(payload, payloadLen, NULL, 0);

    /* Pass 2: actually decompress */
    gchar *decompressed = g_malloc(uncompressedLen);
    zlib_inflate(payload, payloadLen, decompressed, uncompressedLen);

    /* Rebuild: header + decompressed payload */
    gchar *full = g_malloc(headerSize + uncompressedLen);
    memcpy(full, cts->contents, headerSize);   // copy header as-is
    memcpy(full + headerSize, decompressed, uncompressedLen);

    /* Clear the compression flag so downstream code doesn't see it */
    put16lint_at(full, 0xA8, 0);

    /* Update FContents to point to the reconstructed buffer */
    g_free(cts->contents);
    cts->contents = full;
    cts->length = headerSize + uncompressedLen;

    g_free(decompressed);
}
```

**Important detail:** libgpod uses a **two-pass inflate**. The first pass
runs `inflate()` with `Z_FINISH` into a zero-length buffer just to determine
the uncompressed size (by summing `strm.total_out`). The second pass
allocates the right-sized buffer and inflates for real. This avoids
over-allocation.

#### Step 3: Header Fixup Post-Decompression

After decompression, libgpod **clears `unk_0xA8` to 0** and then warns if
it was non-zero:

```c
fimp->itdb->priv->unk_0xa8 = get16lint(cts, 0xA8);
if (fimp->itdb->priv->unk_0xa8 != 0) {
    g_warning("Unknown value for 0xa8: should be 0 for uncompressed, is %d.\n",
              fimp->itdb->priv->unk_0xa8);
}
```

This confirms that the **decompressor is expected to clear 0xA8** before
the main parser sees the data.

#### Step 4: Normal Parsing

Once decompressed, `parse_fimp()` continues exactly as it would for a
regular `iTunesDB` — finding `mhsd` sections, parsing tracks, playlists, etc.
No CDB-specific logic is needed beyond this point.

---

## 5. Write Path — Compression & Signing

The write path in libgpod's `itdb_write()` / `itdb_write_file_internal()`
follows this sequence:

### Step 1: Build Uncompressed Database

```c
/* itdb_write_file_internal() — simplified */
mk_mhbd(fexp, num_mhsds);           // Write mhbd header
write_mhsd_tracks(fexp);             // mhsd type 1
write_mhsd_playlists(fexp, 3);       // mhsd type 3 (podcast playlists) — BEFORE type 2
write_mhsd_playlists(fexp, 2);       // mhsd type 2 (standard playlists)
write_mhsd_albums(fexp);             // mhsd type 4
write_mhsd_artists(fexp);            // mhsd type 8
write_mhsd_type6(fexp);              // mhsd type 6 (empty mhlt)
write_mhsd_type10(fexp);             // mhsd type 10 (empty mhlt)
write_mhsd_playlists(fexp, 5);       // mhsd type 5 (smart playlists)
write_genius_mhsd(fexp);             // mhsd type 9 (Genius CUID, optional)
fix_header(cts, mhbd_seek);          // Backpatch mhbd total_length
```

The database is built entirely in memory as a single contiguous buffer.
At this point `total_length` in the `mhbd` header reflects the **full
uncompressed** size.

### Step 2: Compress (if CDB device)

```c
if (itdb_device_supports_compressed_itunesdb(itdb->device)) {
    itdb_zlib_check_compress_fexp(fexp);
}
```

#### `itdb_zlib_check_compress_fexp()` — The Compressor

```c
/* itdb_zlib.c – simplified pseudocode */
void itdb_zlib_check_compress_fexp(FExport *fexp)
{
    WContents *cts = fexp->wcontents;
    guint32 headerLen = get32lint_from_buf(cts, 4);
    guint32 totalLen  = get32lint_from_buf(cts, 8);  // uncompressed total

    if (headerLen < 0xA9) return;  // Guard

    guint16 flag = get16lint_from_buf(cts, 0xA8);
    if (flag != 0) return;  // Already compressed?  Don't re-compress.

    gulong payloadLen = totalLen - headerLen;
    gulong compBound  = compressBound(payloadLen);  // zlib upper bound
    gchar *compressed = g_malloc(compBound);

    /* Compress with level 1 (Z_BEST_SPEED) */
    compress2(compressed, &compBound,
              cts->contents + headerLen, payloadLen,
              1);  /* ← level 1 */

    /* Rebuild buffer: header + compressed payload */
    gchar *newbuf = g_malloc(headerLen + compBound);
    memcpy(newbuf, cts->contents, headerLen);
    memcpy(newbuf + headerLen, compressed, compBound);

    /* Set compression flag */
    put16lint_at(newbuf, 0xA8, 1);

    /* Patch total_length to compressed size */
    put32lint_at(newbuf, 8, headerLen + compBound);

    /* Replace WContents buffer */
    g_free(cts->contents);
    cts->contents = newbuf;
    cts->pos = headerLen + compBound;

    g_free(compressed);
}
```

**Key observations:**
- Uses **`compress2()` with level 1** (fastest compression, larger output).
  This prioritises write speed over compression ratio.
- Sets **`unk_0xA8` to 1** after compression.
- Patches **`total_length` (+0x08)** to the compressed file size.
- The header itself is **never compressed** — only the payload after
  `header_length` bytes.

### Step 3: Sign (Checksum)

```c
/* After compression, apply the device-specific checksum */
itdb_device_write_checksum(itdb->device,
    (unsigned char *)fexp->wcontents->contents,
    fexp->wcontents->pos,
    &fexp->error);
```

The checksum is computed over the **compressed** data (header + compressed
payload). This is critical — the iPod firmware verifies the hash against
what it reads from disk, which is the compressed form.

### Step 4: Write File & Truncate iTunesDB

```c
/* Determine output filename */
if (itdb_device_supports_compressed_itunesdb(itdb->device)) {
    itunes_filename = g_build_filename(itunes_path, "iTunesCDB", NULL);
} else {
    itunes_filename = g_build_filename(itunes_path, "iTunesDB", NULL);
}

/* Write the database */
result = itdb_write_file_internal(itdb, itunes_filename, error);

/* Truncate iTunesDB to zero bytes if we wrote iTunesCDB */
if (result && itdb_device_supports_compressed_itunesdb(itdb->device)) {
    itunes_filename = g_build_filename(itunes_path, "iTunesDB", NULL);
    g_file_set_contents(itunes_filename, NULL, 0, NULL);  // truncate to 0
}
```

**libgpod truncates `iTunesDB` to zero bytes** rather than deleting it.
This is important because:

1. The iPod firmware may expect the file to exist (even if empty).
2. Some device firmwares check for the presence of `iTunesDB` during boot.
3. Deleting the file could confuse the firmware into thinking the iPod is
   uninitialised.

---

## 6. MHBD Header Deep-Dive

From `db-itunes-parser.h`, the complete `MhbdHeader` struct:

```
Offset  Size  Field               Notes
------  ----  ------------------  ------------------------------------------
0x00    4     header_id            "mhbd" magic
0x04    4     header_len           244 (0xF4) for modern iPods
0x08    4     total_len            File size (compressed or uncompressed)
0x0C    4     unknown1             1 = normal, 2 = CDB-capable device
0x10    4     version_number       libgpod writes 0x30 (iTunes 9.2)
0x14    4     num_children         Number of mhsd sections
0x18    8     db_id                64-bit database identifier
0x20    2     platform             1 = Mac, 2 = Windows
0x22    2     unknown2             Varies (~0x263)
0x24    8     unknown3             Secondary ID (copied into every mhit)
0x2C    4     unknown4             Observed: 0
0x30    2     hashing_scheme       0=none, 1=HASH58, 2=HASH72, 4=HASHAB
0x32    20    unknown5             Zeroed before HASH58 computation
0x46    2     language             e.g. 0x656E = "en"
0x48    8     library_persistent_id
0x50    4     unknown7
0x54    4     unknown8
0x58    20    hash58               HMAC-SHA1 signature (HASH58)
0x6C    4     timezone_offset      Seconds from UTC (signed int32)
0x70    2     unknown9
0x72    46    hash72               AES-based signature (HASH72)
0xA0    2     audio_language
0xA2    2     subtitle_language
0xA4    2     unknown11
0xA6    2     unknown12
0xA8    2     unk_0xa8             ← COMPRESSION FLAG (0 or 1)
0xAA    1     unknown13
0xAB    57    hashAB               HASHAB signature (Nano 6G/7G)
```

### CDB-Relevant Fields

| Offset | Field | CDB Meaning |
|--------|-------|-------------|
| `+0x08` | `total_len` | = compressed file size (header + zlib payload) |
| `+0x0C` | `unknown1` | = 2 for CDB-capable devices, 1 otherwise |
| `+0xA8` | `unk_0xa8` | = 1 when file is compressed on disk, 0 when uncompressed |

### `unk_0x0C` — Compressed DB Capability Flag

libgpod sets this based on device capabilities:

```c
/* mk_mhbd() in itdb_itunesdb.c */
if (itdb_device_supports_compressed_itunesdb(device)) {
    put32lint(cts, 2);   // CDB-capable
} else {
    put32lint(cts, 1);   // Normal
}
```

> **Warning:** iPod Classic 3G will **reject** the database if this is set
> to 2. Only set it for devices that actually support compressed databases.

### `unk_0xA8` — Compression State Flag

This is a **runtime flag** that indicates the current compression state:

- **0** = payload is uncompressed (standard iTunesDB, or after decompression)
- **1** = payload is zlib-compressed (on-disk iTunesCDB format)

libgpod's compressor sets it to 1 when writing; the decompressor clears it
back to 0 when reading.

---

## 7. MHSD Dataset Types

libgpod writes the following `mhsd` types (in this exact order):

| Type | Container | Contents | Required? |
|------|-----------|----------|-----------|
| 1 | `mhlt` | Track list (all `mhit` + `mhod` children) | Yes |
| 3 | `mhlp` | Playlist list — "podcast format" (special `mhip` grouping) | Yes* |
| 2 | `mhlp` | Playlist list — standard format | Yes* |
| 4 | `mhla` | Album list (`mhia` items with album name + artist `mhod`s) | Yes |
| 8 | `mhli` | Artist list (`mhii` items with artist name `mhod`) | Yes |
| 6 | `mhlt` | Unknown (written as empty track list, 0 children) | Padding? |
| 10 | `mhlt` | Unknown (written as empty track list, 0 children) | Padding? |
| 5 | `mhlp` | Smart playlist list (`mhyp` with SPL rules, 0 `mhip`s) | Yes |
| 9 | raw string | Genius CUID (32-byte string, no sub-chunks) | Only if Genius used |

\* The firmware reads type 3 in preference to type 2 for playlists.

### Write Order

Note that libgpod writes **type 3 before type 2**. This matters because
some firmware versions may stop reading after finding the first playlist
section. The type-3 (podcast-aware) format includes proper podcast grouping.

### Dataset Types Not Written

libgpod's `MhsdIndexType` enum only explicitly defines types 1 and 2:

```c
typedef enum {
    MHSD_INDEX_TRACK_LIST    = 1,
    MHSD_INDEX_PLAYLIST_LIST = 2
} MhsdIndexType;
```

Types 3–10 are handled by integer value in the code, not via the enum.
This suggests they were added incrementally as Apple expanded the format.

### Type 8 — Artist List (`mhli`)

This is a list of unique artists, written as `mhii` chunks (confusingly
sharing the same tag as ArtworkDB image items):

```c
/* mk_mhii() for artist list */
put_header(cts, "mhii");
put32lint(cts, 80);           // header size
put32lint(cts, -1);           // total size (backpatched)
put32lint(cts, 1);            // 1 child mhod
put32lint(cts, id->id);       // artist ID
put64lint(cts, id->sql_id);   // SQL ID (for sqlite DB)
put32lint(cts, 2);            // unknown
// ... padding ...

// Child MHOD with artist name
mhod.type = MHOD_ID_ALBUM_ARTIST_MHII;  // type 300
mhod.data.string = track->artist;
mk_mhod(fexp, &mhod);
```

### ID Assignment

Album IDs, artist IDs, and composer IDs are assigned during
`prepare_itdb_for_write()`:

```c
/* Hash table deduplication */
if (track->album != NULL) {
    id = g_hash_table_lookup(fexp->albums, track);
    if (id != NULL) {
        track->priv->album_id = id->id;
    } else {
        add_new_id(fexp->albums, track, album_id);
        track->priv->album_id = album_id++;
    }
}
```

Track IDs are reassigned sequentially starting from `FIRST_IPOD_ID = 52`.

---

## 8. Playlist Handling (Type 2 vs Type 3)

### Read Path — Preference Order

libgpod's `parse_fimp()` reads playlists with this priority:

```c
if (mhsd_3 != -1)
    parse_playlists(fimp, mhsd_3);      // Prefer type 3
else if (mhsd_2 != -1)
    parse_playlists(fimp, mhsd_2);      // Fall back to type 2
else
    /* ERROR: no playlists found */
```

**Only one of type 2 or type 3 is parsed for regular playlists.**
Type 5 (smart playlists) is parsed separately regardless.

### What's Different About Type 3?

Type 3 is the "podcast-aware" playlist format. The podcast playlist uses
hierarchical `mhip` grouping:

```
mhyp (Podcasts playlist)
  └─ mhip (group: album name)
      ├─ mhod TITLE (group name)
      └─ mhip (track reference)
          └─ mhod PLAYLIST (position)
```

In type 2, the podcast playlist is flat (no grouping). The podcast entries
in a type-3 `mhip` tree have a `podcastgroupflag = 256` and reference their
parent group via `podcastgroupref`.

### Nano 6G Observation

Our Nano 6G (`iTunesCDB`, version `0x6F`) has **NO type-2 dataset at all**.
Its datasets are: type 4, type 8, type 1, type 3, type 5.

libgpod's write path always writes both type 2 and type 3, so a
libgpod-generated database would add a type-2 section that iTunes omitted.
The firmware handles this gracefully — it prefers type 3.

---

## 9. Checksum / Signing

Checksum computation happens **after** compression but **before** writing
to disk.

### Dispatch

```c
/* itdb_device.c */
void itdb_device_write_checksum(Itdb_Device *device, ...)
{
    switch (itdb_device_get_checksum_type(device)) {
        case ITDB_CHECKSUM_NONE:    break;
        case ITDB_CHECKSUM_HASH58:  itdb_hash58_write_hash(...);  break;
        case ITDB_CHECKSUM_HASH72:  itdb_hash72_write_hash(...);  break;
        case ITDB_CHECKSUM_HASHAB:  itdb_hashAB_write_hash(...);  break;
    }
}
```

### `hashing_scheme` Value at +0x70

libgpod writes a hint at offset `+0x70` (2 bytes) indicating the signing
scheme level:

| Checksum Type | `+0x70` Value |
|---------------|:-------------:|
| HASH58 / NONE | 0 |
| HASH72 | 2 |
| HASHAB | 4 |

### Hash Input

All hash algorithms operate on the **entire database buffer** as it will be
written to disk (i.e., compressed form for CDB devices). Before computing
the hash, certain header fields are zeroed:

- **HASH58:** zeroes `db_id` (+0x18, 8B), `unk_0x32` (+0x32, 20B),
  and the hash58 field itself (+0x58, 20B)
- **HASH72:** similar zeroing plus uses an AES IV from `HashInfo` file
- **HASHAB:** operates on a different region (+0xAB, 57B)

---

## 10. Comparison: libgpod vs iOpenPod

| Aspect | libgpod | iOpenPod |
|--------|---------|----------|
| **File detection** | `iTunesCDB` first, `iTunesDB` fallback | `resolve_itdb_path()`: same priority |
| **Compression detection** | Checks `unk_0xA8 == 1` | Checks `unk_0x0C == 2` AND first payload byte `0x78` |
| **Decompression** | Two-pass inflate (size calc → allocate → inflate) | Single-pass `zlib.decompress()` (Python handles sizing) |
| **Header fixup on read** | Clears `unk_0xA8` to 0 | Patches `total_length` + clears `unk_0xA8` to 0 |
| **Compression level** | Level 1 (`Z_BEST_SPEED`) | Level 1 (`Z_BEST_SPEED`) |
| **`unk_0xA8` flag** | Set to 1 on compress, cleared to 0 on decompress | Set to 1 on compress, cleared to 0 on decompress |
| **After write** | Truncates `iTunesDB` to 0 bytes | Truncates stale file to 0 bytes |
| **MHSD write order** | 1, 3, 2, 4, 8, 6, 10, 5, 9 | 1, 3, 2, 4, 8, 6, 10, 5 (+ preserved blobs for 9) |
| **Type 6/10** | Writes empty `mhlt` stubs | Writes empty `mhlt` stubs |
| **Type 8 (artists)** | Full `mhli` with `mhii` children | Full `mhli` with `mhii` children (MHOD type 300) |
| **Type 9 (Genius)** | Written if CUID present | Preserved as opaque blob |
| **Checksum signing** | After compression | After compression |
| **Database version** | Always writes `0x30` (iTunes 9.2) | Writes from `DeviceCapabilities.db_version` |
| **`unk_0x0C`** | 2 if CDB-capable, 1 otherwise | Same logic |

### Remaining Differences

1. **Compression detection strategy:** libgpod checks `unk_0xA8 == 1`;
   iOpenPod checks `unk_0x0C == 2` AND the zlib magic byte `0x78`.
   Both approaches work correctly. The dual-check is slightly more
   robust against corruption.

2. **Type 9 (Genius):** libgpod generates this from the Genius CUID;
   iOpenPod preserves it as an opaque blob from existing databases.
   This means Genius data survives rewrites but cannot be created fresh.

3. **Database version:** libgpod hardcodes `0x30` (iTunes 9.2);
   iOpenPod uses per-device `DeviceCapabilities.db_version`, which
   allows targeting older firmware versions correctly.

---

## 11. Comparison: libgpod vs GNUpod

| Aspect | libgpod | GNUpod |
|--------|---------|--------|
| **Language** | C (GLib) | Perl |
| **CDB support** | Full read + write | None |
| **MHSD types** | 1, 2, 3, 4, 5, 6, 8, 9, 10 | 1, 2 only |
| **DB version** | `0x30` (iTunes 9.2) | `0x19` (iTunes 7.4.2) |
| **Hash support** | HASH58, HASH72, HASHAB | HASH58 only |
| **Last update** | ~2014 | ~2007 |
| **Artist list** | Yes (type 8 `mhli`) | No |
| **Album list** | Yes (type 4 `mhla`) | No |
| **Smart playlists** | Yes (type 5) | No |
| **Podcast format** | Yes (type 3) | No |

**GNUpod cannot work with any iPod that requires iTunesCDB.** Its database
version (`0x19`) is also too old for most post-2007 iPods, which require
at least `0x20` or higher.

---

## 12. Key Differences & Gotchas

### 1. The Compression Flag at 0xA8

This is a 16-bit field (`guint16` in C, `<H` in Python struct). It's **not**
part of the hash regions — it sits in the header after the hash fields.

- When writing CDB: set to 1
- When reading CDB: expect 1, clear to 0 after decompression
- For normal iTunesDB: always 0

### 2. Header Size Guard

Both compression and decompression require `headerSize >= 0xA9` (169 bytes).
This ensures the `unk_0xA8` field exists within the header. All modern
iTunesDB files use a 244-byte header, so this is always satisfied for
Nano 5G+ databases.

### 3. `total_length` Semantics Change

- **Uncompressed `iTunesDB`:** `total_length` = entire file size =
  sum of all chunks
- **Compressed `iTunesCDB`:** `total_length` = `header_length` +
  `len(compressed_payload)` = physical file size

This means you **cannot** use `total_length` to allocate a buffer for the
uncompressed data. You must decompress first and then recalculate.

### 4. Checksum is Over Compressed Data

The checksum/hash is computed over the **final on-disk bytes** — i.e., the
compressed form for CDB devices. If you decompress → modify → recompress,
you must recompute the checksum after recompression.

### 5. The iTunesDB Truncation

libgpod truncates `iTunesDB` to zero bytes when writing `iTunesCDB`. This
is because the iPhone firmware (and likely Nano 5G+ firmware) "gets confused
when it has both an iTunesCDB and a non-empty iTunesDB" (per the comment
in `itdb_itunesdb.c`).

### 6. zlib Level 1

Apple/iTunes and libgpod both use zlib level 1. While any valid zlib stream
will decompress correctly, using a different level means the compressed
output will differ byte-for-byte from what iTunes would produce. This
may matter if:

- The firmware does byte-level comparison of databases
- Hash computation includes compressed data (it does!)

Using level 1 is recommended for maximum compatibility.

---

## 13. References

| Source | URL |
|--------|-----|
| libgpod `itdb_itunesdb.c` | [GitHub mirror](https://github.com/gtkpod/libgpod/blob/master/src/itdb_itunesdb.c) |
| libgpod `itdb_zlib.c` | [GitHub mirror](https://github.com/gtkpod/libgpod/blob/master/src/itdb_zlib.c) |
| libgpod `itdb_device.c` | [GitHub mirror](https://github.com/gtkpod/libgpod/blob/master/src/itdb_device.c) |
| libgpod `db-itunes-parser.h` | [GitHub mirror](https://github.com/gtkpod/libgpod/blob/master/src/db-itunes-parser.h) |
| libgpod `itdb_hash58.c` | [GitHub mirror](https://github.com/gtkpod/libgpod/blob/master/src/itdb_hash58.c) |
| libgpod `itdb_hash72.c` | [GitHub mirror](https://github.com/gtkpod/libgpod/blob/master/src/itdb_hash72.c) |
| GNUpod `iTunesDB.pm` | [GitHub](https://github.com/nims11/gnupod) |
| iPodLinux iTunesDB wiki | [Archive](https://web.archive.org/web/20081006030946/http://ipodlinux.org/wiki/ITunesDB) |
