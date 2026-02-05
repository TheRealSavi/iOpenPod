# iOpenPod Copilot Instructions

## Project Overview
iOpenPod is an iPod Classic sync tool that reads/writes Apple's proprietary iTunesDB and ArtworkDB binary formats. The app uses a PyQt6 GUI to browse and manage iPod music libraries.

## Architecture

### Binary Parsers (`iTunesDB_Parser/` and `ArtworkDB_Parser/`)
Both parsers follow the **same recursive chunk-based pattern**:
- `parser.py` - Entry point accepting file path or file-like object
- `chunk_parser.py` - Router using `match` statements to dispatch by 4-byte chunk type (e.g., `mhbd`, `mhit`, `mhod`)
- `mh*_parser.py` - Individual parsers for each chunk type using `struct.unpack("<I", ...)` for little-endian binary reading
- `constants.py` - Maps for chunk types, MHOD types, and iTunes version identifiers

**Key pattern**: Every parser returns `{"nextOffset": int, "result": dict}` to enable recursive child parsing. New chunk parsers must follow this convention.

### GUI (`GUI/`)
- `app.py` - Main window with `ThreadPoolSingleton` for background loading, `Worker`/`WorkerSignals` for async tasks
- `widgets/` - PyQt6 components: `MBGridView` (album grid), `MBListView` (track list), `sidebar` (navigation)
- `imgMaker.py` - Decodes RGB565 artwork from `.ithmb` files using NumPy/Pillow

### Data Flow
1. Binary `.itunesdb`/`.artworkdb` files → Parsers → JSON (`idb.json`, `artdb.json`)
2. JSON → GUI loads via `AlbumLoaderThread`/`TrackLoaderThread` workers
3. Artwork: `mhiiLink` in track data references `imgId` in ArtworkDB → `.ithmb` file offset

## iPod Database Format Reference

### File Locations on iPod
- `/iPod_Control/iTunes/iTunesDB` - Primary music database (never written by iPod firmware)
- `/iPod_Control/iTunes/Play Counts` - Play counts since last sync (iPod creates/updates this)
- `/iPod_Control/Artwork/ArtworkDB` - Album artwork metadata
- `/iPod_Control/Artwork/F*_1.ithmb` - Actual artwork images (RGB565 format)

### iTunesDB Chunk Hierarchy
```
mhbd (Database) → mhsd (DataSet, type 1-5) → 
  type 1: mhlt (TrackList) → mhit (Track) → mhod (strings)
  type 2: mhlp (PlaylistList) → mhyp (Playlist) → mhip (PlaylistItem)
  type 3: mhlp (PodcastList)
  type 4: mhla (AlbumList) → mhia (AlbumItem) → mhod
  type 5: mhlp (SmartPlaylistList)
```

