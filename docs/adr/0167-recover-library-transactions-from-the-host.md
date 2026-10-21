# ADR-0167: Recover Library transactions from the Host

- Status: Accepted
- Date: 2026-10-21
- Amends: ADR-0029, ADR-0030, ADR-0089, ADR-0093, and ADR-0166

ADR-0166 reduces staging overhead but still needs complete originals and a large
replacement on the iPod. Normalize Tags and Sync must also work on nearly full
Volumes with stock firmware and Rockbox. The application now configures persistent
Host recovery for all Library transactions, independently of Backup Snapshots.

Storage copies and verifies every affected original on the Host, verifies all
replacement sources, and rechecks the reviewed device files before publication.
It persists the complete Operation Journal on the Host before mirroring it to the
device. It can then reclaim the allocation of reviewed replacements and removals
before publishing verified replacements in order. This lets Sync Adds use space
from reviewed Removes. Capacity validation accounts for net allocated growth,
directory growth, journal replacements, and caller reserves. A full device still
needs a small journal reserve; additional media must actually fit. Host recovery
capacity and the filesystem's individual file-size limit are also checked.

The original-copy directory is application-owned persistent Host storage, outside
the selected Physical Device. It is not a disposable cache, a temporary preparation
directory, or a Backup Snapshot. Host directories are bound to Physical Device and
Volume identities plus an opaque transaction identifier. No device-provided Host
path is followed. The Host journal remains authoritative if the removable journal
is lost or records an earlier state, and read-only discovery finds unfinished Host
transactions before loading the Library. Recovery requires the computer holding
those originals. Disconnecting still invalidates the Filesystem Session.

Reclaiming allocation deliberately allows affected target paths to be absent
during publication. Files are copied through Storage's private temporary files and
published only after full size/hash verification. Restoration accepts only the
recorded before/after content or an absent affected target in a publication or
restoration state. It checks every original and unchanged dependency before
modifying anything, reclaims the incomplete transaction's allocation, restores the
originals, and can resume after another interruption. Unrelated edits block it.
Verified terminal cleanup flushes and verifies device contents before removing
Host originals. Declining recovery retains the Host originals and retires both
journals. Ordinary Volume-flush warnings remain supported; unconfirmed cleanup
retains recovery material.

Direct Mutagen edits on device files were considered. Existing tag padding can
avoid moving audio, but larger tags can relocate payload and container offsets;
an interrupted in-place edit can leave bytes matching neither the original nor
the intended result. Private Host preparation plus verified publication reuses
device capacity while preserving the existing recovery checks. Rockbox preparation
now reuses existing tag padding without adding speculative padding. Audio is not
transcoded. This policy does not yet optimize device I/O to changed byte ranges.

The original device-retained transaction policy and explicit external Backup
restore policy remain available to other Storage callers. Library transactions
select Host recovery through the configured Filesystem Session. Tests cover low
space, net growth rejection, stock/Rockbox saves, disconnects at each native device
publication/restoration boundary, lost device journals, app restart, and refusal
to overwrite unrelated edits or use corrupted recovery material.

A full save on a private Host copy of the Nano 5 succeeded with an artificial
1 MiB free-space limit: 98 suggested fields, 71 media rewrites, and 79 transaction
writes. Capacity validation required 225,280 bytes. This exercises publication,
verification, cleanup, and reload, but does not establish physical-device durability
or firmware acceptance.
