# ADR-0211: Download the game collection on demand

- Status: Accepted
- Date: 2026-10-30

Game executables must stay outside the application distribution and Git source.
Keep the small catalog, its artwork, and a pinned release/content index in assets.
Gimme Games downloads the complete version16 `iPod.Games.Files.7z` release asset,
shows progress, and extracts the whole collection into persistent Host storage
before opening the browser. This follows the requested download-once workflow;
there is no per-game download or ZIP reconstruction when adding games.

A verified completion receipt allows later clicks to reuse the extracted folder
without downloading, extracting, or hashing the whole collection again. Add checks
the selected files against content pins before creating a Storage Transaction.
An interrupted download retains its partial file for HTTP resume; incomplete
extraction never receives a completion receipt. An OS file lease serializes Host
preparation across app processes. The source and every game content digest are
pinned so upstream replacement cannot silently change the installed bytes.

The application uses py7zr to read the solid 7z release on all supported Hosts,
avoiding a separate 7-Zip installation. This adds its decompression dependency
closure to the application. Archive paths and extraction sizes are bounded before
publication, and Host preparation remains separate from Storage device writes.
The Game Authorization Store workflow and bundled source store remain unchanged.
