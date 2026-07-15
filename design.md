# Design — iOpenPod

A locked design system for the iOpenPod web pages. Every page redesign reads
this file before emitting code. Extend this file when the system needs to grow;
do not regenerate a separate theme per page.

## Genre

Playful with a soft, reassuring voice. Friendly means calm and legible here,
not childish, loud, or novelty-driven.

## Audience and job

- Primary audience: iPod owners on Windows, macOS, and Linux.
- Secondary audience: contributors and hardware testers.
- Primary job: understand that iOpenPod removes media-preparation work—FLAC
  conversion, video preparation, and photo resizing—then choose a comfortable
  installation path without feeling excluded by technical language.
- Secondary job: understand the product through its real interface and find a
  precise fix when installation or device discovery fails.

## Macrostructure family

- Marketing pages: **Split Studio**, pairing short, friendly explanations with
  real product captures. Use H2 Split Diptych for the opening and quiet,
  alternating proof blocks for the product tour.
- App pages: not applicable to this static site.
- Content pages: **Conversational FAQ**, with installation choices stated in
  plain language and technical detail progressively disclosed below them.

## Theme

Custom, tuned to “friendly, calm, familiar.”

- `--color-paper` oklch(98% 0.008 250)
- `--color-paper-2` oklch(95% 0.015 250)
- `--color-paper-3` oklch(92% 0.018 250)
- `--color-ink` oklch(20% 0.020 250)
- `--color-ink-2` oklch(32% 0.018 250)
- `--color-rule` oklch(86% 0.014 250)
- `--color-rule-2` oklch(74% 0.016 250)
- `--color-muted` oklch(43% 0.014 250)
- `--color-neutral` oklch(55% 0.014 250)
- `--color-accent` oklch(50% 0.160 250)
- `--color-accent-ink` oklch(98% 0.008 250)
- `--color-focus` oklch(44% 0.190 250)

Axes: light / rounded-sans / cool.

The accent is a signal, not a section fill. Keep it under 5% of each viewport.

## Typography

- Display: Bricolage Grotesque, weight 700, style normal.
- Body: Geist, weight 400.
- Mono/code: Geist Mono, weight 400–700, reserved for commands and code.
- Display tracking: `-0.025em`.
- Type scale: major third, anchored by
  `--text-display: clamp(2.75rem, 7vw, 4.75rem)`.
- Body measure: 45–65 characters; never below 16px.

The rounded display face makes headings feel open and human; the quieter body
face keeps long instructions easy to scan. Both faces are free and loaded from
Google Fonts.

## Spacing

Use the named 4-point scale in `docs/tokens.css`. Components use
`var(--space-*)`; raw spacing values are reserved for structural calculations
and media-query thresholds.

## Motion

- Easings: `--ease-out`, `--ease-in`, and `--ease-in-out` from
  `docs/tokens.css`.
- Reveal pattern: none. Content is present immediately.
- Allowed microinteraction: button press/hover transform and image-viewer
  opacity/scale transition only.
- Reduced motion: opacity-only and no longer than 150ms.

## Microinteractions stance

- Silent success; no celebratory toasts.
- Focus rings appear instantly and use a two-colour treatment so they remain
  visible against both the page and the blue primary action.
- Hover exists only for fine pointers and always has a focus equivalent.
- Interactive text never wraps; parents reflow instead.

## CTA voice

- Primary CTA: blue fill with high-contrast light text and the label “Install
  options,” leading to the page’s installation choices before any release link.
- Secondary CTA: quiet outlined control on the current surface.
- Shape: soft pill, minimum 44px hit target, never oversized.

## Per-page allowances

- Marketing pages may use only the project’s real application screenshots.
- Content pages may use supplied instructional screenshots inline.
- No generated art, fake browser/device chrome, decorative gradients, or stock
  imagery.

## What pages MUST share

