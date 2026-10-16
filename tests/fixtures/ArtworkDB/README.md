# ArtworkDB golden fixtures

`original-empty.b64` is the Base64 representation of a 696-byte ArtworkDB generated
by the Original iOpenPod `build_artworkdb` implementation with no image or format
items and `next_mhii_id=64`. It was imported on 2026-08-27 as the local
compatibility baseline described by ADR-0004.

Decoded SHA-256:
`0ddb1cdd8603c8e2a167b244f2e2bee8910edad49b73820c3fb2ef238d6db397`.

`original-with-unknown-data.b64` starts with that same Original iOpenPod output and
adds three deliberate compatibility probes: nonzero Unknown Data in the retained
MHFD header, a valid length-delimited unknown `mhzz` child in the image list, and a
root-level suffix outside the MHFD's declared extent. Its decoded SHA-256 is
`d5acc1f5f7376270f2a81cc85e59a473b343769b8e3a7919bbac6d12ee0fcfce`.

The encoded text form keeps the fixture reviewable and platform-neutral. Tests
decode it strictly before asserting complete byte equality.

`nano6-original-1x.b64` is the 2,000-byte output of the unmodified
`write_artworkdb` entry point at Original iOpenPod `origin/1.x` commit
`a20242428b93b672d14b37230772dbad75139c69`, captured on 2026-10-16. The selected
MC688 Nano 6 profile has one Track with persistent ID 101 and a red 80x80 PNG
cover, supplied through normal folder-art extraction into a scratch Volume.
Its MHFD root field at 0x10 is 2, and its image has four thumbnail children with
no auxiliary type-6 MHOD. It is a writer fixture, not a physical-device capture.

Decoded SHA-256:
`d51a61aa1b33136716a9f563b06c9ac0217b047de5453e7dd196f3fdb4a9ffd4`.
