# ADR-0105: Route application updates by Install Channel

- Status: Accepted
- Date: 2026-10-02

iOpenPod needs a built-in startup update check and user-requested installation,
initially for Microsoft Store packages. The Application Layer selects a typed
Update Backend using evidenced Install Channel, starting with Windows package
identity and Store signature. Unsupported or unknown channels never fall back to
the Store. Native packages and API details stay behind that backend; status
progress/actions use ADR-0096's shared presentation.

The Store owns consent and replacement and may terminate the application. A
pre-install recheck precedes the shell's work guard: refuse unsaved Library Drafts
and ongoing workflows, persist settings, pause playback, and reserve device
operations until a terminal result. Qt observes native async completion on the GUI
thread without introducing another event loop. Checks run once per launch, as
requested, with no recurring timer or automatic retry; Store caching still applies.

Settings > About additionally offers explicit manual checks through the same
controller, duplicate suppression, and failure backoff. It displays Install Channel
evidence next to the version. Flatpak and Snap identify packaging, not a particular
store origin; macOS receipt presence is labeled as such and is not validation or
update authority. Source detection does not require per-build channel flags, and
unsupported channels still have no Update Backend.

This separates channel expansion from GUI changes and avoids importing the Original
iOpenPod's GitHub binary-replacement path into Store installs. Real packaged A-to-B
Store validation remains a release requirement. See [Application updates](../app-updates.md).
