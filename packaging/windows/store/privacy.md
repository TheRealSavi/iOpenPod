# iOpenPod privacy policy

Effective date: October 1, 2026

iOpenPod is a desktop application published by TheRealSavi and developed by
John Gibbons. Contact: <johngibbons167@gmail.com>.

## Your library and device

iOpenPod accesses the media folders you choose and the connected iPod you select
to browse, play, edit, synchronize, export, and back up your library. This can
include file paths, track and playlist metadata, artwork, photographs and their
metadata, play counts, ratings, device names, device serial numbers, and volume
identifiers. The app processes this information on your computer and iPod; it
does not upload your media library or device database to the developer.

Settings remember preferences, selected folders, and the last selected volume.
Local caches retain scan results, file facts, and content fingerprints to avoid
repeating work. Acoustic fingerprints are calculated locally using your installed
Chromaprint tool; iOpenPod does not submit them to AcoustID or another recognition
service. Media tools you install run locally on the files needed for the selected
operation. Those tools are separate software with their own terms.

Playback shares the current track title, artist, album, playback state, and
available artwork with Windows media controls. Windows handles this information
under your operating system settings and Microsoft's privacy practices.

## Optional media-tool installation

Choosing Install Missing Tools invokes WinGet to download and install FFmpeg and
Chromaprint from their package channels. WinGet, its package source, and the
download hosts receive package requests, your IP address, and ordinary connection
information under their own privacy practices. This setup does not send your media
files or fingerprints to those services. Checking locally or skipping setup does
not start package installation.

## Podcast network requests

Podcast search sends the words you enter to Apple's public podcast directory,
with the country parameter US. The service receives your IP address and ordinary
connection information. iOpenPod identifies these requests with the user-agent
`iOpenPod/2 Podcast Browser`; it does not require an Apple account.

Adding or refreshing a podcast requests its feed from the feed provider. Opening
a subscribed podcast or the All Podcasts page can refresh feeds automatically.
Displaying podcast covers requests images from the image hosts named by feeds or
already saved subscription records. Directory search results are text-only.
New subscriptions use publisher-feed artwork; the app does not save Apple's
search artwork as a fallback. Image hosts receive your IP address, the requested
URL, and
ordinary connection information; URLs can include tokens supplied by a feed
provider. Redirects can contact additional hosts. Their privacy policies govern
their processing. iOpenPod does not send your local library, iPod serial number,
or listening history as part of these requests.

The app supports HTTPS and HTTP feed/image URLs. HTTPS encrypts the connection;
HTTP does not. Prefer HTTPS feeds and do not enter private credentials or
sensitive information in feed URLs or search terms. To avoid these requests,
do not use podcast search or open podcast pages; unsubscribe from feeds you no
longer want refreshed. Local library management does not require podcast access.

Podcast subscriptions, cached episode information, and listening-state overrides
are saved on the selected iPod under `iPod_Control/iOpenPod/Podcasts`. They can
travel with that device to another computer.

## Diagnostics, support, and donations

iOpenPod keeps rotating diagnostic logs on your computer. Errors and crash traces
can contain file paths, device or media details, and information involved in an
operation. Logs are not automatically uploaded. The app has no developer-operated
analytics, advertising, automatic crash-report upload, or independent online
update-check service in this version. Microsoft Store and Windows can perform
their own installation, update, and diagnostic processing independently.

If you email the developer or open a GitHub issue, the developer receives what you
choose to send, including your contact details and any attachments. Review logs
before sharing them. GitHub issues are public; use email for private reports.
Support information is used to respond, investigate problems, and maintain the
app, and is retained only as needed for those purposes or legal obligations.
Email and GitHub providers process communications under their own policies.

The optional Donate button opens Ko-fi in your browser. Ko-fi and its payment
providers handle the transaction and their privacy policies apply. The developer
may receive donor details and messages that those services share. iOpenPod does
not receive payment card details. Donations are optional, unlock no features, and
are not required to use the app. Microsoft is not the fundraiser or sponsor.

Links to support, licenses, credits, and other websites open in your browser.
Those websites receive browser connection information under their own policies.

## Storage, security, and your choices

Windows settings normally reside in `%APPDATA%\iOpenPod\settings-v2.json`.
Caches normally reside in `%LOCALAPPDATA%\iOpenPod\cache`; logs default to
`%LOCALAPPDATA%\iOpenPod\Logs`. Backups default to
`%LOCALAPPDATA%\iOpenPod\Backups`, unless you choose another location.
Windows may redirect these paths for a packaged installation. Temporary copies
and recovery journals support media processing and interrupted operations.

Local files rely on Windows account and filesystem protections. iOpenPod does
not encrypt your media, settings, logs, or backups itself. Anyone with access to
those files or an unencrypted iPod may be able to read them. Your operating system
or chosen backup/sync software may copy files independently of iOpenPod.

You can change selected folders and preferences, unsubscribe from podcasts, and
manage Backup Snapshots in the app. Close the app before removing its settings,
caches, or logs. Preserve backups and recovery records you still need. Removing
the app does not erase media, exports, backups in custom locations, or data on
your iPod. Request help accessing or deleting information you sent the developer
by emailing <johngibbons167@gmail.com>. Applicable law may also give you rights
to correction, restriction, objection, or a complaint to your data-protection
authority. Requests concerning Apple, a podcast host, Microsoft, GitHub, or Ko-fi
should also be directed to that provider.

The app is intended for a general audience and does not request children's
personal details or provide user accounts. User-selected media and third-party
podcasts may contain content unsuitable for children. Contact the developer if
you believe a child has sent personal information through a support request.

This policy will be updated when the app's data practices change. The effective
date identifies the current version.
