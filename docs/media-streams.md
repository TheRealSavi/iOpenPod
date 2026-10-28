# Choose streams for Sync

In **Sync with Host → Select Media**, click the sliders button beside a Track's
Sync checkbox to open **Choose streams…**. The adjacent **Auto** badge means
automatic stream selection; **Manual** means explicit choices are saved for that
Host file. Opening the chooser does not select or deselect the Track for Sync.
With the Sync cell focused, Enter opens the chooser and Space toggles membership.
You can also right-click one Track and choose **Choose streams…**. For a movie or
TV episode, open its Track list first if the browser is showing collection cards.

Turn off **Use automatic stream selection**, then choose:

- One **Video** stream, identified by its stream number, codec, and dimensions.
- One **Primary audio** stream for video, with language, title, and channel details
  when available. Videos also offer **None** for a silent copy.
- An optional **Alternate audio** stream for video. Choose a different stream from
  the primary; both retain their language and title tags. Audio-only sources still
  have one **Audio** choice.
- The **Subtitles** and **Captions** to include. Uncheck all entries to omit separate
  tracks of that type. Unavailable formats show an explanation.

Each dropdown shows structured stream rows with the title, language, format,
technical details, and any conversion or compatibility note. Subtitle and caption
dropdowns stay open while you check multiple rows; press Escape or Enter to close.

Primary audio is written first and marked as the default; alternate audio is
retained as an additional track. Each can be copied or converted independently.
Sound Check measures the primary. Keeping two streams provides the device with
an alternate, but the Classic's exact **Alternate Audio** On/Off language-selection
policy still needs device verification. Do not assume On always selects the second
track, especially when both tracks use the same language tag.

Use **Apply choices**, select the Track for Sync, and continue to **Review Sync**.
The reason column shows the chosen streams. A changed choice makes an existing iPod
copy an Update. After successful Sync, the same choice stays In sync on subsequent
scans. Review exclusions still skip that action.
Canceling the chooser preserves the previous choice. Re-enable automatic selection
and apply to restore the normal preparation policy.

Choices are saved on this computer for each Host file path. They survive rescans,
restarts, cancelled Syncs, and changes of Active iPod. Missing folders do not erase
them. Changing back to automatic selection replaces a previously customized copy
once. A renamed or moved source needs its choices set at the new path.

The source must remain unchanged between scanning, selection, and preparation.
Changed or unsupported selected streams are reported instead of silently choosing
another language or edition. Reopen the chooser to correct them. Your Host files
are not edited. Save errors keep the chooser open; unreadable saved preferences
block Sync until the file is restored and you scan again. Preferences live in
`media-stream-selections.json` in the application's Host configuration directory,
separately from disposable scan caches.

Video matching does not treat the first 120 seconds of audio as proof of identical
picture, subtitles, or alternate tracks. Previously synced files retain their
established association; changed video file facts request preparation again.
An unfamiliar iPod video with matching audio requires an explicit matching choice
in Review. This avoids copying entire movies just to establish a stronger scan
identity. Silent new videos can be selected for Add and then use Sync provenance
on later scans. Same-size, same-timestamp edits remain outside the cheap cache gate.

Automatic selection retains supported embedded text subtitles. To omit a subtitle
stream, turn off automatic selection and uncheck it.

On iPods that support text subtitles:

- Compatible MOV/MP4 timed text (`tx3g`) is copied when video dimensions stay the
  same. Native track headers, display boxes and clocks are checked and repaired
  when exact preservation is possible. Resized video gets a matching subtitle
  display area. Timing that cannot be safely preserved blocks preparation.
- SubRip/SRT, WebVTT, ASS/SSA, SAMI, SubViewer, MicroDVD, MPL2, and plain timed text
  are converted to readable iPod text in a correctly positioned bottom subtitle
  region. Both its display rectangle and its text/timing are verified.
- ASS signs, karaoke, and effects retain their words where possible. Fonts,
  positioning, animation, and drawings are simplified or removed. Overlapping
  dialogue and signs are combined so neither cuts off the other.
- Damaged text or timing is recovered where possible and reported. A stream with
  no usable text produces an explanation instead of a silently empty subtitle
  track. Uncheck that stream or choose another to continue.

Saved choices that previously converted text with the old display layout or movie
clock request one Update after the application is restarted and the Library is rescanned.
Successful Sync replaces that copy and returns it to In sync.

Supported CEA-608 caption tracks can be retained together with subtitles; the
Classic displays one mode at a time. Caption payloads are checked before and after
preparation. A file with field-2 captions cannot be remuxed by the current tooling
without data loss, so preparation reports that case. An unchanged copy preserves
those captions with a warning that device playback is unverified. Some unsupported
caption control commands also produce warnings without being removed.

Some output formats cannot retain
forced-playback flags; preparation reports this while keeping the selectable text.
Bitmap subtitles and external subtitle files are not converted here. Captions
embedded inside video cannot be selected separately from that video stream.
See ADR-0160 and ADR-0205 for the conversion and verification contract.

On SQLite-capable iPods, including Nano 5, Sync also writes the subtitle and
caption playback descriptors from the finished video. Existing videos with
missing descriptors are repaired during normal Sync or **Refresh Library**, even
when no media changes are selected. This repair reads the existing video and
updates the Library databases without re-encoding or rewriting the video.
Unrelated requested media updates still follow their usual preparation policy.
If a retained video cannot be inspected, Sync reports it and can retry the repair
later. Complete descriptors are retained on later Syncs. The Classic keeps its
existing subtitle preparation. See ADR-0161 for the metadata repair contract.
