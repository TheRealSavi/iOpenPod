# Microsoft Store listing: iOpenPod

Prepared September 25, 2026 for the Windows x64 MSIX release, language `en-US`.
The machine-readable companion is [submission-fields.json](submission-fields.json).
These are submission materials; their presence does not mean Partner Center has
accepted or published a submission.

## Description

```text
Media inspection and conversion require separately installed FFmpeg and FFprobe. Chromaprint (fpcalc) enables optional acoustic matching. The setup helper can install missing packages through WinGet after you choose Install; these tools are not bundled with iOpenPod. A compatible iPod mounted as a Windows drive is required for device management.

Bring your iPod library back into your hands. iOpenPod is a free, open-source desktop app for browsing, organizing, and synchronizing your own music, videos, playlists, and photos without iTunes.

Browse albums and tracks with artwork, search your library, edit metadata and ratings, and organize playlists and Smart Playlists. Play supported local tracks with Windows media controls and explore the music-reactive Synesthesia visualizer.

Choose media folders on your computer, select what belongs on your iPod, and review additions, updates, and removals before Sync. Device-aware preparation converts media when needed. Fingerprint matching helps recognize recordings across format or metadata changes.

Browse and export supported iPod photos, manage Photo Albums, and keep local Backup Snapshots for recovery. Library edits save automatically by default; turn on Draft all changes if you prefer to review them before saving.

Browse podcast subscriptions, find shows through Apple's public podcast directory, and refresh RSS feeds and artwork. Internet access is needed for these features. Your local media library is not uploaded to the developer.

iOpenPod targets filesystem-accessible iPod classic, mini, and nano families. Features depend on the device. iPod touch, iPhone, and iPod shuffle are not supported by this release. Your iPod must already be readable and writable in Windows; no filesystem drivers are included. DRM-protected media is not supported.

All features are free. Optional donations through Ko-fi support development and do not unlock features. Microsoft is not the fundraiser or sponsor. No iOpenPod account is required.

iOpenPod is free software under GPLv3 or later, with third-party notices included. It is an independent project and is not affiliated with or endorsed by Apple Inc. iPod and iTunes are trademarks of Apple Inc. Manage only media you have the right to use, and keep backups of irreplaceable files.
```

## Short description

```text
Browse, organize, and sync your iPod library with a free, open-source desktop app. Supports music, playlists, photos, and local backups. The setup helper installs missing FFmpeg, FFprobe, and Chromaprint tools through WinGet.
```

## Product features

* Browse albums, tracks, artwork, and playlists on a compatible iPod.

* Edit metadata, ratings, playlists, and Smart Playlists.

* Review selected additions, updates, and removals before Sync.

* Match recordings using locally calculated acoustic fingerprints.

* Browse and export supported photos and manage Photo Albums.

* Create and manage local Backup Snapshots.

* Play supported tracks with Windows media controls.

* Explore music-reactive Synesthesia visuals.

* Search podcast feeds and manage subscriptions on your iPod.

* Choose light, dark, or system appearance.

* All features are free; donations are optional.

## Additional fields

| Field                              | Value                                           |
| ---------------------------------- | ----------------------------------------------- |
| Product name                       | iOpenPod                                        |
| Developed by                       | John Gibbons                                    |
| Publisher display name             | TheRealSavi                                     |
| Primary category                   | Music                                           |
| Secondary category                 | Utilities + tools                               |
| Subcategory                        | None                                            |
| Price                              | Free                                            |
| Trial                              | None                                            |
| Device family                      | PC / Windows.Desktop only                       |
| Architecture                       | x64                                             |
| Minimum OS                         | Windows 10 build 19041 (version 2004)           |
| Supported listing/package language | English (United States), en-US                  |
| Release notes for first submission | Leave blank                                     |
| Publish timing                     | Manual hold until the owner chooses Publish now |

Search terms: `music library`, `media manager`, `playlist editor`, `music sync`,
`audio player`, `photo backup`, `podcast organizer`. These contain 14 words across
seven terms; none uses another product's title.

Copyright/trademark field:

```text
Copyright 2025-2026 John Gibbons. iPod and iTunes are trademarks of Apple Inc. iOpenPod is independent and is not affiliated with or endorsed by Apple Inc.
```

Additional minimum requirements, one field per line:

* Compatible iPod mounted as a readable and writable Windows drive for device management.

* FFmpeg and FFprobe installed separately and available on PATH for probing and conversion.

* Chromaprint fpcalc installed separately and available on PATH for fingerprint matching during Sync.

* Internet access for podcast search, feed refresh, and remote artwork.

* Free space for selected media, temporary conversion files, and any Backup Snapshots.

* Graphics hardware and drivers supporting Direct3D 11 for Synesthesia visuals.

Do not invent tested CPU/RAM/disk thresholds. Final package size comes from the
uploaded package. Desktop keyboard and mouse operation are the supported input
baseline; do not declare touch, pen, mixed reality, Xbox, or ARM64 support.

## Privacy, license, and support fields

The app accesses personal information: **Yes**. Local-only access still counts;
podcast queries and ordinary HTTP connection data also leave the device. Use
[privacy.md](privacy.md) or its equivalent [privacy.html](privacy.html). Partner
Center currently supports policy text as well as a URL where available.

Use <johngibbons167@gmail.com> for Support contact info, or the hosted support page.
The existing public issue tracker is also linked in that page.

The prepared public URL candidates use
`https://iopenpod.com/`.
They must be published and opened anonymously before using them as live URLs.
Do not point users at Original iOpenPod's installation instructions as if they
were this release's instructions.

Additional license terms, plain text:

