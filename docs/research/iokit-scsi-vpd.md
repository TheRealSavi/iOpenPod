# IOKit SCSI VPD Passthrough on macOS — How It Works

## Problem

Apple iPods store device identity data (serial number, FamilyID, codec
capabilities, artwork specs) in SCSI VPD (Vital Product Data) pages accessible
via INQUIRY commands.  The existing approach (`iopenpod.device.vpd_libusb`) uses pyusb
to send these SCSI commands over the USB bulk transport, but this requires:

1. **Root / sudo** — the macOS kernel mass-storage driver (`IOUSBMassStorageDriver`)
   must be detached before pyusb can claim the interface.
2. **Disk unmount** — detaching the driver causes the iPod volume to unmount.
   The user sees their iPod disappear from Finder for several seconds.
3. **Remount wait** — after reattaching the driver, the code must wait up to
   12 seconds for the iPod to remount, and the mount point may change
   (e.g. `/Volumes/JOHN'S IPOD` → `/Volumes/JOHN'S IPOD 1`).

The goal was to send the same SCSI INQUIRY commands **without root, without
detaching the driver, and without unmounting the disk**.

## Solution: IOKit SCSITaskLib CFPlugIn

macOS provides `SCSITaskLib.plugin` — a CFPlugIn that lets user-space code send
SCSI commands to devices through the kernel's SCSI architecture, coexisting with
the mass-storage driver.  This is the same mechanism that Apple's Disk Utility and
other tools use internally.

The plugin lives at:
```
/System/Library/Extensions/IOSCSIArchitectureModelFamily.kext/
  Contents/PlugIns/SCSITaskUserClient.kext/
    Contents/PlugIns/SCSITaskLib.plugin/
      Contents/MacOS/SCSITaskLib
```

It is a **universal binary** (x86_64 / arm64 / arm64e).  No third-party packages
are needed — everything is accessed via `ctypes`.

### What the plugin provides

- `SCSITaskDeviceInterface` — manages exclusive SCSI access to a device
- `SCSITaskInterface` — represents a single SCSI command (CDB + scatter-gather
  buffers + timeout + execution)

Both are COM-style interfaces accessed through vtable pointers.

## Key Discoveries

### 1. The documented UUID is wrong

Apple's `SCSITaskLib.h` header declares:

```c
#define kSCSITaskDeviceInterfaceID  CFUUIDGetConstantUUIDWithBytes(NULL, \
    0x6B, 0xD4, 0x8A, 0xE0, 0x08, 0xA2, 0x11, 0xD5, \
    0xA1, 0xB8, 0x00, 0x30, 0x65, 0x7D, 0x05, 0x2A)
```

**This UUID does not work.**  `QueryInterface` returns `E_NOINTERFACE` (0x80000004).

The actual UUID used by the implementation was found by disassembling the
`SCSITaskDeviceClass::QueryInterface` method in the plugin binary:

```bash
otool -arch arm64e -tV SCSITaskLib | grep -A 40 'SCSITaskDeviceClass::QueryInterface'
```

The disassembly shows the method calls `CFUUIDGetConstantUUIDWithBytes` with:

```
UUID: 1BBC4132-08A5-11D5-90ED-0030657D052A
```

This is the UUID that actually works.  In raw bytes:
```python
_kSCSITaskDeviceInterfaceID_bytes = bytes([
    0x1B, 0xBC, 0x41, 0x32, 0x08, 0xA5, 0x11, 0xD5,
    0x90, 0xED, 0x00, 0x30, 0x65, 0x7D, 0x05, 0x2A,
])
```

### 2. COM vtable layout

IOKit CFPlugIn interfaces use Microsoft COM-style vtables with double-pointer
indirection:

```
obj → *(void**) vtable → [slot0, slot1, slot2, ...]
```

The first 5 slots are always:
```
[0] = NULL (reserved)
[1] = QueryInterface(self, uuid_lo, uuid_hi, &ppv)
[2] = AddRef(self)
[3] = Release(self)
[4] = version field (NOT a function pointer — value is 0x1)
```

**Slot 4 is a trap.**  It contains the literal integer `1`, not a function
pointer.  Calling it as a function causes a segfault.  Actual interface methods
start at slot 5.

#### SCSITaskDeviceInterface vtable (confirmed from binary)

| Slot | Method |
|------|--------|
| 5 | `IsExclusiveAccessAvailable` |
| 6 | `AddCallbackDispatcherToRunLoop` |
| 7 | `RemoveCallbackDispatcherFromRunLoop` |
| 8 | `ObtainExclusiveAccess` |
| 9 | `ReleaseExclusiveAccess` |
| 10 | `CreateSCSITask` → returns `SCSITaskInterface*` |

