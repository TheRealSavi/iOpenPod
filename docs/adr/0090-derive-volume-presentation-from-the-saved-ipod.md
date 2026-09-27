# ADR-0090: Derive Volume presentation from the saved iPod

- Status: Accepted
- Date: 2026-09-26

The selected iPod should show its name and model image in desktop file managers,
including when moved between Hosts. The Master Playlist remains the name authority;
companion files and filesystem labels are derived presentation and never feed back
into the Library. The Application Layer generates the files from the saved name and
the Device Profile's packaged product image. Storage owns all device mutations.

The global Host setting **Manage iPod drive appearance** defaults on. Off leaves
desktop companion files, icons, native volume labels, and Finder flags under the
user's control, without reading or rewriting companions during selection or renames.
It applies before startup restoration. Changing this preference retires pending
Library reviews and preparations; an executing operation completes under its original
policy. Turning it on resumes the ordinary selection and saved-rename hooks.
Toggling the preference does not itself mutate or remove device files.

Selection reconciles presentation only after loading an exactly identified iPod.
Discovery remains read-only. Subsequent name edits capture the companion files in
the same reviewed Storage Transaction as the Library. Unsaved Library Drafts do not
rename the Volume. Existing unrelated settings and comments survive; replaced icon
and metadata bytes receive the ordinary retained-original recovery protection.
Selection cleans its own journal only after a verified durable commit. Interrupted
publication retains the normal recovery evidence. Library saves retain their
existing recovery lifecycle, with desktop companions published after the Library.
Changed or newly created files invalidate a captured review. Malformed, oversized,
ambiguous, linked, or unwritable targets fail safely rather than bypassing Storage.

Each Host provisions Windows `autorun.inf` and ICO, GVfs `.xdg-volume-info` and PNG,
KDE `.directory`, and macOS `.VolumeIcon.icns`. The feature adds no executable
actions. KDE's directory icon does not guarantee a matching Places/device-panel
icon or name. Native Storage label updates provide the fallback name for Finder and
desktops that ignore companion names. macOS also enables the custom icon bit while
preserving other Finder information. See [platform behavior](../volume-presentation.md).

Native label and Finder-flag updates follow verified companion/Library publication.
They are independently verified, repeatable derived metadata, outside the file
transaction's rollback set. A native refusal cannot undo a committed Library name;
it produces a diagnostic and is retried on selection. Restoring an earlier Library
and selecting it reconciles its old presentation again. No automatic unmount,
privilege escalation, raw filesystem editing, or Mount Point rename is attempted.
Disconnects invalidate sessions normally. A filesystem's label constraints may
shorten or normalize the native name while the full Master Playlist name survives.

Original iOpenPod was inspected for these companion files and native label APIs;
no existing implementation was found. This adds application behavior using the
established Storage safety model rather than importing another architecture.