```text
iOpenPod is licensed under the GNU General Public License, version 3 or (at your option) any later version. The complete license is available at https://www.gnu.org/licenses/gpl-3.0.html and is included with the app. Copyright 2025-2026 John Gibbons. This software is provided without warranty to the extent permitted by law. You may use, study, modify, and redistribute it under the GPL. Third-party components retain their own notices and applicable licenses supplied with the app. Matching source code and build materials accompany each public release; see https://iopenpod.com/license for the release downloads. No additional restriction on GPL-granted rights is imposed by the developer. Optional donations confer no additional features or license rights. The application icon by DJShott is used under separate permission for iOpenPod updates, not a blanket GPL or standalone-art reuse license.
```

The source URL must expose the actual release and its complete corresponding
source before distribution. The development repository is private. Public source
archives can be release assets in the public Original iOpenPod repository without
changing the development repository's visibility. A moving branch alone is
insufficient.

## Product declarations and age-rating evidence

| Declaration                                    | Prepared answer     | Evidence or qualification                                                                                 |
| ---------------------------------------------- | ------------------- | --------------------------------------------------------------------------------------------------------- |
| Purchases outside Microsoft commerce           | Yes                 | Optional external Ko-fi donation flow; no feature unlocks. Explain in certification notes.                |
| Tested to meet accessibility guidelines        | No                  | Do not claim the full Store accessibility standard without end-to-end assistive-technology testing.       |
| Install on alternate drives                    | Yes                 | No fixed installation path; validate the final packaged install.                                          |
| Include app data in automatic OneDrive backups | No                  | Prepared privacy-preserving submission choice; users may independently back up files.                     |
| Game recording/broadcast                       | No / not applicable | Non-game application.                                                                                     |
| Pen and ink                                    | No                  | No ink workflow.                                                                                          |
| Generative AI                                  | No                  | Procedural graphics and signal analysis; no content-generating AI service/model in this Windows baseline. |
| Account/login required                         | No                  | No iOpenPod account; public podcast lookup needs none.                                                    |

Complete the actual IARC questionnaire in Partner Center; the resulting regional
ratings must come from IARC, not an invented value in this repository. Answer
against the released build and each question's help text. Prepared factual basis:

* Non-game music/media application, not a product directed at children.

* No app-authored violence, sexual content, gambling, drugs, strong language, or
  fear content in the shipped interface or prepared listing media.

* Users can access their own media and an uncurated public podcast directory.
  Podcasts, descriptions, and covers may contain mature content. Disclose this
  wherever the questionnaire asks about online/catalog/user-selected content;
  do not answer that all accessible content is child-safe.

* No chat, user-to-user messaging, user publishing, or social-network sharing.

* No location sharing, contests, prizes, or real/simulated gambling.

* No paid features, subscriptions, loot boxes, or purchases of digital goods.
  The optional external donation is disclosed separately; interpret any payment
  question according to its actual wording rather than treating this as a game.

* External links open the browser, but the app itself is not a general browser.

## Screenshots

Upload the actual release UI screenshots listed in `submission-fields.json`, in
that order. Captions identify demonstration content where applicable. No real
third-party album art, podcast artwork, private paths, or identifiers should be
included without permission. The screenshot capture record supplies provenance.

## Account-specific completion

Partner Center account verification, any required regulatory contact/trader
declarations, and IARC's generated rating are facts about the owner/account.
Use the existing verified records; do not invent a phone, postal address, company,
tax identifier, trader status, or rating. Markets requiring unprovided account
or legal information must not be silently enabled. The app's price remains Free.

## Importing the prepared listing

Use Partner Center's **Export listing** to obtain the app's real UTF-8 CSV. Keep
its `Field`, `ID`, and `Type` columns unchanged; copy values from
`submission-fields.json` into the `en-us` column. Use `default` only for values
intended for every language. For image upload, place the updated CSV and the
screenshots in one folder and enter paths including that folder name, such as
`iopenpod-store/screenshots/01-album-library.png`. Then use **Import listings →
Import folder**. Inspect all import errors before saving the submission.

The JSON is a reviewed field manifest, not a Microsoft API request. Microsoft's
submission API needs a first submission created through Partner Center and
account-specific authentication. Do not invent CSV field IDs or API submission
IDs. See the [requirements research](../../../docs/research/windows-store-requirements.md).

## Assemble the offline submission kit

After the final MSIX and source audit are ready, run:
(Insert version number at `VERSION` IE `2.0.4`)

```powershell
uv run python -m scripts.prepare_store_kit --msix dist/iOpenPod-VERSION-Windows-x64.msix --output dist/windows-store-kit
```

The output directory must be new. The command verifies locally cached upstream
archives, requires current notices inside the MSIX, and copies the listing,
screenshots, Store tile, and deployable pages. It creates reproducible
`source.tar.gz` and `thirdparty.tar.gz` with fixed metadata, verifies every archived
file, inventories the package's EXE/DLL/PYD files, and hashes the complete kit.
`release-record.json` records the actual Git commit and whether the captured
working tree is dirty. It never downloads, signs, submits, or publishes.

The source snapshot uses Git's tracked/non-ignored file list and a narrow
allowlist. It intentionally omits the captured album-index fixtures and the
external SQLite excerpt; `SOURCE-README.txt` identifies affected tests. These
fixtures are not needed to build the application. Synthetic media and golden
writer fixtures remain. Existing files, logs, caches, private plans, and signing
credentials outside that allowlist are excluded.

The kit's public-page staging directory is `site/iopenpod-2`. Its source links
target the public `TheRealSavi/iOpenPod` release tag `iopenpod-VERSION`, with assets
named `source.tar.gz` and `thirdparty.tar.gz`. Keep the release record's hosting,
native provenance, installation, WACK, and account/certification gates pending
until actual evidence is supplied. Preparing a kit does not close those gates.
