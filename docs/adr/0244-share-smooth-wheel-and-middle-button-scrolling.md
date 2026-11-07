# ADR-0244: Share smooth wheel and middle-button scrolling

- Status: Accepted
- Date: 2026-11-06

The application installs one scrolling policy in `GUI/presentation/scrolling`.
It discovers existing and newly shown Qt scroll areas, supplies the Album grid's
bounded 140 ms wheel animation, and coordinates it with middle-button scrolling.
Individual grids and pages do not install their own wheel handlers.

Item views use pixel scrolling so animation can render intermediate positions.
Tables still advance one visible row per wheel notch and stop on row boundaries,
using actual row geometry, including hidden, resized, and reordered rows. The
bottom scroll limit can leave a partial row visible. Smaller angle deltas accumulate
into a notch; a rapid burst queues at most approximately one viewport of travel.
Other pixel item views cap each wheel line at the shared 32-pixel grid step,
retaining smaller native steps and the Host wheel-line preference. Tall Podcast
and Playback Queue rows therefore do not multiply wheel travel by their full
height. Other scroll areas retain their native scrollbar units and step sizes.

Trackpad pixel input remains immediate; native plain-text controls retain Qt's
pixel-to-text-line conversion. Modified and horizontal wheel gestures retain native
behavior. Keyboard navigation, scrollbar interaction, middle-button presses,
external position changes, hiding, and geometry changes cancel pending animation.
Animation belongs to each scroll area's Qt lifetime, including dialog destruction.
