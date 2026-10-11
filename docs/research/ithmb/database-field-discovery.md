# Discovering database fields with the emulator

Research date: **2026-10-11**. Source inspection of `siggifly/ipod-emulator`
at `d39e850ac07baa28abbdd8b00b77b834a757b5e1`, following the
[local artwork experiments](ipod-emulator-experiments.md). This note proposes a
research workflow; **no previously unknown field has been identified here**.

The subsequent [field experiments](database-field-experiments.md) apply this
workflow. They reproduce and locally repair the fast-word read-log defect,
isolate host observation from boot-path read accounting, and export the complete
ATA DMA ledger. The caveats below describe the pinned upstream source inspected
for this proposal; the follow-up records the patched executable and measured
results separately.

## What it can establish

Yes: executing Apple's firmware while changing controlled database bytes can
reveal which values affect parsing, Track selection, artwork lookup, presentation,
or playback. Tracing the instructions that consume those bytes can distinguish a
comparison, bit test, size calculation, and copied metadata. The existing lab
already provides a reproducible positive control: one synthetic library whose
artwork displays correctly, including a selective F1029 content change.
[Recorded controls](ipod-emulator-experiments.md#controlled-results).

The useful evidence chain is **file offset → loaded memory → consuming instruction
→ branch/calculation → observed effect**. A changed screenshot supplies only its
last step. A read supplies an earlier step, but a bulk copy, checksum, or aligned
word load spanning adjacent bytes does not establish a field's semantic use.

## Instruments present in this revision

The `trace` command is the practical research interface. Its `--drive` mode can
replay navigation, capture screens, and save machine snapshots; normal reporting
runs when the drive loop ends. GUI navigation remains a useful visual check, but
our established experiment script uses the command-line machine.
[Drive and reporting][drive], [experiment procedure](ipod-emulator-experiments.md).

| Instrument | Useful answer | Qualification |
| --- | --- | --- |
| `--readlog=ADDR,...` or address file | Which PC reads a listed byte address, and when? | Lists exact bus addresses; no built-in read-range or database-offset option. Word reads account for constituent bytes; halfword reads use the byte path. Values have the caveat below. |
| `--readlog-dump=FILE` | TSV of retained PC/address/value/instruction-count events | Exports the retained sample, not an uncapped event history. |
| `--storelog=PC,...`, `--storeaddr=ADDR,...` | Which objects a known instruction fills, or who writes an exact target | Does not automatically follow a database value through copies and calculations. |
| `--watch-range=BASE:LEN` | Writers touching a contiguous structure | A **write** instrument, not a read watch. |
| `--break=PC`, `--regs-at=PC:N`, `--stop-at=PC:N` | Registers at a consumer, or halt at a selected arrival | `--break` records arrivals; `--stop-at` is the halting option. |
| ATA DMA transfer records | Disk LBA, destination address, transferred length | Sector-level evidence; no database filename or file-offset annotation. |
| Static `dis` tool; `trace --disasm` | Decode the firmware surrounding a discovered PC | Names and semantics still require analysis. |

Sources: [CLI instruments][flags], [byte/word read implementation][reads],
[halfword bus implementation][bus], [write instrumentation][writes],
[ATA transfers][ata], [static disassembler][dis].

## Instrumentation limits that matter before discovery

- **Read values need a positive control.** In the fast-region branch of
  `read32_via`, each byte calls `count()`, which inserts a zero-valued read-log row,
  but that branch does not fill the actual byte values. The byte and slower word
  paths do fill them. Source inspection therefore predicts false zero values for
  some ordinary RAM word loads. PC/address counts are separate. This is a
  source-observed concern, not a runtime reproduction or a completed fix.
  [Collector][collector], [three read paths][reads].
- **Addresses are not canonicalized for the read watch.** Matching occurs before
  memory translation. A physical DMA destination and the logical/uncached address
  used by firmware can denote the same storage but miss the same address list.
  Record the mapping and watch applicable aliases. [Collector][collector],
  [translation][translation].
- **Logs can saturate.** Read and store event samples each cap at 2,000,000;
  range-write samples cap at 4,096. Read counts per address/PC and range-write
  counts per word/PC continue beyond their samples. TSV exports contain only kept
  events. The ATA vector is uncapped, but the CLI prints its first 64 transfers
  and last transfer. Full ordered exports need additional instrumentation.
  [Caps][caps], [exports][exports], [ATA report][ata-report].
- **Observer reads can pollute a trace.** Ordinary `--dump`, `--disasm`, and
  `--watch` use bus reads without the internal-observer guard on those paths;
  dumps run before read-log reporting. Use separate inspection runs until
  observer isolation is tested. [Inspection/report ordering][report-order],
  [memory dumps][dumps], [word watch][word-watch].
- **DMA is not a CPU store.** Inbound ATA DMA writes directly into mapped storage,
  bypassing the CPU store hooks. Its transfer list provides the starting bridge
  from disk to RAM, not automatic provenance after subsequent copies.
  [DMA placement][dma].
- **Recovered names are hints.** `extract_symbols` heuristically scans strings
  and prologues; its own source documents six misnamed boot tasks. This is not an
  Apple database-parser symbol table. [Symbol extraction][symbols].

## A controlled first campaign

1. Validate the instruments with known nonzero byte, halfword, and word loads,
   aliases, DMA, and observer reads. Use already-understood fields as positive
   controls before interpreting unknown bytes. Instrumentation fixes should be
   separate, tested emulator changes.
2. Map each candidate's exact database file offset to FAT sectors, then to its
   DMA destination and subsequent RAM copies. This mapping is currently manual.
   A proposed file-offset provenance tracer would automate it; taint tracking
   through registers and copies would be a further addition, not an existing
   feature.
3. Start from a fresh, hashed copy of the working library. Alter one field or bit
   at a time with valid surrounding structure; record exact byte differences.
   Use baseline, intervention, and reverted control runs. Re-test apparent effects
   with values that discriminate competing interpretations.
4. Exercise the relevant path deliberately: initial database load, Track browsing,
   small and large artwork views, then feature-specific playback or sorting paths.
   Capture consumer PCs/registers, branch behavior, visible output, and resulting
   disk bytes. A crash alone indicates sensitivity, not meaning.
5. Record conclusions as observed behavior for this firmware and fixture, with
   competing explanations and negative controls. Promote names only after the
   code path and controlled effects agree; retain Unknown Data until then.

First candidates are **MHNI `+0x24`**, then **MHII `+0x1C` and `+0x24`**: these
are explicitly unknown in the current definitions and are in the established
artwork path. Compare MHNI's two size fields as a known-structure control, without
assuming they are interchangeable. Early iTunesDB candidates include MHIT
`+0x84`, `+0x94`, and `+0xB3`; inspect consumption before designing semantic tests.
These are priorities, not hypotheses about their meaning.
[MHNI definition](../../../src/iPodDB/ArtworkDB/shared/chunk_defs/mhni.py),
[MHII definition](../../../src/iPodDB/ArtworkDB/shared/chunk_defs/mhii.py),
[MHIT definition](../../../src/iPodDB/iTunesDB/shared/chunk_defs/mhit.py).

The tested MHIT header is `0x148` bytes. Fields beginning at `+0x160` or later are
outside that fixture; extending a header changes the research question and does
not establish that this firmware recognizes later database generations.
Machine snapshots also retain already-loaded database state and require the
matching external disk image: do not swap a changed disk under a post-parse
snapshot and assume the changed bytes were consumed. [Snapshot disk contract][snap].

## What remains unknowable from one successful run

No observed effect means only “no effect detected on the exercised path.” A field
may be used only by iTunes, another database version, another firmware, another
feature, or an error/recovery path. Bytes read only by generic copying remain
semantically unknown. Fields ignored by this consumer may still matter to writers.
Compare independently captured databases and writer behavior for those cases.

The current control is Video 5G firmware 1.3, with synthetic identity, warm entry,
and synthesized BCM display behavior. It cannot establish Classic/nano semantics
or F1061 layout. Findings should name the firmware hash, emulator revision/local
patches, model identity, database/header versions, boot path, clock, and workload;
physical-device and other-firmware confirmation remain separate evidence.
[Lab scope](ipod-emulator-experiments.md#evidence-limits-and-next-questions).

[drive]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/tools/ipod-machine/src/bin/trace.rs#L1590-L1632
[flags]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/tools/ipod-machine/src/bin/trace.rs#L258-L337
[reads]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/tools/ipod-machine/src/lib.rs#L2604-L2705
[bus]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/tools/arm7tdmi/src/bus.rs#L11-L53
[writes]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/tools/ipod-machine/src/lib.rs#L756-L780
[ata]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/tools/ipod-machine/src/hw/ata.rs#L392-L416
[dis]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/tools/ipod-machine/src/bin/dis.rs
[collector]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/tools/ipod-machine/src/lib.rs#L2233-L2249
[translation]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/tools/ipod-machine/src/lib.rs#L2343-L2376
[caps]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/tools/ipod-machine/src/lib.rs#L4599-L4724
[exports]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/tools/ipod-machine/src/bin/trace.rs#L3890-L3924
[ata-report]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/tools/ipod-machine/src/bin/trace.rs#L2281-L2299
[report-order]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/tools/ipod-machine/src/bin/trace.rs#L2846-L2855
[dumps]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/tools/ipod-machine/src/bin/trace.rs#L3247-L3404
[word-watch]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/tools/ipod-machine/src/lib.rs#L9671-L9675
[dma]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/tools/ipod-machine/src/lib.rs#L3230-L3249
[symbols]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/tools/ipod-machine/src/lib.rs#L10942-L11021
[snap]: https://github.com/siggifly/ipod-emulator/blob/d39e850ac07baa28abbdd8b00b77b834a757b5e1/tools/ipod-machine/src/hw/ata.rs#L148-L150
