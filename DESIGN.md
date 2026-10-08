---
name: dsj
description: dekho, suno, jaano. A private reader, player and checker for mixed Urdu and English recordings.
colors:
  field: "#132447"
  field-foreground: "#e6eaf2"
  field-muted: "#a9b4cc"
  field-wave: "#6b7ca3"
  ground-light: "#f3f5f9"
  ground-dark: "#0d1730"
  ink-light: "#16203a"
  ink-dark: "#e6eaf2"
  card-light: "#ffffff"
  card-dark: "#14203f"
  secondary-light: "#e2e6ee"
  secondary-dark: "#1a2748"
  muted-ink-light: "#4a5672"
  muted-ink-dark: "#9aa6bf"
  dim-light: "#5f6b85"
  dim-dark: "#808ba5"
  border-light: "#c9d0de"
  border-dark: "#26355a"
  input-edge-light: "#76829c"
  input-edge-dark: "#61719a"
  gold: "#c8a24a"
  gold-ink-light: "#7f6016"
  playhead-light: "#ebd9a6"
  playhead-dark: "#5c4a1c"
  correction-light: "#b8402a"
  correction-dark: "#e5806a"
  checked-light: "#3e7a5c"
  checked-dark: "#79be98"
  speaker-1-light: "#2f5e9e"
  speaker-1-dark: "#8db4ea"
  speaker-2-light: "#8a4f1f"
  speaker-2-dark: "#e2a774"
  speaker-3-light: "#7a3e7a"
  speaker-3-dark: "#d59ad5"
  speaker-4-light: "#1f6b73"
  speaker-4-dark: "#7fcbd3"
  speaker-5-light: "#4f5b9e"
  speaker-5-dark: "#a9b3ea"
  speaker-6-light: "#6b5e2e"
  speaker-6-dark: "#cdbb85"
  unsure-wash-light: "oklch(0.92 0.06 25)"
  unsure-wash-dark: "oklch(0.38 0.09 25)"
  muted-word-wash-light: "oklch(0.93 0.01 260)"
  muted-word-wash-dark: "oklch(0.3 0.01 260)"
typography:
  wordmark:
    fontFamily: "Literata Variable, Georgia, serif"
    fontSize: "1.5rem"
    fontWeight: 600
    letterSpacing: "-0.025em"
  headline:
    fontFamily: "Literata Variable, Georgia, serif"
    fontSize: "1.875rem"
    fontWeight: 600
  title:
    fontFamily: "Literata Variable, Georgia, serif"
    fontSize: "1.125rem"
    fontWeight: 600
  body:
    fontFamily: "Literata Variable, Georgia, serif"
    fontSize: "1.125rem"
    fontWeight: 400
    lineHeight: 1.7
  body-urdu:
    fontFamily: "Literata Variable, Noto Nastaliq Urdu Variable, serif"
    fontSize: "1.4625rem"
    fontWeight: 400
    lineHeight: 2.1
  review-sentence:
    fontFamily: "Literata Variable, Georgia, serif"
    fontSize: "1.5rem"
    fontWeight: 400
    lineHeight: 1.6
  review-sentence-urdu:
    fontFamily: "Literata Variable, Noto Nastaliq Urdu Variable, serif"
    fontSize: "1.95rem"
    fontWeight: 400
    lineHeight: 2.1
  review-context:
    fontFamily: "Literata Variable, Georgia, serif"
    fontSize: "1.0625rem"
    fontWeight: 400
    lineHeight: 1.65
  review-context-urdu:
    fontFamily: "Literata Variable, Noto Nastaliq Urdu Variable, serif"
    fontSize: "1.38rem"
    fontWeight: 400
    lineHeight: 2.1
  label:
    fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 500
    lineHeight: 1.35
    fontFeature: "tnum"
  interface:
    fontFamily: "system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 500
rounded:
  nameplate: "4px"
  sm: "4.8px"
  md: "6.4px"
  lg: "8px"
  xl: "11.2px"
  review-box: "12px"
  card-phone: "14.4px"
  pill: "9999px"
