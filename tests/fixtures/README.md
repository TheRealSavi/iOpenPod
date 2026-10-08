# Fixture privacy

Stored fixtures must contain fabricated or anonymized data. Original device files
belong outside version control and distribution inputs. Base64, hexadecimal, and
compression are encodings, not anonymization.

For a device-derived regression, reconstruct the smallest necessary example using
fresh Chunks and an explicit field allowlist. Replace names, email/account fields,
device/Library names, persistent identifiers, paths, URLs, timestamps, and unrelated
media metadata. Omit opaque payloads and copied padding; they can contain personal
data that the parser does not expose. Never commit a reversible identity mapping.
Preserve only the relationships needed by the test and document the transformations.

The sort-36 fixtures use fabricated artist/album labels and deterministic synthetic
identifiers. Their original relative album comparisons, member order, grouping,
representative relationships, and relevant sort-field presence are preserved.
They are reconstructed sorting examples, not untouched device captures.

The other binary fixtures are generated Original-writer examples or locally
generated tones, colors, silence, and text. Writing/normalization JSON uses synthetic
inputs. The SQLite plist contains only the documented command-set structure and one
SQL command, with no device identity. Each subdirectory documents its provenance.

`tests/test_fixture_privacy.py` checks stored data, including Base64/hexadecimal
payloads and both UTF-16 byte alignments, for emails and personal Host paths. The
captured-database checks additionally allow only fabricated labels and identifiers,
known required fields, and bytes reproducible from fresh Chunks. Pattern scanning
alone cannot identify every personal name; new fixture content still requires review.

Changing the current files does not remove previously committed versions from Git
history or existing release archives.