### Critical mhit (Track Item) Fields - Currently Unimplemented
| Offset | Field | Size | Notes |
|--------|-------|------|-------|
| 20 | visible | 4 | 1=visible, other=hidden |
| 24 | filetype | 4 | "MP3 ", "M4A ", "M4P " as ASCII |
| 31 | rating | 1 | stars × 20 (0-100) |
| 36 | size | 4 | file size in bytes |
| 40 | length | 4 | duration in milliseconds |
| 44-48 | track_number/total_tracks | 4+4 | |
| 52 | year | 4 | |
| 56 | bitrate | 4 | e.g., 128, 320 |
| 60 | sample_rate | 4 | value × 0x10000 |
| 64 | volume | 4 | -255 to +255 adjustment |
| 80 | play_count | 4 | (iPod doesn't update this directly) |
| 84 | play_count_2 | 4 | plays since last sync |
| 88 | last_played | 4 | Mac timestamp |
| 92-96 | disc_number/total_discs | 4+4 | |
| 104 | date_added | 4 | Mac timestamp |
| 156 | skip_count | 4 | |
| 160 | last_skipped | 4 | Mac timestamp |
| 208 | media_type | 4 | 1=audio, 2=video, 0x20=music video |
| 298 | album_id | 2 | links to mhia |

### Play Counts File Format
Read this file on sync to get actual play counts (iPod updates this, not iTunesDB):
- Header: `mhdp` + entry_length (0x1C for iTunes 7+) + entry_count
- Each entry: play_count(4) + last_played(4) + bookmark(4) + rating(4) + unk(4) + skip_count(4) + last_skipped(4)

### ArtworkDB Image Formats
| Size | Dimensions | Format | Use |
|------|------------|--------|-----|
| 39200 | 140×140 | RGB565_LE | Album art (big) |
| 6272 | 56×56 | RGB565_LE | Album art (small) |
| 20000 | 100×100 | RGB565_LE | Nano/Video art |

## Implementation Roadmap

### Phase 1: Complete Track Parsing (mhit_parser.py)
Add all fields from the table above. Example:
```python
track["rating"] = data[offset + 31]  # single byte
track["playCount"] = struct.unpack("<I", data[offset + 80:offset + 84])[0]
track["length"] = struct.unpack("<I", data[offset + 40:offset + 44])[0]
```

### Phase 2: Playlist Support
1. Add `mhlp_parser.py` for playlist lists
2. Add `mhyp_parser.py` for individual playlists  
3. Add `mhip_parser.py` for playlist items (references track by trackID)
4. Handle MHOD type 50/51 for smart playlist rules

### Phase 3: Play Counts Sync
1. Create `PlayCounts_Parser/` for reading play counts file
2. Merge play_count_2 values back to source library
3. Handle rating sync (compare iPod vs PC, use pessimistic/optimistic strategy)

### Phase 4: Write Support (CRITICAL - Why Simple Edits Break the Database)

**IMPORTANT**: You cannot simply modify a string in the iTunesDB and write it back. Even changing one letter will break the database on newer iPods (Classic, Nano 3G+, etc.) for two reasons:

#### 1. Chunk Length Recalculation
Every chunk has a `total_length` field (offset 8) that includes the header PLUS all children. When a string changes length:
- The MHOD `total_length` must update
- The parent MHIT `total_length` must update  
- The MHLT doesn't store total_length (uses child count instead)
- The parent MHSD `total_length` must update
- The root MHBD `total_length` (= entire file size) must update

**libgpod approach**: Write chunks to a buffer, then backpatch lengths using `fix_header()`:
```c
static void fix_header (WContents *cts, gulong header_seek)
{
    put32lint_seek (cts, cts->pos-header_seek, header_seek+8);
}
```

#### 2. Cryptographic Hash (The Real Blocker)
iPod Classic and Nano 3G+ require a **device-specific cryptographic hash** at mhbd offset 88. Without the correct hash, the iPod will reject the entire database.

**Checksum types by device** (from `itdb_device_get_checksum_type`):
| Checksum Type | Devices | Hash Location | Size | Status |
|--------------|---------|---------------|------|--------|
| NONE | Pre-2007 iPods | N/A | N/A | ✅ Supported |
| HASH58 | iPod Nano 3G | mhbd+88 | 20 bytes | ✅ Supported |
| HASH72 | iPod Classic (all), Nano 4G/5G | mhbd+88 | 46 bytes | ✅ Supported |
| HASHAB | iPod Nano 6G/7G | mhbd+88 | 57 bytes | ❌ **OUT OF SCOPE** |

**Hash generation requires**:
1. The iPod's **FireWire ID** (8 bytes) or **UUID** (20 bytes) - stored in `/iPod_Control/Device/SysInfo`
2. Zero out `db_id` (offset 24), `hash58/72/AB` fields before SHA1
3. Compute SHA1 of the entire database
4. Apply device-specific transformation using AES encryption with the FireWire ID

**From libgpod `itdb_hash58.c`**:
```c
// Generate key from FireWire ID using lookup tables
for (i=0; i<4; i++){
    int a = firewire_id[i*2];
    int b = firewire_id[i*2+1];
    int cur_lcm = lcm(a,b);
    // ... table lookups to generate AES key
}
// HMAC-SHA1 with the generated key
```

**From libgpod `itdb_hash72.c`**:
```c
// Requires a HashInfo file extracted from a valid iTunes sync
// Contains IV + random bytes for AES encryption
hash_generate(signature, sha1, hash_info->iv, hash_info->rndpart);
```

#### Write Implementation Strategy

**Option A: Target older iPods only** (no hash required)
- Pre-2007 iPods (1G-5G) don't require the hash
- Set `mhbd` version to `0x15` (iTunes 7.2) or lower
- Still requires correct chunk length recalculation

**Option B: Use libgpod as a backend**
- Call libgpod via Python bindings or subprocess
- libgpod handles all hash generation correctly
- pip package `python-gpod` wraps libgpod

**Option C: Extract hash info from iTunes sync**
- Sync once with iTunes to generate `/iPod_Control/Device/HashInfo`
- Use this to sign subsequent database writes
- This is how libgpod's HASH72 works

**Option D: Implement full hash generation** (complex)
- Requires reverse-engineered lookup tables and AES implementation
- See `itdb_hash58.c`, `itdb_hash72.c` in libgpod

#### Writer Implementation Checklist
1. Create `iTunesDB_Writer/` mirroring parser structure
2. Build database in memory buffer (not file)
3. Track position and backpatch all `total_length` fields
4. Update counters: `mhbd.num_children`, `mhlt.num_tracks`, etc.
5. Increment `mhbd.next_id` for new tracks
6. Read device SysInfo to determine checksum type
7. Generate appropriate hash or skip for older devices
8. Write atomically (temp file + rename) to prevent corruption

### Hash Algorithm Details (for Python porting)

#### HASH58 (Nano 3G) - FULLY PORTABLE
Complete algorithm from `itdb_hash58.c`:

```python
# Lookup tables (from libgpod itdb_hash58.c lines 45-115)
TABLE1 = bytes([0x63, 0x7C, 0x77, 0x7B, ...])  # 256 bytes - AES S-box
TABLE2 = bytes([0x52, 0x09, 0x6A, 0xD5, ...])  # 256 bytes - Inverse S-box
FIXED = bytes([0x67, 0x23, 0xFE, 0x30, 0x45, 0x33, 0xF8, 0x90, 0x99,
               0x21, 0x07, 0xC1, 0xD0, 0x12, 0xB2, 0xA1, 0x07, 0x81])

def generate_key(firewire_id: bytes) -> bytes:
    """Generate HMAC key from 8-byte FireWire ID using LCM + table lookups"""
    from math import gcd
    import hashlib
    
    def lcm(a, b):
        return (a * b) // gcd(a, b) if a and b else 1
    
    y = bytearray(16)
    for i in range(4):
        a, b = firewire_id[i*2], firewire_id[i*2+1]
        cur_lcm = lcm(a, b)
        hi, lo = (cur_lcm >> 8) & 0xFF, cur_lcm & 0xFF
        y[i*4:i*4+4] = [TABLE1[hi], TABLE2[hi], TABLE1[lo], TABLE2[lo]]
    
    # SHA1(FIXED + y) padded to 64 bytes
    h = hashlib.sha1(FIXED + y).digest()
    return h.ljust(64, b'\x00')

def compute_hash58(firewire_id: bytes, itdb_data: bytes) -> bytes:
    """HMAC-SHA1 using the generated key"""
    import hashlib
    key = generate_key(firewire_id)
    
    # HMAC inner
    inner_key = bytes(b ^ 0x36 for b in key)
    inner_hash = hashlib.sha1(inner_key + itdb_data).digest()
    
    # HMAC outer
    outer_key = bytes(b ^ 0x5c for b in key)
    return hashlib.sha1(outer_key + inner_hash).digest()

def write_hash58(itdb_data: bytearray, firewire_id: bytes):
    """Zero fields, compute hash, write to header"""
    # Backup and zero fields before hashing
    backup_db_id = itdb_data[0x18:0x20]
    backup_unk32 = itdb_data[0x32:0x46]
    itdb_data[0x18:0x20] = b'\x00' * 8   # db_id
    itdb_data[0x32:0x46] = b'\x00' * 20  # unk_0x32
    itdb_data[0x58:0x6C] = b'\x00' * 20  # hash58 field
    
    # Set hashing scheme
    itdb_data[0x46:0x48] = (1).to_bytes(2, 'little')  # HASH58 = 1
    
    # Compute and write hash
    hash_val = compute_hash58(firewire_id, bytes(itdb_data))
    itdb_data[0x58:0x6C] = hash_val
    
    # Restore backed up fields
    itdb_data[0x18:0x20] = backup_db_id
    itdb_data[0x32:0x46] = backup_unk32
```

#### HASH72 (Classic all gens, Nano 5G) - REQUIRES HASHINFO FILE
Requires `/iPod_Control/Device/HashInfo` extracted from a valid iTunes sync.

```python
# AES key (from itdb_hash72.c line 40)
AES_KEY = bytes([0x61, 0x8c, 0xa1, 0x0d, 0xc7, 0xf5, 0x7f, 0xd3,
                 0xb4, 0x72, 0x3e, 0x08, 0x15, 0x74, 0x63, 0xd7])

def read_hash_info(device_path: str) -> tuple[bytes, bytes]:
    """Read HashInfo file: returns (iv[16], rndpart[12])"""
    path = f"{device_path}/iPod_Control/Device/HashInfo"
    with open(path, 'rb') as f:
        data = f.read()
    # struct: header[6] "HASHv0" + uuid[20] + rndpart[12] + iv[16]
    return data[38:54], data[26:38]  # iv, rndpart

def hash72_generate(sha1: bytes, iv: bytes, rndpart: bytes) -> bytes:
    """Generate 46-byte signature using AES encryption"""
    from Crypto.Cipher import AES  # pycryptodome
    
    plaintext = sha1 + rndpart  # 20 + 12 = 32 bytes
    cipher = AES.new(AES_KEY, AES.MODE_CBC, iv)
    encrypted = cipher.encrypt(plaintext)
    
    # Signature format: 0x01 0x00 + rndpart[12] + encrypted[32]
    return bytes([0x01, 0x00]) + rndpart + encrypted
```

#### HASHAB (Nano 6G/7G) - ❌ UNSUPPORTED / OUT OF SCOPE
The HASHAB algorithm was **never reverse-engineered**. It requires a proprietary binary blob
(`libhashab.so`) that contains code extracted from iTunes. Since this only affects iPod Nano 6G
and 7G (a very small user base), these devices are explicitly out of scope for iOpenPod.

If you have a Nano 6G/7G, use iTunes or Rockbox instead.

### Supported Devices by Write Strategy

| Strategy | Devices | Requirements | Status |
|----------|---------|--------------|--------|
| No hash | iPod 1G-5G, Mini, Photo | Just length recalculation | ✅ Supported |
| HASH58 | Nano 3G, Nano 4G | FireWire ID from SysInfo | ✅ Supported |
| HASH72 | Classic (all gens), Nano 5G | HashInfo file (sync with iTunes once) | ✅ Supported |
| HASHAB | Nano 6G/7G only | Not reverse-engineered | ❌ Out of Scope |

### Reading Device Info

```python
def read_sysinfo(ipod_path: str) -> dict:
    """Parse /iPod_Control/Device/SysInfo for device identification"""
    sysinfo = {}
    path = f"{ipod_path}/iPod_Control/Device/SysInfo"
    with open(path, 'r') as f:
        for line in f:
            if ':' in line:
                key, val = line.strip().split(':', 1)
                sysinfo[key.strip()] = val.strip()
    return sysinfo

# Usage:
# sysinfo = read_sysinfo("/media/ipod")
# firewire_id = bytes.fromhex(sysinfo.get("FirewireGuid", ""))
```

## Key Conventions

### Binary Parsing
- Use `struct.unpack("<I", data[offset:offset+4])[0]` for 32-bit LE integers
- Use `struct.unpack("<Q", data[offset:offset+8])[0]` for 64-bit LE (like `dbid`)
- Use `struct.unpack("<H", data[offset:offset+2])[0]` for 16-bit LE
- Single bytes: just `data[offset]`
- MHOD strings: Check for null bytes to determine UTF-16-LE vs UTF-8 encoding
- Mac timestamps: seconds since 1904-01-01 (add 2082844800 to convert to Unix epoch)

### PyQt6 Patterns
- Use `QRunnable` + `WorkerSignals` for background tasks (see `Worker` class in `app.py`)
- Grid items load incrementally via `QTimer.singleShot(1000//144, ...)` for UI responsiveness
- Signals connect components: `sidebar.category_changed.connect(musicBrowser.updateCategory)`

### Important Identifiers
- `dbid` (64-bit): Unique track identifier, links iTunesDB tracks to ArtworkDB images via `songId`
- `mhiiLink`: Track field pointing to album art's `imgId`
- `trackID`: Playlist-scoped identifier (not globally unique)
- `albumID`: Links tracks to album list entries

## Development

### Setup & Running
```bash
uv sync          # Install dependencies
uv run python main.py  # Launch PyQt6 GUI
```

### Dependencies
PyQt6, NumPy, Pillow, DearPyGui (see `pyproject.toml`). Uses **uv** for dependency management.

### Test Data
Parsers expect iPod database files. JSON outputs (`idb.json`, `artdb.json`) should be in the project root. Artwork `.ithmb` files go in `testData/Artwork/`. Paths are computed relative to project root in `GUI/app.py`.

### Adding New MHOD Types
1. Add entry to `constants.py` → `mhod_type_map`
2. Update `mhod_parser.py` if type needs special handling (most are strings)
3. Types 50/51 (smart playlists) have complex binary formats, not strings

### Adding New Chunk Types
1. Add case to `chunk_parser.py` match statement
2. Create `mh*_parser.py` following existing patterns
3. Return `{"nextOffset": offset + chunk_length, "result": {...}}`

## External References
- iPodLinux wiki (archived): https://web.archive.org/web/20081006030946/http://ipodlinux.org/wiki/ITunesDB
- libgpod source (SourceForge): https://sourceforge.net/p/gtkpod/libgpod/ci/master/tree/src/
- libgpod GitHub mirror: https://github.com/gtkpod/libgpod
- Key libgpod files for write support:
  - `itdb_itunesdb.c` - Main database writer (`mk_mhbd`, `mk_mhit`, `fix_header`)
  - `itdb_hash58.c` - Hash generation for Nano 3G
  - `itdb_hash72.c` - Hash generation for Classic/Nano 4G-5G
  - `itdb_device.c` - Device detection and checksum type selection
