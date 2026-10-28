# Provenance of the MHOD 10 lyrics interpretation

Investigated on 2026-10-28. This note concerns decimal MHOD type **10** (`0x0A`)
in iTunesDB. It does not concern MHOD 100, ArtworkDB MHODs, or the separate MHIT
lyrics-presence byte at `+0xB0`. It records implementation history and upstream
evidence; the firmware investigation must establish native behavior separately.

## Conclusion

The examined history provides no independent evidence that Apple used MHOD 10
for lyrics. The present label is traceable to an Original iOpenPod change that
added the interpretation and its writer together. The inspected older upstream
implementations instead support embedded media lyrics plus the MHIT presence flag.
They do not establish an alternative meaning for type 10 either.

This is an evidence limitation, not proof that the number was never used by any
Apple product or firmware. A retained type-10 payload remains Unknown Data until
its provenance and native consumers are established. Finding text in an
iOpenPod-written type-10 record cannot independently validate the interpretation:
that is precisely the representation its own writer creates.

## Where the label entered iOpenPod

The repository's first matching addition is commit
`cb1e69e57743afe4c580a4f93c2183cb82bfc6b8`, dated 2026-03-02. It adds:

- `10: "Lyrics"` to `iTunesDB_Parser/constants.py`; the parent table jumps from
  category 9 to composer 12.
- `MHOD_TYPE_LYRICS = 10` and emission through `write_mhod_string()` to
  `iTunesDB_Writer/mhod_writer.py`.
- A full-text `lyrics` property and text-based presence-flag derivation to the
  Track writer.

The commit contains no type-10-specific source, captured example, or physical
display test. Its broad parser/writer audit description does not establish this
new meaning. These are statements about the inspected patch, not a claim about
the author's motivation.
[Introduction commit](https://github.com/TheRealSavi/iOpenPod/commit/cb1e69e57743afe4c580a4f93c2183cb82bfc6b8),
[parser table](https://github.com/TheRealSavi/iOpenPod/blob/cb1e69e57743afe4c580a4f93c2183cb82bfc6b8/iTunesDB_Parser/constants.py#L149-L162),
[writer](https://github.com/TheRealSavi/iOpenPod/blob/cb1e69e57743afe4c580a4f93c2183cb82bfc6b8/iTunesDB_Writer/mhod_writer.py#L358-L361).

The 2026-08-29 Original baseline retained the label and constant. The initial 2.0
commit on 2026-09-25 carried it into `MhodType.LYRICS = 10`. That establishes
continuity of an application convention, not new native-format evidence.
[Original baseline constants](https://github.com/TheRealSavi/iOpenPod/blob/a20242428b93b672d14b37230772dbad75139c69/src/iopenpod/itunesdb_shared/constants.py),
[initial 2.0 enum](https://github.com/TheRealSavi/iOpenPod/blob/b16088e0734853140609399f49a4aa8c9e8da6a9/src/iPodDB/iTunesDB/shared/constants.py#L7-L23).

The Original constants file claims general cross-references to libgpod and an
iPodLinux wiki snapshot. Libgpod's inspected enum does not contain this entry.
The cited 2008 wiki snapshot could not be retrieved in this pass, so its mention
in a file header is not treated as validation.

## Independent historical evidence

| Source | What it actually establishes |
| --- | --- |
| libgpod `7982c5554f78dde47fd006afbeff659201d6db3d` | The MHOD enum goes from category 9 to composer 12; it has no type-10 lyrics entry. `lyrics_flag` refers to lyrics embedded in media tags. This absence does not prove that Apple reserved or ignored type 10. |
| foo_dop / ipod_manager `08e0657b5ee09bd05cdb60273e1a139205d4d3f6` | `t_track::set_from_metadb_handle` derives `lyrics_flag` from ID3 `UNSYNCED LYRICS` or MP4 `LYRICS` metadata. It does not use a type-10 text field for that detection. |
| GTKpod maintainer response, 2007-09-02 | A fifth-generation iPod needs the database flag updated after lyrics are added to the media file; the flag tells it to read the tag. This is a described working path, not a complete inventory of every MHOD purpose. |

[Libgpod MHOD enum](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb_itunesdb.c#L167-L199),
[libgpod Track contract](https://github.com/gtkpod/libgpod/blob/7982c5554f78dde47fd006afbeff659201d6db3d/src/itdb.h#L1479-L1482),
[foo_dop metadata detection](https://github.com/reupen/ipod_manager/blob/08e0657b5ee09bd05cdb60273e1a139205d4d3f6/foo_dop/itunesdb_track.cpp#L210-L230),
[GTKpod maintainer explanation](https://sourceforge.net/p/gtkpod/mailman/message/6159939/).

The older [lyrics source review](itunesdb-lyrics.md) already distinguished
embedded lyrics from retained MHOD 10 data. It documented retention as application
compatibility, not confirmation that the firmware reads a type-10 lyrics string.

## Reproducing the provenance check

These read-only Git queries find the relevant additions without checking out or
modifying historical code:

```shell
git log --all -S '10: "Lyrics"' -- iTunesDB_Parser/constants.py
git show cb1e69e57743afe4c580a4f93c2183cb82bfc6b8 -- iTunesDB_Parser/constants.py iTunesDB_Writer/mhod_writer.py iTunesDB_Writer/mhit_writer.py
git show cb1e69e57743afe4c580a4f93c2183cb82bfc6b8^:iTunesDB_Parser/constants.py
git show b16088e0734853140609399f49a4aa8c9e8da6a9:src/iPodDB/iTunesDB/shared/constants.py
```

No production code, device files, or wiki content was changed by this provenance
review. The native meaning, if any, requires a traced consumer or an independently
produced record whose origin can be established.