spacing:
  margin-column: "9.5rem"
  margin-gap: "1.75rem"
  turn-gap: "1.4em"
  measure: "68ch"
  measure-urdu: "30ch"
  measure-urdu-desk: "34rem"
  bar-height: "56px"
  touch-target: "44px"
components:
  button-primary:
    backgroundColor: "{colors.gold}"
    textColor: "{colors.ink-light}"
    rounded: "{rounded.lg}"
    height: "32px"
    padding: "0 10px"
  button-primary-phone:
    backgroundColor: "{colors.gold}"
    textColor: "{colors.ink-light}"
    rounded: "{rounded.lg}"
    height: "44px"
  button-outline:
    backgroundColor: "{colors.ground-light}"
    textColor: "{colors.ink-light}"
    rounded: "{rounded.lg}"
    height: "32px"
  top-bar:
    backgroundColor: "{colors.field}"
    textColor: "{colors.field-foreground}"
    height: "{spacing.bar-height}"
  player-rail:
    backgroundColor: "{colors.field}"
    textColor: "{colors.field-foreground}"
    height: "{spacing.bar-height}"
  review-box:
    backgroundColor: "{colors.card-light}"
    textColor: "{colors.ink-light}"
    typography: "{typography.review-sentence}"
    rounded: "{rounded.review-box}"
    padding: "12px 16px"
  language-tag:
    textColor: "{colors.ink-light}"
    rounded: "{rounded.pill}"
    padding: "0 8px"
  library-list:
    backgroundColor: "{colors.card-light}"
    rounded: "{rounded.xl}"
---

# Design System: dsj

## Overview

**Creative North Star: "Hashiya, the manuscript margin"**

In Persian and Urdu manuscripts the main text, the matn, sits in a ruled panel, and the corrections and commentary run in the margin, the hashiya, beside it. dsj is built on that page. The words a person said are the matn: large, calm, set at a reading measure, and the first thing on every screen. Everything about the words (who spoke, when, for how long, whether it was checked, what a correction replaced) lives in a narrow margin on their left. The world lends type, palette, density and that one signature move; navigation and controls stay ordinary web controls, because this is a tool used in focused hour-long sessions, not a page to admire.

Colour owns regions, not decoration. A deep blue field owns the shell (the top bar and the player rail) in both schemes. A pale cool ground in light, or a deep blue-black in dark, carries the words; it is never cream. Gold means "here": the word being said, the keyboard focus, the one primary action on a screen. Red is a correction and nothing else; green is "checked" and nothing else. Six soft speaker colours stay fixed per speaker for the life of a transcript.

It is calm by default. Tools appear on selection or tap; bleeping lives in a drawer; there are no help paragraphs on the page, only one key sheet behind `?` or Ctrl+/. In Review the sentence in hand is the only thing at full contrast, and the sentences around it drop to the dim ink.

**Key Characteristics:**
- The margin on the left of every turn, for Urdu and English alike, so the eye finds who and when in one place.
- Urdu as a first-class script: Noto Nastaliq Urdu, bundled, about 1.3x the English size, 2.1 leading, set right to left inside a left-to-right grid.
- Blue field shell, pale or blue-black reading ground, gold for "here", red and green held to one meaning each.
- Tabular figures for every time and count.
- Thumb-sized targets (44 px) wherever touch is the input; the player rail at the bottom, in thumb reach.

## Colors

A cool blue world with one warm accent: the shell is navy, the words sit on a pale cool ground or a blue-black one, and gold is the only warmth on the page.

