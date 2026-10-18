---
layout: guide
title: How to sync an iPod without iTunes | iOpenPod
description: Add music to an iPod without iTunes using iOpenPod. Choose folders, review additions and removals, and prepare your first Sync on Windows, Mac, or Linux.
heading: Sync your iPod without iTunes.
lead: iOpenPod lets you browse an existing iPod library and add music from folders on your computer. You choose the media and review the changes before Sync runs.
breadcrumb_title: Sync without iTunes
body_class: iop2-page guide-page
permalink: /guides/sync-ipod-without-itunes/
---

## What you need

Start with a [targeted iPod model]({{ '/guides/ipod-compatibility/' | relative_url }})
that your computer can mount and access as a filesystem. iOpenPod targets full-size
iPods, iPod classic, iPod mini, and iPod nano. iPod shuffle, iPod touch, and iPhone
are not supported. Device-specific validation is ongoing.

Install [iOpenPod for your computer]({{ '/#install' | relative_url }}) and set up
FFmpeg and FFprobe through **Settings → Media Tools** for media inspection and
conversion. Chromaprint enables optional acoustic matching; it is not required
just to browse the library. Use media files you can access locally, including
supported folders on mounted network filesystems.

## Your first Sync, step by step

1. **Connect and select your iPod.** Open the Device Picker and choose the iPod
   you want to manage. iOpenPod loads one Active iPod at a time.
2. **Preserve what matters.** Browse the existing library and capture a Backup
   Snapshot before making changes. Backup Snapshots are user-controlled; do not
   assume every Sync creates one automatically.
3. **Choose Sync with Host.** Select the media folders on your computer, the media
   types to include, and whether to scan subfolders. Let the scan finish.
4. **Select the media you want.** Choose albums or tracks instead of assuming the
   whole computer library belongs on the iPod.
5. **Read Sync Review.** Check additions, updates, estimated storage impact,
   and any items needing attention. Removal candidates start unchecked. Leave
   tracks you want to keep out of the removal selection.
6. **Choose Sync Selected.** Keep the iPod connected while iOpenPod prepares media
   and publishes the reviewed changes. Read the result for skipped or failed
   items, then use the app's eject action when finished.

{% include product-shot.html file="sync-change-review.webp" width=1486 height=993 alt="iOpenPod Sync Review showing additions, unchecked removals, and items needing attention" caption="Review selected changes before applying them to the Active iPod." %}

## Will this erase the music already on my iPod?

Using iOpenPod does not require replacing the whole library. It reads the existing
iPod database and lets you choose additions and removals in Sync Review. A track
missing from this computer is not automatically something you should remove.
Review the selection each time, especially when using more than one computer.

Ordinary library edits save automatically by default. Enable **Draft all changes**
if you want to collect and review those edits before saving. That setting is
separate from Sync's review step.

If a write is interrupted, reconnect the same iPod and follow the recovery action
shown by iOpenPod. Keep recovery files in place until recovery completes. An
interruption can leave work incomplete; a Backup Snapshot is an additional copy
of your data, not a promise that a disconnected device can be restored immediately.

## What if my music is in FLAC?

iOpenPod can prepare compatible audio during Sync. The output depends on the iPod
model, source file, installed encoders, and conversion preferences. Read the
[FLAC conversion guide]({{ '/guides/flac-to-ipod/' | relative_url }}) before choosing
between lossless output and smaller lossy files.

## Moving from iTunes or another manager

Start with the library already on your iPod and the media folders on your computer.
Direct import of another manager's application database or settings is not
promised. iOpenPod is an alternative for managing filesystem-accessible iPods; it
does not replace every iTunes feature or manage iPhone and iPod touch.

If the device does not appear, use the
[iPod detection checklist]({{ '/guides/ipod-not-detected/' | relative_url }}) before
attempting a Sync.
