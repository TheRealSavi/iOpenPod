# ADR-0245: Present video through the existing Playback Backend

- Status: Accepted
- Date: 2026-11-06
- Extends: ADR-0017 with an optional Qt video presentation attachment

Qt Multimedia already decodes video, and PySide6 includes `QVideoWidget`. Attach
that native surface to the existing `QtPlaybackBackend` instead of introducing
another decoder dependency, media source, or transport owner. The Original
iOpenPod's `origin/1.x` Player uses `QMediaPlayer` for audio; it provides no separate
video presentation to preserve.

The composition root supplies an optional `PlaybackVideoOutput` alongside the
transport controller. This Qt presentation interface accepts an output
`QObject` or `None` and exposes typed embedded subtitle choices; it exposes neither
the player nor its Playback Source.
`PlaybackBackend` and `PlaybackController` retain their decoder-independent
transport contracts. The video page may import `QtMultimediaWidgets` to own the
surface, extending ADR-0017's restriction on GUI multimedia imports. The backend
continues to own the only `QMediaPlayer`, audio output and identity-bound stream.

Clicking Player artwork for a semantic video Track opens a window-filling video
page with preserved aspect ratio, seeking, volume, Previous, Play/Pause and Next.
These controls send ordinary controller intents, including Chapter navigation.
Escape or Close restores the previous shell and detaches video output without
restarting, seeking, pausing, or changing Queue and History. Video output is
attached only while the page is shown and is released on backend shutdown.
While no surface is attached, a backend-owned video sink retains only the current
frame. Switching sinks transfers that frame and clears the old sink, so opening a
paused video shows its image without a seek or a temporary resume. Source changes
and shutdown clear retained frames. Video decoding continues while the viewer is
hidden to keep that frame current; no frame history or image-conversion loop is kept.
Audio/video transitions while viewing select the appropriate page; clearing the
Playback Session restores the shell. Video transitions are immediate because
native video surfaces do not participate in the audio page's snapshot crossfade.

Playback errors remain visible within the video page, including errors received
before it opens. Play retries through the existing controller. Codec support still
depends on the shipped Qt runtime; no external player or path-based fallback is
introduced. Alternate audio selection and fullscreen controls remain outside this
viewing change.

The Subtitles selector lists the current decoder's embedded streams by title and
language, with numbered fallbacks and an explicit Off choice. Subtitles start off
for each new Playback Entry. Selection is runtime-only and survives closing and
reopening the viewer; it does not change Sync's Media Stream Selection or iPod
metadata. Qt decodes and renders `tx3g` timed text using the existing stream, with
no extraction, external player or custom subtitle parser. A choice made while
paused takes effect on resume. Switching sinks also transfers the current subtitle
text, so reopening a paused viewer preserves the displayed cue. Off, source changes
and shutdown clear subtitle text, and decoder events refresh the available choices.
Selection at position zero is held until the playback clock advances: changing
Qt's subtitle stream during startup can otherwise emit premature EndOfMedia and
advance the Playback Queue. Source disposal cancels any pending choice.

Automated checks cover shell restoration, mixed queues, transport intents, error
retry, H.264 frame decoding and `tx3g` subtitle decoding from the read-only Playback
Source. Native acceptance
on macOS/Linux and physical-device playback remain separate checks.
