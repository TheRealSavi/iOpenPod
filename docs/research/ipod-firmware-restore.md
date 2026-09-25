# iPod Firmware Restore: Technical Reference

A comprehensive guide to restoring legitimate Apple firmware (IPSW) to non-Touch iPod models without iTunes. Covers what is well-documented, what requires reverse engineering, and what open-source prior art exists.

---

## Table of Contents

1. [iPod Families and Restore Mechanisms](#ipod-families-and-restore-mechanisms)
2. [Category A: Disk-Mode iPods (Well Understood)](#category-a-disk-mode-ipods)
3. [Category B: Encrypted Disk-Mode iPods](#category-b-encrypted-disk-mode-ipods)
4. [Category C: DFU-Mode iPods](#category-c-dfu-mode-ipods)
5. [Category D: iPod Shuffle](#category-d-ipod-shuffle)
6. [IPSW File Format](#ipsw-file-format)
7. [Open-Source Prior Art](#open-source-prior-art)
8. [Reverse Engineering Requirements](#reverse-engineering-requirements)
9. [Implementation Roadmap](#implementation-roadmap)

---

## iPod Families and Restore Mechanisms

| Model | Generations | Storage | Restore Mode | Difficulty |
|---|---|---|---|---|
| iPod (Classic lineage) | 1G-5.5G | HDD | Disk Mode (USB Mass Storage) | **Easy** - well documented |
| iPod Classic | 6G (2007), 6.5G/7G (2009) | HDD | Disk Mode (USB Mass Storage) | **Medium** - encrypted firmware |
| iPod Mini | 1G, 2G | Microdrive | Disk Mode (USB Mass Storage) | **Easy** - well documented |
| iPod Nano | 1G | Flash | Disk Mode (USB Mass Storage) | **Easy** - well documented |
| iPod Nano | 2G | Flash | Disk Mode (USB Mass Storage) | **Medium** - encrypted firmware (cracked) |
| iPod Nano | 3G | Flash | DFU Mode | **Hard** - proprietary protocol |
| iPod Nano | 4G, 5G | Flash | DFU Mode | **Hard** - proprietary protocol |
| iPod Nano | 6G, 7G | Flash | DFU Mode | **Very Hard** - signed + encrypted |
| iPod Shuffle | 1G, 2G | Flash | USB Mass Storage | **Medium** - unique format |
| iPod Shuffle | 3G, 4G | Flash | DFU-like | **Hard** - undocumented |

---

## Category A: Disk-Mode iPods

**Models:** iPod 1G-5.5G, iPod Mini 1G-2G, iPod Nano 1G

These are the best-understood iPods. The restore procedure is fully documented by the iPodLinux and Rockbox projects.

### How Disk Mode Works

1. User forces the iPod into **Disk Mode** via button combo:
   - **Click Wheel models (4G+, Mini, Nano):** Hold MENU+SELECT to reboot, then immediately hold SELECT+PLAY until "Disk Mode" screen appears
   - **3G:** Hold MENU+PLAY to reboot, then PLAY+FF
   - **1G/2G (FireWire only):** Hold MENU+PLAY to reboot, then FF+REW
2. The iPod enumerates as a **USB Mass Storage** device (or FireWire mass storage on 1G/2G)
3. The entire disk (HDD or flash) is accessible as a raw block device

### Disk Layout

The iPod disk uses an **MBR partition table** with two partitions:

```
+---------------------+
| MBR (512 bytes)     |
+---------------------+
| Firmware Partition   |  Partition 1 - Type 0x00 (Empty)
| ~80-128 MB          |  Contains bootloader + OS image
+---------------------+
| Data Partition       |  Partition 2 - Type 0x0B (FAT32) or 0xAF (HFS+)
| (remainder of disk)  |  Contains iPod_Control, music, etc.
+---------------------+
```

**Key details:**
- Partition type `0x00` is used for the firmware partition (shows as "empty" to most OS tools)
- Windows-formatted iPods use FAT32 (`0x0B`) for the data partition
- Mac-formatted iPods use HFS+ (`0xAF`) for the data partition
- The firmware partition starts at sector 63 (or sector 1 on some models) and is typically ~80-128 MB

### Firmware Partition Format

The firmware partition contains a concatenation of firmware images with a simple header:

```
Offset  Size  Description
0x0000  4     Magic: "!ATA" (0x21415441) for HDD models
              or "!ATAnano" variant for Nano
0x0004  4     Header version
0x0008  4     Image offset (to first firmware image)
0x000C  4     Image length
0x0010  ...   Directory entries (bootloader, main OS, AUPD images)
```

Each directory entry describes a firmware sub-image:
- **Bootloader** (`osos`): The initial stage bootloader
- **Main OS** (`aupd`): The main operating system image
- The `osos` tag is the main runnable image; `aupd` is used for update staging

### Restore Procedure (Category A)

```
1. Put iPod in Disk Mode
2. Open raw block device (e.g., /dev/sdX or /dev/diskN on macOS)
3. Read MBR to locate firmware partition (partition 1)
4. Extract firmware image from IPSW (see IPSW format section)
5. Write firmware image to firmware partition (raw block write)
6. Optionally: reformat data partition (FAT32 or HFS+)
7. Reboot iPod (MENU+SELECT)
```

This is essentially what iTunes does, and it is what `ipodpatcher` (Rockbox) does to install its bootloader. **No encryption, no signing, no authentication.** You just write bytes to disk.

### Platform Considerations

| Platform | Block Device Access |
|---|---|
| macOS | `/dev/diskN` (unmount first via `diskutil unmountDisk`) |
| Linux | `/dev/sdX` (unmount first) |
| Windows | `\\.\PhysicalDriveN` (via `CreateFile` with admin privileges) |

---

## Category B: Encrypted Disk-Mode iPods

**Models:** iPod Nano 2G, iPod Classic 6G (80/160GB, 2007), iPod Classic 6.5G/7G (120/160GB, 2008-2009)

### What Changed

Starting with the iPod Nano 2G (2006) and continuing with the iPod Classic 6G, Apple introduced:
- **Encrypted firmware**: The firmware image in the firmware partition is AES-128 encrypted
- **Hardware encryption engine**: The S5L8702 SoC (and S5L8720 in 7G) has a hardware AES engine
- **Secure boot chain**: Bootrom verifies the bootloader, bootloader verifies the OS

However, the physical restore mechanism is still **Disk Mode over USB Mass Storage** - the iPod still shows up as a block device.

### The freemyipod.org Breakthrough

The **freemyipod.org** / **emCORE** project reverse-engineered the encryption:
- Extracted AES keys from the bootrom via hardware exploits (voltage glitching on the S5L8702)
- Documented the firmware image encryption format
- The encryption keys are **per-SoC-model**, not per-device, so the same keys work on all iPod Classic 6G units (and separately, all 7G units)
- Keys are publicly available in the emCORE source code
- Also cracked the iPod Nano 2G (S5L8701 SoC) encryption
- Published keys for S5L8700, S5L8701, and S5L8702 SoCs

### Restore Procedure (Category B)

```
1. Put iPod in Disk Mode (same button combo as Category A)
2. Open raw block device
3. Read MBR to locate firmware partition
4. Extract firmware image from IPSW
5. The IPSW firmware image is ALREADY encrypted for the target hardware
   - Apple's IPSW contains the pre-encrypted image, so you write it as-is
6. Write firmware image to firmware partition
7. Optionally: reformat data partition
8. Reboot iPod
```

**Critical insight:** When restoring **legitimate Apple firmware**, you do NOT need to decrypt or re-encrypt anything. Apple's IPSW contains the firmware already encrypted with the correct keys. You just write it to the firmware partition as-is. Decryption keys are only needed if you want to *inspect* or *modify* the firmware.

### NOR Flash (Classic Only)

The iPod Classic has **NOR flash** (1MB) separate from the HDD, containing:
- First-stage bootloader (encrypted)
- NVRAM data
- Boot ROM parameters

NOR flash is **not accessible via Disk Mode** — it requires DFU or specialized tools (emCORE). For a standard firmware restore, the NOR flash does not need to be touched — only the HDD firmware partition is rewritten.

### Complications

- The iPod Classic 6G/7G uses a slightly different firmware partition header format
- The data partition uses a proprietary extent-based filesystem on some models (not standard FAT32/HFS+) - this needs to be formatted correctly for the restored firmware to find its database
- Some 160GB thick models (6G) have a dual-platter drive with a firmware partition layout that spans both platters
- The Nano 2G uses 2048-byte sectors (flash-based) vs 512-byte sectors on HDD-based models — sector alignment matters for raw writes

---

## Category C: DFU-Mode iPods

**Models:** iPod Nano 3G, 4G, 5G, 6G, 7G

### The DFU Paradigm Shift

Starting with the iPod Nano 3G (2007), Apple moved to a completely different restore model inspired by the iPhone. These iPods:
- Do NOT have a user-accessible Disk Mode (the hidden diagnostic mode exists but doesn't expose the filesystem)
- Use **DFU Mode** (Device Firmware Update) for restoration
- Communicate over USB using a **proprietary Apple protocol**, not USB Mass Storage
- The SoCs are from the same S5L family used in iPhones (S5L8720, S5L8922, S5L8723, etc.)

### Entering DFU Mode

- **Nano 3G-5G:** Hold MENU+SELECT to reboot, then immediately hold SELECT+PLAY for ~10 seconds. Screen goes dark, but USB device enumerates in DFU mode
- **Nano 6G-7G:** Connect to USB, hold SLEEP+VOLUME_DOWN for 8 seconds, release SLEEP but keep holding VOLUME_DOWN for another 5 seconds
- Recovery devices enumerate with USB VID `0x05AC` (Apple). The PID changes
  between the Bootrom DFU stage and the WTF/recovery-loader stage:
  - Bootrom DFU: Nano 2G `0x1220`; Nano 3G `0x1223` or `0x1224`;
    Nano 4G `0x1225`; Nano 5G `0x1231`; Nano 6G `0x1232`;
    Shuffle 4G `0x1233`; Nano 7G `0x1234`.
  - WTF/recovery loader: Nano 2G `0x1240`; Classic 6G `0x1241`;
    Nano 3G `0x1242`; Nano 4G `0x1243`; Classic 6.5G `0x1245`;
    Nano 5G `0x1246`; Classic 7G `0x1247`; Nano 6G `0x1248`;
    Nano 7G `0x1249` (or `0x124A` for the Mid-2015 revision).
  - `0x1223` is also shared by all iPod Classic Bootrom DFU revisions, and
    `0x1255` is an alternate Nano 4G DFU identity.

### The USB Protocol

The restore protocol is Apple's proprietary **ASR (Apple Software Restore)** / **Restore Mode** protocol:

1. **DFU Stage:** Host sends a signed bootloader image over USB control transfers
2. **Recovery Stage:** The bootloader runs and enumerates with a new USB PID ("Recovery Mode"). At this point, a higher-level protocol takes over
3. **Restore Stage:** Host sends restore commands and firmware images using a protocol layered on USB bulk transfers. This includes:
   - Uploading a ramdisk image
   - Booting the ramdisk
   - The ramdisk contains the restore agent that writes firmware to flash
   - Communication uses a plist/binary-plist command protocol

### What iTunes Does

iTunes communicates with DFU-mode iPods through:
- **MobileDevice.framework** (macOS) / **iTunesMobileDevice.dll** (Windows)
- This framework handles the USB communication protocol
- It authenticates with Apple's **TSS (Tatsu Signing Server)** to get SHSH blobs for device-specific firmware signing
- The signed firmware is then sent to the device

### Documentation Status

| Component | Status |
|---|---|
| DFU USB enumeration | **Known** - standard USB DFU class with Apple extensions |
| Recovery mode USB protocol | **Partially known** - libirecovery (libimobiledevice project) handles this for iOS devices; likely very similar for Nano 3G+ |
| Firmware image upload | **Partially known** - idevicerestore handles this for iOS; the Nano variants may differ in details |
| TSS / SHSH signing | **Known** - well documented by the jailbreak community. Applies to Nano 4G+ |
| Flash memory layout | **Poorly documented** - NOR/NAND layout specific to each Nano model |
| Nano 3G restore specifics | **Partially known** - S5L8702 based, similar to iPod Classic 6G SoC |
| Nano 4G/5G restore specifics | **Poorly documented** - S5L8720/S5L8922 based |
| Nano 6G/7G restore specifics | **Very poorly documented** - S5L8723/S5L8740 based, uses newer signing |

### SHSH / APTicket Signing

For Nano 4G and later, Apple requires **per-device signing**:
- During restore, iTunes sends the device's ECID (unique chip ID) to Apple's TSS server
- TSS returns a device-specific signature (APTicket / SHSH blob)
- The device bootrom verifies this signature before accepting the firmware
- **This means restoring Nano 4G+ requires communication with Apple's servers** (or saved SHSH blobs)
- If Apple stops signing a firmware version, you cannot restore to it (same as with iPhones)

**Nano 3G** is a special case - it may not require TSS signing, as it predates the APTicket system. This needs verification.

---

## Category D: iPod Shuffle

**Models:** Shuffle 1G, 2G, 3G, 4G

The Shuffle is a unique beast because it has no screen and no standard Disk Mode interface.

### Shuffle 1G

- Appears as **USB Mass Storage** device (essentially a FAT16 flash drive)
- Firmware is stored as a special file on the FAT filesystem — Apple's updater simply copies it
- The firmware update is delivered as a standalone updater application, not an IPSW
- Relatively simple but the firmware file format is not well-documented
- Rockbox does not support any Shuffle

### Shuffle 2G

- Also **USB Mass Storage**
- Uses the **SigmaTel STMP3550** SoC (different vendor than other iPods)
- Firmware is stored on a hidden partition separate from the user-visible FAT volume
- Apple provides standalone updater applications
- The `iPod Shuffle Database` format (`iTunesSD`) is well documented by libgpod
- Firmware restoration format is **poorly documented**

### Shuffle 3G-4G

- Uses **USB HID protocol** (not mass storage, not standard DFU) for communication
- These do NOT appear as drives when connected
- SoC: S5L8720 (3G), S5L8727 (4G)
- Firmware restore requires speaking this proprietary HID protocol
- Very little open-source work has been done on Shuffle restore
- Some community tools can talk to them for database syncing, but firmware restore is essentially undocumented
- **Effectively requires reverse engineering** the USB HID protocol from iTunes traffic captures

---

## IPSW File Format

### What is an IPSW?

IPSW = **iPod/iPhone Software**. Despite the extension, the internal structure varies significantly between iPod generations.

### Important: Early iPods Did Not Use IPSW Files

iPod 1G-5.5G, Mini, and Nano 1G firmware was **not distributed as IPSW files**. Apple distributed these as **standalone updater applications** (Mac `.dmg` / Windows `.exe`) with the firmware image embedded inside. iTunes would download and run these updaters, or directly extract the firmware binary from them.

To support these models, you would either:
1. Extract the firmware binary from the updater application (requires understanding the updater's packaging format)
2. Source pre-extracted firmware images from community archives
3. Read the existing firmware from a known-good iPod as a backup/restore image

### Category B IPSWs (iPod Classic 6G/7G)

The iPod Classic was the first disk-mode iPod to use the **IPSW format** (ZIP archives):

```
iPod_x.x.x_Restore.ipsw
  |-- Firmware/
  |     |-- diskimage.img      (or similar - the raw firmware partition image)
  |     |-- manifest.plist     (describes contents)
  |     |-- dfu/               (DFU-stage images)
  |     |-- all_flash/         (NOR flash images)
  |-- BuildManifest.plist      (build metadata)
```

The key file is the firmware partition image — pre-encrypted and ready to write to the HDD firmware partition as-is.

### Category C IPSWs (DFU-Mode Nanos)

These follow the **iOS-style IPSW format**:

```
iPod_x.x.x_Restore.ipsw
  |-- BuildManifest.plist
  |-- Restore.plist
  |-- Firmware/
  |     |-- dfu/
  |     |     |-- iBSS.*.RELEASE.dfu     (DFU-stage bootloader)
  |     |     |-- iBEC.*.RELEASE.dfu     (Recovery-stage bootloader)
  |     |-- all_flash/
  |     |     |-- LLB.*.RELEASE.img3     (Low-Level Bootloader)
  |     |     |-- DeviceTree.*.img3
  |     |     |-- applelogo.*.img3
  |     |     |-- batterylow*.img3
  |     |     |-- needservice.img3
  |     |-- 058-xxxxx-xxx.dmg            (root filesystem)
  |-- kernelcache.release.*
  |-- xxx-xxxxx-xxx.dmg                  (restore ramdisk)
```

This is structurally identical to iOS IPSWs, just with iPod-specific firmware images. The restore ramdisk and kernelcache are what get loaded during the restore process.

**Image container formats:**
- **IMG2:** Used by Nano 3G/4G — older Apple firmware container format
- **IMG3:** Used by Nano 5G+ — newer format with tags: `DATA` (payload), `KBAG` (key bag for encryption), `SHSH` (signature), `TYPE`, `CERT`
- IMG3 containers are encrypted and signed; the `KBAG` contains the AES key encrypted with the device GID key

### Where to Get IPSWs

Apple historically hosted iPod firmware at URLs like:
- `http://appldnld.apple.com/iPod/...`
- These may still be accessible, and archives like `ipsw.me` catalog them
- iTunes/Finder checks for updates via Apple's version XML catalog

---

## Open-Source Prior Art

### Rockbox - ipodpatcher

**Relevance:** Category A iPods (and partially B)
**What it does:**
- Reads and writes the firmware partition on disk-mode iPods
- Understands the firmware partition header format (`!ATA` magic)
- Can install a dual-boot bootloader alongside Apple firmware
- Written in C, cross-platform (macOS/Linux/Windows)
- **Does NOT handle DFU-mode iPods or Shuffles**

**Source:** `https://git.rockbox.org/` - look for `rbutil/ipodpatcher/`

**Directly useful for:** Understanding firmware partition format, raw disk I/O patterns per platform, and the firmware image header structure.

### freemyipod.org / emCORE

**Relevance:** Category B iPods (iPod Classic 6G/7G), partially Category C (Nano research)
**What it does:**
- Reverse-engineered the S5L8702 and S5L8720 bootrom
- Extracted AES encryption keys for iPod Classic firmware
- Built emCORE, an alternative bootloader/OS for iPod Classic
- Documented the hardware (DMA, LCD controllers, flash, etc.)
- Some work on Nano 3G/4G hardware documentation

**Source:** `https://freemyipod.org/` (wiki), `https://github.com/freemyipod/`

**Directly useful for:** Understanding encrypted firmware format on iPod Classic, SoC documentation, and partial Nano hardware details.

### libimobiledevice / idevicerestore

**Relevance:** Category C iPods (DFU-mode Nanos)
**What it does:**
- `libirecovery`: Communicates with devices in DFU/Recovery mode
- `idevicerestore`: Full firmware restore tool for iOS devices
- Handles the entire restore protocol: DFU upload, recovery mode, TSS signing, ramdisk boot, filesystem restore
- Written in C, cross-platform

**Source:** `https://github.com/libimobiledevice/`

**Directly useful for:** The DFU/Recovery USB protocol is likely identical or very similar for Nano 3G+. `idevicerestore` would be the starting point for Category C support. May need model-specific adaptations.

**Key limitation:** `idevicerestore` does **NOT** support non-Touch iPod models. It is specifically built for iOS-based devices (iPhone, iPad, iPod Touch). Non-Touch iPods do not run iOS and do not have the same restore service stack (`ASR`, `restored`, `lockdownd`). However, the low-level USB DFU code in `libirecovery` is reusable since later Nanos share the same DFU characteristics at the USB transport level.

### libgpod

**Relevance:** Data partition (not firmware restoration)
**What it does:**
- Reads/writes the iTunesDB database
- Manages the iPod data partition content
- Has device detection and model identification

**Not directly useful for firmware restoration**, but useful for reformatting the data partition as part of a full restore (writing a fresh iTunesDB, creating the `iPod_Control` directory structure).

### ipoddfu (freemyipod contributors)

**Relevance:** Category B and C iPods
**What it does:**
- A Python tool for sending DFU payloads to S5L-based iPods
- Can bootstrap payloads onto iPod Classic and some Nanos via DFU mode
- Used alongside emCORE for initial bootloader installation

**Source:** Various repositories on GitHub under freemyipod contributors

**Directly useful for:** Understanding the DFU USB transfer protocol for S5L-based iPods in Python — the closest existing Python implementation to what iOpenPod would need for DFU-mode restore support.

---

## Reverse Engineering Requirements

### What's Already Solved (Can Build Today)

| Task | Status | Source |
|---|---|---|
| Disk Mode entry detection | Solved | Standard USB enumeration; known PIDs |
| Raw disk I/O on macOS/Linux/Windows | Solved | Standard OS APIs |
| Firmware partition read/write (Cat A) | Solved | Rockbox ipodpatcher |
| Firmware partition format (Cat A) | Solved | iPodLinux, Rockbox documentation |
| IPSW extraction (all categories) | Solved | Standard ZIP extraction |
| iPod Classic encrypted FW write | Solved | Write IPSW image as-is (pre-encrypted) |
| Data partition formatting (FAT32) | Solved | Standard filesystem tools |
| DFU mode USB communication | Mostly solved | libirecovery |

### What Needs Work (Partially Known)

| Task | Status | Notes |
|---|---|---|
| iPod Classic data partition format | Needs investigation | 6G/7G may use custom extent-based FS, not plain FAT32 |
| Nano 3G restore protocol details | Partially known | S5L8702-based, similar to Classic 6G. freemyipod has some docs |
| Nano 4G/5G restore protocol | Partially known | Similar to early iOS devices; idevicerestore may work with adaptation |
| TSS signing for Nanos | Partially known | Same server as iOS, but need Nano-specific request format |
| IPSW format for oldest iPods (1G-3G) | Needs verification | May be DMG or package format, not ZIP |

### What Requires Significant Reverse Engineering

| Task | Status | Notes |
|---|---|---|
| Nano 6G/7G restore | Poorly documented | Newer SoC, newer signing, multi-touch models |
| Shuffle 3G/4G restore | Almost undocumented | Proprietary USB protocol, no open-source implementations |
| Shuffle 1G/2G firmware area | Poorly documented | Hidden firmware area format not well understood |
| Nano NOR/NAND flash layout | Poorly documented | Per-model flash memory mapping needed for DFU restore |

---

## Implementation Roadmap

### Phase 1: Disk-Mode iPods (Lowest Hanging Fruit)

**Target:** iPod 1G-5.5G, Mini 1G-2G, Nano 1G

**Effort:** Low-Medium. Well-documented, no encryption, no signing.

**Note:** Early iPods used standalone updater apps, not IPSW files. You'll need a way to source the raw firmware binary (extract from updaters, community archives, or back up from a working iPod).

**Steps:**
1. Detect iPod in Disk Mode via USB VID/PID enumeration
2. Identify the raw block device path (platform-specific)
3. Read MBR, locate firmware partition
4. Parse IPSW ZIP, extract firmware image
5. Validate firmware image (size check, magic bytes)
6. Write firmware image to firmware partition
7. Optionally reformat data partition (FAT32, create `iPod_Control` structure)
8. Eject and reboot

**Python libraries needed:** `pyusb` or platform USB APIs, `zipfile`, raw block device I/O (likely `open()` with `os.O_RDWR` on Unix, `ctypes`/`win32file` on Windows)

### Phase 2: iPod Classic 6G/7G

**Target:** iPod Classic (all sub-generations)

**Effort:** Low-Medium (same as Phase 1 for legitimate firmware). The firmware image from the IPSW is already encrypted and ready to write.

**Target also includes:** iPod Nano 2G (encryption cracked by freemyipod, same write-as-is approach for legitimate firmware)

**Additional steps beyond Phase 1:**
1. Handle the slightly different firmware partition header
2. Handle data partition formatting (need to determine if 6G/7G require specific filesystem format or if FAT32 works)
3. Handle sector size differences: HDD-based iPods use 512-byte sectors, flash-based (Nano 1G/2G) use 2048-byte sectors

### Phase 3: iPod Nano 3G-5G via DFU

**Target:** iPod Nano 3G, 4G, 5G

**Effort:** High. Requires implementing the DFU/Recovery USB protocol.

**Approach:**
1. Use `libirecovery` (via Python bindings or ctypes/cffi) or reimplement the USB control transfer protocol
2. Implement the restore sequence: DFU upload -> Recovery mode -> ramdisk boot -> firmware flash
3. For Nano 4G/5G: implement TSS signing requests to Apple's servers
4. Test extensively - bricking risk is real

**Alternative:** Wrap `idevicerestore` as a subprocess if it supports these Nano models. This avoids reimplementing the protocol but adds a binary dependency.

### Phase 4: Nano 6G/7G and Shuffles

**Target:** iPod Nano 6G-7G, iPod Shuffle 1G-4G

**Effort:** Very High. Significant reverse engineering needed.

**Recommendation:** Defer this phase. These models are the least common in active use and the least documented. Consider partnering with the freemyipod.org community or waiting for more documentation to emerge.

---

## Key Risks and Considerations

### Bricking

- **Category A/B (Disk Mode):** Low brick risk. If the firmware write fails, the user can re-enter Disk Mode and try again. The bootrom is in ROM and cannot be overwritten.
- **Category C/D (DFU):** Higher brick risk. Interrupting a DFU restore can leave the device in an unrecoverable state. However, DFU mode itself is a bootrom feature and should always be re-enterable.

### Apple Server Dependencies

- **Category A/B:** No server dependency. Fully offline restore possible.
- **Category C (Nano 4G+):** Requires Apple's TSS server for signing. If Apple shuts down TSS for these devices, restore becomes impossible without saved SHSH blobs.
- **Nano 3G:** May not require TSS - needs verification.

### Legal Considerations

- Distributing Apple's IPSW files: Apple makes these freely downloadable; redistributing them is a gray area but common practice (ipsw.me, etc.)
- Implementing the restore protocol: This involves interoperating with Apple hardware using publicly observable USB protocols. No DMCA circumvention is required for restoring legitimate, unmodified firmware.
- Using freemyipod encryption keys: Only needed if modifying firmware, not for legitimate restores.

### Platform-Specific Raw Disk Access

- **macOS:** Requires unmounting the disk first (`diskutil unmountDisk`). Raw access via `/dev/rdiskN` (character device) is faster than `/dev/diskN` (block device). May require root or `diskutil` authorization.
- **Linux:** Requires unmounting. Raw access via `/dev/sdX`. Requires root or appropriate udev rules.
- **Windows:** Requires admin privileges. Access via `\\.\PhysicalDriveN` using `CreateFile`. Windows may fight you for exclusive access - may need to take the volume offline first.

---

## References

- **iPodLinux Wiki (archived):** Extensive documentation on firmware partition format, disk layout, and hardware details for 1G-5G iPods
- **Rockbox Wiki & Source:** `ipodpatcher` source code is the definitive reference for firmware partition I/O
- **freemyipod.org Wiki:** S5L8702/S5L8720 SoC documentation, encryption keys, hardware details
- **The iPhone Wiki (theapplewiki.com):** IPSW format documentation, DFU/Recovery protocols, TSS signing, SoC details (applies to Nano 3G+ since they share SoC families with iPhones)
- **libimobiledevice project:** `libirecovery` and `idevicerestore` source code for DFU/Recovery protocol implementation
- **USB IF:** USB DFU class specification (the base protocol Apple's DFU derives from)