### Primary
- **Manuscript Gold** (`gold`): the playhead's fill on the waveform, the one primary action per screen (Add recording, Review, Checked next), the focus ring on the blue field, and the selection wash. As text or as a ring on the pale ground it is too light (2.21:1), so there it becomes **Gold Ink** (`gold-ink-light`); on the dark ground the plain gold reads and is used as is.
- **Playhead Wash** (`playhead-light`, `playhead-dark`): the background behind the word being said. Pale in light and deep in dark, so the word on it keeps 4.5:1.
- **Unsure Rose** (`unsure-wash-light`, `unsure-wash-dark`): behind a word the recogniser was unsure of, when the unsure count is switched on (off by default, #62). Rose, so it never reads as the playhead's amber; body text on it measures 14.9:1 light and 7.8:1 dark (`ui/tests/unit/confidence.test.tsx`).
- **Muted Word Wash** (`muted-word-wash-light`, `muted-word-wash-dark`): behind a word muted for bleeping, with the muted ink and a 2px strike, so it reads as gone while staying in the text to undo.

### Secondary
- **Correction Red** (`correction-light`, `correction-dark`): the struck-through original of a corrected word in the margin, and destructive actions. Nothing else is red.
- **Checked Green** (`checked-light`, `checked-dark`): a checked sentence or turn. Nothing else is green.

### Tertiary
- **The Six Speaker Inks** (`speaker-1` to `speaker-6`, a light and a dark value each): a speaker's nameplate, their dot in the library row, their duration tick and their chip in Review. Fixed by the speaker's place in the transcript's list. None is red, green or gold, which already mean something.

### Neutral
- **Lapis Field** (`field`): the top bar and the player rail, the same blue in both schemes. Its text is `field-foreground`, its quieter text `field-muted`, and the unplayed waveform `field-wave`.
- **Cool Vellum** (`ground-light`) and **Night Ground** (`ground-dark`): the reading ground. Never cream.
- **Iron-gall Ink** (`ink-light`) and **Moonlit Ink** (`ink-dark`): body text. The dark ink is not white: near-white on near-black halates over an hour of reading.
- **Card** (`card-light`, `card-dark`): the library list, the review box, dialogs, menus, the phone's review card.
- **Secondary Wash** (`secondary-light`, `secondary-dark`): quiet buttons, muted and accent surfaces.
- **Muted Ink** (`muted-ink-light`, `muted-ink-dark`): the margin's times, metadata, placeholders.
- **Dim Ink** (`dim-light`, `dim-dark`): the context sentences and the second opinion in Review. Readable (4.5:1), plainly not the one in hand.
- **Rule** (`border-light`, `border-dark`) and **Field Edge** (`input-edge-light`, `input-edge-dark`): dividers, and the 3:1 edge of an input.

### Named Rules
**The One Meaning Rule.** Red is a correction, green is checked, gold is "here". A colour that already means something is never borrowed for emphasis, a badge or a speaker.

**The One Gold Rule.** One gold primary action per screen (Add recording, Review, Checked next). Every other button is outline, secondary or ghost, the rail's play button included: it is a control, outlined on the field, so it never stands beside the screen's gold action as a second one. Gold as a fill elsewhere is a place, not an action: the played part of the waveform, the playhead wash, the focus ring.

**The Measured Pair Rule.** Every text and non-text pair is held to WCAG AA by `ui/tests/unit/palette.test.ts` (4.5:1 for text, 3:1 for a focus ring, a field's edge and the waveform). A new colour enters through `ui/src/styles/theme.css` and that test, not as a literal in a component.

## Typography

**Reading Font:** Literata Variable (with Georgia, serif), bundled.
**Urdu Font:** Noto Nastaliq Urdu Variable, bundled through `@fontsource-variable/noto-nastaliq-urdu`, never a hosted font. Literata comes first in the Urdu stack, so Latin words and digits inside an Urdu line keep the reading face and the Arabic-script letters fall through to Nastaliq.
**Interface Font:** the system UI stack (system-ui, -apple-system, Segoe UI, sans-serif).

**Character:** a bookish serif that holds Latin and Roman Urdu at length, beside a true Nastaliq that sets Urdu as it is written by hand, with the platform's own face for every control so the tool feels native.

### Hierarchy
- **Wordmark** (Literata, 600, 1.5rem, tight tracking): "dsj" in the library's bar.
- **Headline** (Literata, 600, 1.875rem, balanced): the finish panel and the pass chooser's question.
- **Title** (Literata, 600, 1.125rem): the page title in the top bar, recording titles in the library.
- **Body** (Literata, 400, 1.125rem, 1.7 leading): transcript turns, at a 68 character measure, ragged and never justified.
- **Body, Urdu** (Nastaliq, 1.3x the English size, 2.1 leading): Urdu turns, right to left, at a narrower measure of about 45 Urdu letters (30ch of its face), so the line's start, on the right, sits near the margin on the left.
- **Review sentence** (Literata, 400, 1.5rem, 1.6 leading; Urdu 1.95rem at 2.1, at most 34rem wide): the sentence in hand.
- **Review context** (Literata, 400, 1.0625rem, 1.65 leading; Urdu 1.38rem at 2.1, its start lined up with the box text's): the dimmed sentences around it and the second opinion.
- **Label** (system, 500, 0.8125rem, 1.35 leading, tabular figures): the margin's nameplate, time and state.
- **Interface** (system, 500, 0.875rem): buttons, menus, dialogs.

### Named Rules
**The Near Start Rule.** The margin stays on the left for every turn (owner's ruling, 8 Oct 2026). A right-to-left turn takes the narrower measure instead, so the eye goes from who spoke to the first word without crossing the page.

**The Script Follows the Line Rule.** Each paragraph sets its own direction (`dir="auto"`, `unicode-bidi: plaintext`) and an Urdu line carries `lang="ur"`; the grid around it stays left to right, so the margin never swaps sides.

**The Tabular Time Rule.** Every time, length and count is in tabular figures, so columns of times line up and a ticking clock does not jitter.

## Layout

The reader is a two-column grid per turn: a 9.5rem margin, a 1.75rem gap, and the text column at a 68 character measure, with 1.4em between turns. The grid is always left to right; only the paragraph inside turns right to left for Urdu. Review uses the same grid: the sentence in hand in the middle of the window, two dimmed sentences above and below, and a footer line of the five most used keys.

The library is a single column up to 48rem (`max-w-3xl`), one list of rows in a card. The top bar is 56 px of the blue field; the player rail is the same blue, sticky at the bottom. The page's scroll padding at both ends is the bars' measured height, so a word scrolled into view never lands under either.

Below 768 px wide, or wherever the pointer is coarse, the margin folds into one slim line above each turn, the top bar wraps into two rows (search on its own row in the library; the review button and tools on the second row in the reader), and every target is at least 44 px. Review becomes one card per sentence with Back and "Checked, next" at the bottom, in thumb reach.

## Elevation & Depth

Flat by default, with tonal layering doing the work: the blue field, the ground and the card are three tones, and a 1 px rule separates rows. Shadows appear only on things that float over the words.

### Shadow Vocabulary
- **Floating tool** (`box-shadow: 0 10px 15px -3px rgb(0 0 0 / 0.15), 0 4px 6px -4px rgb(0 0 0 / 0.15)`): the selection toolbar, the in-place Correct box and the timing strip, which sit over the transcript.
- **Menu** (`shadow-lg` with a 1 px ring of the ink at low alpha): dropdown menus and the sheet.
- **Phone card** (`box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.05), 0 2px 4px -2px rgb(0 0 0 / 0.05)`): the review card on a phone, just enough to lift it off the ground.

### Named Rules
**The Float Only Rule.** A shadow means "this sits over the words". Rows, the library list and the review box on the laptop are flat.

## Shapes

Gently rounded and consistent: 8px (`lg`) for buttons, inputs and menus; 11.2px (`xl`) for the library list and the selection toolbar; 12px for the review box; 14.4px for the phone's review card. The nameplate's hover wash has 4px corners. Pills (`rounded-full`) only for the language tag, speaker chips and the round play button on the rail. The duration tick is a 3 px bar with 2 px ends, drawn to scale: a minute fills the reader's margin, 15 s fills Review's.

## Components

### Buttons
- **Shape:** gently rounded (8px).
- **Primary:** Manuscript Gold with Iron-gall Ink text, 32px tall on the laptop and 44px on the phone. One per screen.
- **Hover / Focus:** the gold drops to 80% on hover; focus is a 2px outline in Gold Ink, offset 2px, or full gold on the blue field. A pressed button moves down 1px.
- **Outline / Secondary / Ghost:** the ground or the secondary wash with ink text; ghost has no fill until hover. Used for every action that is not the screen's one primary.

### Chips
- **Language tag:** a pill with a 1px rule and small text (Urdu, mixed, English), no fill.
- **Speaker chips (Review on the phone):** pills in the speaker's ink, 44px tall; the chosen one is filled with a wash of that colour and marked `aria-pressed`.

### Cards / Containers
- **Library list:** one card (11.2px corners, 1px rule, no shadow) holding rows divided by the rule. Each row is a title in Literata, then length, language tag and speaker dots in the interface face.
- **Phone review card:** 14.4px corners, card fill, the faint phone-card shadow, 16px padding.

### Inputs / Fields
- **Style:** the shadcn Input and Textarea primitives with the Field Edge for 3:1, 8px corners.
- **Focus:** the 2px gold outline; the primitive's own ring shadow is removed so a control shows one ring, not two.
- **Selection, caret, scrollbars, form accents:** themed from the palette (gold selection wash, Gold Ink caret and accent colour, Field Edge scrollbar).

### Navigation
- **Unsure count:** in the reader's bar, an outlined switch with a swatch of Unsure Rose, hollow while off and filled while on.
- **Top bar:** the blue field, 56px, holding back, title, the one gold action, and icon buttons for the menu and settings. Focus on the field is full gold. On the phone it wraps to two rows.
- **Player rail:** the blue field at the bottom: a round play button outlined in `field-muted` (not gold: see The One Gold Rule), the time in tabular figures (smaller on a phone, never hidden), the waveform as the only scrubber (played part gold, unplayed `field-wave`), and the speed select. In phone Review the card's actions stand 12px clear of it.

### The Margin (signature component)
The narrow column on the left of every turn and every Review sentence: the speaker's nameplate in their ink (click to rename), the start time, the duration tick drawn to scale, the review mark (checked in green, flags in words), and any correction with the original struck through in Correction Red at 1.5px.

### The Review Box (signature component)
The sentence in hand, already in an edit box: card fill, a 2px Gold Ink edge that doubles as its focus mark, 12px corners, the Review sentence type. Its neighbours and the second opinion sit in Dim Ink; where the second opinion's words differ, they are underlined. Beneath it, a quiet ghost "Checked, next" gives Enter a pointer path; in the margin beside it, each speaker is a small ghost button carrying its Ctrl number, so the keys stay readable once speakers have names. Neither takes the focus from the box. The box says, to a screen reader and once in the footer, that Tab plays and Option+Tab moves on.

## Do's and Don'ts

### Do:
- **Do** put every fact about the words in the margin, on the left, for Urdu and English turns alike.
- **Do** take every colour from `ui/src/styles/theme.css` and keep `ui/tests/unit/palette.test.ts` green.
- **Do** use Gold Ink (`gold-ink-light`) for gold text or a gold ring on the pale ground; plain gold only on the blue field, on the dark ground, and as a fill.
- **Do** set Urdu in the bundled Noto Nastaliq Urdu at about 1.3x and 2.1 leading, with `lang="ur"` and `dir="auto"`.
- **Do** make every target 44px where touch is the input, and keep the player rail at the bottom.
- **Do** add a new control with `npx shadcn@4.21.0 add <name>` and theme it, never hand-built.

### Don't:
- **Don't** use a cream or warm ground; the reading ground is cool.
- **Don't** use red, green or gold for anything but correction, checked and "here".
- **Don't** put a second gold action on a screen.
- **Don't** load a hosted font; every face ships with the app.
- **Don't** put help paragraphs on the page; the key sheet holds them.
- **Don't** move the margin to the right for an Urdu turn.
- **Don't** use pure white text on the dark ground; the dark ink is `ink-dark`.
