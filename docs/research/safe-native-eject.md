# Safe Native Eject Research

Date: 2026-09-15

## Scope

This note records the operating-system contracts used by iOpenPod's explicit Eject
action. It covers Windows 11, macOS, and Linux desktop systems. It does not authorize
forced unmount, surprise removal, direct USB reset, or a raw-device media-eject
command as a substitute for operating-system safe removal.

The shared safety requirement is stronger than flushing iOpenPod's own writes. The
Host must coordinate every process, filesystem, driver, Volume, and hardware cache
that can affect the Physical Device. A successful result therefore means the native
service confirmed safe removal or power-off. A rejected request remains a failure,
even if iOpenPod itself no longer has files open.

## Windows 11

Microsoft documents `CM_Request_Device_EjectW` as the Configuration Manager request
that prepares a removable local device instance for safe removal and physically
ejects it where supported. Failure returns both a Configuration Manager result and a
`PNP_VETO_TYPE`; the veto can identify a pending close, application, service,
outstanding handle, driver, unsupported request, non-disableable device, or
insufficient rights.

iOpenPod consequently:

1. retains the disk number returned for the selected mounted Volume;
2. enumerates present `GUID_DEVINTERFACE_DISK` interfaces;
3. uses `IOCTL_STORAGE_GET_DEVICE_NUMBER` to match exactly the retained disk number;
4. uses `CM_Get_Parent` to resolve the disk interface's removable Plug and Play
   parent;
5. sends that parent `DEVINST` to `CM_Request_Device_EjectW`; and
6. reports the veto category and name without claiming success.

The distinction between the disk interface and its parent is required on Windows
11. An Apple iPod test device reported the disk devnode itself as non-removable and
returned `CR_REMOVE_VETOED` with `PNP_VetoIllegalDeviceRequest` when it was used as
the eject target. Its immediate USB mass-storage parent was removable and the same
eject request succeeded against that parent.

It does not use `FSCTL_DISMOUNT_VOLUME` as eject. Microsoft warns that dismounting an
unlocked Volume can have unpredictable effects. It also does not use
`IOCTL_STORAGE_EJECT_MEDIA`, whose contract is for ejecting media from a SCSI device
and which may not be supported. Windows' Quick Removal policy can reduce write
caching, but Better Performance explicitly requires safe removal, so the application
must not infer safety from the configured policy.

Primary references:

- [CM_Request_Device_EjectW](https://learn.microsoft.com/en-us/windows/win32/api/cfgmgr32/nf-cfgmgr32-cm_request_device_ejectw)
- [CM_Get_Parent](https://learn.microsoft.com/en-us/windows/win32/api/cfgmgr32/nf-cfgmgr32-cm_get_parent)
- [PNP_VETO_TYPE](https://learn.microsoft.com/en-us/windows/win32/api/cfg/ne-cfg-pnp_veto_type)
- [IOCTL_STORAGE_GET_DEVICE_NUMBER](https://learn.microsoft.com/en-us/windows/win32/api/winioctl/ni-winioctl-ioctl_storage_get_device_number)
- [FSCTL_DISMOUNT_VOLUME](https://learn.microsoft.com/en-us/windows/win32/api/winioctl/ni-winioctl-fsctl_dismount_volume)
- [IOCTL_STORAGE_EJECT_MEDIA](https://learn.microsoft.com/en-us/windows/win32/api/winioctl/ni-winioctl-ioctl_storage_eject_media)
- [Default removal policy for external media](https://learn.microsoft.com/en-us/windows/client-management/client-tools/change-default-removal-policy-external-storage-media)

## macOS

Apple's Disk Arbitration guide requires a whole-disk eject. Starting with a leaf
partition, a client obtains its whole disk, unmounts every Volume with the whole-disk
option, waits for the completion callback, and only then requests eject. A non-null
`DADissenter` means the operation failed.

The installed `diskutil(8)` client exposes those Disk Arbitration operations. Its
`unmountDisk` verb attempts every Volume, and `eject` makes removable media eligible
for safe manual removal. iOpenPod performs the two stages separately against the
validated `diskN` whole-disk identity and never supplies `force`. Separate stages let
the application distinguish an ordinary unmount refusal from “all Volumes are now
unmounted, but physical eject was not confirmed.”

Primary reference:

- [Apple Disk Arbitration: Manipulating Disks and Volumes](https://developer.apple.com/library/archive/documentation/DriversKernelHardware/Conceptual/DiskArbitrationProgGuide/ManipulatingDisks/ManipulatingDisks.html)

The command contract was also verified against the macOS 27.0 `diskutil(8)` manual
installed with the development Host.

## Linux

UDisks2 is the desktop storage service rather than a mount-directory convention.
Its `Manager.ResolveDevice` method resolves a `/dev` path to managed block objects.
`Filesystem.Unmount` performs an authenticated unmount and fails with `DeviceBusy`
by default when files are in use; iOpenPod does not set its `force` option.

After resolving the selected block object, iOpenPod obtains its Drive, requires
`CanPowerOff`, enumerates and unmounts mounted filesystems on that Drive, and calls
`Drive.PowerOff`. UDisks documents that PowerOff checks for processes, commits
in-flight buffers and caches, and for USB deconfigures the device before disabling
its upstream port. Because PowerOff can affect other drives that share a physical
device, iOpenPod refuses the request when the `SiblingId` relationship identifies
another Drive and directs the user to the desktop safe-removal control.

The application calls the UDisks2 system D-Bus API directly through Qt. The
`udisksctl` manual explicitly says its command-line interface is not intended for
scripts or other programs.

Primary references:

- [UDisks2 Manager.ResolveDevice](https://storaged.org/doc/udisks2-api/latest/gdbus-org.freedesktop.UDisks2.Manager.html)
- [UDisks2 Filesystem.Unmount](https://storaged.org/doc/udisks2-api/latest/gdbus-org.freedesktop.UDisks2.Filesystem.html)
- [UDisks2 Drive.PowerOff](https://storaged.org/udisks/docs/gdbus-org.freedesktop.UDisks2.Drive.html)
- [udisksctl manual](https://storaged.org/udisks/docs/udisksctl.1.html)

## Shared Failure Semantics

There are three externally meaningful outcomes:

- **Confirmed safe removal:** invalidate every Filesystem Session for the Connection
  Generation, clear every candidate on that Physical Device, and tell the user it is
  safe to disconnect.
- **Rejected before unmount:** keep the generation, reopen iOpenPod's read-only
  Filesystem Session, retain the Active iPod, and show the native actionable cause.
- **Unmounted but eject or power-off unconfirmed:** expire the generation and clear
  the Active iPod. State that filesystem access has ended but the OS did not confirm
  physical removal, and direct the user to the OS safe-removal control.

The Eject button is disabled while another device operation or read reservation is
active. Playback is stopped before the background request. If a Library Draft has
unsaved changes, the GUI requires explicit confirmation because a successful eject
will discard that draft.
