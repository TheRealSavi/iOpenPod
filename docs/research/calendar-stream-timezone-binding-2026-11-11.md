# Timezone binding in complete Calendar streams

All 13 readable Calendar-capable firmware inputs agree on 13 complete Calendar
streams per input. The probes run the original root parser, VTIMEZONE and VEVENT
handlers, and adoption. They then query the parsed Calendar for six zone names.
Across **169 streams and 1,014 native name lookups**, each result verifies the
stored event zone, the adopted zone objects and the exact source span.
[Legacy results][legacy-index], [later ARM results][arm-results],
[Nano 4/5 results][thumb-results]

| Stream case | Zone stored on the event |
| --- | --- |
| `VTIMEZONE` for `Synthetic/Eastern` before a matching VEVENT | The parsed Eastern object |
| Same definition after the VEVENT | No zone. The post-parse lookup finds the Eastern object in the Calendar. |
| Matching ASCII case variants of `TZID` | The same parsed Eastern object |
| TZID with a trailing space, or `Missing/Zone` | No zone |
| Floating dates, with or without the Eastern definition | No zone |
| Floating dates with `X-WR-TIMEZONE:Synthetic/Eastern` and the definition | No zone |
| `Z`-suffixed dates or explicit `TZID=Z` | The built-in zero-offset `Z` object |
| Explicit `TZID=UTC` in the fresh Calendar | No zone |
| Known TZID on DTSTART and missing name on DTEND | The Eastern object remains assigned |
| Missing name on DTSTART and known TZID on DTEND | The Eastern object is assigned |

The definition after VEVENT is available to native lookup by the end of the
stream. The parser leaves the earlier event's zone field empty. In the other
order, the event stores the same object pointer returned by the post-parse
lookup. This establishes order dependence in the tested single-event files.
The 09:00–10:00 civil span stays intact in every case. [Legacy results][legacy-index],
[later ARM results][arm-results], [Nano 4/5 results][thumb-results]

Every fixture containing the test definition supplies a STANDARD component
with `DTSTART:20201101T020000`, `TZOFFSETFROM:-0400` and `TZOFFSETTO:-0500`.
The native standard-offset selector returns −18,000 seconds for the parsed
object. For every fresh Calendar, `Z` and `z` find the same zero-offset object
and `UTC` misses. For the custom zone, the exact and lowercase names find the
same object, while the trailing-space key misses. Mini 1/2 and Nano 1 use native
lookup entries `0x00062df4`, `0x00063140` and `0x001aa4e8` respectively. The
later ARM probes resolve the lookup from each image's native event gate. The
Nano 4 and Nano 5 gates call lookup at `0x0825e2e0` and `0x0812e7b0`.
[Legacy results][legacy-index], [later ARM results][arm-results], [Nano 4/5 results][thumb-results],
[Mini 2 lookup instructions][mini2-lookup], [Nano 1 event gate][nano1-gate]

The input adapters supply ASCII characters and file metadata. Allocation,
release and thread adapters retain the boundaries of the respective parser
probes. The cases qualify a single STANDARD component, stored event-zone
selection and lookup after a complete character stream. The experiments leave
byte decoding, mixed transition definitions, event queries with clock context,
duplicate TZIDs in text and physical adoption for separate qualification.
[Legacy source manifest][legacy-sources], [later ARM probe][arm-probe],
[Nano 4/5 probe][thumb-probe]

[legacy-index]: ../../.scratch/calendar-legacy-zone-streams-20261111-v2/index.json
[legacy-sources]: ../../.scratch/calendar-legacy-stream-sources-20261111/manifest.json
[arm-results]: ../../.scratch/calendar-arm-zone-streams-20261111.json
[arm-probe]: ../../.scratch/probe_arm_zone_streams_20261111.py
[thumb-results]: ../../.scratch/calendar-thumb-zone-streams-20261111-v2.json
[thumb-probe]: ../../.scratch/probe_thumb_zone_streams_20261111_v2.py
[mini2-lookup]: ../../../ipod-firmware-lab/Mini2FW/evidence/corpus-v2/functions/00063140.asm.txt
[nano1-gate]: ../../../ipod-firmware-lab/Nano1FW/evidence/corpus/functions/0012ed88.asm.txt
