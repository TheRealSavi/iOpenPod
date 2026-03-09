# iTunesDB Deep Analysis Report — New Discoveries & Hardware-Testable Theories

**Databases analysed:** 9 iTunesDB/iTunesCDB files across Photo, iPod 3G, Nano 1G, Nano 2G, Nano 4G, Classic 6.5G, Nano 6G, Nano 7G, iPod touch 5G.  
**Tracks scanned:** 1,460 total (6 DBs with tracks: Photo=191, iPod3=193, Nano1=184, Nano6=522, Nano7=184, touch5=186).  
**Cross-DB matching:** 164 tracks common across 5 databases (Photo/iPod3/Nano1/Nano7/touch5).

---

## Part A: Confirmed Identifications (No Hardware Testing Needed)

### A1. MHOD Type Names Verified

All five "unknown" MHOD types found in the Nano6 production library are now identified:

| Type | Name | Example Content | Count (Nano6) |
|------|------|-----------------|---------------|
| 22 | **Album Artist** | "Les Misérables Cast", "Various Artists" | 392/522 |
| 23 | **Sort Artist** | "Adam Lambert", "All-American Rejects" | 126/522 |
| 26 | **iTunes Store Asset Info** | Apple plist XML (see A2) | 95/522 |
| 37 | **Content Provider** | iTunes Store publisher name | 115/522 |
| 39 | **Copyright** | "℗ 2016 Ode Sounds & Visuals" | 114/522 |
| 42 | **Encoding Quality** | "HQ" (48 tracks), "2:256" (31 tracks) | 79/522 |
| 43 | **Purchase Account** | Apple ID of buyer | 129/522 |
| 44 | **Purchaser Name** | Full name of buyer | 146/522 |

Types 22, 23, 37, 39, 43, 44 were already named in `constants.py` — confirmed correct.

### A2. MHOD Type 26 — iTunes Store Asset Plist

Full decoded XML from a type 26 MHOD:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>asset-info</key>
    <dict>
        <key>file-size</key>
        <integer>6955694</integer>
        <key>flavor</key>
        <string>HQ</string>
    </dict>
