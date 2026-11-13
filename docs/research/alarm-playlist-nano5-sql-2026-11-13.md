# Nano 5 alarm Playlist catalog from SQLite

Investigated 2026-11-13 against Nano 5 RetailOS **1.0.2 / 34A20020**. The alarm
Playlist selector indexes a filtered vector built from the SQLite bundle. The
firmware's binary-database title comparator is not the ordering contract for this
route. The source is `Library.itdb` together with `Dynamic.itdb`, and the initial
order is SQL `name_order`.

The captured eligible SQL rows are the selectable catalog. Do **not** remove the
last captured row: the excluded last entry is a separately constructed runtime
On-The-Go Playlist. A saved On-The-Go Playlist in the captured database can be
selectable. These conclusions are supported by the original instruction probes
and native call paths below. No physical iPod was accessed or changed.

## Exact source and reproducibility

The original image is
[`Nano5FW/firmware/decrypted/osos.raw.bin`](../../../ipod-firmware-lab/Nano5FW/firmware/decrypted/osos.raw.bin),
SHA-256 `dbd25a9279e7c8ccdc5212d94f2e1b376a73dcebe105b1b1925d9669f0cecd49`.
Raw ranges map to runtime addresses as follows: `0..0xe27c` to `0x22000000`,
`0xe27c..0x2e27c` to `0x22030000`, then `0x6c43a8` bytes to `0x08000000`.
Function addresses below omit the Thumb bit.

[The standalone native probe][probe] checks the complete original image hash,
executes original bounded instructions with Unicorn 2.1.4, and refuses to execute
outside its listed original spans and explicit adapters. [The final receipt][receipt]
records per-span hashes, 399 distinct executed original instruction addresses,
250 cases, adapter descriptions, and three captured-bundle comparisons.

| Artifact | SHA-256 |
| --- | --- |
| Probe script | `51f714e3774eec3093b104955e1173422f70c0dec0d6a07054683faa679e95a6` |
| Final v2 receipt | `a20a0d0a76ca368c9ae8ee21438ade9fe8f5b8b1e3469388c2b629268badd97c` |
| [Product fixture][fixture] | `95864b55bd48d0002ef1784f8910fa050d2c48be498ebf31482ed58def299bc2` |

From the sibling lab, reproduce with:

```powershell
uv run scripts/probe_alarm_playlist_nano5_sql_20261113.py --output artifacts/alarm-playlist-nano5-sql-recheck/native.json
```

An existing receipt cannot be overwritten. The fixture contains 39 media
conversions, 176 typed-row filters, five complete row-order cases, and 30
count/selector/lookup cases. SQL cells, object accessors, lookup caches, and
runtime services are explicit adapters. Vector insertion, filtering, row
iteration, count adjustment, selector validation, and ordinal lookup execute
original instructions. The probe does **not** execute the SQLite query planner,
SQLite VFS, full firmware initialization, or physical playback.

## Captured source and SQL query

The reader constructor at `0x082d30ec` installs the query string at `0x084333a0`
and its column mapping. The probe asserts the exact embedded string before
execution. Read `container` from
`iPod_Control/iTunes/iTunes Library.itlp/Library.itdb` and `container_ui` from
the companion `Dynamic.itdb`. The three existing local captures establish these
table locations. The native query is:

```sql
SELECT container.pid,distinguished_kind,name,parent_pid,media_kinds,is_hidden,
       smart_is_folder,smart_is_dynamic,smart_is_filtered,smart_is_genius,
       smart_is_limited,smart_limit_kind,smart_limit_order,smart_limit_value,
       smart_reverse_limit_order,smart_criteria, description,
       container_ui.play_order, container_ui.is_reversed
FROM container, container_ui
WHERE container.pid IS NOT NULL AND name IS NOT NULL
  AND container.pid = container_ui.container_pid
ORDER BY name_order;
```

The line wrapping above is editorial. A missing matching `container_ui` row
excludes the container through the inner join. The query does not filter empty
Playlists or require Playlist items. It does not sort by the displayed title.
[`0x082d30ec`][reader], [exact-string assertion and captured rows][receipt].

`primary_container_pid` is column 1 of the native DBInfo query at `0x08432910`:

```sql
SELECT pid, primary_container_pid, audio_language, subtitle_language FROM db_info;
```

This is `Library.itdb`'s `db_info` table, not an external DBInfo file. The reader
at `0x0815f600` maps the four results to properties `0,1,3,4`; the vector builder
reads property 1, row 0. All three captures contain one DBInfo row. Multiple
DBInfo rows have no declared ordering and are not qualified by this work.
[`0x0815f600`][dbinfo], [`0x08228320`][filter], [capture receipt][receipt].

