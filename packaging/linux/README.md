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

The canonical bundled rule at
[`src/iopenpod/assets/linux/61-iopenpod.rules`](../../src/iopenpod/assets/linux/61-iopenpod.rules)
covers that compatibility gap. During
the root-owned udev add event it asks udev's existing `scsi_id` helper for page
`0x80` after matching the SCSI vendor/model as an Apple iPod, and records only:

```text
ID_IOPENPOD_PRODUCT_SERIAL=<Apple product serial>
```

It also creates `/dev/disk/by-id/ipod-<serial>`. The rule does **not** change
the block device's owner, group, mode, or ACL. Matching at the SCSI layer keeps
the rule transport-neutral for both USB and FireWire iPods when Linux exposes
them as SCSI block devices.

## Host installation

The preferred path is **Select Device → Review Linux Setup** in iOpenPod. The
generated commands resolve the selected mount back to its exact whole-disk
node, install the bundled rule with an atomic replacement, trigger only that
device, and verify the resulting serial property. They do not disconnect or
unmount the iPod.

The same setup is available from any launcher:

```bash
# Source checkout
uv run iopenpod --linux-identity-status "/media/$USER/IPOD"

# PyPI installation
iopenpod --linux-identity-status "/media/$USER/IPOD"

# AppImage
./iOpenPod-Linux-x86_64.AppImage \
  --linux-identity-status "/media/$USER/IPOD"

# Flatpak
flatpak run io.github.therealsavi.iOpenPod \
  --linux-identity-status "/media/$USER/IPOD"
```

Replace the example mount with the mounted iPod path. The command intentionally
exits nonzero until identity integration is ready, making it suitable for
installer and companion-package checks.

To remove a manual installation:

```bash
sudo rm /etc/udev/rules.d/61-iopenpod.rules
sudo udevadm control --reload-rules
```

### Atomic desktops, Bazzite, Distrobox, and Toolbox

On Fedora Atomic-style systems such as Bazzite, run the generated setup command
on the host system, not inside Distrobox, Toolbox, or another container. The rule
must be installed into the host udev configuration so the host udev daemon can
reload it and republish the selected iPod's block-device properties.

The generated setup command refuses to continue inside common container
environments because installing `/etc/udev/rules.d/61-iopenpod.rules` there would
modify the container filesystem instead of the host.

## Distribution and sandbox packaging

Native distribution packages should install this same bundled rule into the
distribution's
vendor udev-rules directory, normally `/usr/lib/udev/rules.d`. Administrator
overrides belong in `/etc/udev/rules.d`.

Wheels, AppImages, and Flatpaks must not silently modify host system
configuration. iOpenPod ships the rule inside every artifact and displays
transparent host-side setup instructions when the serial bridge is missing.
Native packages may install it directly; Flatpak may use a small companion
package. The Flatpak receives read-only access to `/run/udev` so it can consume
the namespaced property; it still cannot modify the host rule or udev database.

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
