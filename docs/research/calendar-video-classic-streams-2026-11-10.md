# Complete Calendar streams on Video, Classic and Nano 3–5

All ten tested updater inputs match the Mini 2 outcomes for 27 complete
Calendar character streams. Each stream produced one finalized and adopted
VEVENT, followed by eight native day queries. The matrix covers **270 streams
and 2,160 queries**, with exact returned civil spans checked independently on
Video 13/20/25, Classic 24/33/35/38 and Nano 3/4/5 families 26/31/34. The receipts
record each image identity, loader or runtime map, fixture hash and executed
instruction span. [ARM receipt][receipt], [Thumb receipt][thumb-receipt],
[Mini 2 fixture index][mini2]

## What the complete parser establishes

The probe supplies every character from `BEGIN:VCALENDAR` through
`END:VCALENDAR`. The firmware constructs the Calendar collection and its own
character source wrapper, runs the root parser, constructs and finalizes the
VEVENT, and adopts it into the Calendar. The observer checks that the same
finalized event is adopted and queried. Every case reaches the native source
unread method, including the folded RDATE stream. The root passes its actual
VERSION flag to the VEVENT constructor in every case.
[ARM receipt][receipt], [Thumb receipt][thumb-receipt],
[Video per-file call route][video-route],
[Classic per-file call route][classic-route]

| Stream input | Result on all ten inputs |
| --- | --- |
| `VERSION:1.0` with comma-separated RDATE | Both supplied dates contribute |
| `VERSION:2.0` with semicolon-separated RDATE | Both supplied dates contribute |
| Either tested VERSION with the other separator | Only the first supplied date contributes |
| Repeated RDATE or EXDATE in either tested order | Their date lists merge |
| Folded RDATE or an empty later RDATE | The folded dates or prior additions remain effective |
| Bare date values in RDATE | Both supplied dates contribute |
| Explicit `VALUE=DATE` or `VALUE=PERIOD` | The tested list makes no change to membership |
| Explicit `VALUE=DATE-TIME` or the tested TZID spellings | Membership and returned source-time spans match the bare timed list |

The base event spans November 1, 2026 from 09:00 to 10:00. Each case queries
eight consecutive civil days starting November 1. The receipt asserts that each
match returns 09:00–10:00 on the matching day even when an RDATE specifies a
different time. The TZID parameters in this matrix belong to RDATE fixtures.
Event-zone lookup and complete VTIMEZONE processing require separate evidence.
[ARM receipt][receipt], [Thumb receipt][thumb-receipt],
[date parameter analysis][parameters]

## Execution boundaries and addresses

The character provider supplies ASCII code units, end-of-input state and source
position through the native file interface. Video uses the loader's heap adapters.
Classic and Nano 3/4 use synthetic allocation, release for synthetic pointers and
a fixed thread identifier. Nano 5 uses synthetic C++ and string allocation,
reallocation and release. Its receipt lists the heap calls that each fixture
actually reaches. The native source wrapper handles read and unread operations
over that provider. Each call has a two-million instruction bound. The probes
start at object construction and qualify character-stream parsing. Filename
filtering, byte decoding, filesystem enumeration and live adoption remain
separate boundaries. [ARM probe][probe], [Thumb probe][thumb-probe]

| Updater family | Aggregate constructor | Root constructor / parser | Event constructor / adoption |
| --- | --- | --- | --- |
| Video 13/20/25 | `0x0014bfd0` | `0x0018e374` / `0x0018e360` | `0x001e1958` / `0x00236d28` |
| Classic 24 | `0x08101a5c` | `0x08144024` / `0x08144010` | `0x081b94a0` / `0x08247938` |
| Classic 33 | `0x08106210` | `0x0814a2b0` / `0x0814a29c` | `0x081c35fc` / `0x0825cf0c` |
| Classic 35 | `0x0811d5ac` | `0x08161b54` / `0x08161b40` | `0x081dd7e0` / `0x08279a18` |
| Classic 38 | `0x0811d7a0` | `0x08162318` / `0x08162304` | `0x081de5e8` / `0x0827b2e8` |
| Nano 3 family 26 | `0x08114534` | `0x0815a820` / `0x0815a80c` | `0x081db318` / `0x0827d40c` |
| Nano 4 family 31 | `0x0810e0c4` | `0x0813e6f8` / `0x0813e6e8` | `0x081a6254` / `0x08246828` |
| Nano 5 family 34 | `0x081b0b28` | `0x0805b068` / `0x0805b058` | `0x080bc9bc` / `0x080c93fc` |

The source-wrapper constructor and adoption routine are resolved from native
branches, because the short wrapper signatures repeat across the image. The
four Classic images and Nano 3 use relocation-insensitive entry discovery over
their own verified runtime maps. Nano 4's per-file callback calls the root
constructor and parser at `0x080b4e44` and `0x080b4e4a`. Nano 5's corresponding
calls are `0x08049f5c` and `0x08049f62`. Both native reader factories select the
tested source constructor on their branch for the ordinary character source.
Video families 13 and 20 share identical input bytes. Family 25 adds 1,536 zero
bytes to that image. The loader verifies these identities and executes Video's
original startup relocation. The receipts bind the exact probes, source
loaders and shared helper hashes. [ARM receipt][receipt],
[Thumb receipt][thumb-receipt], [Thumb call discovery][thumb-discovery],
[Video image provenance][video]

[receipt]: ../../.scratch/calendar-later-arm-complete-stream-20261110.json
[probe]: ../../.scratch/probe_video_classic_complete_stream_20261110.py
[thumb-receipt]: ../../.scratch/calendar-later-thumb-complete-stream-20261110.json
[thumb-probe]: ../../.scratch/probe_thumb_complete_stream_20261110.py
[thumb-discovery]: ../../.scratch/inspect_thumb_complete_stream_20261110.py
[mini2]: ../../.scratch/calendar-mini2-root-stream-20261110/index.json
[video-route]: ../../../ipod-firmware-lab/artifacts/video-calendar-alarm-20261106-v1/export12/000fc99c.asm.txt
[classic-route]: ../../../ipod-firmware-lab/notes/classic-calendar-alarm-2026-11-06.md#calendar-files-and-property-routing
[parameters]: calendar-exceptions-and-spans-2026-11-09.md#value-and-tzid-date-list-parameters-on-all-thirteen-images
[video]: ../../../ipod-firmware-lab/notes/video-calendar-alarm-2026-11-06.md#exact-inputs-and-scope