Capture comparison reads bytes into in-memory Host SQLite databases. The receipt
records both source fingerprints, original `name_order` values, and selected
PIDs. `MINE` has two joined rows and one selectable saved On-The-Go Playlist;
`USER2` and `USERS` each have two joined rows and no selectable rows. Their
primary containers are hidden, and their Podcasts rows have rejected kind 11.
All three have distinct `name_order` values and no secondary `container` index.
These are captured-file observations, not native SQLite execution.
[Capture receipt][receipt].

## Native eligibility and media conversion

`0x081edaae` visits SQL rows in their returned order and calls `0x08228320`.
That function inserts eligible row indices into the vector at reader offsets
`+0x14c`/`+0x150`. Eligibility requires all of:

1. `distinguished_kind` is one of **0, 17, 101, 20, 25**, through `0x0820777e`.
2. Property 5, `is_hidden`, is false through `0x082077a0`.
3. Converting property 4, `media_kinds`, through `0x08279b7c` gives zero or has
   at least one bit in **`0x0020015d`**.

There is no `smart_is_folder` check in this vector builder. Folder handling in
the separate hierarchy builder must not be imported into this flat catalog.
The row's name, membership count, and smart criteria are not consulted by this
filter. [`0x081edaae`][iteration], [`0x08228320`][filter], [176 filter cases][fixture].

The media converter drops all input bits except the following:

| SQL input bit | Native output bit/mask | Contributes to accepted media |
| --- | --- | --- |
| 0 | `0x00000001` | Yes |
| 1 | `0x00000002` | No |
| 2 | `0x00000004` | Yes |
| 3 | `0x00000008` | Yes |
| 5 | `0x00000010` | Yes |
| 6 | `0x00000020` | No |
| 8 | `0x00000100` | Yes |
| 15 | `0x00000080` | No |
| 20 | `0x00000100` | Yes |
| 21 | `0x00200000` | Yes |

For example input `2` maps to `2` and is rejected; input `0x8000` maps to
`0x80` and is rejected; input `0x8001` maps to `0x81` and is accepted. Input
`0x80000000` maps to zero and is accepted. Therefore testing only the original
input against an accepted-bit mask would be incorrect: unknown-only media bits
also pass after conversion. [`0x08279b7c`][media], [39 native conversion cases][fixture].

The typed integer getter returns a 32-bit word. The SQL row decoder at
`0x081562ba` uses integer conversion for Boolean columns, then `UXTB` at
`0x08156326` before writing a Boolean cell. The cell getter at `0x0816a554`
returns its byte, and the hidden predicate tests nonzero. Thus the relevant
hidden value is the low byte, not an unbounded Host integer. The fixture's
hidden 256 case supplies byte zero at its explicit adapter; the decoder itself
is traced statically rather than executed by that case. Canonical captured
hidden values are 0 and 1. Arbitrary text/float coercion is not qualified here.
[`0x081562ba` disassembly][decoder], [`0x0816a554`][boolean].

PIDs preserve 64 bits through the native paired-register getters. A negative
SQLite INTEGER representation must be interpreted modulo `2^64` when comparing
with the primary PID or a binary database identity. This follows the native
64-bit comparison and lookup, and agrees with the earlier
[captured identity investigation](phase-nano5-database-notes.md).
[`0x08228320`][filter], [`0x0826eada`][lookup].

## Order, primary positioning, and ties

The vector preserves eligible query-row order, except an eligible row whose PID
equals `db_info.primary_container_pid` is inserted at the **front**. A hidden or
otherwise rejected primary is absent. A title comparison is not performed.
The five native iteration fixtures include primary-first, primary-middle,
primary-later, rejected-primary, and absent-primary cases.
[`0x08228320`][filter], [order fixtures][fixture].

