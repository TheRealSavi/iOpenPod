---
layout: guide
title: iPod not detected? Connection & discovery help | iOpenPod
description: Troubleshoot an iPod missing from iOpenPod. Check the model, cable, mounted filesystem, and Device Picker, then collect useful details for support.
heading: When your iPod does not appear.
lead: First check whether the computer can see the iPod's files. Then check whether iOpenPod can identify it. Those are separate steps, and they need different fixes.
breadcrumb_title: iPod not detected
body_class: iop2-page guide-page
permalink: /guides/ipod-not-detected/
related_guides:
  - /guides/apple-devices-itunes-ipod-windows/
  - /guides/ipod-music-not-syncing/
  - /guides/ipod-podcasts-not-syncing/
---

## 1. Check the iPod model

iOpenPod targets filesystem-accessible full-size iPods, iPod classic, iPod mini,
and iPod nano. It does not currently support iPod shuffle, iPod touch, or iPhone.
See the [compatibility guide]({{ '/guides/ipod-compatibility/' | relative_url }})
for generations and validation limits.

## 2. Check the connection and mounted filesystem

Connect the iPod with a cable appropriate for that model. Check whether its files
are accessible in File Explorer on Windows, Finder on macOS, or your Linux file
manager. Charging alone does not establish that the computer can access data.

If no filesystem appears, check the cable, connection, and operating-system
mounting behavior first. iOpenPod cannot load an iPod that the Host cannot access.
Do not reformat the iPod, delete its library database, or restore it merely to
refresh discovery; those actions can remove existing data.

## 3. Open the Device Picker

With the iPod mounted, open iOpenPod's Device Picker. Discovery refreshes while
the picker is open. Select the intended iPod when it appears. Only one Active
iPod is loaded at a time.

On Linux, follow device-identification setup shown by the app. An iPod can be
visible as a mounted volume while hardware-identification information is still
unavailable. If iOpenPod cannot confidently identify the model, report the result
instead of trying to disguise it as another model.

## 4. Separate detection from Sync problems

If the library opens but media preparation fails, discovery has already succeeded.
Check **Settings → Media Tools**, the selected encoder, and the reported source
file. Use the [media-tool instructions]({{ '/install-help/#helper-tools' | relative_url }})
or [FLAC conversion guide]({{ '/guides/flac-to-ipod/' | relative_url }}).

If a write was interrupted, reconnect the same iPod and follow the recovery action
shown by iOpenPod. Keep recovery files in place until that workflow completes.
Reconnecting starts a new Filesystem Session; it does not mean the interrupted
operation finished.

## 5. Send a useful support report

Open a [GitHub issue](https://github.com/TheRealSavi/iOpenPod/issues) with:

- Your iPod model and generation, firmware version if known, and any storage modification.
- Operating system and version, iOpenPod version, and installation channel.
- Whether the operating system can access the iPod's files.
- What appears in the Device Picker and the exact error text, if any.
- The steps that reproduce the problem, including whether it follows an interrupted write.

**Settings → About** shows the application version and Install Channel. The
[log-file FAQ]({{ '/#faq-logs' | relative_url }}) lists the default diagnostic
locations. Review logs before posting because they can contain personal file
paths and library metadata. A focused excerpt is more useful than an unexplained
dump of your library.
