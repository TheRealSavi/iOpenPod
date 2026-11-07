# Latest Classic clock-change observers

Research date: 2026-11-05, America/Detroit. Scope: Classic Calendar Targets
24 / 1.1.2, 33 / 2.0.1, 35 / 2.0.4 and 38 / 2.0.5 only.

The previously unidentified deferred clock-change collection contains **MediaItem
references to a selected set of imported Tracks**. Its concrete virtual method
recomputes **a protected-timing cache at Track extension +0x24**. This is now
verified independently in all four latest images. It is neither a demonstrated
loop rebasing ordinary added/modified/played/skipped dates nor a Smart Playlist
day-context reset. The general notification recipients remain a separate open
boundary. [Original uncertainty][prior], [new primary-byte receipt][receipt]

All four Smart membership loops also have a verified context lifecycle: a new
evaluation zeroes a local 24-byte context; candidates share it; its first needed
relative-date rule captures the Firmware Calendar day; subsequent candidates
reuse that day. This closes the context-lifetime question, but does not establish
when a clock-change notification schedules a new evaluation. [Receipt][receipt]

## Evidence identity and method

The [target identity report](classic-latest-firmware-targets-2026-11-05.md) establishes
the latest release for each updater family. The names Classic 7 and 7.5 remain
task aliases for the two later firmware targets, not newly proved retail SKUs.
No older release was substituted for a latest target.

| Target | Pinned OSOS SHA-256 |
| --- | --- |
| 24 / 1.1.2 | `9fc12ffc0817d481af6bcdded1a8f3c720027c85872aa13bade22cbe60913b4a` |
| 33 / 2.0.1 | `220913cb8569af0538a7e828f1aaa08d9313bf9a5c2b0a7a7e6e2dc0bee5f16e` |
| 35 / 2.0.4 | `2ca353870e84bc92ff5090024122ee0712d9bb992c6933b3b230c0ae613b0ffe` |
| 38 / 2.0.5 | `d7669f9266e7cae15867248eeb9c34a2711f1f9a1f3cf40132ef86d9fdbf8224` |

The [read-only verifier][script] checks these full image hashes, records each
memory-map hash, exports exact bytes and ARM listings, resolves constructor
literals and initialized vtable slots, and guards the actual call instructions.
Family 33 uses the normalized OSOS and pinned `classic6g-reva-2.0.1` map; the
other three use their decrypted originals and corresponding runtime maps.
No firmware execution, device access, persistent firmware change, application
source edit or shared Ghidra mutation occurred. Function labels are research
names, not recovered Apple symbols. [Receipt][receipt]

## Callback registration and immediate notification

Each initializer installs a calendar callback and a zone callback. Each callback
obtains the clock/selection model and calls virtual +0x1d4, then obtains the
maintenance singleton and sets its byte +0x70 to one. The zone callback first
calls model virtual +0x58 with `r1 = 0x2a2a2a2a`, `r2 = 0x80a9`.
Neither callback accepts a Track pointer or old/new timestamp delta.
[Callback and registration listings in receipt][receipt]

| Target | Registration | Calendar callback | Zone callback | Pending-byte setter |
| --- | --- | --- | --- | --- |
| 24 / 1.1.2 | `0815dae8` | `080833b0` | `080a239c` | `081090c4` |
| 33 / 2.0.1 | `081653d4` | `08085aa0` | `080a5710` | `0810e2bc` |
| 35 / 2.0.4 | `0817d4bc` | `0809c5a8` | `080bc3c8` | `0812544c` |
| 38 / 2.0.5 | `0817dd7c` | `0809c65c` | `080bc46c` | `08125644` |

Two inspected model vtables per target resolve +0x1d4 to a concrete stub that
copies the current model sample stamp into its previous-sample stamp, then
branches to the calendar model refresher. The stubs are `0815d4d0`, `08164dbc`,
`0817cea4` and `0817d764`. They directly write model sampling state, not Track
date fields. This extends the previously traced 2.0.1 forced-resampling route;
it does not infer that every downstream callback has the same effects.
[Prior model analysis][prior], [vtable words and stub bytes][receipt]

The +0x58 implementations allocate an event, copy the two callback arguments to
event +8/+0x0c and pass it to a common notification router. A real target
difference is preserved:

| Target | Notify helper | Event constructor | Event type | Router entry |
| --- | --- | --- | --- | --- |
| 24 / 1.1.2 | `0823625c` | `0819ee6c` | `0x10` | `080fe778` |
| 33 / 2.0.1 | `0824a958` | `081a8820` | `0x13` | `08102d80` |
| 35 / 2.0.4 | `08267428` | `081c28e0` | `0x13` | `0811a11c` |
| 38 / 2.0.5 | `08268cf8` | `081c3264` | `0x13` | `0811a310` |

The inspected router prefix walks the source object's observer collection at
+4 and can call a recipient's virtual +0x30. That is a **different collection**
from the deferred maintenance object's +0x18 collection resolved below. We have
not enumerated all dynamically registered recipients, cross-thread forwarding
or their scheduling effects. Event `0x80a9` alone is therefore not evidence of
a date-rebase command or completed Smart reevaluation. Imported-clock event
`0x11`, investigated separately, is also outside this recipient analysis.
[Event constructors and router prefixes][receipt]

