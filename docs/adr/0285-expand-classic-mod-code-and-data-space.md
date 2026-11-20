# ADR-0285: Expand Classic mod code and data space

- Status: Accepted
- Date: 2026-11-17

The original 2.0.5 OS slot left only 6,912 bytes after the prepared Apple OS;
0.2.2-dev used 4,064 of them. Expand the shared OS slot to 16 MiB and relocate
the unchanged AUPD/hash tail within the existing firmware partition. Do not
repartition the disk or consume the public music filesystem. The live partition
must accommodate the complete 101,871,616-byte image.

Give linked mods a 4 MiB combined code/data/zero-initialized RAM budget beginning
at `0x08b3c000`. Reserve only the actual payload extent, rounded to pages, from
Apple's heap. Preserve native BSS and exception-stack locations. A larger future
RAM budget needs separate memory-layout qualification; free disk bytes alone do
not establish usable runtime memory. Use overlap-safe startup relocation and
explicitly initialize mod BSS before native startup continues.

Bootloader 2.1.0 raises the schema-2 body bound to `0xfff800`, retaining schema-1
bounds, stock authentication and CRC/read-count checks. The expanded release
requires a matching complete-loader receipt, even while its actual OS payload
is still small enough for the old loader. This gives all later builds the same
installation prerequisite. Upgrade old shared loaders through one DFU setup;
subsequent compatible OS updates use normal USB. Existing pending installation
receipts keep their original release's byte count and never replay a write.

See [layout and validation evidence](../research/classic-expanded-mod-space-2026-11-17.md).