- The `iOpenPod` wordmark and blue accent.
- The Bricolage Grotesque display plus Geist body pairing.
- CTA geometry, focus treatment, spacing scale, and inline footer.
- Left-aligned section heads with no decorative eyebrow labels.
- Warm-white paper, pale blue supporting surfaces, generous negative space,
  and very little visible chrome.

## What pages MAY differ on

- Homepage: minimal utility navigation for install help, Discord, and donations;
  a split opening; and spacious screenshot pairings.
- Install help: the same utility navigation, a lightweight topic index, one calm
  reading column, and native disclosure controls.

## Product story

- Lead with the whole library: music, video, photos, podcasts, and audiobooks.
- Name FLAC directly and explain that unsupported audio is converted and cached
  automatically.
- Explain that video and photos are prepared automatically, replacing separate
  HandBrake conversion and manual resizing workflows.
- Pair convenience with control: preview sync changes and keep automatic device
  snapshots for restoration.

## Exports

### docs/tokens.css

```css
:root {
  --color-paper: oklch(98% 0.008 250);
  --color-paper-2: oklch(95% 0.015 250);
  --color-paper-3: oklch(92% 0.018 250);
  --color-rule: oklch(86% 0.014 250);
  --color-rule-2: oklch(74% 0.016 250);
  --color-neutral: oklch(55% 0.014 250);
  --color-muted: oklch(43% 0.014 250);
  --color-ink-2: oklch(32% 0.018 250);
  --color-ink: oklch(20% 0.020 250);
  --color-accent: oklch(50% 0.160 250);
  --color-accent-ink: oklch(98% 0.008 250);
  --color-focus: oklch(44% 0.190 250);
  --color-success: oklch(42% 0.130 145);
  --color-warning: oklch(48% 0.130 75);
  --color-error: oklch(48% 0.170 25);

  --font-display: "Bricolage Grotesque", "Arial Narrow", sans-serif;
  --font-body: "Geist", "Aptos", sans-serif;
  --font-outlier: "Geist Mono", "Cascadia Code", monospace;

  --space-3xs: 0.125rem;
  --space-2xs: 0.25rem;
  --space-xs: 0.5rem;
  --space-sm: 0.75rem;
  --space-md: 1rem;
  --space-lg: 1.5rem;
  --space-xl: 2.5rem;
  --space-2xl: 4rem;
  --space-3xl: 6rem;
  --space-4xl: 9rem;

  --text-xs: 0.75rem;
  --text-sm: 0.875rem;
  --text-base: 1rem;
  --text-md: 1.25rem;
  --text-lg: 1.5625rem;
  --text-xl: 1.9531rem;
  --text-2xl: 2.4414rem;
  --text-display: clamp(2.75rem, 7vw, 4.75rem);

  --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
  --ease-in: cubic-bezier(0.7, 0, 0.84, 0);
  --ease-in-out: cubic-bezier(0.65, 0, 0.35, 1);
  --dur-micro: 120ms;
  --dur-short: 220ms;
  --dur-long: 420ms;

  --rule-hair: 1px;
  --rule-fine: 2px;
  --radius-card: 0.75rem;
  --radius-pill: 999px;
  --radius-input: 0.5rem;
}
```

### Tailwind v4 `@theme`

