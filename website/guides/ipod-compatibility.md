---
layout: guide
title: iPod compatibility — classic, mini & nano | iOpenPod
description: Check iOpenPod's iPod classic, mini, and nano targets, unsupported models, filesystem requirements, and hardware validation limits before syncing.
heading: Check your iPod before you sync.
lead: iOpenPod manages filesystem-accessible iPods. The model, firmware, filesystem, and computer all affect which features are available.
breadcrumb_title: iPod compatibility
body_class: iop2-page guide-page
permalink: /guides/ipod-compatibility/
related_guides:
  - /guides/sync-ipod-without-itunes/
  - /guides/ipod-not-detected/
  - /guides/ipod-album-artwork-missing/
---

## Which iPods does iOpenPod target?

| Family | Target generations | What to check |
| --- | --- | --- |
| iPod and iPod classic | Full-size generations 1–5.5 and the classic family | The computer must mount the iPod and be able to access its files. |
| iPod mini | 1st and 2nd generation | Features depend on the model's capabilities. |
| iPod nano | 1st–7th generation | Later models use additional database formats; check current release notes and device reports. |

These are compatibility targets, not a claim that every model, firmware revision,
storage modification, and operating-system combination has passed physical testing.
Artwork, video, photos, and audio formats depend on the Device Profile.

**iPod shuffle, iPod touch, and iPhone are not supported.** A device appearing in
another Apple application does not establish that iOpenPod can access its library.

## Hardware validation is still ongoing

Automated database and virtual-volume tests are useful evidence, but they cannot
establish playback or boot behavior on a physical iPod. In particular, the project
has documented a reported iPod nano 6th-generation boot failure after Sync.
Compatibility corrections exist in the source, but the
[compatibility decision record](https://github.com/TheRealSavi/iOpenPod/blob/main/docs/adr/0147-restore-late-ipod-firmware-write-compatibility.md)
does not establish that the physical failure is resolved.

Check the [latest release notes](https://github.com/TheRealSavi/iOpenPod/releases/latest)
and [current device reports](https://github.com/TheRealSavi/iOpenPod/issues)
for your exact model. Keep a Backup Snapshot before trying write workflows on a
device whose behavior you have not validated.

## Your computer must be able to access the filesystem

iOpenPod works with a mounted iPod filesystem. It does not make an unreadable
filesystem readable or provide a universal driver for every device. The Host
must be able to read and write the iPod's files for Sync to work.

Before your first Sync, check that the iPod appears in your operating system's
file manager. If it does not, follow the
[detection checklist]({{ '/guides/ipod-not-detected/' | relative_url }}).
Reformatting is not a routine discovery fix: it can erase the library you are
trying to preserve.

## Windows, Mac, and Linux requirements

Native downloads are available for Windows x64, Apple Silicon and Intel Macs,
and Linux x64. A download for one platform does not prove compatibility with all
versions of that operating system. See the
[platform guide]({{ '/guides/ipod-manager-windows-mac-linux/' | relative_url }})
for the current macOS and Linux constraints, and use the
[installation guide]({{ '/install-help/' | relative_url }}) for setup steps.

## Help improve the compatibility evidence

A useful hardware report includes the exact iPod model and generation, firmware
version if known, any storage modification, operating system, iOpenPod version,
and the operation you tried. Say whether library loading, Sync, ejecting, rebooting,
and on-device playback worked; those are different outcomes.

Share a reproducible report through
[GitHub issues](https://github.com/TheRealSavi/iOpenPod/issues) or the
[iOpenPod community](https://discord.gg/9Yy499Tf5d). Review logs before sharing:
diagnostics can contain personal file paths and library metadata.
