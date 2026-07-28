# Linux iPod identity integration

iOpenPod needs two different serials:

- the USB transport serial, which is normally the iPod's 16-hex-character
  FireWire GUID;
- the Apple product serial from SCSI VPD page `0x80`, which resolves the exact
  model, capacity, and color.

Linux's ordinary USB/udev properties expose the first value. Some kernels also
cache page `0x80` at `/sys/class/block/<disk>/device/vpd_pg80`, which iOpenPod
can read without extra permissions. Older and quirked iPods may not get that
sysfs attribute.

[`61-iopenpod.rules`](61-iopenpod.rules) covers that compatibility gap. During
the root-owned udev add event it asks udev's existing `scsi_id` helper for page
`0x80` after matching the SCSI vendor/model as an Apple iPod, and records only:

```text
ID_IOPENPOD_PRODUCT_SERIAL=<Apple product serial>
```

It also creates `/dev/disk/by-id/ipod-<serial>`. The rule does **not** change
the block device's owner, group, mode, or ACL. Matching at the SCSI layer keeps
the rule transport-neutral for both USB and FireWire iPods when Linux exposes
them as SCSI block devices.

## Manual installation

From a source checkout:

```bash
sudo install -Dm644 packaging/linux/61-iopenpod.rules \
  /etc/udev/rules.d/61-iopenpod.rules
sudo udevadm control --reload-rules
```

Unplug and reconnect the iPod, then verify the whole-disk node:

```bash
udevadm info --query=property --name=/dev/sdX |
  grep ID_IOPENPOD_PRODUCT_SERIAL
```

Replace `/dev/sdX` with the iPod's whole disk, not a partition. `lsblk` can
show the mapping. Do not guess a disk name when running commands that can
write.

To remove a manual installation:

```bash
sudo rm /etc/udev/rules.d/61-iopenpod.rules
sudo udevadm control --reload-rules
```

## Distribution and sandbox packaging

Native distribution packages should install the rule into the distribution's
vendor udev-rules directory, normally `/usr/lib/udev/rules.d`. Administrator
overrides belong in `/etc/udev/rules.d`.

Wheels, AppImages, and Flatpaks must not silently modify host system
configuration. Ship this as an explicit native integration step or a small
companion package.

## Why not `MODE="660", TAG+="uaccess"`?

`uaccess` gives the active local seat read/write access to the raw disk. That
is broader than identification needs, does not provide a read-only mode, and
does not reliably cover SSH, headless, non-systemd, or WSL sessions. iOpenPod
therefore keeps raw SG_IO as a diagnostic fallback and does not grant the GUI
raw-disk access by default.

## WSL testing

Mounting a Windows drive letter with `drvfs` exposes only its filesystem. It
does not expose the iPod as a Linux USB/SCSI device, so it cannot test sysfs,
udev, or SG_IO behavior.

Use `usbipd` attachment for those tests. Windows temporarily loses access to
the device while it is attached to WSL:

```powershell
usbipd list
usbipd attach --wsl --busid <BUSID>
usbipd detach --busid <BUSID>
```

Some older iPod storage firmware needs a physical disconnect/reconnect after a
USB handoff before Windows reports media capacity again.

## Upstream references

- [Linux SCSI sysfs VPD attributes](https://github.com/torvalds/linux/blob/master/drivers/scsi/scsi_sysfs.c)
- [systemd `scsi_id`](https://github.com/systemd/systemd/tree/main/src/udev/scsi_id)
- [systemd persistent-storage rules](https://github.com/systemd/systemd/blob/main/rules.d/60-persistent-storage.rules.in)
- [udev rule syntax](https://www.freedesktop.org/software/systemd/man/latest/udev.html)
- [Microsoft WSL USB attachment](https://learn.microsoft.com/windows/wsl/connect-usb)
