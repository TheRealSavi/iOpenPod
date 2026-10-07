# ADR-0126: Persist individual iPod setting overrides

- Status: Accepted
- Date: 2026-10-07

The Original iOpenPod separated Host settings from portable device settings. The
2.0 settings resolver already supported device precedence, but its device store
was memory-only and no selection workflow loaded it. Settings now offers Host and
iPod scopes with an animated selector and individual inheritance choices.

Each overridable setting resolves from the Active iPod, then the Host, then its
typed default. An absent key means inheritance. Explicit `false`, zero, and values
equal to the Host remain overrides until the user chooses **Use Host**. The Host
editor always reads the Host layer, even while another effective value is active.
Device selection and unloading notify runtime consumers of effective changes.

Portable settings cover the iPod Library view and double-click shortcut, audio
transcoding including encoder-specific controls, optional Sync behavior including
scrobbling, and Backup Snapshot retention. Appearance, language, window state,
Host paths, accounts and credentials, draft safety, and desktop integration stay
on the Host. Account secrets continue to use the native keyring. Firmware iPod
Preferences and iTunesPrefs remain a separate, read-only display under iPod.

Overrides live in `iPod_Control/iOpenPod/settings-v2.json`, with a version-1
document envelope and an `overrides` object. This application-owned path is
independent of Original iOpenPod files and Host `settings-v2.json`. Unknown
override keys are retained. Invalid known values fall through the typed resolver;
malformed, oversized, and unsupported-version documents are left unchanged and
disable editing until the iPod is reloaded. No settings file is created simply by
selecting an iPod or changing scope.

Selection captures the bounded document through its identity-bound Filesystem
Session. A save reserves the Active iPod through DeviceController, runs outside
the GUI thread, and asks Storage to atomically replace the exact captured file
revision, verify the bytes, and flush. A switched connection, external edit,
read-only Volume, or interrupted Sync cannot authorize a settings overwrite.
Effective settings update after verified publication. Failures retain the last
confirmed values, display the error, and require reload before another write;
an incomplete flush is reported with safe-eject guidance. Unloading drops all
device values, and reconnecting reads the document again.