## Concrete deferred collection and registration

The pending consumer checks owner +0x70 and, when set, invokes the collection
walk. The walk iterates owner +0x18, invokes each member's virtual method, then
clears +0x70 unconditionally after iterator cleanup. There is no aggregate
success check around the member calls. [Gated consumers and walks][receipt]

| Target | Singleton getter | Deferred walk | MediaItem vtable | Actual slot | Concrete updater |
| --- | --- | --- | --- | --- | --- |
| 24 / 1.1.2 | `08109148` | `08108ed4` | `088ee924` | `+0x178` | `082341a8` |
| 33 / 2.0.1 | `0810e340` | `0810e0cc` | `0897bbc0` | `+0x17c` | `0824883c` |
| 35 / 2.0.4 | `081254d0` | `0812525c` | `089a5b30` | `+0x180` | `08265268` |
| 38 / 2.0.5 | `081256c8` | `08125454` | `089ada34` | `+0x180` | `08266acc` |

This resolution follows an actual object construction chain in each image:

1. The singleton constructor initializes the collection at +0x18 and installs
   the concrete collection vtable. Its item-width override returns four bytes.
2. The member-registration routine allocates 0x18 bytes, constructs a MediaItem
   with the vtable above, and copies fields +4/+8/+0x0c/+0x10/+0x14 from the
   incoming reference. That copy does not replace the new object's vtable.
3. The registration routine passes the new object's pointer by address to
   collection +0x1c. The collection's copy-in route uses its four-byte item
   width; its copy-out route returns that stored pointer to the iterator.
4. The walk's per-image virtual slot resolves to the updater shown above.
   Neither the slot number nor the implementation address was inferred from
   a uniform relocation offset. [Constructors, tables and collection methods][receipt]

| Target | Import call site | Register member | MediaItem constructor | Reference copy |
| --- | --- | --- | --- | --- |
| 24 / 1.1.2 | `08071b34` | `081090f8` | `082343e4` | `08234468` |
| 33 / 2.0.1 | `08074040` | `0810e2f0` | `08248a78` | `08248afc` |
| 35 / 2.0.4 | `0808a86c` | `08125480` | `082654bc` | `08265540` |
| 38 / 2.0.5 | `0808a908` | `08125678` | `08266d20` | `08266da4` |

The importer takes this route only when its flag value has bit `0x8000` and
the runtime Track's +0x1c flags do not have `0x4000`. Thus this is a selected
collection, not every Track. A four-byte-aligned immediate ARM B/BL scan of
initialized regions finds exactly the listed importer call to each member
registrar. This is a bounded direct-call result; it does not exclude computed
calls or runtime replacement. [Importer windows and scan results][receipt]

## What the updater actually writes

Let `M` be the MediaItem, `R = *(M + 8)` its runtime Track, and
`E = *(R + 0x10)` the extension pointer. The updater checks the concrete validity
method and a protected-flag predicate. The latter tests runtime flags
`R + 0x1c`, bit `0x2000`; a true result skips this update. The inspected validity
and flag methods themselves contain no ordinary timestamp stores.
[Member predicate listings][receipt]

For an admitted reference it calls a protected-timing query using Track
+0xb0/+0xb4. The exact lower query implementation remains a boundary:
`0827b310`, `08296478`, `082b3554`, or `082b4e54` respectively. On success, its
four output words are processed as follows:

```text
firstEnd  = u32(output[0] + output[1])
selected  = firstEnd                         if output[2] == 0xffffffff
            min_unsigned(firstEnd,
                         u32(output[2] + output[3])) otherwise
converted = 0                               if selected == 0
            u32(selected - 60 * baseMinutes - 60 * dstMinutes) otherwise
E[+0x24]  = 0xfffffffe                       if converted == 0xffffffff
            converted                       otherwise
```

Query status `-42170` stores zero; other nonzero statuses store `0xffffffff`.
The zero-preserving conversion calls the inspected current-offset reader in
each target. These operations establish a **current-offset-derived timing
cache**, not an exact historical UTC conversion. The baseline field's broader
protected-media consumer evidence is retained in the [field analysis][protected].
Do not infer the complete protected-query epoch or selector meaning from the
subtraction alone. [Concrete updater and conversion bytes][receipt]

Every direct non-stack store in each concrete updater targets **E+0x24**.
There are no direct stores to the ordinary runtime Track date slots +0x58
(added), +0x6c (modified), +0x98 (played) or +0xa8 (skipped). There is also no
Smart context pointer or Smart membership call in these concrete updater bodies.
This resolves the previous unknown virtual member without pretending to prove
every transitive callee or general event recipient harmless. It also prevents
the overstatement that a clock change can never modify any date-shaped cache.
[Store inventories and calls][receipt]

The updater byte extents and SHA-256 values are:

