---
layout: guide
title: Install iPod click wheel games without a VM | iOpenPod
description: Install click wheel games on supported iPod Video, Classic, and nano models without a virtual machine. Follow iOpenPod's download and game selection steps.
heading: Install iPod click wheel games without a virtual machine
lead: iOpenPod downloads the preserved game collection and lets you select games to install on your iPod. You do not need to set up a virtual machine.
breadcrumb_title: Install click wheel games
body_class: iop2-page guide-page
permalink: /guides/install-ipod-click-wheel-games/
og_image: /screenshots/iop2/click-wheel-games.webp
og_image_alt: iOpenPod Games page with installed click wheel games and the Install Games button
cta_heading: Get iOpenPod and open Games
cta_description: iOpenPod is free and open source for Windows, macOS, and Linux. Install the latest app, connect a compatible iPod, and follow the steps above.
related_guides:
  - /guides/phase-playlist-ipod/
  - /guides/ipod-compatibility/
  - /guides/ipod-not-detected/
---

Need the app first? [Download iOpenPod]({{ '/#install' | relative_url }}) for
Windows, macOS, or Linux. Game files download separately when you choose
**Install Games** in the app.

## Which iPods have the Games page?

The Games page is available for these model families:

- **iPod Video:** 5th and 5.5th generation.
- **iPod Classic:** 6th, 6.5th, and 7th generation.
- **iPod nano:** 3rd, 4th, and 5th generation.

This is narrower than iOpenPod's general music-library support. An iPod mini or
nano 6th generation, for example, does not gain click wheel games just because
iOpenPod can manage its library. iPod touch and iPhone games are a different format.

Your computer must be able to read and write the connected iPod's filesystem.
Game compatibility also depends on firmware. If **Game compatibility** appears,
review the model and firmware it reports before deciding whether to continue.
The option to continue with unverified firmware does not establish that a game
will launch successfully. Physical device validation is still ongoing.

## Install games, step by step

1. **Install the latest iOpenPod and connect your iPod.** Select it in the Device
   Picker and let its library load. Check that you have selected the intended device.
2. **Open Games in the sidebar.** The page lists installed games with their covers.
   Use the [detection guide]({{ '/guides/ipod-not-detected/' | relative_url }}) if
   your iPod does not appear at all.
3. **Choose Install Games.** On the first run, iOpenPod downloads and extracts the
   complete preservation collection onto your computer. The current download is
   about 1.8 GB, with additional space needed for extracted files. Follow progress
   in the status bar; the games are not all installed on the iPod at this point.
4. **Choose games in Available games.** Select individual cards, or clear the
   search field and choose **Select all** for every available game for your model.
   If you use the search field, Select all applies to the displayed results.
5. **Choose Add.** Keep the iPod connected while copying and verification finish.
   Installed titles appear on the Games page and leave the available list.
6. **Eject when the operation has finished.** Open the iPod's Games menu to check
   the installed titles on the device itself.

{% include product-shot.html file="click-wheel-games.webp" width=1741 height=1048 alt="iOpenPod Games page showing installed game covers and the Install Games action" caption="Installed click wheel games appear in iOpenPod's Games page." %}

## Do I need a virtual machine or another installer?

No virtual machine is required for this iOpenPod workflow. Collection preparation
and game installation run through the app. You also do not need to install Python
separately when using a native iOpenPod download.

The game files come from the
[click wheel games preservation project](https://github.com/Olsro/ipodclickwheelgamespreservationproject).
They are separate from the iOpenPod application download. The first preparation
needs an internet connection; subsequent visits reuse the prepared collection
on your computer while it remains available.

## Why are some games missing from the available list?

The catalog filters games for the selected iPod model. Some titles are only
offered for iPod Video. Games already installed on the iPod are excluded, even if
their version is older; **Add** does not overwrite existing installations.
Clear the search field to see the full available selection.

Installing Phase adds the game, but playing your own songs needs a further step:
[create a Phase Playlist and prepare its music]({{ '/guides/phase-playlist-ipod/' | relative_url }}).

## If installation stops or a game will not launch

Keep recovery files in place and follow the app's instructions after an interrupted
write. Reconnect and select the same iPod if it disconnected. A successfully listed
game is not, by itself, proof of successful playback on every firmware revision.

When reporting a problem, include your iPod model, firmware, operating system,
iOpenPod version, game title, and whether the failure happened during download,
installation, or launch on the iPod. The
[community](https://discord.gg/9Yy499Tf5d) and
[issue tracker](https://github.com/TheRealSavi/iOpenPod/issues) are linked from the site.

To remove a game, right-click it in iOpenPod and choose **Uninstall**. That also
removes its saved progress and game data; do not use uninstall as a harmless refresh.
