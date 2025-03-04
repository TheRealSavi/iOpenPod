# iOpenPod

iOpenPod is a powerful music synchronization tool designed first for iPod Classic models. It bridges the gap between your computer's music library and your iPod, ensuring exact synchronization of metadata, play counts, ratings, and more- All without unnecessary duplication, manual management, or lack of use of the iPod specfic controls offered.

## Features

- **Complete Synchronization**: Ensures the iPod's music library matches the computer's library.
- **Speaks the iPod's language**: Reads and writes iTunesDB files for quick up and down stream sync
- **Play Count, Rating & Skip Count Sync**:
  - Uses a dedicated `syncDB` to extract the plays since last sync and update both library's play count correctly.
  - Ratings sync supports _pessimistic_ (lower rating) or _optimistic_ (higher rating) strategies.
- **Review Queue for Missing Tracks**:
  - Tracks removed from the PC but still on the iPod enter a review queue.
  - Tracks missing from the iPod can be reviewed for adding.
- **Filetype Agnostic**: Converts files to iPod playable formats on-the-fly without keeping duplicates, unless you prefer a cache enabled workflow, where alternate filetypes will be maintained in the background for fast sync to multidevice households.
- **Metadata Updates**:
  - Has basic metadata management and corrections via MusicBrainz.
  - Mismatched and poorly formated metadata detection to prevent your albums from splitting and other strangeness.
- **Storage Management**:
  - Automatically select a subset of songs from your PC for smaller iPods.
  - Optional manual selection of songs to be synced.
  - Option to exclude metadata fields from syncing.
  - Settings to use the Auto-skip tracks in shuffle mode based on rating or skip count.
- **Backup & Rollback**: Restore previous states of both PC and iPod data by snapshotting metadata.

## How it Works

1. **Assigning Track Identifiers**: A new beets plugin generates unique iPod-like track identifiers for each song.
2. **Reading iTunesDB**: iOpenPod reads the iTunesDB from the iPod to determine existing tracks and metadata.
3. **Metadata Synchronization**:
   - Updates iPod metadata to match the latest PC library data.
   - Syncs play counts, ratings, and skip counts by summing across devices.
4. **Handling Missing Tracks**:
   - Tracks removed from PC but still on the iPod require user review.
   - Tracks missing from both PC and iPod prompt a decision to re-add.
5. **Efficient File Conversion**:
   - Converts unsupported formats only when syncing, without storing duplicates.
   - Optionally cache converted files for faster future syncs.
6. **Metadata-Only Updates**: Changes to metadata are applied directly to iTunesDB without redundantly modifying iPod files.

## Planned Features & To-Do

- [ ] Validate the longevity of metadata-only updates to iTunesDB (without modifying files).

## Installation & Usage

_(Coming Soon)_

## License

_(To Be Determined)_

---

### Contributions

Contributions are welcome! Feel free to submit issues, feature requests, or pull requests to help improve iOpenPod.

---

Enjoy seamless iPod synchronization with **iOpenPod**!
