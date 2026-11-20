# ADR-0279: Guide Classic bootloader unlock through Device Summary

- Status: Accepted
- Date: 2026-11-17
- Extends: ADR-0277, ADR-0278

Device Summary now owns a guided first bootloader unlock for Windows and the
120 GB Classic family 33 on Apple 2.0.1. This supersedes the earlier decision to
leave all DFU installation in the lab. The application retires the selected
Filesystem Session before the mode change; Storage alone owns USB transfers.
The remaining Restore and Update buttons retain their download-only behavior.

Ship a pinned delta against the qualified stock loader and a parameterized RAM
writer, with native source and offline rebuild tools. Do not distribute one
device's authenticated loader as a reusable installer or depend on the lab at
runtime. The host authenticates the installed image, constructs the candidate,
and asks that iPod's hardware to seal the initial bootloader. Subsequent unsigned
OS updates retain the policy from ADR-0278.

Embed `iOpenPod-Bootloader-v1`, schema, loader version and target in unused PAD
payload. It is an identifier, not a signing key or proof of installation. Only
the qualified full body digests recognize an unlocked loader; recognize the
previous, physically tested unmarked loader too, without reinstalling it.

A durable handoff record precedes the only launch command. A fresh retained USB
session must read the matching nonce and complete verified flash digests before
success is reported. Unfinished handoffs permit read-only result checks, including
after application restart without a Mounted Volume; they never trigger a second
write. Retain one initial boot-flash copy and reuse it. Closing the dialog or
application cannot detach a live writer. This does not establish power-loss
recovery, support for other Classic generations, or nano support.