The query has only `ORDER BY name_order`, with no secondary PID or title key.
The image embeds SQLite version **3.5.9** at `0x08447684`. Executing this query
with the Host's SQLite does not establish that this old native engine has the
same traversal for equal keys. SQLite's documented contract leaves equal
ordering keys unordered; ascending order places NULL before non-NULL values.
[SQLite SELECT documentation](https://www.sqlite.org/lang_select.html#orderby).

The remaining tied-order qualification is narrow: two or more **eligible
non-primary** rows with equal keys can exchange final selector positions.
Ties involving only rejected rows cannot affect the filtered order, and moving
the eligible primary to the front removes its position from this ambiguity.
This is a deduction from the verified filter and front-insertion algorithm.
No additional PID/title tie-break should be presented as native behavior.

The captured schemas do not have a `container(name_order)` index from which to
deduce traversal. Even a future indexed capture would require an exact query
plan/engine argument. Full native SQLite preparation and stepping reach
`0x081776fc → 0x0822d2ec` and `0x082632b8`; executing these with a synthetic VFS
and tied-key database remains unperformed. The bounded probe deliberately starts
at typed rows, so its receipt does not close that gap.
[Native prepare wrapper][prepare], [native row decoder][decoder], [capture receipt][receipt].

## Runtime On-The-Go and selector identity

The alarm setter `0x080b2ba8` obtains its browser, asks virtual slot `+0x1c4`
for user count, subtracts one when nonzero, and checks the requested selector
against that result before storing it at alarm `+0x1c`. Its browser uses
`0x0830a384` for user count and `0x082a2b1a` for raw count. Raw count ensures
the runtime On-The-Go singleton, then returns **vector length + 1**; user count
subtracts the implicit root entry, leaving vector length. The alarm's further
subtraction excludes the runtime tail.
[Alarm setter][setter], [raw count][raw-count], [user count][user-count].

The runtime tail has a concrete construction path:

1. `0x0826f6cc` lazily allocates the On-The-Go handle and invokes its virtual
   `+0x6c`, `0x082c58e8`.
2. That calls `0x08271af0(handle, 0, 1)`, obtains a new generated 64-bit PID,
   and creates distinguished kind **101** (`0x65`). The handle base initializer
   `0x08255090` sets the hidden byte at `+4` to zero.
3. `0x082034c8 → 0x082cba04` appends a typed row with that PID and kind,
   `media_kinds = 0`, the hidden byte, and NULL values for properties 6–18.
4. `0x082cba04` explicitly calls the indexer for `row_count - 1` after insertion.
   This row passes the native kind/hidden/media checks and appends to the vector.

[Singleton][otg], [runtime activation][otg-activation], [PID/kind creation][otg-create],
[handle initialization][handle-init], [row insertion][row-insert].

This static lifecycle trace identifies why the last **runtime** row is reserved.
The probe executes the original indexer with the resulting kind101/hidden0/media0
row; it adapts singleton allocation and does not run the entire constructor.
It confirms that the alarm accepts all preceding eligible captured rows and
rejects the runtime tail. A persisted captured kind101 row is not automatically
the runtime singleton and must not be dropped solely because of its kind.
[Selector fixtures][fixture].

For identity, the user wrapper at `0x0825cca0` adds one to selector `n` before
calling `0x0826eada`. That lookup reserves internal index zero for the primary
root. Positive internal indices call `0x082d3822(reader, internal_index - 1)`,
which directly reads the row index from the eligible vector and resolves its
64-bit PID. Therefore the stored alarm selector is **zero-based into the
eligible captured catalog**, after primary-front positioning.
[Wrapper][wrapper], [lookup][lookup], [native selector/PID cases][fixture].

The native alarm setter's signed comparison alone does not reject negative
values; the product-facing catalog should expose the validated nonnegative
range `0..N-1`. The probes cover that range, its excluded runtime tail, and the
next invalid index. This research establishes source-derived selector identity,
not physical delivery, reload timing, or playback of every eligible row.
[Setter][setter], [receipt][receipt].

[probe]: ../../../ipod-firmware-lab/scripts/probe_alarm_playlist_nano5_sql_20261113.py
[receipt]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-nano5-sql-20261113-v2/native.json
[fixture]: ../../tests/fixtures/alarms/native_nano5_playlists.json
[reader]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-nano5-sql-v5-20261113/082d30ec.c
[dbinfo]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-nano5-sql-v2-20261113/0815f600.c
[filter]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-nano5-sql-v5-20261113/08228320.c
[iteration]: ../../../ipod-firmware-lab/artifacts/phase-nano5/rowload/081edaae.c
[media]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-nano5-sql-v5-20261113/08279b7c.c
[decoder]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-nano5-sql-v8-20261113/081562ba.asm.txt
[boolean]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-nano5-sql-v8-20261113/0816a554.c
[prepare]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-nano5-sql-v11-20261113/081776fc.c
[setter]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-source-nano5-20261113/080b2ba8.c
[raw-count]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-source-nano5b-20261113/082a2b1a.c
[user-count]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-source-nano5b-20261113/0830a384.c
[otg]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-nano5-sql-v3-20261113/0826f6cc.c
[otg-activation]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-nano5-sql-v4-20261113/082c58e8.c
[otg-create]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-nano5-sql-v4-20261113/08271af0.c
[handle-init]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-nano5-sql-v6-20261113/08255090.c
[row-insert]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-nano5-sql-v5-20261113/082cba04.c
[wrapper]: ../../../ipod-firmware-lab/artifacts/phase-nano5/library/0825cca0.c
[lookup]: ../../../ipod-firmware-lab/artifacts/alarm-playlist-source-nano5b-20261113/0826eada.c
