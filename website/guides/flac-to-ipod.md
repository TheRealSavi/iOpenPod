---
layout: guide
title: FLAC to iPod — Convert music during Sync | iOpenPod
description: Use iOpenPod to convert a FLAC collection into audio your iPod supports. Learn about lossless output, smaller files, media tools, and Sync Review.
heading: Bring your FLAC collection along.
lead: iOpenPod can convert FLAC and other supported source files during Sync. It prepares audio for your iPod; it does not add native FLAC playback to Apple's firmware.
breadcrumb_title: FLAC to iPod
body_class: iop2-page guide-page
permalink: /guides/flac-to-ipod/
---

## Conversion depends on your iPod

The correct output depends on the selected Device Profile and your conversion
settings. A file extension alone does not establish compatibility: the codec,
sample rate, channels, and available encoder also matter. iOpenPod inspects incoming
media and checks prepared output against the selected iPod's limits.

Start by [checking your iPod model]({{ '/guides/ipod-compatibility/' | relative_url }}).
Do not assume that every iPod supports the same lossless formats or video features.

## Lossless audio or smaller files?

| Choice | Why choose it? | Tradeoff |
| --- | --- | --- |
| Compatible lossless output, such as ALAC where supported | Keep lossless audio rather than deliberately encode a lossy copy. | Larger files use more storage. Device limits can require 16-bit output, resampling, or downmixing. |
| Compatible lossy output, such as AAC or MP3 | Fit more albums on the iPod. | Lossy encoding discards audio information; bitrate and encoder settings affect quality and size. |

Settings control lossless conversion, lossy encoding, and spoken-word media.
Review those choices before a large Sync. A supported output format is not a
promise that every optional encoder is available in your FFmpeg installation.

{% include product-shot.html file="audio-transcoding-settings.webp" width=1486 height=993 alt="iOpenPod audio conversion settings with encoder, bitrate, and lossless conversion options" caption="Choose how incoming audio is prepared before reviewing Sync." %}

## Convert FLAC during Sync

1. Install iOpenPod and select your mounted iPod.
2. Open **Settings → Media Tools** and set up FFmpeg and FFprobe. Confirm that the
   encoder you intend to use is available.
3. Open **Settings → Transcoding** and review your audio conversion preferences. Check lossless and lossy choices
   against your storage needs and iPod capabilities.
4. Choose **Sync with Host**, add the folder containing your FLAC collection, and
   select a small set of albums for the first run.
5. Read **Sync Review**, including additions, updates, removals, estimated storage
   impact, and any items needing attention, then choose **Sync Selected**.
6. Read the result, eject the iPod using the app, and verify playback on the device
   before moving a larger collection.

For the full first-run workflow, including Backup Snapshots and removal selection,
see [syncing without iTunes]({{ '/guides/sync-ipod-without-itunes/' | relative_url }}).

## Does conversion change my original FLAC files?

Incoming media preparation creates the device-ready files separately on the Host;
it does not replace your source audio with the converted output. This is distinct
from optional Back Sync workflows that can apply supported metadata to Host files.
Keep your original collection and its own backups.

## When conversion needs attention

If FFmpeg, FFprobe, or the selected encoder is unavailable, check
**Settings → Media Tools** and your encoder choice. Chromaprint's fpcalc is for
optional acoustic matching, not audio encoding. See
[media-tool setup]({{ '/install-help/#helper-tools' | relative_url }}).

Damaged, unreadable, or unsupported sources can fail preparation. A completed Sync
may report skipped or failed items alongside successful ones. Read those results
instead of assuming every selected track transferred.