#### SCSITaskInterface vtable (confirmed from binary)

| Slot | Method | Signature |
|------|--------|-----------|
| 5 | `IsTaskActive` | `(self) → bool` |
| 6 | `SetTaskAttribute` | `(self, SCSITaskAttribute) → IOReturn` |
| 7 | `GetTaskAttribute` | `(self, SCSITaskAttribute*) → IOReturn` |
| 8 | `SetCommandDescriptorBlock` | `(self, uint8*, uint8 cdbSize) → IOReturn` |
| 9 | `GetCommandDescriptorBlockSize` | `(self) → uint8` |
| 10 | `GetCommandDescriptorBlock` | `(self, uint8*) → IOReturn` |
| 11 | `SetScatterGatherEntries` | `(self, IOVirtualRange*, uint8 count, uint64 xferLen, uint8 direction) → IOReturn` |
| 12 | `SetTimeoutDuration` | `(self, uint32 ms) → IOReturn` |
| 13 | `GetTimeoutDuration` | `(self) → uint32` |
| 14 | `SetTaskCompletionCallback` | `(self, callback, void*) → IOReturn` |
| 15 | `ExecuteTaskAsync` | `(self) → IOReturn` |
| 16 | `ExecuteTaskSync` | `(self, SenseData*, TaskStatus*, uint64* realized) → IOReturn` |
| 17 | `AbortTask` | `(self) → IOReturn` |
| 18 | `GetServiceResponse` | `(self) → SCSIServiceResponse` |
| 19 | `GetTaskState` | `(self) → SCSITaskState` |
| 20 | `GetTaskStatus` | `(self) → SCSITaskStatus` |
| 21 | `GetRealizedDataTransferCount` | `(self) → uint64` |
| 22 | `GetAutoSenseData` | `(self, SenseData*) → IOReturn` |
| 23 | `SetSenseDataBuffer` | ... |
| 24 | `ResetForNewTask` | `(self) → IOReturn` |

These were confirmed by reading the vtable data section of the arm64e binary
using `otool -d` and cross-referencing function addresses from `nm -arch arm64e`.

### 3. The critical ctypes bug

The root cause of **every segfault** during development was a single missing line:

```python
_iok.IOServiceMatching.restype = c_void_p  # ← THIS LINE
```

Without it, ctypes defaults the return type to `c_int` (32-bit).
`IOServiceMatching` returns a `CFMutableDictionaryRef` — a 64-bit pointer on
modern macOS.  The upper 32 bits were silently truncated, producing a corrupted
dictionary pointer that was passed to `IOServiceGetMatchingServices`, which
then corrupted memory in unpredictable ways.

**Lesson**: Always set `.restype = c_void_p` on every IOKit/CoreFoundation
function that returns a pointer.  The default `c_int` will silently truncate
64-bit pointers.

### 4. QueryInterface UUID calling convention

On ARM64 macOS, `QueryInterface` takes `REFIID` — a `CFUUIDBytes` struct (16
bytes passed by value).  In ctypes, passing two `c_uint64` values achieves the
same register layout:

```python
uuid_lo, uuid_hi = struct.unpack("<QQ", uuid_bytes)
hr = _vt_call(plugin, 1, c_uint32,
    [c_uint64, c_uint64, POINTER(c_void_p)],
    c_uint64(uuid_lo), c_uint64(uuid_hi), byref(out_ptr))
```

This works on both ARM64 and x86_64 because a 16-byte struct is passed in two
registers on both architectures (x0/x1 on ARM, rdi/rsi on x86_64 after `self`).

### 5. Fat binary analysis

The SCSITaskLib plugin is a universal binary.  Running `nm` without specifying
an architecture defaults to x86_64, which gives wrong addresses on Apple Silicon:

```bash
# Wrong — shows x86_64 symbols
nm SCSITaskLib

# Correct — shows arm64e symbols matching runtime addresses
nm -arch arm64e SCSITaskLib
```

### 6. IOKit service matching

iPods register as `com_apple_driver_iPodSBCNub` in the IOKit registry.  This
class name is specific to iPod mass-storage devices and does not match other
Apple USB devices:

```python
match_dict = _iok.IOServiceMatching(b"com_apple_driver_iPodSBCNub")
```

