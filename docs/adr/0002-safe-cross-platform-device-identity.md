# Device identity uses typed evidence and least privilege

The Device Identity module treats the Apple product serial, USB transport
serial, storage identifier, and volume identifier as different facts. The
Apple product serial populates `DeviceInfo.serial` and is the preferred input
to exact model/capacity/color lookup. The iPod USB descriptor serial populates
`firewire_guid`/`usb_serial`; it is normally the 16-hex-character FireWire GUID
used for database signing and must not be mistaken for the product serial.
Mutable filesystem identity remains in `volume_identity_key`.

Platform adapters gather evidence without requiring elevated application
privileges:

- Windows correlates the selected volume with `Win32_DiskDrive` or the storage
  descriptor. Its `SerialNumber` is candidate product-serial evidence; a
  16-hex transport-shaped value remains a FireWire GUID. SetupAPI/PnP data
  supplies USB PID and transport identity.
- macOS correlates Disk Arbitration media with IOKit. The storage node's
  `Device Characteristics` → `Serial Number` is product-serial evidence; `USB
  Serial Number` is transport evidence.
- Linux first reads the kernel-cached SCSI VPD page `0x80`, then the custom
  `ID_IOPENPOD_PRODUCT_SERIAL` udev property. Raw SG_IO is a diagnostic
  fallback, not the default permission model.

Linux packages may install `packaging/linux/61-iopenpod.rules`. The root-owned
udev event first matches the Apple/iPod SCSI vendor and model, performs one
read-only page-`0x80` query, and publishes only the serial. Matching at the
SCSI layer supports USB and FireWire transports without widening access.
iOpenPod does not grant its GUI `MODE="0660"`, membership in the `disk` group,
`TAG+="uaccess"`, `CAP_SYS_RAWIO`, or blanket `sudo` access.

Capabilities are synthesized after identity resolution. Exact model-table
capabilities remain the portable baseline; live SysInfoExtended/VPD fields
supplement them with per-field provenance. A lower-authority USB PID, disk
size, or volume identifier may corroborate identity but may not overwrite a
conflicting product serial.

We rejected one generic `serial` gathered from whichever platform property was
easiest, because that conflates product and transport identity. We also
rejected raw-disk ACLs as the normal Linux route: even read-only raw access
exposes all media contents, while systemd `uaccess` grants write access and is
not portable to headless, non-systemd, or WSL sessions.
