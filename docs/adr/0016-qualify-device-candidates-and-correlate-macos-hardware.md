# ADR-0016: Qualify Device Candidates and correlate macOS hardware

- Status: Accepted
- Date: 2026-08-31

## Context

Storage deliberately discovers generic removable Volumes. Treating every such
Volume as a Device Candidate caused ordinary USB flash drives to appear in the
Device Picker, even though neither their filesystem nor their hardware evidence
suggested an iPod. Filtering removable media inside Storage would instead make that
lower boundary interpret iPod-specific facts.

An iPod-shaped Volume can also lack SysInfo. On macOS, `diskutil info` supplies the
mounted Volume and BSD whole-disk relationship but does not reliably include the USB
Vendor ID, Product ID, or transport serial needed to anchor a hardware probe. The
Original iOpenPod demonstrates a working read-only correlation between IOMedia BSD
names and IOUSBHostDevice properties. It also obtains the SCSITask plug-in from the
registered `com_apple_driver_iPodSBCNub` service rather than a generic peripheral
nub.

## Decision

- Storage continues to discover generic removable Volumes without deciding whether
  they are iPods.
- During read-only preflight, `DeviceCoordinator` creates a Device Candidate only
  when the mounted Volume contains the `iPod_Control` marker. A qualifying Volume
  may still have an unknown, ambiguous, conflicting, recovery, or unsupported
  Identification Result; the marker is candidate qualification, not model identity.
- The macOS Storage adapter correlates a `diskutil` BSD whole-disk identity with
  generic USB Vendor ID, Product ID, and transport-serial observations from IOKit.
  It builds that index once per discovery snapshot and refreshes it for direct
  inspection.
- The macOS SCSI transport opens the registered iPod SCSITask service proven by the
  Original iOpenPod. It still returns only generic standard inquiry, unit-serial,
  transport-serial, and vendor-payload observations. Storage does not perform model
  lookup or assign product-serial meaning.
- The Application Layer remains responsible for translating Apple observations
  into ranked Device Evidence, and Device Registry remains responsible for exact
  model resolution.

## Consequences

Ordinary removable media no longer appears in the Device Picker, while an
unrecognized iPod-shaped Volume can still explain why it is not selectable. macOS
can correlate the selected Volume to its current USB device and query VPD identity
without requiring SysInfo or writing during discovery.

The IOKit text and plist formats are now native-adapter inputs and require captured,
multi-device regression fixtures. A mounted device without `iPod_Control` is not
offered for selection; supporting initialization of a blank iPod would require a
separate explicit workflow rather than weakening normal discovery.
