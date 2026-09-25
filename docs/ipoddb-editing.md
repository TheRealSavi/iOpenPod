# Editing iPod Database Documents

iTunesDB, ArtworkDB, and PhotosDB expose one parse/edit/write workflow:

```text
bytes -> parse -> Database Document -> typed persistent edit -> write -> bytes
```

The parsed root is the Database Document. There is no separate mutable model, writer
input model, normalization step, or compatibility writer. The family writer accepts
only the matching root-header type.

Application consumers use the [Library Draft preparation API](library-writing.md)
to request semantic edits, resource validation, signatures, and verified output.
That layer reconciles these same retained documents through the shared writers.
The low-level examples below demonstrate Chunk editing; they do not reconcile
all semantic dependencies or authorize device saving.

## Edit an iTunesDB title

```python
from dataclasses import replace

from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.chunk_defs.mhit import MhitHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
)
from iPodDB.iTunesDB.writer.write_iTunesDB import write_iTunesDB

database = parse_iTunesDB(source_bytes)

track = next(
    selection
    for selection in database.find_chunks(MhitHeader)
    if selection.chunk.header.track_id == track_id
)
title = next(
    selection
    for selection in track.find_chunks(MhodHeader)
    if selection.chunk.header.mhod_type == 1
)

edited_title = title.chunk.edit_payload(
    MhodStringPayload,
    lambda payload: replace(payload, value="Blue Train"),
)
edited_database = database.replace_chunk(title, edited_title)
output_bytes = write_iTunesDB(edited_database)
```

IntelliSense knows that `track` selects an `MhitHeader`, `title` selects an iTunesDB
`MhodHeader`, and `edited_database` retains the iTunesDB `MhbdHeader` root type.
`track.find_chunks(...)` still returns selections anchored to `database`, so replacing
`title` does not require rebuilding the Track, Track List, dataset, and root.

## Edit an ArtworkDB album name

```python
from dataclasses import replace

from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.shared.chunk_defs.mhba import MhbaHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
)
from iPodDB.ArtworkDB.writer.write_ArtworkDB import write_ArtworkDB

database = parse_ArtworkDB(source_bytes)
album = database.find_chunks(MhbaHeader)[0]
name = album.find_chunks(MhodHeader)[0]

edited_name = name.chunk.edit_payload(
    MhodStringPayload,
    lambda payload: replace(payload, value="Weekend"),
)
edited_database = database.replace_chunk(name, edited_name)
output_bytes = write_ArtworkDB(edited_database)
```

## Edit a PhotosDB album name

```python
from dataclasses import replace

from iPodDB.PhotosDB.parser.parse_PhotosDB import parse_PhotosDB
from iPodDB.PhotosDB.shared.chunk_defs.mhba import MhbaHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhod import MhodHeader
from iPodDB.PhotosDB.shared.chunk_defs.mhod_payloads.string_mhod import (
    MhodStringPayload,
)
from iPodDB.PhotosDB.writer.write_PhotosDB import write_PhotosDB

database = parse_PhotosDB(source_bytes)
album = database.find_chunks(MhbaHeader)[0]
name = album.find_chunks(MhodHeader)[0]

edited_name = name.chunk.edit_payload(
    MhodStringPayload,
    lambda payload: replace(payload, value="Road Trip"),
)
edited_database = database.replace_chunk(name, edited_name)
output_bytes = write_PhotosDB(edited_database)
```

All three examples use the same operations and differ only in their
artifact-specific root type and format-specific Header or payload types.

## Add a new typed child

Family builders create writable Chunks through the same definitions used by the
reader and writer. For example, a new iTunesDB title can be appended to a selected
Track:

```python
from iPodDB.iTunesDB.builder.build_iTunesDB import new_string_mhod

edited_track = track.chunk.append_child(new_string_mhod(1, "Blue Train"))
edited_database = database.replace_chunk(track, edited_track)
output_bytes = write_iTunesDB(edited_database)
```

The writer validates parent/child structure and payload representation, recalculates
derived lengths and counts, and preserves untouched source bytes and Unknown Data.

## Selection lifetime

A Chunk Selection belongs to the Database Document state from which it was found.
After replacing that selected branch, reacquire selections within the branch before
editing it again. Reusing a stale selection raises an explicit error instead of
writing to an unintended location. Selections in untouched persistent branches
remain valid.