USB properties (PID, serial) are not on the SCSI service itself but on parent
entries in the IOKit registry tree.  Walking up the parent chain with
`IORegistryEntryGetParentEntry` finds the USB device node with `idProduct`,
`idVendor`, and `USB Serial Number` properties.

### 7. No root required

Unlike the pyusb approach, IOKit's SCSITaskLib does not require detaching the
kernel driver.  The plugin creates a user client that coexists with
`IOUSBMassStorageDriver`.  `ObtainExclusiveAccess` only serializes SCSI commands
— it does not take the device away from the mass-storage stack.

Works as uid 501 (normal user).  The iPod disk stays mounted throughout.

### 8. Task reuse

A single `SCSITaskInterface` can be reused for multiple commands by calling
`ResetForNewTask` (slot 24) before each new INQUIRY.  There is no need to
create/destroy a task per command.

## iPod VPD Page Layout

iPods respond to SCSI INQUIRY with Apple-proprietary VPD pages:

| Page | Content |
|------|---------|
| 0x00 | Standard supported VPD pages list |
| 0x80 | Unit Serial Number (ASCII) |
| 0xC0 | Index of data pages (list of page numbers containing XML fragments) |
| 0xC1 | Unused / empty |
| 0xC2–0xFF | Fragments of XML plist (up to 248 bytes per page) |

The XML plist fragments are concatenated in page order to reconstruct a complete
`SysInfoExtended`-style plist containing:

- `SerialNumber` — Apple serial (last 3 chars encode exact model)
- `FireWireGUID` — 16-hex-char device identifier
- `FamilyID` / `UpdaterFamilyID` — device family classification
- `BuildID` / `VisibleBuildID` — firmware version
- `BoardHwName` — hardware board identifier
- `ModelNumStr` — model number string
- `ImageSpecifications` — artwork format details (dimensions, pixel formats)
- Audio codec capabilities, storage info, etc.

The Classic 120GB returned **76 fields** and **12,464 bytes** of raw XML.
The Nano 2G returned **37 fields** and **6,279 bytes**.

## Architecture

```
iopenpod.device.vpd_libusb
  └─ identify_via_vpd()                              ← single entry point
       ├─ _vpd_query_any_platform()
  │    ├─ macOS fast path: iopenpod.device.vpd_iokit.query_ipod_vpd()  ← IOKit, no root
       │    └─ Fallback: query_ipod_vpd()             ← pyusb, root on Linux
  ├─ iopenpod.device.lookup_by_serial()              ← serial-last-3 → exact model
       ├─ _wait_for_remount()                         ← pyusb remount handling
       └─ write_sysinfo()                             ← persist to iPod

src/iopenpod/device/info.py
  └─ _enrich_from_usb_vpd()  → calls identify_via_vpd()

src/iopenpod/device/scanner.py
  └─ _try_vpd_identification()  → calls identify_via_vpd()
```

On non-macOS platforms, `iopenpod.device.vpd_iokit` raises `ImportError` at import time
(line 34: `if sys.platform != "darwin": raise ImportError`).  The centralized
`_vpd_query_any_platform()` catches this and falls through to pyusb automatically.

## Platform Compatibility

| Platform | IOKit module | Fallback | Root needed |
|----------|-------------|----------|-------------|
| macOS ARM64 | Works (tested on M-series) | pyusb | No |
| macOS x86_64 | Should work (same ABI) | pyusb | No |
| Linux | `ImportError` → skip | pyusb | Yes |
| Windows | `ImportError` → skip | pyusb | No |

## Structures

```c
// IOVirtualRange — scatter-gather entry (ARM64)
struct IOVirtualRange {
    uint64_t address;   // virtual memory address of buffer
    uint64_t length;    // buffer length in bytes
};

// SCSI_Sense_Data — 18 bytes of sense data returned on error
struct SCSI_Sense_Data {
    uint8_t data[18];
};

// Transfer direction constants
enum {
    kSCSIDataTransfer_NoDataTransfer        = 0,
    kSCSIDataTransfer_FromInitiatorToTarget  = 1,  // write
    kSCSIDataTransfer_FromTargetToInitiator  = 2,  // read (INQUIRY)
};
```

## References

- `SCSITaskLib.h` — Apple header (Xcode SDK), documents the C API but has the
  wrong UUID for `kSCSITaskDeviceInterfaceID`
- `IOSCSIArchitectureModelFamily` kext source — partially open-source in older
  macOS releases
- libgpod `itdb_device.c` — uses `IOServiceMatching("com_apple_driver_iPodSBCNub")`
  for iPod detection on macOS (but doesn't use SCSITaskLib for VPD)