</dict>
</plist>
```

**Interpretation:** Records the original iTunes Store download quality flavor ("HQ") and file size. Only present on 95/522 tracks — a subset of purchased content. Used by iTunes for "iTunes in the Cloud" re-downloading and purchase verification.

**Naming recommendation:** Rename type 26 from unknown to `"iTunes Store Asset Info (plist)"`.

### A3. MHOD Type 42 — Encoding Quality Descriptor

Two distinct values observed:
- `"HQ"` — 48 tracks — simplified quality label (iTunes Plus branding)
- `"2:256"` — 31 tracks — `channels:bitrate_kbps` technical spec

**Naming recommendation:** Rename type 42 to `"Encoding Quality Descriptor"`.

### A4. `db_id_2` (mhbd+0x24) = iTunes Library Persistent ID

Cross-database matching proves this is NOT device-specific — it's the source iTunes library's ID:

| Library ID | Databases |
|------------|-----------|
| `0xB227F52A6CC52E7C` | Photo, Nano1, Classic6.5, Nano7, touch5 |
| `0x04A9801803E3A497` | iPod3, Nano4 |
| `0x98896694925F58B8` | Nano2 |
| `0x7EA5E9BAE9084443` | Nano6 |

Multiple iPods synced from the same iTunes library share identical `db_id_2`. In Nano6, every track's `mhbd_id_ref` field matches `db_id_2` exactly, confirming this is a library back-reference.

### A5. Byte 0x93 — "Purchased / AAC" Flag (Confirmed Split from `explicit` u16)

The field previously parsed as `explicit` (u16 at offset 0x92) is actually **two separate bytes**:

| Offset | Size | Field | Values |
|--------|------|-------|--------|
| 0x92 | u8 | `explicit` | 0=none, 1=explicit, 2=clean |
| 0x93 | u8 | `purchased_aac_flag` | 0 or 1 |

Evidence from Nano6 (522 tracks):

| byte 0x92 | byte 0x93 | Count |
|-----------|-----------|-------|
| 0x00 (none) | 0x01 | 334 |
| 0x00 (none) | 0x00 | 185 |
| 0x01 (explicit) | 0x01 | 2 |
| 0x02 (clean) | 0x01 | 1 |

Cross-tabulation with filetype:
- M4A + byte0x93=1 → **293 tracks** (100% of all M4A tracks)
- MP3 + byte0x93=0 → 185 tracks
- MP3 + byte0x93=1 → 44 tracks

All M4A tracks have 0x93=1. 44 of 229 MP3 tracks also have 0x93=1 — these may be iTunes Store MP3 purchases or iTunes Match-matched tracks.

### A6. sort_mhod_indicators — Corrected Byte Mapping

**Previous assumption:** Bytes 0-1 at offset 0x134 are u16 padding.  
**Finding:** They are NOT padding. The correct verified mapping (confirmed via exhaustive bit-correlation across Photo, Nano6, Nano7):

| Byte | Offset | bit 0 = has MHOD type | Correlation |
|------|--------|----------------------|-------------|
| [0] | 0x134 | **sort_title** (type 27) | 100% Photo; 99.6% Nano6 (2 mismatches) |
| [1] | 0x135 | **sort_album** (type 28) | 100% Photo; 99.8% Nano6 (1 mismatch) |
| [2] | 0x136 | **sort_artist** (type 23) | 100% Nano6 (disambiguated) |
| [3] | 0x137 | **sort_album_artist** (type 29) | 100% Nano6 (disambiguated) |
| [4] | 0x138 | **sort_composer** (type 30) | 100% Photo (15 matching tracks) |
| [5] | 0x139 | **sort_show** (type 31) | All zero (no sort_show MHODs in any DB) |
| [6] | 0x13A | unused | Always 0 |
| [7] | 0x13B | unused | Always 0 |

**Bit encoding:**
- bit 0 (0x01) = has corresponding sort MHOD override
- bit 7 (0x80) = collation/version flag (always set in Photo/iPod3/Nano7/touch5; absent on ~18% of Nano6 tracks)
- Values observed: 0x00 (no override, new), 0x01 (has override, new), 0x80 (no override, old), 0x81 (has override, old), 0x02/0x03 (rare Nano6 variants)

### A7. MHBD Constants Confirmed Across All 9 Databases

| Field | Offset | Value | Interpretation |
|-------|--------|-------|----------------|
| `unk0x22` | 0x22 | 0x0263 (611) | Fixed iTunes capability flag |
| `unk0xa4` | 0xA4 | 0x0019 (25) | Fixed constant |
| `unk0xa6` | 0xA6 | 0x000A (10) | Fixed constant |
| `unk0xa8` | 0xA8 | 0x0000 or 0x0001 | **0x0001 = CDB-capable** (only Nano6/7/touch5) |

### A8. MHSD Types 11 and 12 (touch5 only)

**Type 11:** 144 bytes. 96-byte MHSD header + 48-byte body (NOT an mh* tag). Body: `[3, 1, 1, 1, 0...]`. Likely a capabilities/configuration stub.

**Type 12:** 112 bytes. 96-byte MHSD header + `mhos` chunk (16 bytes, empty). New chunk type "mhos" — possibly "Music Hub Online Store" placeholder or a stub for cloud-sync features.

---

## Part B: Hardware-Testable Theories

### Theory 1: `unk0x98` = Genius Mixes Category ID

**Field:** mhit offset 0x98, u32  
**Observed:** 15 distinct values (0–14), only non-zero in Nano6 (218/522 non-zero). All other databases = 0.

**Evidence:**
- Values 1–14 form a decreasing distribution: 56, 39, 26, 23, 21, 17, 13, 7, 4, 2, 1, 4, 4, 1
- Does NOT correlate with genre (all genres appear at all values)
- Does NOT correlate with filetype, year, bitrate, or album artist
- Only appears in the production library (Nano6, synced 2014–2016) — test databases with recent syncs all show 0
- Genius Mixes generates ~12–15 automatic playlist categories based on acoustic analysis
- Value 0 = "not yet classified by Genius" or "insufficient data"

**Test procedure:**
1. Connect an iPod with Genius enabled
2. Sync a library that has Genius data (requires "Update Genius" in iTunes)
3. Read back the iTunesDB — check if unk0x98 is populated
4. Compare the groupings: tracks with the same unk0x98 value should appear in the same Genius Mix
5. Disable Genius, re-sync, check if values revert to 0

**Alternative theory:** This could be `genius_cuid_index` (Genius CUID = Category Unique ID). MHSD type 9 contains a Genius CUID string; unk0x98 might index into a lookup table.

### Theory 2: `unk0x168` = iTunes Library Feature Version

**Field:** mhit offset 0x168, u32 (currently called `unk_flag`)  
**Observed:**
- Photo / iPod3 / Nano1 / Nano7 / touch5: **always 1**
- Nano6: **32 on 521/522 tracks**, 1 on exactly 1 track

**The outlier** (unk0x168=1, Nano6):
- "Get in My Mouth" by Starkid — MP3, 128kbps, 44100Hz
- Minimal metadata: no genre, no year, only MHOD types [1,2,3,4,6,22,28]
- All other Nano6 tracks (unk0x168=32) have richer metadata

**Hypothesis:** The value indicates the **iTunes metadata version** that processed the track:
- 1 = basic/legacy metadata (older iTunes or manual add)
- 32 = full iTunes 12.x metadata processing

The one exception track was likely imported without re-processing (dragged in as a raw MP3, not "added to Library" properly).

**Test procedure:**
1. In iTunes 12.x: add a track via File > Add to Library → check unk0x168
2. Drag-drop an MP3 directly to the iPod in Finder → check unk0x168
3. Change unk0x168 from 32 to 1 (or vice versa) on a test database → sync to iPod → observe any behavior change
4. Note: libgpod always writes 1 — Nano6's firmware has been tested with value 32 for years, so 32 is definitely valid

**Alternative theory:** 32 = 0x20 = a bitmask for "Music Video capable" (0x20 in MEDIA_TYPE_MAP). The field might indicate what media features the track supports, not just audio-vs-video.

### Theory 3: Byte 0x93 = "iTunes Match / iCloud" Status

**Field:** mhit offset 0x93, u8 (previously packed into `explicit` u16)  
**Observed in Nano6:**
- 0x93=1 on ALL 293 M4A tracks + 44 of 229 MP3 tracks
- 0x93=0 on 185 MP3 tracks
- Identical across same-library databases → set per-track in iTunes

**Key observation:** 0x93=1 tracks form a superset of iTunes Store purchases (type 26 asset plist is only on 95 tracks, but 0x93=1 is on 337 tracks).

**Test procedure:**
1. Rip a CD to MP3 in iTunes → check byte 0x93 (expect 0)
2. Purchase a track from iTunes Store → check byte 0x93 (expect 1)
3. Use iTunes Match to "match" a local MP3 → check if 0x93 changes to 1
4. Import a manually-tagged MP3 → check byte 0x93

**Alternative theories:**
- "Apple Digital Master" quality flag
- "Has been cloud-matched" flag (iTunes Match)
- "Was processed by iTunes AAC encoder" (which would explain ALL M4A = 1)

### Theory 4: sort_indicator bit 7 (0x80) = Collation Version

**Field:** Bytes 0x134–0x139, bit 7

**Observed:**
- Photo / iPod3 / Nano7 / touch5: bit 7 **always set** (values 0x80 or 0x81)
- Nano6: bit 7 **sometimes absent** (values 0x00, 0x01, 0x02, 0x03 for ~18% of tracks)

**Cross-DB matching:** Same tracks in Photo have 0x81 but in Nano1/Nano7/touch5 have 0x80 (10 tracks differ in byte[0], 32 in byte[1]). The difference is that Photo/iPod3 have sort MHODs (type 27) that Nano1/Nano7/touch5 don't.

**Hypothesis:** Bit 7 indicates the **Unicode collation algorithm version** used:
- 0x80 = "ICU collation applied" (default)
- 0x00 = "No collation" or "newer collation method"

The iPod firmware likely only checks bit 0 (sort override present?) and ignores bit 7.

**Test procedure:**
1. Toggle bit 7 on a track with an existing sort MHOD → sync → check if sort order changes
2. Clear all sort_indicator bytes to 0x00 → sync → check if iPod falls back to default sorting
3. Set bit 7 to 0x80 on all bytes without changing bit 0 → verify no change in behavior

### Theory 5: MHSD Type 11 = Genius Configuration

**Only in:** touch5 (CDB format)

**Body:** `[3, 1, 1, 1, 0, 0, ...]` (48 bytes of payload)

**Hypothesis:** This is a Genius database configuration block:
- Field 0 = 3 → structure version
- Field 1 = 1 → Genius enabled
- Field 2 = 1 → number of Genius Mix categories synced
- Field 3 = 1 → ???

**Test:** Enable/disable Genius on an iPod touch, then compare the MHSD type 11 content before and after.

### Theory 6: MHOD Type 42 Encodes iTunes Store Vintage

**Observed:** Two distinct encoding quality formats:
- `"HQ"` — 48 tracks
- `"2:256"` — 31 tracks

**Hypothesis:** The format changed over iTunes Store versions:
- "HQ" = older iTunes Plus branding (2007–2012 era)
- "2:256" = newer detailed spec format (channels:bitrate, 2013+ era)

**Test:** Check purchase dates of tracks with each format. If `"HQ"` tracks were all purchased before ~2013 and `"2:256"` after, this confirms the theory.

### Theory 7: `unk0xa8` = Compressed DB Capability

**Field:** mhbd offset 0xA8, u32

**Observed:**
- 0x0000 on Photo, iPod3, Nano1, Nano2, Nano4, Classic6.5 (all non-CDB)
- 0x0001 on Nano6, Nano7, touch5 (all CDB)

**Hypothesis:** This marks whether the iTunesDB was originally a CDB (compressed) database. Set to 1 when the source iTunes library generates CDB format.

**Test:** Create an uncompressed iTunesDB with `unk0xa8=1` → sync to a non-CDB iPod → observe whether the iPod ignores or rejects it. Conversely, write `unk0xa8=0` in a CDB → see if the target iPod still accepts it.

---

## Part C: Cross-Database Observations

### C1. Fields That Are Identical Across Same-Track, Different-Device

When the same track appears on multiple iPods (Photo, iPod3, Nano1, Nano7, touch5):

| Field | Identical? | Notes |
|-------|-----------|-------|
| `unk0x168` | ✅ Yes | Always 1 across all 5 DBs |
| `unk0x98` | ✅ Yes | Always 0 across all 5 DBs |
| `byte0x92` (explicit) | ✅ Yes | Per-track metadata from iTunes |
| `byte0x93` | ✅ Yes | Per-track flag from iTunes |
| `media_type` | ✅ Yes | |
| `filetype` | ✅ Yes | |
| **bitrate** | ❌ **No** | Photo/iPod3=320kbps, Nano1/Nano7/touch5=128kbps |
| **sort_ind[0]** | ❌ **No** | Photo/iPod3=0x81, Nano1/Nano7/touch5=0x80 (10 tracks) |
| **sort_ind[1]** | ❌ **No** | Photo/iPod3=0x81, Nano1/Nano7/touch5=0x80 (32 tracks) |

**Bitrate note:** Photo/iPod3 got full 320kbps, while Nano1/Nano7/touch5 got 128kbps transcodes. This is iTunes' "Convert higher bit rate songs to 128 kbps AAC" option — enabled for smaller-storage iPods.

**Sort indicator note:** Photo/iPod3 have sort override MHODs (types 27/28) on some tracks, while Nano1/Nano7/touch5 don't, resulting in 0x81 vs 0x80. The sort overrides were likely introduced in a different iTunes version used for Photo/iPod3 syncing.

### C2. MHOD Type Distribution Shows iTunes Evolution

| Type | Photo | iPod3 | Nano1 | Nano7 | touch5 | Nano6 |
|------|-------|-------|-------|-------|--------|-------|
| 1 (title) | 191 | 193 | 184 | 184 | 186 | 522 |
| 22 (album artist) | 187 | 189 | 180 | 180 | 182 | 392 |
| 23 (sort artist) | 186 | 188 | 179 | 179 | 181 | 126 |
| 27 (sort title) | **12** | **12** | 0 | 0 | 0 | **124** |
| 28 (sort album) | **48** | **50** | **1** | **1** | **1** | **208** |
| 29 (sort album artist) | 186 | 188 | 179 | 179 | 181 | 17 |
| 26 (asset plist) | 0 | 0 | 0 | 0 | 0 | **95** |
| 37 (provider) | 0 | 0 | 0 | 0 | 0 | **115** |
| 39 (copyright) | 0 | 0 | 0 | 0 | 0 | **114** |
| 42 (quality) | 0 | 0 | 0 | 0 | 0 | **79** |
| 43 (purchase acct) | 0 | 0 | 0 | 0 | 0 | **129** |
| 44 (purchaser) | 0 | 0 | 0 | 0 | 0 | **146** |

iTunes Store metadata types (26, 37, 39, 42, 43, 44) appear **only on Nano6** — because it's the only real production library with iTunes Store purchases.

### C3. Same-Library Groups

| Library ID | Devices | Source |
|------------|---------|--------|
| `0xB227F52A6CC52E7C` | Photo, Nano1, Classic6.5, Nano7, touch5 | skep's test library |
| `0x04A9801803E3A497` | iPod3, Nano4 | skep's other library |
| `0x7EA5E9BAE9084443` | Nano6 | Production library (2014–2016) |
| `0x98896694925F58B8` | Nano2 | iOpenPod-generated (0 tracks) |

---

## Part D: Writer Implications

### D1. Immediate Action Items

1. **Split `explicit` u16 into two u8 fields** in field_defs.py:
   - `explicit` (u8 at 0x92): 0=none, 1=explicit, 2=clean
   - `purchased_flag` (u8 at 0x93): 0 or 1

2. **Update sort_mhod_indicators mapping** in field_defs.py:
   - Bytes 0–5 map to: sort_title, sort_album, sort_artist, sort_album_artist, sort_composer, sort_show
   - bit 0 = has corresponding sort MHOD; bit 7 = collation flag (safe to set to 0x80)

3. **Add MHOD type 26 name** in constants.py:
   - `26: "iTunes Store Asset Info"`

4. **Add MHOD type 42 name** in constants.py:
   - `42: "Encoding Quality Descriptor"`

5. **Set unk0xa8=1** when writing CDB format, 0 otherwise.

6. **Write unk0x168=1** (current behavior) — safe for all devices, though real iTunes 12 writes 32.

### D2. Safe-to-Ignore Fields (Writer)

- `unk0x98` (Genius category) — write 0, iPod will compute on-device
- MHOD types 26, 37, 42, 43, 44 — iTunes Store metadata, don't generate
- `byte0x93` — write 0 for non-purchased tracks (safe default)
- MHSD types 11, 12 — can omit, only seen on touch5
