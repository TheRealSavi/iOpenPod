# iPod names and icons in desktop file managers

**Settings → Library → Manage iPod drive appearance** is on by default and persists
as a global Host preference. Turn it off before selecting an iPod to preserve custom
companion files, icons, native volume labels, and Finder flags. Off skips appearance
updates entirely, including during startup restoration and saved renames; it does
not remove or restore files previously written by iOpenPod. The Library's iPod name
can still be changed independently.

With the setting on, selecting an identified, writable iPod installs its model image
and saved iPod name for desktop file managers. Renaming the iPod in the sidebar
updates the companion files when that Library change is saved. With **Draft all
changes** enabled, the desktop name changes only after **Save to iPod**. Reselecting
the iPod repairs stale presentation, including a name changed by another application.

Changing the setting invalidates pending Library reviews so an earlier review cannot
publish appearance changes after they are disabled. Transactions already executing
finish under their original policy. Turning it back on resumes updates at the next
selection or saved rename; changing the setting alone does not write to the iPod.

| Desktop | Files and behavior |
| --- | --- |
| Windows Explorer | Root `autorun.inf` supplies `icon` and `label`, using a multi-size ICO under `iPod_Control/iOpenPod`. Windows may limit the displayed label to 32 characters or ignore metadata under Host policy. |
| GNOME and GVfs-backed file managers | Root `.xdg-volume-info` uses `[Volume Info]`, `Name`, and volume-relative `IconFile`. This includes installations of Cinnamon, MATE, and Xfce whose device view uses GVfs; the desktop integration determines the result. |
| KDE Dolphin | Root `.directory` supplies `[Desktop Entry]`, `Name`, and a `./`-relative PNG icon. KIO uses the directory icon; the Places panel or device notifier may use the filesystem label and its own icon. |
| macOS Finder | Root `.VolumeIcon.icns` supplies the icon. When running on macOS, Storage enables the root's custom icon flag. Finder's volume name comes from the native filesystem label. There is no equivalent portable name file. |

All icon files are generated from the existing Device Profile image, with a generic
iPod image if the packaged image is unavailable. Companion files are provisioned
for all platforms regardless of the current Host. No executable or AutoPlay actions
are added. Unrelated existing companion settings, including Dolphin view settings,
are preserved. Existing text must be UTF-8 or BOM-marked UTF-16 to be updated safely.

The native volume label is updated through Windows `SetVolumeLabelW`, macOS Volume
attributes, or Linux UDisks2 `Filesystem.SetLabel`. FAT labels use at most eleven
portable ASCII characters, in uppercase; other supported filesystems have their own
encoding and length limits. A shortened/normalized label never changes the actual
iPod name. The full name is retained in the Library and text companions, although
Windows replaces control characters with spaces and may truncate its display.

Native label changes can be refused by permissions, a filesystem driver, or desktop
policy. iOpenPod reports such limitations after preserving the committed Library
name. It never unmounts the iPod or asks for elevated privileges to change appearance.
The native macOS icon flag can only be activated while running on macOS; merely
copying the ICNS file on Windows or Linux does not promise Finder activation.
File managers cache names and icons, so a refresh or safe eject/reconnect may be
needed before the display changes.

## Safety and verification

Only the selected iPod is modified. Reads are bounded and use validated Device
Paths. Companion publication uses fingerprint preconditions, staged writes,
verification, retained originals, and the normal Operation Journal.
Selection cleans its completed presentation journal after verified durable
publication, without touching any unrelated recovery record. Interrupted writes
retain recovery evidence. Read-only selection remains usable and reports that
presentation was skipped. Native metadata
is derived after the file transaction and retried on selection; it is not part of
the file transaction's restoration set. See [ADR-0090](adr/0090-derive-volume-presentation-from-the-saved-ipod.md).

After ejecting and reconnecting, a committed rename journal is recognized as
completed even if the Host reports a different volume identity. Such a journal is
retained without offering restoration or cleanup; it does not block loading the
iPod. Genuine interruptions and invalid journals still require attention.

Automated tests cover file formats, Unicode names, injection-resistant values,
preservation, idempotence, rename publication and recovery, stale review rejection,
read-only/disconnected sessions, native-label verification, and native API contracts
with test doubles. Physical-device and desktop-cache behavior still requires manual
verification on Windows, macOS, GNOME/GVfs, and KDE. No real device was modified by
these automated tests.

## Platform sources

- [Microsoft autorun.inf entries](https://learn.microsoft.com/en-us/windows/win32/shell/autorun-cmds)
- [Microsoft SetVolumeLabelW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setvolumelabelw)
- [GNOME GVfs companion-file reader](https://github.com/GNOME/gvfs/blob/master/common/gvfsmountinfo.c)
- [KDE KIO directory-icon reader](https://github.com/KDE/kio/blob/master/src/core/kfileitem.cpp)
- [Apple Volume and Finder attribute definitions](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/attr.h)
- [Apple custom icon flag](https://developer.apple.com/documentation/coreservices/1429609-anonymous/khascustomicon)
- [UDisks2 Filesystem.SetLabel](https://storaged.org/doc/udisks2-api/latest/gdbus-org.freedesktop.UDisks2.Filesystem.html)
- [Pillow icon format support](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html)
