---
layout: guide
title: Finder podcasts not syncing to iPod? Missing episodes | iOpenPod
description: Podcasts downloaded on your Mac but missing from your iPod? Check Finder selection and missing tabs, then try an episode with iOpenPod.
heading: Finder podcasts not syncing to your iPod?
lead: An episode is downloaded in Apple Podcasts, but absent on your iPod classic or nano. Perhaps Finder has no Podcasts tab, or the episode appears under Music. Start with the checks for your symptom.
breadcrumb_title: Podcasts not syncing
body_class: iop2-page guide-page
permalink: /guides/ipod-podcasts-not-syncing/
cta_heading: Manage podcasts with iOpenPod
cta_description: Add a publisher's RSS feed and test one episode on a supported iPod using iOpenPod's own Podcast workflow.
related_guides:
  - /guides/ipod-music-not-syncing/
  - /guides/ipod-not-detected/
  - /guides/sync-ipod-without-itunes/
---

Reviewed October 18, 2026. iOpenPod steps were checked against
[v2.0.13](https://github.com/TheRealSavi/iOpenPod/releases/tag/v2.0.13).
This guide is for filesystem-accessible classic, mini, and nano targets, with
Podcast capabilities depending on the model. iOpenPod does not support iPod touch
or shuffle; check [model compatibility]({{ '/guides/ipod-compatibility/' | relative_url }})
before switching.

## Apple Podcasts sync is not the same as an iPod transfer

Apple's **Sync Library** setting shares followed shows, listening position, and
other podcast information across account-connected devices such as Macs and
iPhones. It does not send episodes wirelessly to an iPod classic or nano. Those
models still need a computer transfer.
[Apple distinguishes cloud sync from older iPod syncing](https://support.apple.com/guide/podcasts/sync-podcasts-across-devices-pod5c911347/mac).

On Catalina and later, Apple's Mac workflow uses Finder. On Windows, Apple's
instructions route users to iTunes or Apple Devices; the choice depends on the
setup. A control described for Finder may not exist in the Windows app you use.
See [Apple's computer-sync overview](https://support.apple.com/en-us/108311).

## Check the download and Finder's selection

1. **Confirm the episode is on this Mac.** In Apple Podcasts, find the episode
   and use its More menu to download it. Check **Downloaded** in the sidebar.
   Seeing an episode in a show's catalog, or saving it with automatic downloads
   disabled, is not the same as having its media downloaded.
   [Apple's download instructions](https://support.apple.com/guide/podcasts/save-download-or-remove-episodes-poda4f6be01/1.1.0/mac/26)
   explain the difference.
2. **Check the selected content.** Connect the iPod, select it in Finder's
   sidebar, and open **Podcasts** if available. Enable podcast syncing and check
   the shows you intend to transfer. Review **Automatically copy**: a rule for
   recent or unplayed episodes may omit the older or already-played episode you
   expected.
3. **Read the pending choices before applying.** Apple's syncing can remove
   content when it is deselected or removed from the computer. Preserve existing
   selections you want to keep, click **Apply**, and wait for completion before
   ejecting. These controls are described in
   [Apple's Finder sync guide](https://support.apple.com/en-ie/guide/mac-help/mchlde9a31f1/mac).

If only some episodes transfer, compare one missing episode with one that works:
is it actually downloaded, from a selected show, and eligible under the same
recent/unplayed rule? Also check Apple Podcasts' download-retention and played
episode settings. A hidden or automatically removed download can look like a
transfer failure. [Apple documents these settings](https://support.apple.com/en-mide/guide/podcasts/pod4130f48/mac).

## Finder has no Podcasts tab

Owners have [reported a missing tab even with downloaded episodes](https://www.reddit.com/r/ipod/comments/1ie8131/).
Those reports establish a symptom, not one cause or a universal fix.

First separate a missing tab from an inaccessible device. If Finder cannot see the
iPod at all, use the [detection checklist]({{ '/guides/ipod-not-detected/' | relative_url }}).
If the device is present but the tab remains absent, record the iPod model and
macOS version for troubleshooting. Avoid changing unrelated sync selections just
to make the tab appear.

An alternative is a manager that reads the mounted iPod directly. iOpenPod has
its own Podcast workflow and does not depend on Finder displaying that tab.

## Try one podcast episode with iOpenPod

1. **Check your model and install** [iOpenPod]({{ '/#install' | relative_url }})
   for Windows, macOS, or Linux. Connect the iPod, choose it in the Device Picker,
   and select **Use This iPod**. Browse the existing library and capture a Backup
   Snapshot before changes. Finish any Apple sync before using another manager.
2. **Prepare the tools.** Set up FFmpeg and FFprobe through **Settings → Media
   Tools** for media inspection and preparation.
3. **Add the show.** Open **Podcasts → Add Podcast**. Paste the publisher's full
   HTTP(S) RSS address into **RSS feed URL**, then choose **Add Feed**. An Apple
   Podcasts share-page link is not necessarily an RSS feed. Alternatively, search
   the directory, select the intended result, and choose **Subscribe**.
4. **Start with one episode.** Select the show and an episode, then choose
   **Add to iPod**. This bypasses automatic retention selection. Read the result,
   eject through the app, and test playback on the iPod.
5. **Review rules before ongoing syncing.** In **Sync Settings…**, check **Keep**,
   episode ordering, and removal conditions. **At next sync** can remove eligible
   episodes without replacements; **Only when replaced** waits for a successful
   replacement. Saved rules can add and remove episodes.

**Add to iPod**, **Sync Podcast**, and **Sync Podcasts** execute directly, without
the Host Sync selection and Review screens. A feed entry still needs a working
download; iOpenPod does not import Apple subscriptions or unlock paid episodes.

## The episode appears as Music instead

If the file is already on the iPod, inspect it before adding another copy.
iOpenPod's Track context menu offers **Convert to Podcast** on capable models.
It changes classification and playback flags without re-encoding, and does not
create a feed subscription. Ordinary library edits save immediately unless
**Draft all changes** is enabled. See the
[versioned conversion behavior](https://github.com/TheRealSavi/iOpenPod/blob/v2.0.13/src/iOpenPod/app/track_conversion.py#L68).
If drafting is enabled, use **Review Changes → Save to iPod** and wait for a
successful save before ejecting.
Check the result on your device; classification alone does not guarantee how every
firmware menu presents the episode.