| Target | Extent | SHA-256 |
| --- | --- | --- |
| 24 / 1.1.2 | 240 bytes at `082341a8` | `f4d2fe493347fe2c70e084f4a2704319db60cc3f2f8b0c1c2a74f9c466808c54` |
| 33 / 2.0.1 | 264 bytes at `0824883c` | `067a953f6c4eab63f61f3b83afdcf4997cfc0573ff86c298abe8c458d91c4b65` |
| 35 / 2.0.4 | 264 bytes at `08265268` | `d2d1b48c514bb02367f80b4aa66193b68cdd8a0a41d55a93a8796949db3d1d7d` |
| 38 / 2.0.5 | 264 bytes at `08266acc` | `497b099bacf1b048e2d8c98f8fa3bfeebf9e80d3820da9c308a9c1afc405e53e` |

## Smart contexts refresh per evaluation, not per pending flag

| Target | Membership lifecycle window | Context reset | Lazy day initialization |
| --- | --- | --- | --- |
| 24 / 1.1.2 | `0804b000` | `080354ec` | `080b2410` |
| 33 / 2.0.1 | `0804c284` | `08036428` | `080b5740` |
| 35 / 2.0.4 | `08062414` | `0804d268` | `080cc3a0` |
| 38 / 2.0.5 | `080624b4` | `0804d294` | `080cc444` |

For the criteria-evaluation path, the actual membership loop passes `sp+0x40`
to its reset helper, which zeroes 0x18 bytes. It passes that same pointer to
each candidate's match wrapper. The lazy initializer tests context byte +0;
when nonzero it returns without sampling again. Otherwise it captures one
Firmware Calendar value at +4, computes inclusive midnight and 23:59:59 bounds
from that same value, stores them at +8/+0x10 with zero high words, and sets
the ready byte. [Reset helpers, complete zeroing bodies, lifecycle windows and
day initializers][receipt]

A later evaluation reaching that reset gets fresh context state; an already
initialized context retains its captured day even across midnight or a clock
change. This is a mechanism claim, not a guarantee that a particular screen or
notification immediately invokes another evaluation. The resolved protected
timing walk does not supply that missing scheduling proof. Earlier detailed
[Smart arithmetic evidence][smart] still applies to the separate comparison
semantics; this report adds the all-four lifecycle evidence.

## Support implications and remaining questions

iOpenPod should preserve unchanged native ordinary date words and keep calendar
interpretation best effort, as required by
[ADR-0240](../adr/0240-treat-calendar-dates-as-best-effort-metadata.md). No ordinary
date migration or new blocking condition follows from this observer research.
Protected timing/security state is a separate domain; this report does not
authorize weakening its checks or writing its cache from the Host.

| Target | Newly closed in this pass | Still unanswered |
| --- | --- | --- |
| Classic 6: 24 / 1.1.2 | Concrete +0x178 member, import registration, extension-cache writes, event type 0x10, fresh per-evaluation Smart context. | All event recipients and scheduling; protected-query internals and persistence; physical behavior during a clock change. |
| Classic 6.5: 33 / 2.0.1 | Previously open +0x17c member resolves to protected timing; fresh Smart context independently rechecked. | Same indirect boundaries; no whole-program proof that every existing timestamp stays unchanged. |
| Classic 7 target: 35 / 2.0.4 | Independent +0x180 member/vtable/registration proof and Smart context lifecycle. | Same indirect boundaries; no physical clock-change observation in this pass. |
| Classic 7.5 target: 38 / 2.0.5 | Independent +0x180 member/vtable/registration proof and Smart context lifecycle. | Same indirect boundaries; no physical clock-change observation in this pass. |

In particular, we still need to establish which registered notification
recipients schedule Smart membership recomputation, whether an in-progress
evaluation can be interrupted and restarted, which lower protected-query calls
have side effects, and when the derived timing cache is persisted. These are
specific remaining boundaries, not reasons to block Library date handling.

## Reproduction

From the firmware lab root, choose a new output path:

```powershell
uv run scripts/check_classic_clock_observers.py --output artifacts/classic-clock-observers-new
```

The retained [receipt][receipt] contains 124 exact byte/listing windows, eight
vtables, per-window SHA-256 values, concrete call and literal addresses, direct
registration scans and eight independent Host arithmetic examples. The examples
exercise current base/DST subtraction, a smaller second end, preserved zero,
reserved-word remapping, two query errors, wrapping addition and a negative
base offset. They are not ARM emulation, notification scheduling tests or a
physical-device acceptance test. The script refuses unexpected firmware hashes
and existing output directories; originals remain unchanged.

[script]: ../../../ipod-firmware-lab/scripts/check_classic_clock_observers.py
[receipt]: ../../../ipod-firmware-lab/artifacts/classic-clock-observers-20261105-v3/receipt.json
[prior]: ../../../ipod-firmware-lab/notes/itunesdb/timezone-change-propagation.md
[protected]: ../../../ipod-firmware-lab/notes/itunesdb/track-unknown-field-consumers.md
[smart]: ../../../ipod-firmware-lab/notes/itunesdb/smart-time-rules.md