```css
@theme {
  --color-paper: oklch(98% 0.008 250);
  --color-paper-2: oklch(95% 0.015 250);
  --color-paper-3: oklch(92% 0.018 250);
  --color-rule: oklch(86% 0.014 250);
  --color-rule-2: oklch(74% 0.016 250);
  --color-muted: oklch(43% 0.014 250);
  --color-ink-2: oklch(32% 0.018 250);
  --color-ink: oklch(20% 0.020 250);
  --color-accent: oklch(50% 0.160 250);
  --color-accent-ink: oklch(98% 0.008 250);
  --color-focus: oklch(44% 0.190 250);

  --font-display: "Bricolage Grotesque", "Arial Narrow", sans-serif;
  --font-body: "Geist", "Aptos", sans-serif;

  --spacing-xs: 0.5rem;
  --spacing-sm: 0.75rem;
  --spacing-md: 1rem;
  --spacing-lg: 1.5rem;
  --spacing-xl: 2.5rem;
  --spacing-2xl: 4rem;
  --spacing-3xl: 6rem;

  --text-xs: 0.75rem;
  --text-sm: 0.875rem;
  --text-base: 1rem;
  --text-md: 1.25rem;
  --text-lg: 1.5625rem;
  --text-xl: 1.9531rem;
  --text-2xl: 2.4414rem;

  --radius-card: 0.75rem;
  --radius-input: 0.5rem;
  --ease-out: cubic-bezier(0.16, 1, 0.3, 1);
  --ease-in: cubic-bezier(0.7, 0, 0.84, 0);
  --ease-in-out: cubic-bezier(0.65, 0, 0.35, 1);
}
```

### DTCG `tokens.json`

```json
{
  "$schema": "https://design-tokens.github.io/community-group/format/",
  "color": {
    "paper": { "$value": "oklch(98% 0.008 250)", "$type": "color" },
    "paper-2": { "$value": "oklch(95% 0.015 250)", "$type": "color" },
    "paper-3": { "$value": "oklch(92% 0.018 250)", "$type": "color" },
    "ink": { "$value": "oklch(20% 0.020 250)", "$type": "color" },
    "ink-2": { "$value": "oklch(32% 0.018 250)", "$type": "color" },
    "muted": { "$value": "oklch(43% 0.014 250)", "$type": "color" },
    "rule": { "$value": "oklch(86% 0.014 250)", "$type": "color" },
    "accent": { "$value": "oklch(50% 0.160 250)", "$type": "color" },
    "accent-ink": { "$value": "oklch(98% 0.008 250)", "$type": "color" },
    "focus": { "$value": "oklch(44% 0.190 250)", "$type": "color" }
  },
  "font": {
    "display": { "$value": "Bricolage Grotesque, Arial Narrow, sans-serif", "$type": "fontFamily" },
    "body": { "$value": "Geist, Aptos, sans-serif", "$type": "fontFamily" }
  },
  "space": {
    "xs": { "$value": "0.5rem", "$type": "dimension" },
    "sm": { "$value": "0.75rem", "$type": "dimension" },
    "md": { "$value": "1rem", "$type": "dimension" },
    "lg": { "$value": "1.5rem", "$type": "dimension" },
    "xl": { "$value": "2.5rem", "$type": "dimension" },
    "2xl": { "$value": "4rem", "$type": "dimension" },
    "3xl": { "$value": "6rem", "$type": "dimension" }
  },
  "duration": {
    "micro": { "$value": "120ms", "$type": "duration" },
    "short": { "$value": "220ms", "$type": "duration" },
    "long": { "$value": "420ms", "$type": "duration" }
  }
}
```

### shadcn/ui CSS variables

```css
:root {
  --background: 98% 0.008 250;
  --foreground: 20% 0.020 250;
  --card: 95% 0.015 250;
  --card-foreground: 20% 0.020 250;
  --popover: 95% 0.015 250;
  --popover-foreground: 20% 0.020 250;
  --primary: 50% 0.160 250;
  --primary-foreground: 98% 0.008 250;
  --secondary: 92% 0.018 250;
  --secondary-foreground: 32% 0.018 250;
  --muted: 86% 0.014 250;
  --muted-foreground: 43% 0.014 250;
  --accent: 50% 0.160 250;
  --accent-foreground: 98% 0.008 250;
  --destructive: 48% 0.170 25;
  --destructive-foreground: 98% 0.008 250;
  --border: 86% 0.014 250;
  --input: 86% 0.014 250;
  --ring: 44% 0.190 250;
  --radius: 0.75rem;
}
```
