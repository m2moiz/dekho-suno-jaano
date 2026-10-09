# Hashiya Redesign and Review Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild `dsj ui` in the Hashiya visual world (blue shell, a margin beside the words, Urdu set as Urdu) and add Review mode, which checks a transcript sentence by sentence against its audio and saves the result as an answer key.

**Architecture:** The React page in `ui/src` keeps its plain-text reader (one text node per speaker turn, painted with the CSS Custom Highlight API) and its single `Editor` over the `dsj hatao` edit list. Hashiya restyles it through tokens in `theme.css`, a margin column per turn, a contextual selection toolbar and a drawer for bleeping. Review mode is a third route over the same edit list: a pure TypeScript model of segments keyed by time span, saved as a per-transcript review document beside the library through a new `dsj/ui/review.py` and two routes, plus a reference (answer-key) exporter. Speaker reassignment is a new `EditOp` kind; speaker names live in an optional names table in the edit list file; recording titles and a script share live in library schema version 5.

**Tech Stack:** React 19.3, TypeScript 6.0.3 (pinned), Tailwind 4.3, `@base-ui/react` 1.8 through shadcn 4.21.0, Vite 8, Vitest 5, Playwright 1.63 (chromium and webkit); Python 3.12, FastAPI, pydantic, SQLite, pytest, ruff, pyright, uv, just.

**Spec:** `docs/superpowers/specs/2026-10-07-hashiya-review-mode-design.md`. Read it, `PRODUCT.md`, `AGENTS.md` ("Working on the UI" is binding) and the critique it answers, `.impeccable/critique/2026-10-06T22-54-24Z__ui-src.md`, before Task 1.

## Global Constraints

Every task's requirements include these lines.

- Work on branch `v0.5-hashiya`. Never commit to `main`. Never `git add .` or `git add -A` at the repo root; stage files by name. The one exception is the build output, staged as `git add -A -- dsj/ui/static/`, because its file names are content hashes that change on every build.
- AGENTS.md rule 1: before running a patched `dsj` from this checkout, the change to `dsj/*.py` has an issue. Each backend task names the issue title to file with `gh issue create` before its first `uv run pytest`. Any constant introduced carries the measurement and the command behind it in its comment.
- AGENTS.md "Working on the UI", verbatim requirements: `just ui-build` before any commit that touches `ui/src/`, `ui/index.html`, `ui/vite.config.ts`, `ui/tsconfig.json` or the two package files, then commit `dsj/ui/static/`; `just api` after changing `dsj/ui/schemas.py` or a route (and because that rewrites `ui/src/api/schema.d.ts`, `just ui-build` after it too); `uv run just check` is the gate, and its last line is pasted into the task report; TypeScript stays at 6.0.3; the package is `@base-ui/react`; never hand-write a UI primitive, add it with `npx shadcn@4.21.0 add <name>` from `ui/`; every version in `ui/package.json` is exact.
- Palette (spec starting points, then the built tokens chosen for contrast): field `#132447` owns the top bar and player rail; reading ground `#F3F5F9` light and `#0D1730` dark, never cream; ink `#16203A` / `#E6EAF2`; gold `#C8A24A` for playback highlight, keyboard focus and the one primary action per screen (as a ring or text on the light ground it is `#8A6A1C`, because `#C8A24A` measures 2.2:1 there); red `#B8402A` for corrections only (`#E5806A` on the dark ground); green `#3E7A5C` for "checked" only (`#79BE98` on the dark ground); six soft speaker colours fixed per speaker index. WCAG AA: 4.5:1 for text, 3:1 for non-text, held by `ui/tests/unit/palette.test.ts`.
- Type: Urdu in Noto Nastaliq Urdu (OFL), bundled locally through `@fontsource-variable/noto-nastaliq-urdu` 5.3.0, never a hosted font, about 1.3x the English size, line height about 2.1, right-aligned, `lang="ur"`. English in Literata (already bundled). Interface in the system UI stack. Times and counts in tabular figures.
- Mixed lines: `dir="auto"` per paragraph and `unicode-bidi: plaintext`. The margin sits on the left for Urdu and English turns alike.
- Targets of 44 px or more on the phone (390x844); a visible gold focus ring of at least 2 px; one level-1 heading per page; speaker turns as list items, not headings; reduced motion respected.
- Review keys, exactly (spec table): Enter checks (with any edits), goes to the next sentence and plays it; Shift+Enter previous; Tab play or pause (resume backs up 1.5 s); Shift+Tab replay from its start; Ctrl+, / Ctrl+. slower / faster through 0.75x, 1x, 1.25x, 1.5x; Ctrl+1 to Ctrl+9 speaker n; Ctrl+G take the second opinion's reading; Ctrl+U can't make it out (adds `[?]` at the cursor when text is selected or empty); Ctrl+F flag menu (not speech, overlapping talk, cut off); Ctrl+S split at the cursor; Ctrl+M merge with the previous sentence; Ctrl+J / Ctrl+Shift+J next / previous likely error; Ctrl+/ key sheet; Esc leave (progress is saved). Arriving on a sentence plays it from 0.3 s before its start to 0.2 s after its end. Typing pauses playback. A footer line always shows the five most used keys. The key sheet records the Ctrl+F trade (it shadows the text field's one-character-forward key).
- Long recordings: 2.5 h is about 1,500 sentences; the perf suite's p95 frame budget (20 ms) holds on a 1,500-sentence fixture.
- Ruff's RUF001 calls some Arabic-script letters in a Python string "ambiguous" (confusable with Latin). Every Python line below that holds Urdu text carries `# noqa: RUF001`, the way `pyproject.toml` already exempts `dsj/alignment.py`'s CJK punctuation; never "fix" the letters.
- Privacy: never commit a private recording or transcript, never quote one's text in code, tests, docs or commit messages. Every fixture is synthetic (made up here, or a tone ffmpeg makes) or public. Screenshots go to `/tmp/dsj-shots/`, never into the repo. Never print the token URL `dsj ui --print-url` writes; `scratch/ui_shots.py` reads it and hands it to agent-browser without echoing it.
- Speed is not in play here (the 2x-realtime floor is for transcription engines); the Transcribe dialog only reports the measured speeds that already exist.
- Out of scope (spec): the Gemini engine (B), scoring answer keys (E), voiceprints and cross-recording identity (D), spelling conventions (C), full-text search (#68), cancel (#72). The seams for B and C are named in Tasks 9 and 10.

## Review Focus

The five inputs most likely to bite the owner, most likely first. Each has its pinning test in the task that owns the code.

1. **A mixed-direction line: English words and numbers inside an Urdu sentence** ("میں نے 3 بجے meeting رکھی ہے"). Expect: the paragraph is set right to left in Nastaliq, "3" and "meeting" keep their own order inside it, a click on "meeting" seeks to that word, and a line that opens in English stays left to right. Pinned in Task 1 (`ui/tests/unit/script.test.ts`, and the Urdu test in `ui/tests/e2e/reader.spec.ts`).
2. **A correction that changes the word count inside a reviewed sentence** ("charlie" retyped as "Charles Darwin"). Expect: the sentence keeps its time span, shows the new words, its neighbours keep theirs, and checking it again does not apply the correction twice. Pinned in Task 11 (`ui/tests/unit/review-model.test.ts`, "a correction that changes the word count").
3. **Splitting at a cursor with no word boundary**: inside a word, before the first word, after the last, in a one-word sentence. Expect: inside a word snaps to the nearer edge of that word; an edge at either end of the sentence, or a one-word sentence, is refused with a sentence saying why; nothing changes on a refusal. Pinned in Task 11 (`splitAt` tests).
4. **Resuming a review after the transcript was transcribed again** (a run from the app with the same settings writes the same JSON path). Expect: the stale edit list is moved aside, not applied to new words; checked sentences whose span still matches stay checked; the rest are unchecked again and the page says how many. Pinned in Task 10 (`tests/test_ui_review.py`, "transcribed again") and Task 11 (`resume` tests).
5. **A 2.5 h transcript** (1,500 sentences, four speakers). Expect: the reader scrolls and Review steps sentence to sentence inside the 20 ms p95 frame budget, and building the review's segments takes under 50 ms. Pinned in Task 11 (model timing on the long fixture) and Task 15 (`ui/tests/perf/long.spec.ts`).

## File Structure

| Path | Responsibility | Task |
|---|---|---|
| `ui/src/styles/theme.css` | Every colour token, Hashiya palette, both schemes | 1 |
| `ui/src/index.css` | Tailwind theme mapping, fonts, browser surfaces (selection, caret, focus, scrollbars) | 1 |
| `ui/src/lib/script.ts` | First strong script of a text, Urdu share, `lang` | 1 |
| `ui/src/features/transcript/transcript.css` | Reader type: Literata, Nastaliq, margin grid | 1, 3 |
| `scratch/ui_shots.py` | Seeds a synthetic library, screenshots pages at 1440x900 and 390x844, light and dark | 1 |
| `ui/src/features/shell/AppBar.tsx`, `SettingsMenu.tsx` | Blue top bar, wordmark, colours menu | 2 |
| `ui/src/lib/media.ts` | `useMediaQuery` | 2 |
| `ui/src/features/player/Player.tsx`, `Waveform.tsx`, `SpeedControl.tsx`, `speed.ts` | Blue player rail, waveform as the scrubber, extended `PlayerControls` | 2 |
| `ui/src/features/transcript/TranscriptView.tsx` | Turns as list items with the margin | 3 |
| `ui/src/features/edit/corrections.ts` | Which words were corrected, and what they were | 3 |
| `ui/src/features/edit/SelectionToolbar.tsx`, `InlineCorrect.tsx` | Tools on selection; Correct in place | 3 |
| `ui/src/features/transcript/UnsureNav.tsx` | Unsure count with previous and next | 3 |
| `ui/src/features/shell/KeySheet.tsx`, `keys.ts` | The `?` key sheet and the key lists | 3 |
| `ui/src/features/transcript/MoreMenu.tsx`, `ui/src/features/bleep/BleepDrawer.tsx`, `useMatches.ts` | Reader menu, bleep drawer with badge | 4 |
| `dsj/hatao.py` | Optional `names` table in the edit list file | 5 |
| `dsj/ui/edits.py`, `dsj/ui/routes/marks.py` | Names saved and served; export payload; stale list moved aside | 5, 6, 10 |
| `ui/src/lib/editOps.ts`, `ui/src/features/edit/speaker.ts` | `SpeakerOp` and its builder | 5 |
| `ui/src/features/transcript/speakers.ts`, `Nameplate.tsx` | Display name and colour of a speaker; the renamable nameplate | 3, 5 |
| `dsj/ui/routes/recording.py`, `dsj/ui/store.py` | Title, script share, language tag, review progress; schema v5 | 7 |
| `ui/src/features/library/title.ts`, `RecordingRow.tsx`, `LibraryPage.tsx` | Readable titles, rows, versions, search, states | 8 |
| `ui/src/features/transcribe/choices.ts`, `TranscribeDialog.tsx`, `dsj/ui/jobs.py` | "What's spoken?" picker; roman-urdu transcripts get their own path | 9 |
| `dsj/ui/review.py`, `dsj/ui/routes/review.py` | Review document storage, reference export | 10 |
| `ui/src/features/review/model.ts` | Segments, split, merge, passes, likely errors, resume | 11 |
| `ui/src/features/review/secondOpinion.ts` | Other transcript's words per segment, differing words | 12 |
| `ui/src/features/review/keymap.ts`, `useReviewSession.ts`, `ReviewPage.tsx`, `ReviewDesk.tsx`, `FinishPanel.tsx`, `reviewApi.ts` | Review mode on the laptop | 13 |
| `ui/src/features/review/ReviewCard.tsx`, `swipe.ts` | Review mode on the phone | 14 |
| `ui/tests/perf/fixture.ts`, `ui/tests/perf/long.spec.ts`, `ui/tests/e2e/review*.spec.ts` | 1,500-sentence fixture, long perf, review journeys | 15 |
| `DESIGN.md`, `README.md`, `.agents/skills/dsj/SKILL.md` | Finish | 16 |

## How every UI task ends

Each UI task's last steps are, in order: the gate, the build, the look, the commit. The look comes after the build because `dsj ui` serves the committed build, and before the commit so that what is committed is what was looked at. The look is always the same command with that task's label and pages, then reading every PNG it prints with the Read tool and checking the named things against the craft floor (`/Users/moiz/.claude/skills/impeccable/reference/craft-floor.md`): contrast, focus ring, spacing, measure, overflow at 390 px, states, and nothing left in browser-default styling.

---

### Task 1: Hashiya tokens, the Nastaliq face, and Urdu set as Urdu

**Files:**
- Modify: `ui/package.json`, `ui/package-lock.json` (one exact dependency)
- Modify: `ui/src/styles/theme.css` (whole file)
- Modify: `ui/src/index.css` (the `@theme inline` block, plus a new unlayered block at the end)
- Modify: `ui/src/features/transcript/transcript.css`
- Modify: `ui/src/features/transcript/TranscriptView.tsx` (the `<p>`)
- Create: `ui/src/lib/script.ts`
- Create: `ui/tests/unit/contrast.ts`, `ui/tests/unit/palette.test.ts`, `ui/tests/unit/script.test.ts`
- Modify: `ui/tests/unit/confidence.test.tsx` (use the shared contrast helper)
- Modify: `tests/test_ui_theme.py` (`lightness` and the `--foreground` regex read hex)
- Modify: `ui/tests/e2e/reader.spec.ts` (alignment `start`; new Urdu test)
- Create: `scratch/ui_shots.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: CSS custom properties `--field`, `--field-foreground`, `--field-muted`, `--field-wave`, `--dim`, `--gold`, `--gold-ink`, `--correction`, `--checked`, `--playhead`, `--speaker-1` to `--speaker-6`, and Tailwind colours `bg-field`, `text-field-foreground`, `text-field-muted`, `text-field-wave`, `text-dim`, `bg-gold`, `text-gold`, `text-gold-ink`, `text-correction`, `text-checked`; font utilities `font-reading`, `font-urdu`. From `ui/src/lib/script.ts`: `type Script = "arabic" | "latin" | "other" | "none"`, `firstStrong(text: string): Script`, `urduShare(text: string): number`, `langOf(text: string): "ur" | undefined`. From `ui/tests/unit/contrast.ts`: `luminance(colour: string): number`, `contrast(a: string, b: string): number`, `token(css: string, name: string, scheme: "light" | "dark"): string`, `pair(css: string, selector: string, property: string): [string, string]`. The command `uv run python scratch/ui_shots.py --label <label> <page>...` with pages `library`, `library-focus`, `menu`, `reader`, `reader-urdu`, `reader-english`, `bleep`, `transcribe`, `review`.

- [ ] **Step 1: Load impeccable: read /Users/moiz/.claude/skills/impeccable/reference/craft-floor.md before editing**

Read it in full; build to it without announcing its checklist. Then run `git status` and confirm the tree holds only `.DS_Store` and `.impeccable/questions/` untracked (AGENTS.md rule 2: never touch a file someone else has modified).

- [ ] **Step 2: Write the failing script test**

Create `ui/tests/unit/script.test.ts`:

```ts
// Which script a paragraph opens in decides its direction, its face and its
// lang (Hashiya spec, Type). The sentences are made up for this test.
import { describe, expect, it } from "vitest";

import { firstStrong, langOf, urduShare } from "../../src/lib/script";

describe("firstStrong", () => {
  it.each([
    ["an Urdu sentence", " آج صبح ہم نے نیا منصوبہ دیکھا۔", "arabic"],
    // Review Focus 1: a number and an English word inside Urdu do not move the paragraph.
    ["Urdu with a number and English inside", "میں نے 3 بجے meeting رکھی ہے۔", "arabic"],
    ["English with Urdu inside", " I said کیا ہوا", "latin"],
    ["Roman Urdu", " Yaar, kal ki meeting 10 baje hai.", "latin"],
    ["a number first, then English", " 3, 4 then ok", "latin"],
    ["a number first, then Urdu", " 3 بجے", "arabic"],
    ["Devanagari", "नमस्ते", "other"],
    ["digits and Urdu punctuation only", " 123 ۔،", "none"],
    ["nothing", "", "none"],
  ] as const)("%s opens in %s", (_, text, script) => {
    expect(firstStrong(text)).toBe(script);
  });
});

describe("langOf", () => {
  it("tags a paragraph that opens in Urdu script as Urdu and leaves the rest untagged", () => {
    expect(langOf("میں نے 3 بجے meeting رکھی ہے۔")).toBe("ur");
    expect(langOf(" I said کیا ہوا")).toBeUndefined();
    expect(langOf("नमस्ते")).toBeUndefined();
  });
});

describe("urduShare", () => {
  it("is the share of letters in Urdu script, digits and spaces left out", () => {
    expect(urduShare("ab پ 12")).toBeCloseTo(1 / 3, 5);
    expect(urduShare(" آج")).toBe(1);
    expect(urduShare(" 12 ")).toBe(0);
  });
});
```

- [ ] **Step 3: Run it to see it fail**

Run: `cd ui && npx vitest run tests/unit/script.test.ts`
Expected: FAIL, `Failed to resolve import "../../src/lib/script"`.

- [ ] **Step 4: Write `ui/src/lib/script.ts`**

```ts
// Which script a stretch of text is in, for setting it (Hashiya spec, Type).
//
// A paragraph is set by its first letter that has a direction, the rule both
// `dir="auto"` and `unicode-bidi: plaintext` follow (Unicode bidi rules P2 and
// P3). So the page picks the face and the `lang` by the very letter the
// browser picks the direction by: "میں نے 3 بجے meeting رکھی" opens in Urdu
// script and is set right to left in Nastaliq, with "3" and "meeting" kept in
// their own order inside it; "I said کیا ہوا" opens in Latin and is set left
// to right. Digits and punctuation have no direction of their own (bidi
// classes EN, AN, CS, ON) and are skipped, which is why a line opening with
// "3 بجے" is still Urdu.
//
// No imports, so node and the unit test can run it on its own.

export type Script = "arabic" | "latin" | "other" | "none";

// The blocks Urdu is written in: Arabic, Arabic Supplement, Arabic
// Extended-A, and the two Presentation Forms blocks. Letters only: the
// Arabic-Indic digits in U+0660 to U+0669 and U+06F0 to U+06F9 are not \p{L}.
const ARABIC = /[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]/u;
const LETTER = /\p{L}/u;
const LATIN = /\p{Script=Latin}/u;

/** The script of the first letter in `text`, or "none" when it has no letter. */
export function firstStrong(text: string): Script {
  for (const ch of text) {
    if (!LETTER.test(ch)) continue;
    if (ARABIC.test(ch)) return "arabic";
    return LATIN.test(ch) ? "latin" : "other";
  }
  return "none";
}

/** The share of `text`'s letters that are in Urdu script, 0 when it has no letters. */
export function urduShare(text: string): number {
  let letters = 0;
  let urdu = 0;
  for (const ch of text) {
    if (!LETTER.test(ch)) continue;
    letters += 1;
    if (ARABIC.test(ch)) urdu += 1;
  }
  return letters === 0 ? 0 : urdu / letters;
}

/**
 * "ur" for a paragraph that opens in Urdu script, else nothing: the page's
 * own `lang="en"` stands. Roman Urdu is Latin script and is set as English
 * text is, which is what its letters need.
 */
export function langOf(text: string): "ur" | undefined {
  return firstStrong(text) === "arabic" ? "ur" : undefined;
}
```

- [ ] **Step 5: Run the script test to see it pass**

Run: `cd ui && npx vitest run tests/unit/script.test.ts`
Expected: PASS, 12 tests.

- [ ] **Step 6: Write the shared contrast helper and the failing palette test**

Create `ui/tests/unit/contrast.ts`:

```ts
// WCAG 2 contrast for the colours the stylesheets write: `#rrggbb` and
// `oklch(l c h)`. Hex through the sRGB transfer curve; oklch -> OKLab ->
// linear sRGB per Björn Ottosson's published matrices. Shared by
// palette.test.ts and confidence.test.tsx, so a colour changed in a
// stylesheet is checked where it is used.

function srgb(channel: number): number {
  const c = channel / 255;
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

function fromOklch(l: number, c: number, h: number): [number, number, number] {
  const a = c * Math.cos((h * Math.PI) / 180);
  const b = c * Math.sin((h * Math.PI) / 180);
  const l_ = (l + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m_ = (l - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s_ = (l - 0.0894841775 * a - 1.291485548 * b) ** 3;
  const clamp = (x: number) => Math.min(1, Math.max(0, x));
  return [
    clamp(4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_),
    clamp(-1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_),
    clamp(-0.0041960863 * l_ - 0.7034186147 * m_ + 1.707614701 * s_),
  ];
}

/** Relative luminance of `#rrggbb` or `oklch(l c h)`. */
export function luminance(colour: string): number {
  const text = colour.trim();
  const hex = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(text);
  let rgb: [number, number, number];
  if (hex !== null) {
    rgb = [srgb(parseInt(hex[1] ?? "0", 16)), srgb(parseInt(hex[2] ?? "0", 16)), srgb(parseInt(hex[3] ?? "0", 16))];
  } else {
    const found = /^oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)/.exec(text);
    if (found === null) throw new Error(`not a colour this helper reads: ${colour}`);
    rgb = fromOklch(Number(found[1]), Number(found[2]), Number(found[3]));
  }
  return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2];
}

export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((p, q) => q - p);
  return ((hi ?? 0) + 0.05) / ((lo ?? 0) + 0.05);
}

/** The two halves of `light-dark(x, y)`, split at the comma outside any parentheses. */
function halves(value: string): [string, string] {
  const inner = value.trim().replace(/^light-dark\(/, "").replace(/\)$/, "");
  let depth = 0;
  for (let i = 0; i < inner.length; i += 1) {
    const ch = inner[i];
    if (ch === "(") depth += 1;
    else if (ch === ")") depth -= 1;
    else if (ch === "," && depth === 0) return [inner.slice(0, i).trim(), inner.slice(i + 1).trim()];
  }
  throw new Error(`no light-dark pair in ${value}`);
}

/** One scheme's side of `--name` as `css` declares it: the value itself, or its light or dark half. */
export function token(css: string, name: string, scheme: "light" | "dark"): string {
  const found = new RegExp(`(?:^|[\\s;{])${name.replace(/[-]/g, "\\-")}:\\s*([^;]+);`, "m").exec(css);
  if (found?.[1] === undefined) throw new Error(`${name} is not declared`);
  const value = found[1].trim();
  if (!value.startsWith("light-dark(")) return value;
  const [light, dark] = halves(value);
  return scheme === "light" ? light : dark;
}

/** The light and dark colours inside `light-dark(...)` on the line declaring `property` after `selector`. */
export function pair(css: string, selector: string, property: string): [string, string] {
  const block = css.slice(css.indexOf(selector));
  const line = new RegExp(`${property}:\\s*(light-dark\\([^;]+\\));`).exec(block)?.[1];
  if (line === undefined) throw new Error(`no light-dark pair for ${property} in ${selector}`);
  return halves(line);
}
```

Create `ui/tests/unit/palette.test.ts`:

```ts
// The Hashiya palette (spec, "The world") held to WCAG AA in both schemes:
// 4.5:1 for text, 3:1 for a focus ring, a field's edge and the waveform. The
// spec's hexes were starting points; the tokens in theme.css are what passed.
import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { contrast, token } from "./contrast";

const theme = readFileSync(path.resolve(import.meta.dirname, "../../src/styles/theme.css"), "utf8");
const SCHEMES = ["light", "dark"] as const;
const SPEAKERS = [1, 2, 3, 4, 5, 6].map((n) => `--speaker-${n}`);

function measured(fg: string, bg: string, scheme: "light" | "dark"): number {
  return contrast(token(theme, fg, scheme), token(theme, bg, scheme));
}

describe("the Hashiya palette", () => {
  it.each(["--foreground", "--muted-foreground", "--dim", "--gold-ink", "--correction", "--checked", ...SPEAKERS])(
    "%s reads at 4.5:1 or more on the reading ground, light and dark",
    (name) => {
      for (const scheme of SCHEMES) expect(measured(name, "--background", scheme)).toBeGreaterThanOrEqual(4.5);
    },
  );

  it.each(["--foreground", "--muted-foreground", "--correction"])("%s reads at 4.5:1 or more on a card", (name) => {
    for (const scheme of SCHEMES) expect(measured(name, "--card", scheme)).toBeGreaterThanOrEqual(4.5);
  });

  it("shell text and gold read at 4.5:1 or more on the blue field", () => {
    for (const name of ["--field-foreground", "--field-muted", "--gold"]) {
      expect(measured(name, "--field", "light")).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("the primary action's ink reads at 4.5:1 or more on gold", () => {
    expect(measured("--primary-foreground", "--primary", "light")).toBeGreaterThanOrEqual(4.5);
  });

  it("the focus ring and a field's edge stand at 3:1 or more against the ground", () => {
    for (const scheme of SCHEMES) {
      expect(measured("--ring", "--background", scheme)).toBeGreaterThanOrEqual(3);
      expect(measured("--input", "--background", scheme)).toBeGreaterThanOrEqual(3);
    }
    expect(measured("--field-wave", "--field", "light")).toBeGreaterThanOrEqual(3);
  });

  it("keeps the ground cool, never cream: more blue than red in the light ground", () => {
    const ground = token(theme, "--background", "light");
    const red = parseInt(ground.slice(1, 3), 16);
    const blue = parseInt(ground.slice(5, 7), 16);
    expect(blue).toBeGreaterThan(red);
  });
});
```

- [ ] **Step 7: Run it to see it fail**

Run: `cd ui && npx vitest run tests/unit/palette.test.ts`
Expected: FAIL, `--field is not declared` (and the oklch tokens fail the hue test).

- [ ] **Step 8: Rewrite `ui/src/styles/theme.css`**

Replace the whole file with:

```css
/* Every colour the app uses, written once for both schemes (#116), in the
 * Hashiya world (docs/superpowers/specs/2026-10-07-hashiya-review-mode-design.md).
 * Colour owns regions: the deep blue field owns the shell (top bar and player
 * rail); a pale cool ground carries the words; gold marks where you are, the
 * keyboard focus and the one primary action on a screen; red is a correction
 * and nothing else; green is "checked" and nothing else.
 *
 * light-dark() picks a side by the root's color-scheme, so with nothing chosen
 * the Mac's own Appearance decides, and changing it changes this window at
 * once, with no reload and no listener. A choice of Light or Dark pins the
 * scheme through data-theme, which the inline script at the top of
 * ui/index.html sets from the dsj-theme cookie before this file loads.
 *
 * Every pair is held to WCAG AA by ui/tests/unit/palette.test.ts: 4.5:1 for
 * text, 3:1 for a focus ring, a field's edge and the waveform. The spec's
 * hexes were starting points, and three moved to pass: gold as a ring or as
 * text on the pale ground is #8A6A1C (the spec's #C8A24A measures 2.2:1
 * there), and red and green on the dark ground are #E5806A and #79BE98
 * (#B8402A measures 3.2:1 and #3E7A5C 3.5:1 on #0D1730).
 *
 * Dark body text is #E6EAF2, not white: near-white on near-black halates, and
 * over an hour of reading that glare is the whole complaint (#57 section 11.3).
 */

:root {
  color-scheme: light dark;

  /* The shell: the same blue in both schemes. */
  --field: #132447;
  --field-foreground: #e6eaf2;
  --field-muted: #a9b4cc;
  --field-wave: #6b7ca3;

  /* The reading ground and its ink. */
  --background: light-dark(#f3f5f9, #0d1730);
  --foreground: light-dark(#16203a, #e6eaf2);
  --card: light-dark(#ffffff, #14203f);
  --card-foreground: light-dark(#16203a, #e6eaf2);
  --popover: light-dark(#ffffff, #14203f);
  --popover-foreground: light-dark(#16203a, #e6eaf2);
  --secondary: light-dark(#e2e6ee, #1a2748);
  --secondary-foreground: light-dark(#16203a, #e6eaf2);
  --muted: light-dark(#e2e6ee, #1a2748);
  --muted-foreground: light-dark(#4a5672, #9aa6bf);
  --accent: light-dark(#e2e6ee, #1a2748);
  --accent-foreground: light-dark(#16203a, #e6eaf2);
  /* Context around the sentence in hand in Review: readable, plainly not the one in hand. */
  --dim: light-dark(#5f6b85, #808ba5);
  --border: light-dark(#c9d0de, #26355a);
  --input: light-dark(#76829c, #61719a);

  /* Gold: the one primary action, the focus ring, the playhead. */
  --primary: #c8a24a;
  --primary-foreground: #16203a;
  --gold: #c8a24a;
  --gold-ink: light-dark(#8a6a1c, #c8a24a);
  --ring: light-dark(#8a6a1c, #c8a24a);
  --playhead: light-dark(#ebd9a6, #5c4a1c);

  /* Red is a correction; green is checked. */
  --correction: light-dark(#b8402a, #e5806a);
  --checked: light-dark(#3e7a5c, #79be98);
  --destructive: light-dark(#b8402a, #e5806a);

  /* One per speaker, by place in the transcript's speaker list. None is red,
     green or gold, which already mean something. */
  --speaker-1: light-dark(#2f5e9e, #8db4ea);
  --speaker-2: light-dark(#8a4f1f, #e2a774);
  --speaker-3: light-dark(#7a3e7a, #d59ad5);
  --speaker-4: light-dark(#1f6b73, #7fcbd3);
  --speaker-5: light-dark(#4f5b9e, #a9b3ea);
  --speaker-6: light-dark(#6b5e2e, #cdbb85);

  /* shadcn's chart and sidebar slots, unused by the app, kept on the palette. */
  --chart-1: light-dark(#2f5e9e, #8db4ea);
  --chart-2: light-dark(#8a4f1f, #e2a774);
  --chart-3: light-dark(#7a3e7a, #d59ad5);
  --chart-4: light-dark(#1f6b73, #7fcbd3);
  --chart-5: light-dark(#4f5b9e, #a9b3ea);
  --sidebar: light-dark(#e2e6ee, #14203f);
  --sidebar-foreground: light-dark(#16203a, #e6eaf2);
  --sidebar-primary: #c8a24a;
  --sidebar-primary-foreground: #16203a;
  --sidebar-accent: light-dark(#e2e6ee, #1a2748);
  --sidebar-accent-foreground: light-dark(#16203a, #e6eaf2);
  --sidebar-border: light-dark(#c9d0de, #26355a);
  --sidebar-ring: light-dark(#8a6a1c, #c8a24a);

  --radius: 0.5rem;
}

:root[data-theme="light"] {
  color-scheme: light;
}

:root[data-theme="dark"] {
  color-scheme: dark;
}
```

- [ ] **Step 9: Map the tokens and theme the browser surfaces in `ui/src/index.css`**

In the `@theme inline` block, replace the two font lines (`--font-heading`, `--font-sans`) with:

```css
    --font-heading: var(--font-sans);
    --font-sans: system-ui, -apple-system, "Segoe UI", sans-serif;
    --font-reading: "Literata Variable", Georgia, serif;
    /* Literata first: Latin letters inside an Urdu line keep the reading face,
       and the Arabic-script letters, which Literata has none of, fall through
       to Nastaliq. */
    --font-urdu: "Literata Variable", "Noto Nastaliq Urdu Variable", serif;
    --color-field: var(--field);
    --color-field-foreground: var(--field-foreground);
    --color-field-muted: var(--field-muted);
    --color-field-wave: var(--field-wave);
    --color-dim: var(--dim);
    --color-gold: var(--gold);
    --color-gold-ink: var(--gold-ink);
    --color-correction: var(--correction);
    --color-checked: var(--checked);
    --color-playhead: var(--playhead);
    --color-speaker-1: var(--speaker-1);
    --color-speaker-2: var(--speaker-2);
    --color-speaker-3: var(--speaker-3);
    --color-speaker-4: var(--speaker-4);
    --color-speaker-5: var(--speaker-5);
    --color-speaker-6: var(--speaker-6);
```

Append to the end of the file, outside every `@layer`:

```css
/* The browser's own surfaces in the palette (craft floor, "Browser surfaces"):
   selection, caret, focus, scrollbars, form accents. Unlayered on purpose: a
   rule outside every @layer outranks Tailwind's utilities, so a primitive's
   `outline-none` cannot take the gold ring away, and the shadcn half-alpha
   ring shadow is dropped so a focused control shows one ring, not two. */
::selection {
  background-color: color-mix(in srgb, var(--gold) 40%, transparent);
  color: inherit;
}

:root {
  caret-color: var(--gold-ink);
  accent-color: var(--gold-ink);
  scrollbar-color: var(--input) transparent;
}

:focus-visible {
  outline: 2px solid var(--ring);
  outline-offset: 2px;
}

[data-slot]:focus-visible {
  box-shadow: none;
}

/* On the blue field the ring is the full gold, which reads there. */
.bg-field :focus-visible {
  outline-color: var(--gold);
}

@media (prefers-reduced-motion: reduce) {
  *,
  ::before,
  ::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
```

- [ ] **Step 10: Install the Nastaliq face**

Run: `cd ui && npm install --save-exact @fontsource-variable/noto-nastaliq-urdu@5.3.0`
Expected: `ui/package.json` gains `"@fontsource-variable/noto-nastaliq-urdu": "5.3.0"` (no `^`), and `package-lock.json` changes. Confirm with `grep nastaliq ui/package.json`.

- [ ] **Step 11: Set Urdu as Urdu in `ui/src/features/transcript/transcript.css`**

Replace the comment, the `@import` and the `.transcript` and `.transcript p` rules (keep the three `::highlight` rules after them, with the playhead one changed as below):

```css
/* The transcript as something to read for forty minutes (#58, #57 section 11.1),
 * in the Hashiya world (spec, Type).
 *
 * Literata for English, Noto Nastaliq Urdu for Urdu at 1.3x and 2.1 leading
 * (Nastaliq's stacked joins need the room), the system face for everything
 * else. A 68 character measure, ragged and never justified. Both faces are
 * bundled: only their weight axis, and the browser fetches just the scripts
 * on the page (Nastaliq's Arabic file is 239 KB, fetched only when a word in
 * Urdu script is drawn).
 *
 * Each paragraph takes its direction from its own first letter (`dir="auto"`
 * and `unicode-bidi: plaintext`), so an Urdu turn reads right to left with
 * the English words and numbers inside it in their own order, and aligns to
 * its start: the right edge for Urdu, the left for English.
 */
@import "@fontsource-variable/literata/wght.css";
@import "@fontsource-variable/noto-nastaliq-urdu/wght.css";

.transcript {
  max-width: 68ch;
  font-family: var(--font-reading);
  font-size: 1.125rem;
  line-height: 1.7;
  text-align: start;
  hyphens: manual;
}

.transcript section + section {
  margin-top: 1.25em;
}

.transcript h2 {
  font: 500 0.8125rem/1.4 system-ui, sans-serif;
  color: var(--muted-foreground);
  margin: 0;
}

.transcript p {
  margin: 0;
  unicode-bidi: plaintext;
  text-align: start;
  /* Every word is a seek target (#60). */
  cursor: pointer;
}

.transcript p:lang(ur) {
  font-family: var(--font-urdu);
  font-size: 1.3em;
  line-height: 2.1;
}
```

Change the playhead highlight's background (the comment above it says amber; make it say gold):

```css
/* The word being said (#60). A background only: ::highlight() takes colour,
 * background and decoration, never border-radius or padding (#57 section 7).
 * Hashiya gold, light enough in light mode and dark enough in dark mode that
 * the body text on it keeps 4.5:1 (confidence.test.tsx measures it). Literal
 * values, not var(--playhead): custom properties inside ::highlight() are
 * not resolved in every engine this app supports. */
::highlight(dsj-playhead) {
  background-color: light-dark(#ebd9a6, #5c4a1c);
  color: var(--foreground);
}
```

- [ ] **Step 12: Tag Urdu paragraphs in `ui/src/features/transcript/TranscriptView.tsx`**

Add `import { langOf } from "@/lib/script";` and change the paragraph to:

```tsx
            <p data-turn={i} dir="auto" lang={langOf(turn.text)}>
              {turn.text}
            </p>
```

- [ ] **Step 13: Point `confidence.test.tsx` at the shared helper**

In `ui/tests/unit/confidence.test.tsx`, delete the local `luminance`, `contrast` and `pair` functions and the comment above them, and add `import { contrast, pair } from "./contrast";` beside the other imports. The `describe("tinted text stays readable", ...)` block is unchanged: `pair` now returns strings, and `contrast` takes strings.

- [ ] **Step 14: Run the unit tests to see them pass**

Run: `cd ui && npx vitest run tests/unit/palette.test.ts tests/unit/script.test.ts tests/unit/confidence.test.tsx`
Expected: PASS, all three files.

- [ ] **Step 15: Make the Python theme test read hex**

In `tests/test_ui_theme.py`, replace `lightness` and the regex in `test_dark_body_text_is_not_pure_white`:

```python
def lightness(colour: str) -> float:
    """OKLab lightness, 0 to 1, of an `oklch(...)` or a `#rrggbb` colour."""
    colour = colour.strip()
    if colour.startswith("#"):
        r, g, b = (int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5))
        lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, b)]
        l_ = 0.4122214708 * lin[0] + 0.5363325363 * lin[1] + 0.0514459929 * lin[2]
        m_ = 0.2119034982 * lin[0] + 0.6806995451 * lin[1] + 0.1073969566 * lin[2]
        s_ = 0.0883024619 * lin[0] + 0.2817188376 * lin[1] + 0.6299787005 * lin[2]
        return (
            0.2104542553 * l_ ** (1 / 3)
            + 0.7936177850 * m_ ** (1 / 3)
            - 0.0040720468 * s_ ** (1 / 3)
        )
    found = re.fullmatch(r"oklch\(\s*([\d.]+)(%?)\s.*\)", colour)
    assert found, colour
    value = float(found[1])
    return value / 100 if found[2] else value


def test_dark_body_text_is_not_pure_white() -> None:
    """Near-white on near-black halates over an hour's reading (#57 section 11.3)."""
    css = THEME_CSS.read_text()
    found = re.search(r"(?<![\w-])--foreground:\s*light-dark\(([^,]+),\s*([^)]+)\)", css)
    assert found, "no light-dark() --foreground in theme.css"
    assert lightness(found[2]) < 0.95
    # And the light side really is the dark text, so the pair is not reversed.
    assert lightness(found[1]) < 0.5
```

Run: `uv run pytest tests/test_ui_theme.py -q`
Expected: the two source-reading tests pass; the three that read the built CSS still read the old build and pass or fail on it alone until Step 19 rebuilds. Note which; they must all pass after Step 19.

- [ ] **Step 16: Pin Review Focus 1 in the browser**

In `ui/tests/e2e/reader.spec.ts`, change `expect(layout.align).toBe("left");` to `expect(layout.align).toBe("start");`, and append:

```ts
// Urdu as Urdu (Hashiya spec, Type), and Review Focus 1: a turn that opens in
// Urdu script is set right to left in Nastaliq at about 1.3x with 2.1
// leading, a number and an English word inside it keep their own order, a
// click on that English word still seeks to it, and a turn that opens in
// English stays left to right. The sentences are made up for this test.
test("an Urdu turn is set right to left in Nastaliq, and a mixed line keeps its words in order", async ({ page }) => {
  const dir = scratchDir();
  const seeded = seed(
    {
      audio: tone(dir, 13, "urdu.wav"),
      model: "mlx-community/whisper-large-v3-turbo",
      speakers: ["SPEAKER_00", "SPEAKER_01"],
      diarization: "senko 0.1.0",
      text: "",
      unclear: [],
      sentences: [
        sentence(0, 0, [" آج", " صبح", " ہم", " نے", " نیا", " منصوبہ", " دیکھا۔"]),
        sentence(4, 1, [" میں", " نے", " 3", " بجے", " meeting", " رکھی", " ہے۔"]),
        sentence(8, 0, [" I", " said", " کیا", " ہوا"]),
      ],
    },
    dir,
  );
  await page.goto(readerUrl(seeded));
  const paragraphs = page.getByRole("article", { name: "Transcript" }).locator("p");
  await expect(paragraphs).toHaveCount(3);

  const shape = await page.evaluate(async () => {
    await document.fonts.ready;
    const words = (p: Element, word: string) => {
      const text = p.firstChild as Text;
      const at = text.data.indexOf(word);
      const range = document.createRange();
      range.setStart(text, at);
      range.setEnd(text, at + word.length);
      return range.getBoundingClientRect();
    };
    const ps = Array.from(document.querySelectorAll("article p"));
    return {
      nastaliq: [...document.fonts].some((f) => f.family.includes("Noto Nastaliq Urdu") && f.status === "loaded"),
      turns: ps.map((p) => {
        const style = getComputedStyle(p);
        const box = p.getBoundingClientRect();
        const range = document.createRange();
        range.selectNodeContents(p);
        const first = range.getClientRects()[0] ?? box;
        return {
          lang: p.getAttribute("lang"),
          direction: style.direction,
          family: style.fontFamily,
          size: parseFloat(style.fontSize),
          leading: parseFloat(style.lineHeight) / parseFloat(style.fontSize),
          rightGap: box.right - first.right,
          leftGap: first.left - box.left,
        };
      }),
      three: words(ps[1] as Element, "3"),
      meeting: words(ps[1] as Element, "meeting"),
    };
  });
  const [urdu, mixed, english] = shape.turns;
  expect(shape.nastaliq).toBe(true);
  for (const turn of [urdu, mixed]) {
    expect(turn?.lang).toBe("ur");
    expect(turn?.direction).toBe("rtl");
    expect(turn?.family).toContain("Noto Nastaliq Urdu");
    expect(turn?.leading).toBeCloseTo(2.1, 1);
    // Set from the right edge, as Urdu is.
    expect(turn?.rightGap).toBeLessThan(2);
  }
  expect((urdu?.size ?? 0) / (english?.size ?? 1)).toBeCloseTo(1.3, 1);
  expect(english?.lang).toBeNull();
  expect(english?.direction).toBe("ltr");
  expect(english?.leftGap).toBeLessThan(2);
  // Right to left, "3" comes before "meeting", so it sits to its right.
  expect(shape.three.left).toBeGreaterThan(shape.meeting.right);

  // A click on "meeting" seeks to it: 4 s + 4 words x 0.4 s.
  await expect.poll(() => page.evaluate(() => document.querySelector("audio")?.readyState ?? 0)).toBeGreaterThan(0);
  const seekTo = page.evaluate(
    () =>
      new Promise<number>((resolve) => {
        const audio = document.querySelector("audio") as HTMLAudioElement;
        audio.addEventListener("seeking", () => resolve(audio.currentTime), { once: true });
      }),
  );
  await page.mouse.click(shape.meeting.left + shape.meeting.width / 2, shape.meeting.top + shape.meeting.height / 2);
  expect(await seekTo).toBeCloseTo(5.6, 2);
});
```

The e2e run waits for the build (Step 19), because the specs load the committed page.

- [ ] **Step 17: Write the screenshot helper `scratch/ui_shots.py`**

```python
"""Screenshots of `dsj ui` for a UI task's look check: laptop and phone, light and dark.

Every UI task in docs/superpowers/plans/2026-10-07-hashiya-review-mode.md ends
with this, after `just ui-build`, because `dsj ui` serves the committed build.

It never touches the owner's library or word list. It builds a library of its
own under /tmp/dsj-shots/library/ from tones ffmpeg makes and three
transcripts made up here (English, Urdu script, and Roman Urdu with English
inside it), starts `dsj ui --print-url` on it, and drives agent-browser
through each page at 1440x900 and 390x844 in light and dark. The token URL
the server prints is read from its stdout into this process and handed to
agent-browser; it is never printed, logged or written to a file, and any
agent-browser error is shown with the token cut out.

    uv run python scratch/ui_shots.py --label t3 library reader reader-urdu
    # -> /tmp/dsj-shots/t3/<page>-<w>x<h>-<scheme>.png, one path a line
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parent.parent
OUT = Path("/tmp/dsj-shots")
VIEWPORTS = ((1440, 900), (390, 844))
SCHEMES = ("light", "dark")

# Made up for this script; no line comes from a recording.
SENTENCES: dict[str, list[list[str]]] = {
    "english": [
        [" See", " this", " column", " here."],
        [" It", " moved", " again", " today."],
        [" Fine,", " then", " we", " ship", " it."],
    ],
    "urdu": [
        [" آج", " صبح", " ہم", " نے", " نیا", " منصوبہ", " دیکھا۔"],  # noqa: RUF001
        [" میں", " نے", " 3", " بجے", " meeting", " رکھی", " ہے۔"],  # noqa: RUF001
        [" یہ", " بات", " ٹھیک", " ہے،", " لیکن", " وقت", " کم", " ہے۔"],  # noqa: RUF001
    ],
    "mixed": [
        [" Yaar,", " kal", " ki", " meeting", " 10", " baje", " hai."],
        [" Theek", " hai,", " main", " slides", " bana", " deta", " hoon."],
        [" Aur", " budget", " ka", " kya", " scene", " hai?"],
    ],
}
# Words given a low confidence, so the unsure count has something to count.
UNSURE = {"scene", "منصوبہ", "moved"}  # noqa: RUF001
MODELS = {
    "english": ("parakeet", "mlx-community/parakeet-tdt-0.6b-v3"),
    "urdu": ("whisper", "mlx-community/whisper-large-v3-turbo"),
    "mixed": ("whisper", "mlx-community/whisper-large-v3-turbo"),
}


def transcript(audio: Path, kind: str) -> dict[str, Any]:
    """Twelve sentences between two speakers, each word 0.35 s long and 0.5 s apart."""
    t = 0.3
    sentences: list[dict[str, Any]] = []
    for i, words in enumerate(SENTENCES[kind] * 4):
        tokens: list[dict[str, Any]] = []
        for w in words:
            c = 0.25 if w.strip(" .,?۔،") in UNSURE else 0.95  # noqa: RUF001
            tokens.append({"t": round(t, 3), "e": round(t + 0.35, 3), "w": w, "c": c})
            t += 0.5
        t += 0.4
        sentences.append({
            "start": tokens[0]["t"], "end": tokens[-1]["e"], "speaker": i % 2,
            "text": "".join(x["w"] for x in tokens), "tokens": tokens,
        })
    engine, model = MODELS[kind]
    return {
        "audio": str(audio), "engine": engine, "model": model,
        "speakers": ["SPEAKER_00", "SPEAKER_01"], "diarization": "senko 0.1.0",
        "text": "", "unclear": [], "sentences": sentences,
    }


def seed(root: Path) -> dict[str, tuple[int, int]]:
    """A fresh library under `root`: one recording and one transcript per kind."""
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    os.environ["DSJ_LIBRARY"] = str(root / "library.db")
    from dsj.ui.store import Library  # after DSJ_LIBRARY is set

    ids: dict[str, tuple[int, int]] = {}
    # A second apart, or the library would rightly file three equal tones as one recording.
    for seconds, kind in enumerate(SENTENCES, start=60):
        audio = root / f"{kind}.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
             f"sine=frequency=330:duration={seconds}", str(audio)],
            check=True,
        )
        path = root / f"{kind}.json"
        path.write_text(json.dumps(transcript(audio, kind), ensure_ascii=False), encoding="utf-8")
        with Library.open() as library:
            adoption = library.adopt([path])
            if adoption.refused:
                raise SystemExit(f"the library refused {path}: {adoption.refused}")
            found = library.transcript(adoption.transcripts[0])
            assert found is not None
            ids[kind] = (found.recording_id, found.id)
    return ids


QUERIES = {
    "library": lambda ids: "",
    "transcribe": lambda ids: "",
    "bleep": lambda ids: "?recording={}&transcript={}".format(*ids["mixed"]),
    "library-focus": lambda ids: "",
    "menu": lambda ids: "?recording={}&transcript={}".format(*ids["mixed"]),
    "reader": lambda ids: "?recording={}&transcript={}".format(*ids["mixed"]),
    "reader-urdu": lambda ids: "?recording={}&transcript={}".format(*ids["urdu"]),
    "reader-english": lambda ids: "?recording={}&transcript={}".format(*ids["english"]),
    "review": lambda ids: "?recording={}&transcript={}&review=1".format(*ids["mixed"]),
}

# What to do on a page before its shot. Base UI's menus open on the pointer
# events a real click starts with, so a menu is pressed with all of them.
PRESS = (
    "const press = (el) => { for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) "
    "el?.dispatchEvent(new PointerEvent(type, { bubbles: true, pointerType: 'mouse', button: 0 })); };"
)
# Keys to press on a page before its shot: two Tabs land on the bar's second control.
KEYS = {"library-focus": ["Tab", "Tab"]}
ACTIONS = {
    # The first recording's Transcribe dialog (Task 9).
    "transcribe": PRESS + "press(Array.from(document.querySelectorAll('button')).find((b) => b.textContent.trim() === 'Transcribe'));",
    # The reader's menu, open (Tasks 4 and 6).
    "menu": PRESS + "press(document.querySelector('button[aria-label=More]'));",
    # The reader's menu, then Bleep: the drawer (Task 4).
    "bleep": PRESS + "press(document.querySelector('button[aria-label=More]'));"
    "setTimeout(() => press(Array.from(document.querySelectorAll('[role=menuitem]'))"
    ".find((el) => el.textContent.trim().startsWith('Bleep'))), 300);",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--label", required=True, help="a folder name under /tmp/dsj-shots/")
    parser.add_argument("pages", nargs="+", choices=sorted(QUERIES))
    args = parser.parse_args()
    out = OUT / args.label
    out.mkdir(parents=True, exist_ok=True)
    root = OUT / "library"
    ids = seed(root)
    server = subprocess.Popen(
        ["uv", "run", "dsj", "ui", "--print-url"], cwd=REPO,
        env={**os.environ, "DSJ_LIBRARY": str(root / "library.db"),
             "DSJ_WORDS": str(root / "words.toml")},
        stdout=subprocess.PIPE, text=True,
    )
    assert server.stdout is not None
    url = server.stdout.readline().strip()
    if not url.startswith("http://127.0.0.1:"):
        server.terminate()
        raise SystemExit("dsj ui printed no address; run `uv run dsj ui --print-url` by hand to see why")
    parts = urlsplit(url)
    token = parts.fragment

    def browse(*argv: str) -> None:
        done = subprocess.run(["agent-browser", *argv], capture_output=True, text=True)
        if done.returncode != 0:
            said = (done.stderr or done.stdout).replace(token, "<token>")[:500]
            raise SystemExit(f"agent-browser {argv[0]} failed: {said}")

    try:
        for name in args.pages:
            address = f"{parts.scheme}://{parts.netloc}/{QUERIES[name](ids)}#{token}"
            for width, height in VIEWPORTS:
                for scheme in SCHEMES:
                    browse("set", "viewport", str(width), str(height))
                    browse("set", "media", scheme)
                    browse("open", address)
                    browse("wait", "1200")
                    if name in ACTIONS:
                        browse("eval", ACTIONS[name])
                        browse("wait", "900")
                    # Real key presses, so the browser shows its keyboard focus ring.
                    for key in KEYS.get(name, []):
                        browse("press", key)
                    shot = out / f"{name}-{width}x{height}-{scheme}.png"
                    browse("screenshot", str(shot))
                    print(shot)
    finally:
        subprocess.run(["agent-browser", "close"], capture_output=True)
        server.terminate()
        server.wait(timeout=20)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 18: Lint the helper**

Run: `uv run ruff check scratch/ui_shots.py`
Expected: `All checks passed!`

- [ ] **Step 19: Build, gate, and run the reader browser tests**

Run, in order:
1. `uv run just ui-build` (expected: Vite writes `dsj/ui/static/` and a Nastaliq woff2 appears under `dsj/ui/static/assets/`; then `ui_manifest.py write`).
2. `uv run just check` (expected last line: pytest's summary, `N passed` with no failures; paste it).
3. `cd ui && npx playwright test tests/e2e/reader.spec.ts --project chromium` then `--project webkit` (expected: 2 passed each).

- [ ] **Step 20: Look at it**

Run: `uv run python scratch/ui_shots.py --label t1 library reader reader-urdu reader-english`
Expected: 16 PNG paths. Read each with the Read tool. Check: the Urdu turns sit flush right in Nastaliq with room between lines, and "3" and "meeting" read in order inside them; the ground is cool white (light) and blue-black (dark), never cream; body text is ink, not grey. The shell's colours and the focus ring are judged from Task 2 on.

- [ ] **Step 21: Commit**

```bash
git add ui/package.json ui/package-lock.json ui/src/styles/theme.css ui/src/index.css \
  ui/src/features/transcript/transcript.css ui/src/features/transcript/TranscriptView.tsx \
  ui/src/lib/script.ts ui/tests/unit/contrast.ts ui/tests/unit/palette.test.ts \
  ui/tests/unit/script.test.ts ui/tests/unit/confidence.test.tsx ui/tests/e2e/reader.spec.ts \
  tests/test_ui_theme.py scratch/ui_shots.py
git add -A -- dsj/ui/static/
git commit -m "feat(ui): Hashiya palette, bundled Nastaliq, Urdu set right to left"
```

---

### Task 2: The app shell and the player rail

**Files:**
- Create: `ui/src/features/shell/AppBar.tsx`, `ui/src/features/shell/SettingsMenu.tsx`, `ui/src/lib/media.ts`
- Create (shadcn): `ui/src/components/ui/dropdown-menu.tsx`
- Modify: `ui/src/App.tsx` (whole file), `ui/src/features/library/LibraryPage.tsx` (wrap in the bar), `ui/src/features/transcript/TranscriptPage.tsx` (wrap in the bar; `open` renamed `openTranscript` and exported)
- Modify: `ui/src/features/player/Player.tsx` (whole file), `ui/src/features/player/Waveform.tsx` (component), `ui/src/features/player/SpeedControl.tsx` (controlled), `ui/src/features/player/speed.ts` (`REVIEW_SPEEDS`, `stepSpeed`), `ui/src/features/player/playhead.ts` (reduced motion)
- Delete: `ui/src/features/theme/ThemeControl.tsx` (its job moves into `SettingsMenu`)
- Test: `ui/tests/unit/shell.test.tsx` (new), `ui/tests/unit/rail.test.tsx` (new), `ui/tests/unit/media.ts` and `ui/tests/unit/menus.ts` (new helpers), `ui/tests/unit/theme.test.tsx`, `ui/tests/unit/playback-rate.test.tsx`, `ui/tests/unit/video.test.tsx`, `ui/tests/e2e/journeys.spec.ts`, `ui/tests/e2e/correction.spec.ts`, `ui/tests/e2e/player.spec.ts`

**Interfaces:**
- Consumes: Task 1's tokens (`bg-field`, `text-field-foreground`, `text-field-muted`, `text-field-wave`, `text-gold`, `bg-gold`).
- Produces:
  - `AppBar({ back?: boolean; children?: ReactNode })` and `BAR_HEIGHT = "--dsj-bar-height"`.
  - `SettingsMenu({ extra?: ReactNode })`: the colours radio group, and room for menu items later tasks add (Task 3 adds "Keys").
  - `useMediaQuery(query: string): boolean` from `@/lib/media`.
  - `export async function openTranscript(recordingId: number, transcriptId: number): Promise<Opened>` and `export type Opened` from `TranscriptPage.tsx`.
  - `PlayerControls = { hear(from: number, to: number): void; toggle(backS?: number): void; pause(): void; isPlaying(): boolean; setSpeed(speed: Speed): void; speed(): Speed }`.
  - `Player` props: `article?: RefObject<HTMLElement | null>` (now optional) and `selectOnTap?: boolean` (used from Task 3).
  - From `speed.ts`: `REVIEW_SPEEDS = [0.75, 1, 1.25, 1.5] as const`, `stepSpeed(current: Speed, by: 1 | -1): Speed`.
  - `SpeedControl({ speed: Speed; onSpeed: (speed: Speed) => void })`.

- [ ] **Step 1: Load impeccable: read /Users/moiz/.claude/skills/impeccable/reference/craft-floor.md before editing**

Read it in full; build to it without announcing its checklist.

- [ ] **Step 2: Add the menu primitive**

Run: `cd ui && npx shadcn@4.21.0 add dropdown-menu --dry-run`, then `npx shadcn@4.21.0 add dropdown-menu`.
Then confirm the exports this plan imports: `grep -n "^export\|^function" src/components/ui/dropdown-menu.tsx`. Expected names: `DropdownMenu`, `DropdownMenuTrigger`, `DropdownMenuContent`, `DropdownMenuItem`, `DropdownMenuLabel`, `DropdownMenuSeparator`, `DropdownMenuRadioGroup`, `DropdownMenuRadioItem`, `DropdownMenuSub`, `DropdownMenuSubTrigger`, `DropdownMenuSubContent`. If the generator names one differently, use its name everywhere this plan uses that one. If `package.json` gained a dependency, check it is exact (no `^`).

- [ ] **Step 3: Write the failing shell and rail tests**

Create `ui/tests/unit/media.ts`:

```ts
// jsdom has neither matchMedia nor ResizeObserver; the bar, the rail and the
// phone layouts use both. Each test file that needs them installs them in
// beforeEach; nothing here restores them.

/** A ResizeObserver that never fires: jsdom lays nothing out, so there is nothing to observe. */
export function stubResizeObserver(): void {
  globalThis.ResizeObserver ??= class {
    observe() {}
    disconnect() {}
    unobserve() {}
  };
}

/** matchMedia answering each query with `matches(query)`: a phone is `(q) => q.includes("coarse")`. */
export function stubMatchMedia(matches: (query: string) => boolean = () => false): void {
  stubResizeObserver();
  window.matchMedia = ((query: string) => ({
    matches: matches(query),
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}
```

Create `ui/tests/unit/shell.test.tsx`:

```tsx
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { AppBar } from "../../src/features/shell/AppBar";
import { stubMatchMedia } from "./media";
import { choose } from "./menus";

beforeEach(() => {
  stubMatchMedia();
  document.cookie = "dsj-theme=; max-age=0; path=/";
  delete document.documentElement.dataset.theme;
});
afterEach(cleanup);

describe("the app bar", () => {
  it("carries the wordmark home on the library, and a way back on any other page", () => {
    const { rerender } = render(<AppBar />);
    expect(screen.getByRole("link", { name: "dsj" }).getAttribute("href")).toBe("/");
    rerender(<AppBar back />);
    expect(screen.getByRole("link", { name: "Library" }).getAttribute("href")).toBe("/");
  });

  it("is a banner on the blue field", () => {
    render(<AppBar>tools</AppBar>);
    expect(screen.getByRole("banner").className).toContain("bg-field");
  });

  it("keeps the colours choice in its settings menu, and keeps it in the cookie", async () => {
    render(<AppBar />);
    act(() => fireEvent.click(screen.getByRole("button", { name: "Settings" })));
    choose(await screen.findByRole("menuitemradio", { name: "Dark" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.cookie).toContain("dsj-theme=dark");
  });
});
```

Create `ui/tests/unit/menus.ts`, which every later menu test uses:

```ts
import { act, fireEvent } from "@testing-library/react";

/**
 * Pick a Base UI menu or select item as a real click does. A click alone picks
 * nothing in jsdom: Base UI's items also want the pointerdown a real click
 * starts with (found for the Select in playback-rate.test.tsx, #81).
 */
export function choose(item: HTMLElement): void {
  act(() => {
    fireEvent.pointerDown(item, { pointerType: "mouse" });
    fireEvent.click(item);
  });
}
```

Create `ui/tests/unit/rail.test.tsx`:

```tsx
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.hoisted(() => {
  globalThis.fetch = (async () => new Response(new Int8Array([-1, 1, -2, 2]))) as unknown as typeof fetch;
});

import type { RecordingRow } from "../../src/features/library/types";
import { Player, type PlayerControls } from "../../src/features/player/Player";
import { REVIEW_SPEEDS, saveSpeed, stepSpeed } from "../../src/features/player/speed";
import { read } from "../../src/features/transcript/document";
import { installHighlights } from "./highlights";
import { stubMatchMedia } from "./media";

const recording: RecordingRow = {
  id: 4,
  path: "/r/call.mp3",
  size_bytes: 10,
  duration_s: 30,
  content_id: "c",
  audio_codec: "aac",
  video_codec: null,
  first_seen: "2026-09-20T17:00:00+00:00",
  missing: false,
  unreadable: null,
  transcripts: [],
};

const reading = read({ audio: "a", model: "m", sentences: [{ start: 0, end: 1, text: " Hi.", tokens: [{ t: 0, w: " Hi." }] }] });

beforeEach(() => {
  installHighlights();
  stubMatchMedia();
  document.cookie = "dsj-speed=; max-age=0; path=/";
});
afterEach(cleanup);

describe("the player rail", () => {
  it("is one blue rail with a play button, the time, the waveform and the speed, and no browser audio bar", () => {
    render(<Player recording={recording} reading={reading} />);
    const rail = screen.getByRole("region", { name: "Player" });
    expect(rail.querySelector(".bg-field")).not.toBeNull();
    expect(screen.getByRole("button", { name: "Play" })).toBeTruthy();
    expect(screen.getByRole("slider", { name: "Position" })).toBeTruthy();
    expect(screen.getByRole("combobox", { name: "Playback speed" })).toBeTruthy();
    expect(document.querySelector("audio")?.hasAttribute("controls")).toBe(false);
  });

  it("moves the position by five seconds an arrow key, thirty with Shift", () => {
    render(<Player recording={recording} reading={reading} />);
    const audio = document.querySelector("audio") as HTMLAudioElement;
    Object.defineProperty(audio, "duration", { value: 120 });
    audio.play = () => Promise.resolve();
    const slider = screen.getByRole("slider", { name: "Position" });
    act(() => fireEvent.keyDown(slider, { key: "ArrowRight" }));
    expect(audio.currentTime).toBe(5);
    act(() => fireEvent.keyDown(slider, { key: "ArrowRight", shiftKey: true }));
    expect(audio.currentTime).toBe(35);
    act(() => fireEvent.keyDown(slider, { key: "Home" }));
    expect(audio.currentTime).toBe(0);
  });

  it("starts at the saved speed, and the page can change it through its controls", () => {
    saveSpeed(1.5);
    const controls = createRef<PlayerControls | null>() as { current: PlayerControls | null };
    render(<Player recording={recording} reading={reading} controls={controls} />);
    const audio = document.querySelector("audio") as HTMLAudioElement;
    expect(audio.playbackRate).toBe(1.5);
    act(() => controls.current?.setSpeed(0.75));
    expect(audio.playbackRate).toBe(0.75);
    expect(controls.current?.speed()).toBe(0.75);
  });

  it("backs up when told to on resuming", () => {
    const controls = { current: null } as { current: PlayerControls | null };
    render(<Player recording={recording} reading={reading} controls={controls} />);
    const audio = document.querySelector("audio") as HTMLAudioElement;
    audio.play = () => Promise.resolve();
    audio.currentTime = 10;
    act(() => controls.current?.toggle(1.5));
    expect(audio.currentTime).toBe(8.5);
  });
});

describe("stepSpeed", () => {
  it("walks Review's four speeds and stops at either end", () => {
    expect(REVIEW_SPEEDS).toEqual([0.75, 1, 1.25, 1.5]);
    expect(stepSpeed(1, 1)).toBe(1.25);
    expect(stepSpeed(1.5, 1)).toBe(1.5);
    expect(stepSpeed(0.75, -1)).toBe(0.75);
    // From a reader speed outside the four, to the nearest one in that direction.
    expect(stepSpeed(2, -1)).toBe(1.5);
    expect(stepSpeed(0.5, 1)).toBe(0.75);
  });
});
```

- [ ] **Step 4: Run them to see them fail**

Run: `cd ui && npx vitest run tests/unit/shell.test.tsx tests/unit/rail.test.tsx`
Expected: FAIL, `Failed to resolve import "../../src/features/shell/AppBar"` and `REVIEW_SPEEDS` not exported.

- [ ] **Step 5: Write `ui/src/lib/media.ts`**

```ts
// Whether a CSS media query matches, as React state that follows it live: the
// phone layouts (Hashiya spec, "Laptop and phone") read `(pointer: coarse)`
// and widths through this, so a window dragged narrower changes layout at once.

import { useSyncExternalStore } from "react";

function supported(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function";
}

export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (changed) => {
      if (!supported()) return () => undefined;
      const list = window.matchMedia(query);
      list.addEventListener("change", changed);
      return () => list.removeEventListener("change", changed);
    },
    () => supported() && window.matchMedia(query).matches,
  );
}

/** A touch screen, or a window as narrow as a phone: where the touch layouts take over. */
export const TOUCH = "(pointer: coarse), (max-width: 767px)";
```

- [ ] **Step 6: Write `ui/src/features/shell/SettingsMenu.tsx`**

```tsx
import { Settings2 } from "lucide-react";
import { type ReactNode, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { readTheme, saveTheme, THEMES, type Theme } from "@/features/theme/theme";

const LABELS: Record<Theme, string> = { light: "Light", dark: "Dark", system: "Same as the Mac" };

/**
 * The bar's one settings menu: colours (Light / Dark / follow the Mac, #116),
 * and whatever the page adds below it (Task 3 adds the key sheet). A menu,
 * not three buttons in the bar, so the bar holds only what the page is for.
 */
export function SettingsMenu({ extra }: { extra?: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(() => readTheme());
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            variant="ghost"
            size="icon"
            aria-label="Settings"
            className="size-11 text-field-foreground hover:bg-white/10 hover:text-field-foreground"
          />
        }
      >
        <Settings2 aria-hidden />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-52">
        <DropdownMenuLabel>Colours</DropdownMenuLabel>
        <DropdownMenuRadioGroup
          value={theme}
          onValueChange={(picked: string) => {
            const next = THEMES.find((t) => t === picked);
            if (next === undefined) return;
            setTheme(next);
            saveTheme(next);
          }}
        >
          {THEMES.map((value) => (
            <DropdownMenuRadioItem key={value} value={value}>
              {value === "system" ? LABELS.system : LABELS[value]}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
        {extra}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
```

The radio item for `system` is named "Same as the Mac"; `ui/tests/e2e/journeys.spec.ts` changes from "System" to that name in Step 13.

- [ ] **Step 7: Write `ui/src/features/shell/AppBar.tsx`**

```tsx
import { ArrowLeft } from "lucide-react";
import { type ReactNode, useEffect, useRef } from "react";

import { SettingsMenu } from "./SettingsMenu";

// The custom property on <html> holding the bar's height, which the page's
// top scroll padding reads (index.css), so a word the browser scrolls into
// view (a Cmd+F match, #230) never lands under the bar.
export const BAR_HEIGHT = "--dsj-bar-height";

/**
 * The blue field's top half (Hashiya spec, "Colour owns regions"): the
 * wordmark on the library, a way back everywhere else, then the page's own
 * tools, then settings. It wraps to a second row on a phone rather than
 * squeezing its targets under 44 px.
 */
export function AppBar({ back = false, children, settings }: { back?: boolean; children?: ReactNode; settings?: ReactNode }) {
  const bar = useRef<HTMLElement>(null);
  useEffect(() => {
    const element = bar.current;
    if (element === null) return;
    const root = document.documentElement;
    const resized = new ResizeObserver(() => root.style.setProperty(BAR_HEIGHT, `${element.getBoundingClientRect().height}px`));
    resized.observe(element);
    return () => {
      resized.disconnect();
      root.style.removeProperty(BAR_HEIGHT);
    };
  }, []);
  return (
    <header ref={bar} className="sticky top-0 z-30 bg-field text-field-foreground">
      <div className="mx-auto flex min-h-14 w-full max-w-6xl flex-wrap items-center gap-x-2 gap-y-1 px-2 py-1.5 sm:px-6">
        {back ? (
          <a
            href="/"
            aria-label="Library"
            className="inline-flex size-11 shrink-0 items-center justify-center rounded-lg hover:bg-white/10"
          >
            <ArrowLeft aria-hidden className="size-5" />
          </a>
        ) : (
          <a href="/" className="px-2 font-reading text-2xl font-semibold tracking-tight">
            dsj
          </a>
        )}
        {children}
        <div className="ml-auto">
          <SettingsMenu extra={settings} />
        </div>
      </div>
    </header>
  );
}
```

In `ui/src/index.css`, inside `@layer base`'s `html` rule, beside `scroll-padding-bottom`, add:

```css
    /* And the bar at the top, which writes its own height (AppBar.tsx). */
    scroll-padding-top: var(--dsj-bar-height, 0px);
```

- [ ] **Step 8: Rewrite `ui/src/App.tsx`**

```tsx
import { ErrorBoundary } from "@/features/errors/ErrorBoundary";
import { ShownErrorDialog } from "@/features/errors/ErrorDialog";
import { LibraryPage } from "@/features/library/LibraryPage";
import { TranscriptPage } from "@/features/transcript/TranscriptPage";
import { readRoute } from "@/lib/route";

/**
 * Each page draws its own bar (AppBar), because what the bar carries is the
 * page's: search and Add recording on the library, the title and the
 * transcript's tools on a transcript.
 */
export function App() {
  const route = readRoute(window.location.search);
  return (
    <div className="flex min-h-dvh flex-col font-sans">
      <ErrorBoundary>
        {route.page === "transcript" ? (
          <TranscriptPage recording={route.recording} transcript={route.transcript} />
        ) : (
          <LibraryPage />
        )}
      </ErrorBoundary>
      <ShownErrorDialog />
    </div>
  );
}
```

- [ ] **Step 9: Put the library and the reader under the bar**

In `ui/src/features/library/LibraryPage.tsx`, import `AppBar` and wrap the page: the `return (<div className="flex flex-col gap-6">...)` becomes

```tsx
  return (
    <>
      <AppBar>
        <h1 className="sr-only">Library</h1>
      </AppBar>
      <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-3 py-6 sm:px-6">
        {/* the existing children of the old <div>, unchanged */}
      </main>
    </>
  );
```

and the loading branch returns `<AppBar><h1 className="sr-only">Library</h1></AppBar>` instead of `null`. Task 8 rebuilds this page; this step only moves it under the bar.

In `ui/src/features/transcript/TranscriptPage.tsx`:
1. Rename `async function open(` to `export async function openTranscript(` and export the `Opened` type (`export type Opened = ...`). Update its one caller.
2. Delete the `<nav>` with "← Library".
3. While loading or failed, render `<AppBar back><h1 className="truncate text-lg">Transcript</h1></AppBar>` and, when failed, `<main className="mx-auto w-full max-w-3xl px-3 py-6 sm:px-6"><p className="text-muted-foreground">This transcript could not be opened.</p></main>`.
4. In `Page`, replace the `<header className="mb-8 ...">` block with the bar, and wrap the rest in `<main>`:

```tsx
    <>
      <AppBar back>
        <h1 className="min-w-0 flex-1 truncate font-reading text-lg font-semibold">{fileName(recording.path)}</h1>
        <UnsureToggle reading={reading} model={doc.model} article={article} />
      </AppBar>
      <main className="mx-auto w-full max-w-5xl flex-1 px-3 pt-6 pb-10 sm:px-6">
        {children}
        <TranscriptView reading={reading} articleRef={article} />
      </main>
      {recording.missing ? (
        <p className="sticky bottom-0 bg-field px-4 py-3 text-sm text-field-foreground">
          The recording is not where it was last seen, so this transcript cannot play. Last seen at{" "}
          <span className="font-mono break-all">{recording.path}</span>
        </p>
      ) : (
        <Player
          recording={recording}
          reading={reading}
          article={article}
          muteSpans={muteSpans ?? null}
          {...(controls === undefined ? {} : { controls })}
        />
      )}
    </>
```

The model id under the title is gone (critique: "Model repo ID as subtitle"); it returns in the library's details in Task 8.

- [ ] **Step 10: Add Review's speeds to `ui/src/features/player/speed.ts`**

Append:

```ts
// Review's four steps (Hashiya spec, key table: Ctrl+, and Ctrl+.). Slower
// than 0.75x drags Urdu's long vowels apart; faster than 1.5x outruns typing.
export const REVIEW_SPEEDS = [0.75, 1, 1.25, 1.5] as const;

/** The next of Review's speeds from `current` in direction `by`, staying at either end. */
export function stepSpeed(current: Speed, by: 1 | -1): Speed {
  if (by > 0) return REVIEW_SPEEDS.find((s) => s > current) ?? REVIEW_SPEEDS[REVIEW_SPEEDS.length - 1] ?? current;
  return [...REVIEW_SPEEDS].reverse().find((s) => s < current) ?? REVIEW_SPEEDS[0] ?? current;
}
```

`stepSpeed(1.5, 1)` finds no faster step and returns 1.5; `stepSpeed(2, -1)` finds 1.5.

- [ ] **Step 11: Make `SpeedControl` controlled**

Replace `ui/src/features/player/SpeedControl.tsx`'s component with:

```tsx
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { type Speed, SPEEDS, speedLabel } from "./speed";

const ITEMS = SPEEDS.map((value) => ({ value, label: speedLabel(value) }));

/**
 * 0.5x to 2x (#81). The Player owns the speed now, because Review changes it
 * from the keyboard (Ctrl+, and Ctrl+.) and this select must show that.
 */
export function SpeedControl({ speed, onSpeed }: { speed: Speed; onSpeed: (speed: Speed) => void }) {
  return (
    <Select
      items={ITEMS}
      value={speed}
      onValueChange={(picked) => {
        const next = SPEEDS.find((s) => s === picked);
        if (next !== undefined) onSpeed(next);
      }}
    >
      <SelectTrigger
        size="sm"
        aria-label="Playback speed"
        className="h-11 w-20 border-white/20 bg-transparent text-field-foreground tabular-nums"
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {ITEMS.map((item) => (
          <SelectItem key={item.value} value={item.value}>
            {item.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
```

- [ ] **Step 12: Rebuild the Waveform as the rail's scrubber**

Keep `columns` and `draw` in `ui/src/features/player/Waveform.tsx` as they are, and replace the `Props` type and the `Waveform` component with:

```tsx
type Props = {
  recordingId: number;
  media: RefObject<HTMLMediaElement | null>;
  /** Where the playhead tells this view the time, every frame it paints (#60). */
  frames: Set<(seconds: number) => void>;
  /** Move the one playhead there: the same seek a click on a word makes. */
  onSeek: (seconds: number) => void;
};

// One arrow key press moves this far; with Shift, SHIFT_STEP_S.
const STEP_S = 5;
const SHIFT_STEP_S = 30;

/**
 * The recording's shape as the only scrubber (Hashiya spec, Reader: "the
 * waveform as the only scrubber with the played part tinted gold"). Two
 * canvases drawn once, the second in gold and cut by clip-path to the played
 * part, so a frame moves one clip and draws nothing. A slider to the keyboard
 * and to a screen reader (critique: "waveform unreachable by keyboard").
 */
export function Waveform({ recordingId, media, frames, onSeek }: Props) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const played = useRef<HTMLCanvasElement>(null);
  const cursor = useRef<HTMLDivElement>(null);
  const slider = useRef<HTMLDivElement>(null);
  const [peaks, setPeaks] = useState<Int8Array | null>(null);

  useEffect(() => {
    let live = true;
    const route = `/api/recording/${recordingId}/waveform`;
    api
      .GET("/api/recording/{recording_id}/waveform", {
        params: { path: { recording_id: String(recordingId) } },
        parseAs: "arrayBuffer",
      })
      .then(({ data, error, response }) => {
        if (data === undefined) throw new ApiError(fromBody(error, response, route));
        if (live) setPeaks(new Int8Array(data));
      })
      .catch((thrown: unknown) => {
        if (live) showError(fromThrown(thrown, route));
      });
    return () => {
      live = false;
    };
  }, [recordingId]);

  // Drawn again when the canvas changes size or the colours change scheme.
  useEffect(() => {
    const base = canvas.current;
    const gold = played.current;
    if (base === null || gold === null || peaks === null) return;
    const redraw = () => {
      draw(base, peaks);
      draw(gold, peaks);
    };
    redraw();
    const resized = new ResizeObserver(redraw);
    resized.observe(base);
    const themed = new MutationObserver(redraw);
    themed.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const scheme = window.matchMedia("(prefers-color-scheme: dark)");
    scheme.addEventListener("change", redraw);
    return () => {
      resized.disconnect();
      themed.disconnect();
      scheme.removeEventListener("change", redraw);
    };
  }, [peaks]);

  // The cursor and the gold clip move with the playhead's own frame, never
  // with React state; the slider's value is written at most once a second.
  useEffect(() => {
    let lastSecond = -1;
    const move = (seconds: number) => {
      const duration = media.current?.duration ?? Number.NaN;
      if (!Number.isFinite(duration) || duration <= 0) return;
      const share = Math.min(seconds, duration) / duration;
      const width = cursor.current?.parentElement?.clientWidth ?? 0;
      if (cursor.current !== null) cursor.current.style.transform = `translateX(${share * width}px)`;
      if (played.current !== null) played.current.style.clipPath = `inset(0 ${(1 - share) * 100}% 0 0)`;
      const second = Math.floor(seconds);
      if (second !== lastSecond && slider.current !== null) {
        lastSecond = second;
        slider.current.setAttribute("aria-valuenow", String(second));
        slider.current.setAttribute("aria-valuemax", String(Math.round(duration)));
        slider.current.setAttribute("aria-valuetext", `${durationLabel(seconds) ?? "0:00"} of ${durationLabel(duration) ?? "0:00"}`);
      }
    };
    frames.add(move);
    return () => {
      frames.delete(move);
    };
  }, [frames, media]);

  const key = (event: KeyboardEvent<HTMLDivElement>) => {
    const element = media.current;
    if (element === null) return;
    const duration = Number.isFinite(element.duration) ? element.duration : Number.POSITIVE_INFINITY;
    const step = event.shiftKey ? SHIFT_STEP_S : STEP_S;
    const to =
      event.key === "ArrowRight" || event.key === "ArrowUp"
        ? element.currentTime + step
        : event.key === "ArrowLeft" || event.key === "ArrowDown"
          ? element.currentTime - step
          : event.key === "Home"
            ? 0
            : event.key === "End" && Number.isFinite(duration)
              ? duration
              : null;
    if (to === null) return;
    event.preventDefault();
    onSeek(Math.min(Math.max(0, to), duration));
  };

  return (
    <div
      ref={slider}
      role="slider"
      tabIndex={0}
      aria-label="Position"
      aria-valuemin={0}
      aria-valuemax={0}
      aria-valuenow={0}
      className="relative h-11 min-w-0 flex-1 cursor-pointer rounded-md"
      onKeyDown={key}
      onClick={(event) => {
        const duration = media.current?.duration ?? Number.NaN;
        if (!Number.isFinite(duration)) return;
        const box = event.currentTarget.getBoundingClientRect();
        onSeek(((event.clientX - box.left) / box.width) * duration);
      }}
    >
      <canvas ref={canvas} aria-label="Waveform" className="h-full w-full text-field-wave" />
      <div ref={cursor} aria-hidden className="pointer-events-none absolute inset-y-1 left-0 w-0.5 rounded bg-gold" />
      <canvas
        ref={played}
        aria-hidden
        className="pointer-events-none absolute inset-0 h-full w-full text-gold"
        style={{ clipPath: "inset(0 100% 0 0)" }}
      />
    </div>
  );
}
```

Add the imports this needs at the top: `type KeyboardEvent` from `react`, and `durationLabel` from `@/features/library/describe`. The canvas keeps `aria-label="Waveform"` and the cursor stays its next sibling, which `ui/tests/e2e/player.spec.ts` reads (`'[aria-label="Waveform"] + div'`).

- [ ] **Step 13: Rewrite `ui/src/features/player/Player.tsx`**

Replace the file from `const MEDIA_ERRORS` down to the end with the following (keep `mediaSrc`, `NOT_SUPPORTED`, `play`, `SCROLL_KEYS` above it, and add `import { Pause, Play } from "lucide-react";`, `import { applySpeed, readSpeed, saveSpeed, type Speed } from "./speed";` and `import { useCallback } from "react";` to the imports):

```tsx
const MEDIA_ERRORS: Record<number, string> = {
  1: "loading was stopped",
  2: "the network failed while loading it",
  3: "the browser could not decode it",
  4: "the browser cannot play this kind of file",
};

/** What a page can ask of the player beyond a click on a word: the reader's Hear, and all of Review. */
export type PlayerControls = {
  /** Play from `from` and stop at `to`, both in seconds: audition one span (#84). */
  hear: (from: number, to: number) => void;
  /** Play, or pause; playing again starts `backS` seconds before where it stopped (Review's Tab). */
  toggle: (backS?: number) => void;
  pause: () => void;
  isPlaying: () => boolean;
  /** Play at `speed` and keep it for later launches (#81). */
  setSpeed: (speed: Speed) => void;
  speed: () => Speed;
};

type Props = {
  recording: RecordingRow;
  reading: Reading;
  /** The transcript's <article>, whose paragraphs the playhead paints. Review has none. */
  article?: RefObject<HTMLElement | null>;
  /** Spans to play silent, as a render of the edit list would (#84). */
  muteSpans?: readonly Span[] | null;
  /** Filled in with this player's controls while it is mounted. */
  controls?: RefObject<PlayerControls | null>;
  /** On a touch screen, a tap on a word selects it for the selection toolbar rather than seeking (Task 3). */
  selectOnTap?: boolean;
};

/**
 * The recording under the transcript (#60), as the blue rail of the Hashiya
 * shell: play, the time, the waveform as the one scrubber, the speed. Click a
 * word to hear it; the word being said is highlighted as it plays, with the
 * view following it until the reader scrolls away. The browser's own audio
 * bar is gone (critique: "two scrubbers").
 *
 * A screen recording plays in a <video> on the same playhead (#80), shown
 * above the rail and folded away with display: none, which keeps it playing.
 */
export function Player({ recording, reading, article, muteSpans = null, controls, selectOnTap = false }: Props) {
  const media = useRef<HTMLMediaElement>(null);
  // A file this browser will not open plays from a copy of its sound instead (#110).
  const [soundOnly, setSoundOnly] = useState(false);
  const hasVideo = recording.video_codec !== null && !soundOnly;
  const [videoShown, setVideoShown] = useState(() => readVideoShown());
  const [playing, setPlaying] = useState(false);
  const [noPicture, setNoPicture] = useState(false);
  const [speed, setSpeedState] = useState<Speed>(() => readSpeed());
  const clock = useRef<HTMLSpanElement>(null);
  const playhead = useRef<Playhead | null>(null);
  const [following, setFollowing] = useState(true);
  // Views that move with the playhead's frame: the waveform's cursor (#61).
  const [frames] = useState(() => new Set<(seconds: number) => void>());
  // Where an audition stops, in seconds, while one plays (#84).
  const stopAt = useRef<number | null>(null);

  const changeSpeed = useCallback((next: Speed) => {
    setSpeedState(next);
    saveSpeed(next);
  }, []);
  const speedNow = useRef(speed);
  speedNow.current = speed;

  useEffect(() => {
    if (media.current !== null) applySpeed(media.current, speed);
  }, [speed, soundOnly]);

  /** Hear `seconds`: the one seek a word, the waveform and anything later share. */
  const seek = (seconds: number) => {
    const element = media.current;
    if (element === null) return;
    // Any seek ends an audition; `hear` sets its stop again after its own.
    stopAt.current = null;
    element.currentTime = seconds;
    playhead.current?.follow();
    play(element);
  };
  const seekRef = useRef(seek);
  seekRef.current = seek;
  // The live mute (#84), one per media element, with the spans it follows.
  const gate = useRef<MuteGate | null>(null);
  const spans = useRef<readonly Span[]>(muteSpans ?? []);

  useEffect(() => {
    spans.current = muteSpans ?? [];
    gate.current?.setSpans(spans.current);
  }, [muteSpans]);

  useEffect(() => {
    if (controls === undefined) return;
    controls.current = {
      hear: (from, to) => {
        seekRef.current(from);
        stopAt.current = to;
      },
      toggle: (backS = 0) => {
        const element = media.current;
        if (element === null) return;
        if (!element.paused) {
          element.pause();
          return;
        }
        stopAt.current = null;
        if (backS > 0) element.currentTime = Math.max(0, element.currentTime - backS);
        play(element);
      },
      pause: () => media.current?.pause(),
      isPlaying: () => media.current !== null && !media.current.paused,
      setSpeed: changeSpeed,
      speed: () => speedNow.current,
    };
    return () => {
      controls.current = null;
    };
  }, [controls, changeSpeed]);

  useEffect(() => {
    const element = media.current;
    const root = article?.current ?? null;
    if (element === null) return;
    const texts: Text[] = [];
    if (root !== null) {
      for (const p of root.querySelectorAll<HTMLElement>("p[data-turn]")) {
        if (p.firstChild instanceof Text) texts[Number(p.dataset["turn"])] = p.firstChild;
      }
    }
    const mute = new MuteGate(element);
    mute.setSpans(spans.current);
    gate.current = mute;
    const head = new Playhead({
      media: element,
      reading,
      texts,
      onFollowing: setFollowing,
      onFrame: (seconds) => {
        mute.update(seconds);
        // An audition ends where it was asked to, on the frame that reaches it.
        if (stopAt.current !== null && seconds >= stopAt.current) {
          stopAt.current = null;
          element.pause();
        }
        for (const frame of frames) frame(seconds);
      },
    });
    playhead.current = head;
    // Made again whenever the words change (an edit, #66), which can happen
    // mid-play: the new loop starts at once rather than at the next `play`.
    if (!element.paused) head.start();

    const started = () => {
      mute.update(element.currentTime);
      head.start();
      setPlaying(true);
    };
    const stopped = () => {
      head.stop();
      setPlaying(false);
    };
    // A video track the browser cannot draw (ProRes in Chromium, measured for
    // #59) plays its sound over a blank box and raises no error, so say so.
    const loaded = () => {
      if (element instanceof HTMLVideoElement) setNoPicture(element.videoWidth === 0);
    };
    const seeked = () => {
      mute.update(element.currentTime);
      if (element.paused) head.paint();
    };
    // Frames stop in a hidden tab and the sound does not: the element's own
    // clock, a few times a second, keeps the mute in step there.
    const ticked = () => mute.update(element.currentTime);
    const failed = () => {
      const code = element.error?.code ?? 0;
      if (code === NOT_SUPPORTED && !soundOnly) {
        setSoundOnly(true);
        return;
      }
      const detail = element.error?.message ? ` ${element.error.message}` : "";
      showError({
        error: "MediaError",
        message: `The recording could not be played: ${MEDIA_ERRORS[code] ?? `media error ${code}`}.${detail}`,
        // The path only: the query holds the token, and this text is copied.
        request: `/api/recording/${recording.id}/media`,
      });
    };
    const click = (event: MouseEvent) => {
      // A drag that selected text is a selection, not a seek.
      if (event.button !== 0 || window.getSelection()?.isCollapsed === false) return;
      const hit = offsetAtPoint(event);
      if (hit === null) return;
      const word = wordAtOffset(reading, hit.turn, hit.offset);
      // On a touch screen a tap selects the word, so the selection toolbar
      // can offer Correct and Hear (Hashiya spec, Reader); a Mac click seeks.
      if (selectOnTap && window.matchMedia("(pointer: coarse)").matches) {
        selectWordAt(reading, texts, word);
        return;
      }
      const at = reading.words.start[word];
      if (at !== undefined) seekRef.current(at);
    };
    const scrolledByHand = () => head.unfollow();
    const key = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing = target?.closest("input, textarea, select, audio, video, button, [contenteditable], [role=slider]");
      if (SCROLL_KEYS.has(event.key) && typing == null) head.unfollow();
    };

    element.addEventListener("play", started);
    element.addEventListener("pause", stopped);
    element.addEventListener("ended", stopped);
    element.addEventListener("seeked", seeked);
    element.addEventListener("timeupdate", ticked);
    element.addEventListener("error", failed);
    element.addEventListener("loadedmetadata", loaded);
    root?.addEventListener("click", click);
    window.addEventListener("wheel", scrolledByHand, { passive: true });
    window.addEventListener("touchmove", scrolledByHand, { passive: true });
    window.addEventListener("keydown", key);
    return () => {
      element.removeEventListener("play", started);
      element.removeEventListener("pause", stopped);
      element.removeEventListener("ended", stopped);
      element.removeEventListener("seeked", seeked);
      element.removeEventListener("timeupdate", ticked);
      element.removeEventListener("error", failed);
      element.removeEventListener("loadedmetadata", loaded);
      root?.removeEventListener("click", click);
      window.removeEventListener("wheel", scrolledByHand);
      window.removeEventListener("touchmove", scrolledByHand);
      window.removeEventListener("keydown", key);
      head.dispose();
      playhead.current = null;
      mute.dispose();
      gate.current = null;
    };
  }, [reading, article, recording.id, frames, soundOnly, selectOnTap]);

  // The time, written by the playhead's own frame.
  useEffect(() => {
    const tick = (seconds: number) => {
      const duration = media.current?.duration ?? Number.NaN;
      if (clock.current === null) return;
      const total = Number.isFinite(duration) ? ` / ${durationLabel(duration)}` : "";
      clock.current.textContent = `${durationLabel(seconds)}${total}`;
    };
    frames.add(tick);
    return () => {
      frames.delete(tick);
    };
  }, [frames]);

  // The page's scroll padding at the bottom is this rail's height (#230), and
  // the playhead's follow band ends where it starts (#231).
  const bar = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const element = bar.current;
    if (element === null) return;
    const root = document.documentElement;
    const resized = new ResizeObserver(() => {
      root.style.setProperty(PLAYER_HEIGHT, `${element.getBoundingClientRect().height}px`);
    });
    resized.observe(element);
    return () => {
      resized.disconnect();
      root.style.removeProperty(PLAYER_HEIGHT);
    };
  }, []);

  const attach = (element: HTMLMediaElement | null) => {
    media.current = element;
  };
  const src = mediaSrc(recording.id, soundOnly);
  const toggle = () => {
    const element = media.current;
    if (element === null) return;
    if (element.paused) play(element);
    else element.pause();
  };

  return (
    <div ref={bar} role="region" aria-label="Player" className="sticky bottom-0 z-20 pb-[env(safe-area-inset-bottom)]">
      {hasVideo && (
        <div className={videoShown ? "border-t bg-background/95 px-3 py-2 backdrop-blur sm:px-6" : "hidden"}>
          <video ref={attach} src={src} playsInline preload="metadata" className="mx-auto max-h-[35vh] w-full rounded-md bg-black" aria-label="Recording" />
          {noPicture && (
            <p className="text-sm text-muted-foreground">
              This browser cannot show this recording's picture ({recording.video_codec}). The sound plays.
            </p>
          )}
        </div>
      )}
      {soundOnly && (
        <p className="bg-field px-4 pt-2 text-sm text-field-muted">
          This browser cannot open this recording's file, so a copy of its sound is playing.
        </p>
      )}
      {!hasVideo && <audio ref={attach} src={src} preload="metadata" aria-label="Recording" className="hidden" />}
      <div className="bg-field text-field-foreground">
        <div className="mx-auto flex h-14 w-full max-w-6xl items-center gap-2 px-2 sm:gap-3 sm:px-6">
          <Button
            variant="ghost"
            size="icon"
            aria-label={playing ? "Pause" : "Play"}
            onClick={toggle}
            className="size-11 shrink-0 rounded-full bg-gold text-primary-foreground hover:bg-gold/90"
          >
            {playing ? <Pause aria-hidden className="size-5" /> : <Play aria-hidden className="size-5" />}
          </Button>
          <span ref={clock} className="hidden shrink-0 text-sm text-field-muted tabular-nums sm:inline">
            0:00
          </span>
          <Waveform recordingId={recording.id} media={media} frames={frames} onSeek={(seconds) => seekRef.current(seconds)} />
          <SpeedControl speed={speed} onSpeed={changeSpeed} />
          {hasVideo && (
            <Button
              variant="ghost"
              className="h-11 shrink-0 text-field-foreground hover:bg-white/10 hover:text-field-foreground"
              onClick={() => {
                setVideoShown(!videoShown);
                saveVideoShown(!videoShown);
              }}
            >
              {videoShown ? "Hide picture" : "Show picture"}
            </Button>
          )}
          {!following && (
            <Button
              variant="ghost"
              className="h-11 shrink-0 text-field-foreground hover:bg-white/10 hover:text-field-foreground"
              onClick={() => playhead.current?.follow()}
            >
              Follow playback
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

/** Select word `word` in its paragraph's text, without the space in front of it. */
function selectWordAt(reading: Reading, texts: Text[], word: number): void {
  const { turn, offset, length } = reading.words;
  const text = texts[turn[word] ?? -1];
  if (text === undefined) return;
  const from = offset[word] ?? 0;
  const to = from + (length[word] ?? 0);
  const lead = /^\s*/.exec(text.data.slice(from, to))?.[0].length ?? 0;
  const range = document.createRange();
  range.setStart(text, from + lead);
  range.setEnd(text, to);
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
}
```

Remove the now-unused `useState` import of `SpeedControl`'s old form, if any, and keep `readVideoShown`, `saveVideoShown`, `PLAYER_HEIGHT`, `Playhead`, `Waveform`, `SpeedControl`, `MuteGate`, `durationLabel`, `offsetAtPoint`, `wordAtOffset` imports.

- [ ] **Step 14: Respect reduced motion in the follow scroll**

In `ui/src/features/player/playhead.ts`, `reveal()`'s last line becomes:

```ts
    // Smooth for the eye, unless the Mac asks for less motion.
    const behavior = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
    window.scrollBy({ top: rect.top - target, behavior });
```

- [ ] **Step 15: Move the old tests to the new shell**

1. Delete `ui/src/features/theme/ThemeControl.tsx`. In `ui/tests/unit/theme.test.tsx`, delete the `describe` block that renders `ThemeControl` and its import; the head-script and `readTheme`/`saveTheme` blocks stay. The menu's behaviour is now in `shell.test.tsx`.
2. In `ui/tests/unit/playback-rate.test.tsx`, replace the `describe("SpeedControl", ...)` block with:

```tsx
describe("SpeedControl", () => {
  it("shows the speed it is given and hands back the one picked", async () => {
    const picked: number[] = [];
    render(<SpeedControl speed={1.5} onSpeed={(s) => picked.push(s)} />);
    const trigger = screen.getByRole("combobox", { name: "Playback speed" });
    expect(trigger.textContent).toContain("1.5×");
    act(() => fireEvent.click(trigger));
    const double = await screen.findByRole("option", { name: "2×" });
    // A click alone picks nothing here: Base UI's Select item also wants the
    // pointerdown a real click starts with (tried one event at a time).
    act(() => {
      fireEvent.pointerDown(double, { pointerType: "mouse" });
      fireEvent.click(double);
    });
    expect(picked).toEqual([2]);
  });
});
```

   and drop the now-unused `createRef` import. The "starts at the saved speed" case lives in `rail.test.tsx`.
3. In `ui/tests/unit/video.test.tsx`, a test that clicked "Play" when the picture was hidden still finds `button "Play"`; one that checked `audio[controls]` or a `video[controls]` attribute now expects no `controls` attribute. Run the file and change only what fails, by those two rules.
4. In `ui/tests/e2e/journeys.spec.ts`, every `page.getByRole("button", { name: "Dark" })` (and "System", "Light") becomes a two-step open: `await page.getByRole("button", { name: "Settings" }).click(); await page.getByRole("menuitemradio", { name: "Dark" }).click();` with "System" renamed "Same as the Mac".
5. In `ui/tests/e2e/correction.spec.ts`, `page.getByRole("link", { name: "← Library" })` becomes `page.getByRole("link", { name: "Library" })`.
6. In `ui/tests/e2e/player.spec.ts`, nothing reads the native controls; run it and fix only a selector that names removed text.

- [ ] **Step 16: Run the unit tests**

Run: `cd ui && npx vitest run tests/unit/shell.test.tsx tests/unit/rail.test.tsx tests/unit/theme.test.tsx tests/unit/playback-rate.test.tsx tests/unit/video.test.tsx tests/unit/waveform.test.tsx`
Expected: PASS.

- [ ] **Step 17: Gate, build, browser tests**

Run: `uv run just check` (paste the last line), then `uv run just ui-build`, then `cd ui && npx playwright test tests/e2e/player.spec.ts tests/e2e/video.spec.ts tests/e2e/journeys.spec.ts tests/e2e/correction.spec.ts --project chromium`.
Expected: all pass.

- [ ] **Step 18: Look at it**

Run: `uv run python scratch/ui_shots.py --label t2 library library-focus reader reader-urdu`
Expected: 16 PNGs. Check: in the `library-focus` shots a 2 px gold ring sits around the focused control, offset from it; the bar and the rail are the same deep blue at both sizes, the gold play button is round and 44 px, the waveform fills the rail with no browser audio bar anywhere, the time is tabular, the settings icon sits at the bar's right edge, and on 390 px nothing in the rail overflows (the time hides there by design).

- [ ] **Step 19: Commit**

```bash
git add ui/src/App.tsx ui/src/index.css ui/src/lib/media.ts ui/src/features/shell/AppBar.tsx \
  ui/src/features/shell/SettingsMenu.tsx ui/src/components/ui/dropdown-menu.tsx \
  ui/src/features/library/LibraryPage.tsx ui/src/features/transcript/TranscriptPage.tsx \
  ui/src/features/player/Player.tsx ui/src/features/player/Waveform.tsx \
  ui/src/features/player/SpeedControl.tsx ui/src/features/player/speed.ts \
  ui/src/features/player/playhead.ts ui/tests/unit/media.ts ui/tests/unit/menus.ts ui/tests/unit/shell.test.tsx \
  ui/tests/unit/rail.test.tsx ui/tests/unit/theme.test.tsx ui/tests/unit/playback-rate.test.tsx \
  ui/tests/unit/video.test.tsx ui/tests/e2e/journeys.spec.ts ui/tests/e2e/correction.spec.ts \
  ui/tests/e2e/player.spec.ts ui/package.json ui/package-lock.json
git rm ui/src/features/theme/ThemeControl.tsx
git add -A -- dsj/ui/static/
git commit -m "feat(ui): blue app bar and player rail, waveform as the scrubber"
```

(`ui/package.json` and the lock are staged only if Step 2 changed them; `git status` says.)

---
### Task 3: The reader's margin, the selection toolbar, Correct in place, unsure navigation, the key sheet

**Files:**
- Create: `ui/src/features/transcript/speakers.ts`, `ui/src/features/edit/corrections.ts`, `ui/src/features/edit/SelectionToolbar.tsx`, `ui/src/features/edit/InlineCorrect.tsx`, `ui/src/features/transcript/UnsureNav.tsx`, `ui/src/features/transcript/VersionPicker.tsx`, `ui/src/features/transcript/readerKeys.ts`, `ui/src/features/shell/keys.ts`, `ui/src/features/shell/KeySheet.tsx`
- Create (shadcn): `ui/src/components/ui/kbd.tsx`
- Modify: `ui/src/features/transcript/TranscriptView.tsx` (whole file), `ui/src/features/transcript/transcript.css` (turn grid), `ui/src/features/transcript/TranscriptPage.tsx` (whole file), `ui/src/features/edit/EditBar.tsx` (`EditBar` slimmed; `useCorrectedPaint` added), `ui/src/features/library/describe.ts` (`versionLabel`), `ui/src/features/player/Player.tsx` (`SCROLL_KEYS`), `ui/src/App.tsx` (mount `KeySheet`)
- Delete: `ui/src/features/edit/CorrectDialog.tsx`, `ui/src/features/transcript/UnsureToggle.tsx`
- Test: `ui/tests/unit/corrections.test.ts` (new), `ui/tests/unit/reader.test.tsx` (new), `ui/tests/unit/correction.test.tsx`, `ui/tests/unit/confidence.test.tsx`, `ui/tests/unit/edit.test.tsx`, `ui/tests/unit/transcript.test.tsx`, `ui/tests/e2e/reader.spec.ts`, `ui/tests/e2e/correction.spec.ts`, `ui/tests/e2e/edit.spec.ts`, `ui/tests/e2e/bounds.spec.ts`, `ui/tests/e2e/find.spec.ts`, `ui/tests/e2e/follow.spec.ts`, `ui/tests/perf/reader.spec.ts`

**Interfaces:**
- Consumes: Task 2's `AppBar({ back, children, settings })`, `Player` with `selectOnTap`, `PlayerControls.hear/toggle`, `useMediaQuery`, `TOUCH`; Task 1's `langOf`.
- Produces:
  - `speakers.ts`: `type Names = Readonly<Record<string, string>>`, `NO_NAMES: Names`, `speakerColour(index: number | null): string | undefined`, `displayName(speakers: readonly string[], names: Names, index: number | null): string | null`.
  - `corrections.ts`: `type Correction = { turn: number; first: number; last: number; original: string; now: string }`, `type Tokens`, `tokensOf(doc: TranscriptDoc): Tokens`, `originalText(tokens: Tokens, from: number, to: number): string`, `corrections(reading: Reading, tokens: Tokens): Correction[]`.
  - `TranscriptView` props: `{ reading; articleRef?; corrections?: readonly Correction[]; names?: Names; nameplate?: (speaker: number, label: string, name: string) => ReactNode }`.
  - `SelectionToolbar` props `{ editor; content; edit; selected; controls; onCorrect(picked: Picked): void; onTiming(word: number): void }`; `type Picked = { start: number; stop: number; from: number; to: number; box: Box; paragraph: HTMLElement }`; `type Box`; `boxOf(range: Range): Box`.
  - `keys.ts`: `type Key = { keys: string[]; does: string }`, `type Sheet = { title: string; keys: readonly Key[]; notes: readonly string[] }`, `READER_SHEET: Sheet`.
  - `KeySheet.tsx`: `showKeys(sheet: Sheet): void`, `hideKeys(): void`, `KeySheet()`, `KeysItem({ sheet })`.
  - `useReaderKeys(controls: RefObject<PlayerControls | null>, sheet: Sheet): void`.
  - `TranscriptPage.tsx`'s `Page` takes `tools?: ReactNode`, `corrections?`, `names?`, `nameplate?`, `selectOnTap?` (later tasks add to the bar through `tools`).

- [ ] **Step 1: Load impeccable: read /Users/moiz/.claude/skills/impeccable/reference/craft-floor.md before editing**

Read it in full; build to it without announcing its checklist.

- [ ] **Step 2: Add the key primitive**

Run: `cd ui && npx shadcn@4.21.0 add kbd --dry-run`, then `npx shadcn@4.21.0 add kbd`. Confirm with `grep -n "^export\|^function" src/components/ui/kbd.tsx` that it exports `Kbd` (and `KbdGroup`); use the generated names if they differ.

- [ ] **Step 3: Write the failing corrections test**

Create `ui/tests/unit/corrections.test.ts`:

```ts
// Which words were corrected, for the margin (Hashiya spec, "The margin").
import { describe, expect, it } from "vitest";

import { correction } from "../../src/features/edit/correct";
import { corrections, originalText, tokensOf } from "../../src/features/edit/corrections";
import { readContent } from "../../src/features/edit/readContent";
import type { TranscriptDoc } from "../../src/features/transcript/document";
import type { Content, Item } from "../../src/lib/editOps";

function item(sourceStart: number, length: number, text: string, confidence: number | null = 0.9): Item {
  return { kind: "item", source: "0", sourceStart, length, text, muted: false, confidence };
}

const DOC: TranscriptDoc = {
  audio: "a.wav",
  model: "parakeet",
  sentences: [
    { start: 0.2, end: 1.6, text: " alpha bravo charlie delta", tokens: [
      { t: 0.2, w: " alpha", e: 0.5, c: 0.9 },
      { t: 0.6, w: " bravo", e: 0.9, c: 1 },
      { t: 1.0, w: " charlie", e: 1.3, c: 0.3 },
      { t: 1.3, w: " delta", e: 1.6, c: 0.9 },
    ] },
  ],
};

const CONTENT: Content = [
  { kind: "paragraph", speaker: null, language: null },
  item(0, 0.2, "", null),
  item(0.2, 0.3, " alpha"),
  item(0.5, 0.1, "", null),
  // A word the recogniser was fully sure of: confidence 1, never edited.
  item(0.6, 0.3, " bravo", 1),
  item(0.9, 0.1, "", null),
  item(1.0, 0.3, " charlie", 0.3),
  item(1.3, 0.3, " delta"),
];

describe("corrections", () => {
  const tokens = tokensOf(DOC);

  it("finds a retyped stretch and what the transcript had there", () => {
    const retyped = CONTENT.slice();
    const op = correction(retyped, 6, 7, "Charles Darwin");
    const after = [...retyped.slice(0, 6), ...op.entries, ...retyped.slice(7)];
    const found = corrections(readContent(after, undefined).reading, tokens);
    expect(found).toEqual([{ turn: 0, first: 2, last: 3, original: "charlie", now: "Charles Darwin" }]);
  });

  it("does not count a word the recogniser was sure of, or one whose edges alone moved", () => {
    expect(corrections(readContent(CONTENT, undefined).reading, tokens)).toEqual([]);
    const retimed = CONTENT.map((e, i) => (i === 7 && e.kind === "item" ? { ...e, sourceStart: 1.35, length: 0.25, confidence: 1 } : e));
    expect(corrections(readContent(retimed, undefined).reading, tokens)).toEqual([]);
  });

  it("reads the transcript's own words over a stretch of time", () => {
    expect(originalText(tokens, 0.6, 1.3)).toBe("bravo charlie");
    expect(originalText(tokens, 5, 6)).toBe("");
  });
});
```

The retimed `delta` keeps its text, so `original === now` and it is left out; `bravo` has confidence 1 and its text matches the transcript's.

- [ ] **Step 4: Run it to see it fail**

Run: `cd ui && npx vitest run tests/unit/corrections.test.ts`
Expected: FAIL, `Failed to resolve import "../../src/features/edit/corrections"`.

- [ ] **Step 5: Write `ui/src/features/edit/corrections.ts`**

```ts
// Which words a person corrected (#83), and what the recogniser had written
// there, for the margin (Hashiya spec, "The margin": "corrections with the
// original struck through in red").
//
// A corrected word reads back with confidence 1: correct.ts gives every new
// word 1, and dsj/ui/edits.py `_confidences` gives 1 to any item that matches
// no token of the transcript. So does a word whose edges alone were dragged
// (#85), and now and then a word the recogniser was fully sure of. So a run of
// confidence-1 words counts as a correction only when the transcript's own
// tokens over the same stretch of time say something else.

import type { Reading, TranscriptDoc } from "@/features/transcript/document";

export type Correction = {
  /** The paragraph it is in. */
  turn: number;
  /** Its first and last word, as indexes into the reading's words. */
  first: number;
  last: number;
  /** What the transcript had over the same stretch of time, and what it says now. */
  original: string;
  now: string;
};

/** Every token's start and text, in time order: made once per transcript. */
export type Tokens = { t: Float64Array; w: readonly string[] };

// Half a millisecond: dsj/hatao.py rounds times to the millisecond.
const EPS = 0.0005;

export function tokensOf(doc: TranscriptDoc): Tokens {
  const t: number[] = [];
  const w: string[] = [];
  for (const sentence of doc.sentences) {
    for (const token of sentence.tokens) {
      t.push(token.t);
      w.push(token.w);
    }
  }
  return { t: Float64Array.from(t), w };
}

/** The first token starting at or after `seconds`. */
function firstFrom(times: Float64Array, seconds: number): number {
  let lo = 0;
  let hi = times.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if ((times[mid] ?? 0) < seconds) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** The transcript's own words starting in [from, to), joined and trimmed. */
export function originalText(tokens: Tokens, from: number, to: number): string {
  let text = "";
  for (let i = firstFrom(tokens.t, from - EPS); i < tokens.t.length && (tokens.t[i] ?? 0) < to - EPS; i += 1) {
    text += tokens.w[i] ?? "";
  }
  return text.trim();
}

/** Every corrected stretch, one per run of confidence-1 words inside one paragraph. */
export function corrections(reading: Reading, tokens: Tokens): Correction[] {
  const { start, end, confidence, turn, offset, length } = reading.words;
  const out: Correction[] = [];
  let w = 0;
  while (w < start.length) {
    if (confidence[w] !== 1) {
      w += 1;
      continue;
    }
    let last = w;
    while (last + 1 < start.length && confidence[last + 1] === 1 && turn[last + 1] === turn[w]) last += 1;
    const paragraph = reading.turns[turn[w] ?? 0];
    const now = (paragraph?.text ?? "").slice(offset[w] ?? 0, (offset[last] ?? 0) + (length[last] ?? 0)).trim();
    const original = originalText(tokens, start[w] ?? 0, end[last] ?? 0);
    if (original !== now) out.push({ turn: turn[w] ?? 0, first: w, last, original, now });
    w = last + 1;
  }
  return out;
}
```

- [ ] **Step 6: Run it to see it pass**

Run: `cd ui && npx vitest run tests/unit/corrections.test.ts`
Expected: PASS, 3 tests.

- [ ] **Step 7: Write `ui/src/features/transcript/speakers.ts`**

```ts
// Who a speaker is on the page: their name and their colour (Hashiya spec,
// "a fixed nameplate and colour per speaker"). The colour follows the
// speaker's place in the transcript's list, so speaker 1 is the same blue in
// every turn and every page; sub-project D later ties it to a person.

import { speakerName } from "./document";

/** Names a person gave the speakers, by label (Task 5 saves them in the edit list). */
export type Names = Readonly<Record<string, string>>;

export const NO_NAMES: Names = Object.freeze({});

/** `var(--speaker-n)` for the speaker at `index`, cycling through the six. */
export function speakerColour(index: number | null): string | undefined {
  return index === null || index < 0 ? undefined : `var(--speaker-${(index % 6) + 1})`;
}

/** The name a person gave the speaker, else "Speaker n" for a diarizer's label, else the label. */
export function displayName(speakers: readonly string[], names: Names, index: number | null): string | null {
  if (index === null) return null;
  const label = speakers[index];
  if (label === undefined) return null;
  return names[label] ?? speakerName([...speakers], index);
}
```

- [ ] **Step 8: Rewrite `ui/src/features/transcript/TranscriptView.tsx`**

```tsx
import { type CSSProperties, memo, type ReactNode, type Ref } from "react";

import type { Correction } from "@/features/edit/corrections";
import { durationLabel } from "@/features/library/describe";
import { langOf } from "@/lib/script";
import type { Reading } from "./document";
import { displayName, type Names, NO_NAMES, speakerColour } from "./speakers";
import "./transcript.css";

// A minute of speech fills the margin's tick; a longer turn stops there.
const TICK_FULL_S = 60;
const NONE: readonly Correction[] = [];

type Props = {
  reading: Reading;
  articleRef?: Ref<HTMLElement>;
  /** Corrected stretches, shown struck through in the margin beside their turn. */
  corrections?: readonly Correction[];
  names?: Names;
  /** Draws a speaker's nameplate; the reader passes a renamable one (Task 5). */
  nameplate?: (speaker: number, label: string, name: string) => ReactNode;
};

/**
 * One list item per speaker turn: the margin (who, when, how long, what was
 * corrected) and one `<p>` holding one plain text node, with no element per
 * word (#58). 21,847 words drawn whole scroll at the display's own pace (#57
 * section 7), and plain text keeps Cmd+F, drag-select and copy native. The
 * playhead and every later mark paint over this text with the CSS Custom
 * Highlight API, which adds no elements either (#60).
 *
 * Turns are list items under the page's one heading, not 238 headings
 * (critique: "56 level-2 headings"). Memoised: nothing that changes while it
 * plays may re-render this.
 */
export const TranscriptView = memo(function TranscriptView({
  reading,
  articleRef,
  corrections = NONE,
  names = NO_NAMES,
  nameplate,
}: Props) {
  const byTurn = new Map<number, Correction[]>();
  for (const c of corrections) byTurn.set(c.turn, [...(byTurn.get(c.turn) ?? []), c]);
  const { end } = reading.words;
  return (
    <article ref={articleRef} className="transcript" aria-label="Transcript">
      <ol className="turns">
        {reading.turns.map((turn, i) => {
          const name = displayName(reading.speakers, names, turn.speaker);
          const label = turn.speaker === null ? undefined : reading.speakers[turn.speaker];
          const seconds = Math.max(0, (end[turn.first + turn.count - 1] ?? turn.start) - turn.start);
          const style = {
            "--speaker": speakerColour(turn.speaker),
            "--tick": `${Math.min(100, (seconds / TICK_FULL_S) * 100)}%`,
          } as CSSProperties;
          return (
            <li key={i} className="turn" style={style}>
              <div className="margin" data-margin>
                {name !== null &&
                  label !== undefined &&
                  turn.speaker !== null &&
                  (nameplate ? nameplate(turn.speaker, label, name) : <span className="nameplate">{name}</span>)}
                <time dateTime={`PT${turn.start.toFixed(2)}S`}>{durationLabel(turn.start)}</time>
                <span className="tick" aria-hidden />
                {byTurn.get(i)?.map((c) => (
                  <span key={c.first} className="correction" dir="auto">
                    <span className="sr-only">Was: </span>
                    <del>{c.original === "" ? "nothing" : c.original}</del>
                  </span>
                ))}
              </div>
              <p data-turn={i} dir="auto" lang={langOf(turn.text)}>
                {turn.text}
              </p>
            </li>
          );
        })}
      </ol>
    </article>
  );
});
```

- [ ] **Step 9: Lay out the margin in `ui/src/features/transcript/transcript.css`**

Replace the `.transcript` rule's `max-width: 68ch;` line with nothing (the measure moves to the column), and replace the `.transcript section + section` and `.transcript h2` rules with:

```css
.transcript .turns {
  list-style: none;
  margin: 0;
  padding: 0;
}

/* The margin (Hashiya spec, "Signature move: the margin"): who and when, on
   the left for Urdu and English turns alike, so the eye finds them in one
   place. The grid runs left to right whatever the paragraph's direction; the
   paragraph sets its own. The text column is the 68 character measure. */
.transcript .turn {
  display: grid;
  grid-template-columns: 9.5rem minmax(0, 68ch);
  column-gap: 1.75rem;
  direction: ltr;
}

.transcript .turn + .turn {
  margin-top: 1.4em;
}

.transcript .margin {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.3rem;
  min-width: 0;
  padding-top: 0.45em;
  font: 500 0.8125rem/1.35 var(--font-sans);
  color: var(--muted-foreground);
  font-variant-numeric: tabular-nums;
}

.transcript .nameplate {
  max-width: 100%;
  color: var(--speaker, var(--muted-foreground));
  font-weight: 650;
  overflow-wrap: anywhere;
}

/* How long the turn lasted, to scale: a minute fills the margin. */
.transcript .tick {
  display: block;
  height: 3px;
  border-radius: 2px;
  inline-size: max(3px, var(--tick, 0%));
  background: var(--speaker, var(--muted-foreground));
  opacity: 0.55;
}

.transcript .correction {
  max-width: 100%;
  font: 400 0.875rem/1.4 var(--font-reading);
  overflow-wrap: anywhere;
}

.transcript .correction del {
  color: var(--correction);
  text-decoration-thickness: 1.5px;
}

/* The phone: the margin folds into one slim line above the turn. */
@media (max-width: 767px) {
  .transcript .turn {
    grid-template-columns: minmax(0, 1fr);
  }

  .transcript .margin {
    flex-flow: row wrap;
    align-items: center;
    gap: 0.25rem 0.75rem;
    padding: 0 0 0.2rem;
  }

  .transcript .tick {
    inline-size: calc(max(3px, var(--tick, 0%)) * 0.6);
  }
}
```

Add after the `::highlight(dsj-muted)` rule:

```css
/* Words a person corrected (#83): a thin red underline, the margin's red. */
::highlight(dsj-corrected) {
  text-decoration-line: underline;
  text-decoration-color: light-dark(#b8402a, #e5806a);
  text-decoration-thickness: 1.5px;
  text-underline-offset: 0.3em;
}
```

- [ ] **Step 10: Write the key lists and the key sheet**

`ui/src/features/shell/keys.ts`:

```ts
// Every key the app answers, in one place per page, for the sheet behind `?`
// (Hashiya spec: "No help paragraphs in the page: one key sheet behind ?").

import { HISTORY_LIMIT } from "@/lib/editOps";

export type Key = { keys: string[]; does: string };
export type Sheet = { title: string; keys: readonly Key[]; notes: readonly string[] };

export const READER_SHEET: Sheet = {
  title: "Keys in the reader",
  keys: [
    { keys: ["Space"], does: "Play or pause" },
    { keys: ["]"], does: "Next unsure word" },
    { keys: ["["], does: "Previous unsure word" },
    { keys: ["⌘", "Z"], does: "Undo the last edit" },
    { keys: ["⇧", "⌘", "Z"], does: "Redo" },
    { keys: ["Esc"], does: "Let go of the selection" },
    { keys: ["?"], does: "This sheet" },
  ],
  notes: [
    "Select words to correct, hear, re-time or mute them. On a phone, tap a word.",
    `Edits are saved as you make them. Undo goes back up to ${HISTORY_LIMIT.toLocaleString("en")} steps while this page is open; closing or reloading it keeps the edits and forgets their undo.`,
  ],
};
```

`ui/src/features/shell/KeySheet.tsx`:

```tsx
import { useSyncExternalStore } from "react";

import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DropdownMenuItem, DropdownMenuSeparator } from "@/components/ui/dropdown-menu";
import { Kbd } from "@/components/ui/kbd";
import type { Sheet } from "./keys";

// The sheet on show, if any: module state, as the error dialog's is, so the
// `?` key, Ctrl+/ in Review and the settings menu all open the one sheet.
let shown: Sheet | null = null;
const listeners = new Set<() => void>();

function emit(): void {
  for (const listener of listeners) listener();
}

export function showKeys(sheet: Sheet): void {
  shown = sheet;
  emit();
}

export function hideKeys(): void {
  shown = null;
  emit();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The key sheet, mounted once by App. */
export function KeySheet() {
  const sheet = useSyncExternalStore(subscribe, () => shown);
  if (sheet === null) return null;
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) hideKeys();
      }}
    >
      <DialogContent className="sm:max-w-lg" aria-label="Keys">
        <DialogHeader>
          <DialogTitle>{sheet.title}</DialogTitle>
          <DialogDescription className="sr-only">Every key this page answers.</DialogDescription>
        </DialogHeader>
        <table className="w-full text-sm">
          <tbody>
            {sheet.keys.map((key) => (
              <tr key={key.does} className="border-b border-border/60 last:border-0">
                <td className="py-1.5 pr-4 whitespace-nowrap">
                  {key.keys.map((k) => (
                    <Kbd key={k} className="mr-1">
                      {k}
                    </Kbd>
                  ))}
                </td>
                <td className="py-1.5">{key.does}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {sheet.notes.map((note) => (
          <p key={note} className="text-sm text-muted-foreground">
            {note}
          </p>
        ))}
      </DialogContent>
    </Dialog>
  );
}

/** "Keys" in the settings menu, for the page's own sheet. */
export function KeysItem({ sheet }: { sheet: Sheet }) {
  return (
    <>
      <DropdownMenuSeparator />
      <DropdownMenuItem onClick={() => showKeys(sheet)}>
        Keys
        <Kbd className="ml-auto">?</Kbd>
      </DropdownMenuItem>
    </>
  );
}
```

In `ui/src/App.tsx`, import `KeySheet` from `@/features/shell/KeySheet` and render `<KeySheet />` beside `<ShownErrorDialog />`.

- [ ] **Step 11: Write `ui/src/features/transcript/readerKeys.ts`**

```ts
// The reader's keys (Hashiya spec; critique, Alex: "undo/redo only; Space
// scrolls"): Space plays or pauses, `?` opens the key sheet, Esc lets go of
// the selection. By `event.code` where a printed key could differ: with the
// Urdu input source the key labelled "/" types something else, and the
// sheet must still open.

import { type RefObject, useEffect } from "react";

import type { PlayerControls } from "@/features/player/Player";
import { showKeys } from "@/features/shell/KeySheet";
import type { Sheet } from "@/features/shell/keys";

// Where a key is someone else's: typing, a button's own Space, a slider's arrows, an open menu or dialog.
export const NOT_OURS = "input, textarea, select, button, a, [contenteditable], [role=slider], [role=menu], [role=dialog], [role=listbox]";

export function isOurs(event: KeyboardEvent): boolean {
  if (event.metaKey || event.ctrlKey || event.altKey || event.isComposing) return false;
  return !(event.target as Element | null)?.closest?.(NOT_OURS);
}

export function useReaderKeys(controls: RefObject<PlayerControls | null>, sheet: Sheet): void {
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (!isOurs(event)) return;
      if (event.code === "Space") {
        event.preventDefault();
        controls.current?.toggle();
      } else if (event.code === "Slash" && event.shiftKey) {
        event.preventDefault();
        showKeys(sheet);
      } else if (event.key === "Escape") {
        window.getSelection()?.removeAllRanges();
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [controls, sheet]);
}
```

In `ui/src/features/player/Player.tsx`, Space no longer scrolls the reader, so it no longer stops the follow: change `SCROLL_KEYS` to `new Set(["PageUp", "PageDown", "ArrowUp", "ArrowDown", "Home", "End"])` and update its comment to say Space plays and pauses instead (readerKeys.ts).

- [ ] **Step 12: Write `ui/src/features/edit/SelectionToolbar.tsx`**

```tsx
import { type CSSProperties, type RefObject, useEffect, useState } from "react";
import { createPortal } from "react-dom";

import { Button } from "@/components/ui/button";
import type { PlayerControls } from "@/features/player/Player";
import { type Content, type Editor, muteRange } from "@/lib/editOps";
import { TOUCH, useMediaQuery } from "@/lib/media";
import { cn } from "@/lib/utils";
import type { EditReading } from "./readContent";
import type { Selected } from "./selection";

/** A box on screen, in viewport pixels. */
export type Box = { top: number; left: number; bottom: number; right: number; width: number; height: number };

/** `range`'s box. jsdom lays nothing out and has no Range.getBoundingClientRect, so it gets an empty box. */
export function boxOf(range: Range): Box {
  if (typeof range.getBoundingClientRect !== "function") return { top: 0, left: 0, bottom: 0, right: 0, width: 0, height: 0 };
  const r = range.getBoundingClientRect();
  return { top: r.top, left: r.left, bottom: r.bottom, right: r.right, width: r.width, height: r.height };
}

/** What Correct needs, read off the selection the moment it is pressed. */
export type Picked = {
  /** The words' entries in the edit list, [start, stop). */
  start: number;
  stop: number;
  /** Where they start and end in the recording, in seconds. */
  from: number;
  to: number;
  box: Box;
  paragraph: HTMLElement;
};

// A press on a button that acts on the selection must not clear it first.
function keepSelection(event: { preventDefault: () => void }): void {
  event.preventDefault();
}

const HEIGHT_PX = 44;
const WIDTH_PX = 300;

/** Above the selection, or below it when the bar is in the way, never off the window's sides. */
function besideSelection(box: Box): CSSProperties {
  const bar = Number.parseFloat(document.documentElement.style.getPropertyValue("--dsj-bar-height")) || 0;
  const above = box.top - HEIGHT_PX - 8;
  const top = above < bar + 4 ? box.bottom + 8 : above;
  const left = Math.min(Math.max(8, box.left + box.width / 2 - WIDTH_PX / 2), window.innerWidth - WIDTH_PX - 8);
  return { top, left };
}

type Props = {
  editor: Editor;
  content: Content;
  edit: EditReading;
  selected: Selected | null;
  controls: RefObject<PlayerControls | null>;
  onCorrect: (picked: Picked) => void;
  /** Open the timing strip for one word (#85). */
  onTiming: (word: number) => void;
};

/**
 * The tools for the words selected, beside them (Hashiya spec, Reader:
 * "Correct, Hear, Timing, Mute"), and nowhere until something is selected.
 * On a touch screen it sits just above the player rail, in thumb reach, with
 * 44 px targets. The Correct and Timing logic is #83's and #85's, unchanged.
 */
export function SelectionToolbar({ editor, content, edit, selected, controls, onCorrect, onTiming }: Props) {
  const touch = useMediaQuery(TOUCH);
  const [box, setBox] = useState<Box | null>(null);
  useEffect(() => {
    if (selected === null) {
      setBox(null);
      return;
    }
    const place = () => {
      const selection = window.getSelection();
      setBox(selection !== null && selection.rangeCount > 0 ? boxOf(selection.getRangeAt(0)) : null);
    };
    place();
    window.addEventListener("scroll", place, { passive: true });
    window.addEventListener("resize", place);
    return () => {
      window.removeEventListener("scroll", place);
      window.removeEventListener("resize", place);
    };
  }, [selected]);
  if (selected === null || box === null) return null;

  const range = { start: edit.first[selected.first] ?? 0, stop: edit.stop[selected.last] ?? 0 };
  const words = selected.last - selected.first + 1;
  const { turn, start, end } = edit.reading.words;
  const from = start[selected.first] ?? 0;
  const to = end[selected.last] ?? from;
  // A correction stays inside one paragraph of the reader: one speaker's turn.
  const oneTurn = turn[selected.first] === turn[selected.last];
  let allMuted = true;
  for (let i = range.start; i < range.stop; i += 1) {
    const entry = content[i];
    if (entry?.kind === "item" && entry.text !== "" && !entry.muted) allMuted = false;
  }
  const tool = cn("shrink-0", touch ? "h-11 flex-1 px-2" : "h-9 px-3");

  const pick = (): Picked | null => {
    const selection = window.getSelection();
    if (selection === null || selection.rangeCount === 0) return null;
    const live = selection.getRangeAt(0);
    const paragraph = live.startContainer.parentElement?.closest<HTMLElement>("p[data-turn]");
    return paragraph ? { ...range, from, to, box: boxOf(live), paragraph } : null;
  };

  return createPortal(
    <div
      role="toolbar"
      aria-label="Selection"
      className={cn(
        "fixed z-40 flex items-center gap-1 rounded-xl border bg-popover p-1 text-popover-foreground shadow-lg shadow-black/15",
        touch ? "inset-x-2" : "",
      )}
      style={touch ? { bottom: "calc(var(--dsj-player-height, 0px) + 0.5rem)" } : besideSelection(box)}
    >
      <Button
        variant="ghost"
        className={tool}
        disabled={!oneTurn}
        onMouseDown={keepSelection}
        onClick={() => {
          const picked = pick();
          if (picked !== null) onCorrect(picked);
        }}
      >
        Correct
      </Button>
      <Button
        variant="ghost"
        className={tool}
        onMouseDown={keepSelection}
        onClick={() => controls.current?.hear(Math.max(0, from - 0.3), to + 0.3)}
      >
        Hear
      </Button>
      <Button
        variant="ghost"
        className={tool}
        disabled={words !== 1}
        onMouseDown={keepSelection}
        onClick={() => onTiming(selected.first)}
      >
        Timing
      </Button>
      <Button
        variant="ghost"
        className={tool}
        onMouseDown={keepSelection}
        onClick={() => editor.applyEdit(muteRange(content, range.start, range.stop, !allMuted))}
      >
        {allMuted ? "Unmute" : words > 1 ? `Mute ${words} words` : "Mute"}
      </Button>
      {!oneTurn && <span className="px-2 text-xs text-muted-foreground">Correct works inside one turn</span>}
    </div>,
    document.body,
  );
}
```

- [ ] **Step 13: Write `ui/src/features/edit/InlineCorrect.tsx`**

```tsx
import { type FormEvent, useState } from "react";
import { createPortal } from "react-dom";

import { Button } from "@/components/ui/button";
import { langOf } from "@/lib/script";
import type { Box } from "./SelectionToolbar";

type Props = {
  /** The words as they read now. */
  heard: string;
  /** The words' box when Correct was pressed, and the paragraph whose face the field takes. */
  box: Box;
  paragraph: HTMLElement;
  onSave: (text: string) => void;
  onCancel: () => void;
  onHear: () => void;
};

/**
 * Correct in place (Hashiya spec, Reader: "Correct (edits in place, no
 * modal)"; critique: "Correct is a modal, Timing inline"). A field laid over
 * the selected words in the paragraph's own face and size, with the words in
 * it, so retyping reads like typing on the page. The words keep the same
 * stretch of the recording (#83); an emptied field leaves it as audio with no
 * words. Enter saves, Esc cancels; Hear plays the stretch with 0.3 s either side.
 */
export function InlineCorrect({ heard, box, paragraph, onSave, onCancel, onHear }: Props) {
  const [text, setText] = useState(heard);
  const face = getComputedStyle(paragraph);
  const width = Math.min(Math.max(box.width + 64, 260), window.innerWidth - 16);
  const left = Math.min(Math.max(window.scrollX + 8, box.left + window.scrollX - 8), window.scrollX + window.innerWidth - width - 8);
  const top = box.top + window.scrollY - 6;
  const unchanged = text.trim() === heard.trim();
  const save = (event: FormEvent) => {
    event.preventDefault();
    if (unchanged) onCancel();
    else onSave(text);
  };
  return createPortal(
    <form
      aria-label="Correct"
      className="absolute z-40 flex flex-col gap-1.5 rounded-lg border-2 border-gold-ink bg-card p-1.5 text-card-foreground shadow-lg shadow-black/15"
      style={{ top, left, width }}
      onSubmit={save}
    >
      <input
        aria-label="What was said"
        autoFocus
        dir="auto"
        lang={langOf(text)}
        value={text}
        spellCheck={false}
        onFocus={(event) => event.currentTarget.select()}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            onCancel();
          }
        }}
        className="w-full rounded-md bg-background px-2 py-1 text-foreground"
        style={{ fontFamily: face.fontFamily, fontSize: face.fontSize, lineHeight: face.lineHeight }}
      />
      <div className="flex items-center gap-1">
        <Button type="button" variant="ghost" size="sm" className="h-9" onClick={onHear}>
          Hear
        </Button>
        <span className="ml-1 hidden text-xs text-muted-foreground sm:inline">Enter saves · Esc cancels</span>
        <Button type="button" variant="ghost" size="sm" className="ml-auto h-9" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" size="sm" className="h-9" disabled={unchanged}>
          Save
        </Button>
      </div>
    </form>,
    document.body,
  );
}
```

- [ ] **Step 14: Write `ui/src/features/transcript/UnsureNav.tsx`**

```tsx
import { ChevronLeft, ChevronRight } from "lucide-react";
import { type RefObject, useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Toggle } from "@/components/ui/toggle";
import { cutoffFor, UNSURE, unsureHighlight, unsureWords } from "./confidence";
import type { Reading } from "./document";
import { isOurs } from "./readerKeys";

type Props = {
  reading: Reading;
  model: string;
  /** The transcript's <article>, whose paragraphs the tint paints. */
  article: RefObject<HTMLElement | null>;
};

/** Select word `word` and bring it to a third of the way down the window. */
function goTo(reading: Reading, root: HTMLElement, word: number): void {
  const { turn, offset, length } = reading.words;
  const text = root.querySelector(`p[data-turn="${turn[word] ?? -1}"]`)?.firstChild;
  if (!(text instanceof Text)) return;
  const from = offset[word] ?? 0;
  const to = from + (length[word] ?? 0);
  const lead = /^\s*/.exec(text.data.slice(from, to))?.[0].length ?? 0;
  const range = document.createRange();
  range.setStart(text, from + lead);
  range.setEnd(text, to);
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
  if (typeof range.getBoundingClientRect === "function") {
    const behavior = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
    window.scrollBy({ top: range.getBoundingClientRect().top - window.innerHeight * 0.35, behavior });
  }
}

/**
 * The unsure words (#62) as a count with previous and next (Hashiya spec,
 * Reader; critique: "158 unsure words with no next/previous"). The count
 * switches the tint; an arrow switches it on, selects the word, so the
 * selection toolbar offers Correct and Hear at once, and brings it into view.
 * `]` and `[` do the same from the keyboard.
 */
export function UnsureNav({ reading, model, article }: Props) {
  const [on, setOn] = useState(false);
  const at = useRef(-1);
  const highlight = useRef<Highlight | null>(null);
  const cutoff = cutoffFor(model);
  const words = useMemo(() => (cutoff === null ? [] : unsureWords(reading, cutoff)), [reading, cutoff]);

  useEffect(() => {
    highlight.current = null;
    at.current = -1;
    return () => {
      CSS.highlights.delete(UNSURE);
    };
  }, [reading]);

  useEffect(() => {
    const root = article.current;
    if (!on || root === null) {
      CSS.highlights.delete(UNSURE);
      return;
    }
    if (highlight.current === null) {
      const texts: Text[] = [];
      for (const p of root.querySelectorAll<HTMLElement>("p[data-turn]")) {
        if (p.firstChild instanceof Text) texts[Number(p.dataset["turn"])] = p.firstChild;
      }
      highlight.current = unsureHighlight(reading, words, texts);
    }
    CSS.highlights.set(UNSURE, highlight.current);
  }, [on, reading, words, article]);

  const go = (by: 1 | -1) => {
    const root = article.current;
    if (words.length === 0 || root === null) return;
    setOn(true);
    at.current = at.current < 0 ? (by > 0 ? 0 : words.length - 1) : (at.current + by + words.length) % words.length;
    goTo(reading, root, words[at.current] ?? 0);
  };
  const goRef = useRef(go);
  goRef.current = go;

  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (!isOurs(event)) return;
      if (event.code === "BracketRight") goRef.current(1);
      else if (event.code === "BracketLeft") goRef.current(-1);
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);

  if (cutoff === null || !reading.words.confidence.some((c) => !Number.isNaN(c))) return null;
  const quiet = "size-11 text-field-foreground hover:bg-white/10 hover:text-field-foreground";
  return (
    <div role="group" aria-label="Unsure words" className="flex items-center">
      <Toggle
        pressed={on}
        onPressedChange={setOn}
        className="h-11 px-3 text-field-foreground hover:bg-white/10 hover:text-field-foreground data-[pressed]:bg-white/15"
      >
        <span className="tabular-nums">{words.length}</span> unsure
      </Toggle>
      <Button variant="ghost" size="icon" aria-label="Previous unsure word" disabled={words.length === 0} className={quiet} onClick={() => go(-1)}>
        <ChevronLeft aria-hidden />
      </Button>
      <Button variant="ghost" size="icon" aria-label="Next unsure word" disabled={words.length === 0} className={quiet} onClick={() => go(1)}>
        <ChevronRight aria-hidden />
      </Button>
    </div>
  );
}
```

The toggle's accessible name is its visible text, "12 unsure" (WCAG 2.5.3, label in name).

- [ ] **Step 15: Write `ui/src/features/transcript/VersionPicker.tsx` and `versionLabel`**

Append to `ui/src/features/library/describe.ts`:

```ts
/** "2 Oct 2026, 18:05 · whisper": how the version picker tells one transcript of a recording from another. */
export function versionLabel(t: TranscriptRow): string {
  return `${whenLabel(t.finished_at)} · ${t.engine ?? "unknown engine"}`;
}
```

`ui/src/features/transcript/VersionPicker.tsx`:

```tsx
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { versionLabel } from "@/features/library/describe";
import type { RecordingRow } from "@/features/library/types";
import { transcriptHref } from "@/lib/route";

/** The recording's other transcripts, when it has more than one (Hashiya spec, Reader: "version picker"). */
export function VersionPicker({ recording, transcript }: { recording: RecordingRow; transcript: number }) {
  if (recording.transcripts.length < 2) return null;
  const items = recording.transcripts.map((t) => ({ value: t.id, label: versionLabel(t) }));
  return (
    <Select
      items={items}
      value={transcript}
      onValueChange={(picked) => {
        if (typeof picked === "number" && picked !== transcript) window.location.assign(transcriptHref(recording.id, picked));
      }}
    >
      <SelectTrigger aria-label="Version" className="h-11 max-w-60 border-white/20 bg-transparent text-field-foreground">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {items.map((item) => (
          <SelectItem key={item.value} value={item.value}>
            {item.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
```

- [ ] **Step 16: Slim `EditBar` and paint corrections in `ui/src/features/edit/EditBar.tsx`**

Keep `MUTED`, `turnTexts`, `mutedWords`, `useMutedPaint`, `useSelection`, `FIELDS`, `useUndoKeys` and `SAVE_TEXT` as they are. Delete `spanOf`, `keepSelection`, the old `Props` and the old `EditBar`, and the imports only they used (`CorrectDialog`, `correction`, `textOf`, `atLabel`, `muteRange`, `HISTORY_LIMIT`, `Selected`, `selectedWords` stays for `useSelection`). Add:

```tsx
import { Redo2, Undo2 } from "lucide-react";

import type { Reading } from "@/features/transcript/document";
import type { Correction } from "./corrections";

export const CORRECTED = "dsj-corrected";

/** Underline every corrected word (`::highlight(dsj-corrected)`), again after each change. */
export function useCorrectedPaint(reading: Reading, fixed: readonly Correction[], article: RefObject<HTMLElement | null>): void {
  useEffect(() => {
    const root = article.current;
    if (root === null) return;
    const words: number[] = [];
    for (const c of fixed) for (let w = c.first; w <= c.last; w += 1) words.push(w);
    const highlight = wordsHighlight(reading, words, turnTexts(root));
    CSS.highlights.set(CORRECTED, highlight);
    return () => {
      if (CSS.highlights.get(CORRECTED) === highlight) CSS.highlights.delete(CORRECTED);
    };
  }, [reading, fixed, article]);
}

/**
 * Undo, Redo and whether the edits are saved, in the bar where they are
 * always in reach. The tools for selected words are the Selection toolbar's.
 * "Saved" shows once there is something it is about (critique: "Saved shows
 * before any edit"); the status element is always there, so a screen reader
 * hears it change.
 */
export function EditBar({ editor, saving }: { editor: Editor; saving: SaveState }) {
  const undo = editor.undoLabel();
  const redo = editor.redoLabel();
  const said = saving !== "saved" || undo !== null || redo !== null;
  const quiet = "size-11 text-field-foreground hover:bg-white/10 hover:text-field-foreground";
  return (
    <div role="toolbar" aria-label="Edit" className="flex items-center">
      <Button variant="ghost" size="icon" aria-label="Undo" disabled={undo === null} className={quiet} onClick={() => editor.undo()}>
        <Undo2 aria-hidden />
      </Button>
      <Button variant="ghost" size="icon" aria-label="Redo" disabled={redo === null} className={quiet} onClick={() => editor.redo()}>
        <Redo2 aria-hidden />
      </Button>
      <span role="status" className="min-w-16 px-1 text-sm text-field-muted">
        {said ? SAVE_TEXT[saving] : ""}
      </span>
    </div>
  );
}
```

Delete `ui/src/features/edit/CorrectDialog.tsx` and `ui/src/features/transcript/UnsureToggle.tsx`.

- [ ] **Step 17: Rewrite `ui/src/features/transcript/TranscriptPage.tsx`**

```tsx
import { type ReactNode, type RefObject, useEffect, useMemo, useRef, useState } from "react";

import { api } from "@/api/client";
import { BleepPanel } from "@/features/bleep/BleepPanel";
import { correction, textOf } from "@/features/edit/correct";
import { type Correction, corrections, tokensOf } from "@/features/edit/corrections";
import { EditBar, useCorrectedPaint, useMutedPaint, useSelection, useUndoKeys } from "@/features/edit/EditBar";
import { type Editable, loadEditable, type Span, useContent, useLatest, useSave } from "@/features/edit/editing";
import { InlineCorrect } from "@/features/edit/InlineCorrect";
import { type EditReading, keepReading, readContent } from "@/features/edit/readContent";
import { type Picked, SelectionToolbar } from "@/features/edit/SelectionToolbar";
import { TimingStrip } from "@/features/edit/TimingStrip";
import { ApiError, fromBody, fromThrown, showError } from "@/features/errors/appError";
import { fileName } from "@/features/library/describe";
import type { RecordingRow } from "@/features/library/types";
import { Player, type PlayerControls } from "@/features/player/Player";
import { AppBar } from "@/features/shell/AppBar";
import { KeysItem } from "@/features/shell/KeySheet";
import { READER_SHEET } from "@/features/shell/keys";
import { parseTranscript, read, type Reading, type TranscriptDoc } from "./document";
import { useReaderKeys } from "./readerKeys";
import type { Names } from "./speakers";
import { TranscriptView } from "./TranscriptView";
import { UnsureNav } from "./UnsureNav";
import { VersionPicker } from "./VersionPicker";

export type Opened = {
  recording: RecordingRow;
  doc: TranscriptDoc;
  /** The edit list, or why this transcript has none (#66). */
  editable: Editable | { reason: string };
};
type Loaded = { state: "loading" } | { state: "failed" } | ({ state: "ready" } & Opened);

export async function openTranscript(recordingId: number, transcriptId: number): Promise<Opened> {
  const transcriptRoute = `/api/transcripts/${transcriptId}`;
  const [list, file, editable] = await Promise.all([
    api.GET("/api/recordings"),
    api.GET("/api/transcripts/{transcript_id}", {
      params: { path: { transcript_id: String(transcriptId) } },
    }),
    loadEditable(transcriptId),
  ]);
  if (list.data === undefined) {
    throw new ApiError(fromBody(list.error, list.response, "/api/recordings"));
  }
  if (file.data === undefined) {
    throw new ApiError(fromBody(file.error, file.response, transcriptRoute));
  }
  const recording = list.data.find((row) => row.id === recordingId);
  if (recording === undefined || !recording.transcripts.some((t) => t.id === transcriptId)) {
    throw new ApiError({
      error: "NotInLibrary",
      message: `The library has no transcript ${transcriptId} of recording ${recordingId}.`,
      request: transcriptRoute,
    });
  }
  return { recording, doc: parseTranscript(file.data), editable };
}

/** One transcript, opened from the library, to read (#58) and to edit (#66). */
export function TranscriptPage({ recording, transcript }: { recording: number; transcript: number }) {
  const [loaded, setLoaded] = useState<Loaded>({ state: "loading" });
  useEffect(() => {
    let live = true;
    openTranscript(recording, transcript).then(
      (opened) => {
        if (live) setLoaded({ state: "ready", ...opened });
      },
      (thrown: unknown) => {
        if (!live) return;
        setLoaded({ state: "failed" });
        showError(fromThrown(thrown, `/api/transcripts/${transcript}`));
      },
    );
    return () => {
      live = false;
    };
  }, [recording, transcript]);

  if (loaded.state !== "ready") {
    return (
      <>
        <AppBar back>
          <h1 className="min-w-0 flex-1 truncate font-reading text-lg font-semibold">Transcript</h1>
        </AppBar>
        {loaded.state === "failed" && (
          <main className="mx-auto w-full max-w-3xl px-3 py-6 sm:px-6">
            <p className="text-muted-foreground">This transcript could not be opened.</p>
          </main>
        )}
      </>
    );
  }
  return "editor" in loaded.editable ? (
    <EditablePage opened={loaded} editable={loaded.editable} transcriptId={transcript} />
  ) : (
    <ReadOnlyPage opened={loaded} reason={loaded.editable.reason} transcriptId={transcript} />
  );
}

function ReadOnlyPage({ opened, reason, transcriptId }: { opened: Opened; reason: string; transcriptId: number }) {
  const reading = useMemo(() => read(opened.doc), [opened.doc]);
  const article = useRef<HTMLElement>(null);
  const controls = useRef<PlayerControls | null>(null);
  useReaderKeys(controls, READER_SHEET);
  return (
    <Page opened={opened} transcriptId={transcriptId} reading={reading} article={article} controls={controls}>
      <p className="mb-6 text-sm text-muted-foreground" role="note">
        This transcript cannot be edited: {reason}
      </p>
    </Page>
  );
}

function EditablePage({ opened, editable, transcriptId }: { opened: Opened; editable: Editable; transcriptId: number }) {
  const { editor } = editable;
  const content = useContent(editor);
  const previous = useRef<EditReading | null>(null);
  const edit = useMemo(() => {
    const next = keepReading(previous.current, readContent(content, opened.doc.speakers));
    previous.current = next;
    return next;
  }, [content, opened.doc.speakers]);
  const article = useRef<HTMLElement>(null);
  const saving = useSave(transcriptId, editable);
  const selected = useSelection(edit, article);
  const renderable = useLatest(editable.renderable);
  const controls = useRef<PlayerControls | null>(null);
  // The word whose edges are being dragged (#85), while the strip is open.
  const [timing, setTiming] = useState<number | null>(null);
  // The words being retyped in place (#83), while the field is open.
  const [correcting, setCorrecting] = useState<Picked | null>(null);
  const tokens = useMemo(() => tokensOf(opened.doc), [opened.doc]);
  const fixed = useMemo(() => corrections(edit.reading, tokens), [edit.reading, tokens]);
  useUndoKeys(editor);
  useMutedPaint(edit, content, article);
  useCorrectedPaint(edit.reading, fixed, article);
  useReaderKeys(controls, READER_SHEET);
  return (
    <Page
      opened={opened}
      transcriptId={transcriptId}
      reading={edit.reading}
      article={article}
      muteSpans={renderable.spans}
      controls={controls}
      corrections={fixed}
      selectOnTap
      tools={<EditBar editor={editor} saving={saving} />}
    >
      <SelectionToolbar
        editor={editor}
        content={content}
        edit={edit}
        selected={correcting === null ? selected : null}
        controls={controls}
        onCorrect={setCorrecting}
        onTiming={setTiming}
      />
      {correcting !== null && (
        <InlineCorrect
          heard={textOf(content, correcting.start, correcting.stop)}
          box={correcting.box}
          paragraph={correcting.paragraph}
          onHear={() => controls.current?.hear(Math.max(0, correcting.from - 0.3), correcting.to + 0.3)}
          onCancel={() => setCorrecting(null)}
          onSave={(text) => {
            editor.applyEdit(correction(content, correcting.start, correcting.stop, text));
            setCorrecting(null);
            window.getSelection()?.removeAllRanges();
          }}
        />
      )}
      {timing !== null && timing < edit.first.length && (
        <TimingStrip
          editor={editor}
          content={content}
          edit={edit}
          word={timing}
          recordingId={opened.recording.id}
          controls={controls}
          onClose={() => setTiming(null)}
        />
      )}
      <BleepPanel
        transcriptId={transcriptId}
        editor={editor}
        content={content}
        edit={edit}
        renderable={renderable}
        padS={editable.padS}
        controls={controls}
      />
    </Page>
  );
}

type PageProps = {
  opened: Opened;
  transcriptId: number;
  reading: Reading;
  article: RefObject<HTMLElement | null>;
  children?: ReactNode;
  /** In the bar, after the unsure count: the Edit toolbar, and later Review and the menu. */
  tools?: ReactNode;
  muteSpans?: readonly Span[] | null;
  controls?: RefObject<PlayerControls | null>;
  corrections?: readonly Correction[];
  names?: Names;
  nameplate?: (speaker: number, label: string, name: string) => ReactNode;
  selectOnTap?: boolean;
};

function Page({ opened, transcriptId, reading, article, children, tools, muteSpans, controls, corrections: fixed, names, nameplate, selectOnTap = false }: PageProps) {
  const { recording, doc } = opened;
  return (
    <>
      <AppBar back settings={<KeysItem sheet={READER_SHEET} />}>
        <h1 className="min-w-0 flex-1 truncate font-reading text-lg font-semibold">{fileName(recording.path)}</h1>
        <VersionPicker recording={recording} transcript={transcriptId} />
        <UnsureNav reading={reading} model={doc.model} article={article} />
        {tools}
      </AppBar>
      <main className="mx-auto w-full max-w-5xl flex-1 px-3 pt-6 pb-10 sm:px-6">
        {children}
        <TranscriptView
          reading={reading}
          articleRef={article}
          {...(fixed === undefined ? {} : { corrections: fixed })}
          {...(names === undefined ? {} : { names })}
          {...(nameplate === undefined ? {} : { nameplate })}
        />
      </main>
      {recording.missing ? (
        <p className="sticky bottom-0 bg-field px-4 py-3 text-sm text-field-foreground">
          The recording is not where it was last seen, so this transcript cannot play. Last seen at{" "}
          <span className="font-mono break-all">{recording.path}</span>
        </p>
      ) : (
        <Player
          recording={recording}
          reading={reading}
          article={article}
          muteSpans={muteSpans ?? null}
          selectOnTap={selectOnTap}
          {...(controls === undefined ? {} : { controls })}
        />
      )}
    </>
  );
}
```

- [ ] **Step 18: Write the failing reader test**

Create `ui/tests/unit/reader.test.tsx` (its fetch harness is `correction.test.tsx`'s, with two speakers):

```tsx
// The reader in the Hashiya world: turns as list items with a margin, tools on
// selection, Correct in place, and the corrected words shown struck through.
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fetchMock = vi.hoisted(() => {
  const mock = vi.fn<(request: Request) => Promise<Response>>();
  globalThis.fetch = mock as unknown as typeof fetch;
  return mock;
});

import { dismissError } from "../../src/features/errors/appError";
import { takeToken } from "../../src/features/session/session";
import { TranscriptPage } from "../../src/features/transcript/TranscriptPage";
import type { Content, Entry, Item } from "../../src/lib/editOps";
import { installHighlights } from "./highlights";
import { stubMatchMedia } from "./media";

function item(sourceStart: number, length: number, text: string, confidence: number | null = 0.95): Item {
  return { kind: "item", source: "0", sourceStart, length, text, muted: false, confidence };
}
const para = (speaker: string): Entry => ({ kind: "paragraph", speaker, language: null });

const CONTENT: Content = [
  para("SPEAKER_00"),
  item(0, 0.2, "", null),
  item(0.2, 0.3, " alpha"),
  item(0.6, 0.3, " bravo"),
  item(1.0, 0.3, " charlie", 0.3),
  para("SPEAKER_01"),
  item(2.0, 0.4, " delta"),
];
const DOC = {
  audio: "/rec/a.wav",
  model: "mlx-community/parakeet-tdt-0.6b-v3",
  speakers: ["SPEAKER_00", "SPEAKER_01"],
  sentences: [
    { start: 0.2, end: 1.3, speaker: 0, text: " alpha bravo charlie", tokens: [
      { t: 0.2, w: " alpha", e: 0.5, c: 0.95 }, { t: 0.6, w: " bravo", e: 0.9, c: 0.95 }, { t: 1.0, w: " charlie", e: 1.3, c: 0.3 },
    ] },
    { start: 2.0, end: 2.4, speaker: 1, text: " delta", tokens: [{ t: 2.0, w: " delta", e: 2.4, c: 0.95 }] },
  ],
};

let saved: Content[] = [];

beforeEach(() => {
  installHighlights();
  stubMatchMedia();
  window.history.replaceState(null, "", "/?recording=2&transcript=7#t=a-token");
  takeToken();
  saved = [];
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (request: Request) => {
    const path = new URL(request.url).pathname;
    if (path === "/api/recordings") {
      return Response.json([{
        id: 2, path: "/rec/a.wav", size_bytes: 1, duration_s: 3, content_id: "c", audio_codec: "pcm",
        video_codec: null, first_seen: "x", missing: false, unreadable: null,
        transcripts: [{ id: 7, finished_at: "x", engine: "parakeet", model: "parakeet", diarized: true, speaker_count: 2, mark_count: null, language: null, last_edited_at: null }],
      }]);
    }
    if (path === "/api/transcripts/7") return Response.json(DOC);
    if (path === "/api/transcripts/7/edits") {
      const content = request.method === "PUT" ? ((await request.json()) as { content: Content }).content : CONTENT;
      if (request.method === "PUT") saved.push(content);
      return Response.json({ content, pad_s: 0.1, edited_at: null, spans: [], unrenderable: null });
    }
    if (path === "/api/transcripts/7/matches") return Response.json({ matches: [], words_searched: 4, lists: ["en"], recall: "recall: x" });
    if (path === "/api/recording/2/waveform") return new Response(new Int8Array([-3, 3]));
    return Response.json({ detail: "Not Found" }, { status: 404 });
  });
});

afterEach(() => {
  cleanup();
  act(() => dismissError());
});

function select(word: string): void {
  const p = Array.from(document.querySelectorAll("article p")).find((x) => x.textContent?.includes(word)) as HTMLElement;
  const text = p.firstChild as Text;
  const range = document.createRange();
  range.setStart(text, text.data.indexOf(word));
  range.setEnd(text, text.data.indexOf(word) + word.length);
  window.getSelection()?.removeAllRanges();
  window.getSelection()?.addRange(range);
  document.dispatchEvent(new Event("selectionchange"));
}

describe("the reader", () => {
  it("draws each turn as a list item with its speaker, time and duration in the margin, under one heading", async () => {
    render(<TranscriptPage recording={2} transcript={7} />);
    const article = await screen.findByRole("article", { name: "Transcript" });
    const turns = within(article).getAllByRole("listitem");
    expect(turns).toHaveLength(2);
    expect(within(turns[0] as HTMLElement).getByText("Speaker 1")).toBeTruthy();
    expect(within(turns[1] as HTMLElement).getByText("0:02")).toBeTruthy();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(article.querySelectorAll("h2")).toHaveLength(0);
    // The words are still one text node a paragraph (#58).
    expect(article.querySelectorAll("p *")).toHaveLength(0);
  });

  it("shows the tools for a selection only while there is one", async () => {
    render(<TranscriptPage recording={2} transcript={7} />);
    await screen.findByRole("toolbar", { name: "Edit" });
    expect(screen.queryByRole("toolbar", { name: "Selection" })).toBeNull();
    act(() => select("bravo"));
    const tools = await screen.findByRole("toolbar", { name: "Selection" });
    for (const name of ["Correct", "Hear", "Timing", "Mute"]) expect(within(tools).getByRole("button", { name })).toBeTruthy();
  });

  it("corrects in place, saves it, and strikes the original through in the margin", async () => {
    render(<TranscriptPage recording={2} transcript={7} />);
    await screen.findByRole("toolbar", { name: "Edit" });
    act(() => select("charlie"));
    const correct = within(await screen.findByRole("toolbar", { name: "Selection" })).getByRole("button", { name: "Correct" });
    fireEvent.click(correct);
    const field = (await screen.findByRole("textbox", { name: "What was said" })) as HTMLInputElement;
    expect(field.value).toBe("charlie");
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.change(field, { target: { value: "Charles Darwin" } });
    fireEvent.submit(field.form as HTMLFormElement);
    await vi.waitFor(() => expect(document.querySelector("article p")?.textContent).toBe(" alpha bravo Charles Darwin"));
    await vi.waitFor(() => expect(saved).toHaveLength(1));
    const margin = document.querySelector("article li [data-margin]") as HTMLElement;
    expect(margin.querySelector("del")?.textContent).toBe("charlie");
  });

  it("opens the key sheet with ?, and it says the undo history does not outlive the page", async () => {
    render(<TranscriptPage recording={2} transcript={7} />);
    await screen.findByRole("toolbar", { name: "Edit" });
    act(() => fireEvent.keyDown(window, { key: "?", code: "Slash", shiftKey: true }));
    // KeySheet is App's; this page only asks for it, so the request is read back here.
    const { KeySheet } = await import("../../src/features/shell/KeySheet");
    render(<KeySheet />);
    expect((await screen.findByRole("dialog")).textContent).toContain("forgets their undo");
  });
});
```

- [ ] **Step 19: Run it**

Run: `cd ui && npx vitest run tests/unit/reader.test.tsx tests/unit/corrections.test.ts`
Expected: PASS. If the Selection toolbar does not appear in the second test, check that `useSelection`'s `selectionchange` listener fired (the test dispatches it) before changing any code.

- [ ] **Step 20: Move the old tests to the new reader**

| File | Was | Now |
|---|---|---|
| `ui/tests/unit/correction.test.tsx` | `describe("the Correct button")`: button `Correct…`, then a dialog | `within(screen.getByRole("toolbar", { name: "Selection" })).getByRole("button", { name: "Correct" })`; the field `What was said` and button `Save` keep their names; no dialog |
| `ui/tests/unit/confidence.test.tsx` | renders `UnsureToggle`; button `Unsure words (2)` | renders `UnsureNav` (import from `UnsureNav`); button `2 unsure`; and `Next unsure word` selects the first unsure word |
| `ui/tests/unit/edit.test.tsx` | Mute, Unmute, Correct…, Timing… in toolbar `Edit`; help text in the bar | Mute and Unmute in toolbar `Selection` (Unmute shows when every selected word is muted); Undo, Redo and status stay in toolbar `Edit`; the "says that edits are kept" test opens the sheet as `reader.test.tsx` does and reads "forgets their undo" there |
| `ui/tests/unit/transcript.test.tsx` | heading named `review.m4a`; paragraphs under `section` | heading level 1 named `review.m4a`; turns are `listitem`s; `getByRole("note")` unchanged |
| `ui/tests/e2e/reader.spec.ts` | `article.locator("h2")` texts `Speaker 1 · 0:00` | `article.locator(".nameplate")` texts `["Speaker 1", "Speaker 2", "Speaker 1"]` and `article.locator("[data-margin] time")` texts `["0:00", "0:03", "0:08"]`; the measure probe is appended to `p.parentElement` and compared with `p.getBoundingClientRect().width` instead of the article's `max-width` |
| `ui/tests/e2e/correction.spec.ts` | `Unsure words (1)` / `(0)`; `Correct…`; `Save` | `1 unsure` / `0 unsure`; Selection toolbar `Correct`; `Save`; `Edit` toolbar status still `Saved` |
| `ui/tests/e2e/edit.spec.ts` | `bar.getByRole("button", { name: "Mute", exact: true })`; `toContainText("keeps the edits and forgets their undo")` | `page.getByRole("toolbar", { name: "Selection" }).getByRole("button", { name: "Mute", exact: true })`; after the reload, `await page.keyboard.press("Shift+Slash")` and `await expect(page.getByRole("dialog")).toContainText("forgets their undo")` |
| `ui/tests/e2e/bounds.spec.ts` | `button "Timing…"` | `page.getByRole("toolbar", { name: "Selection" }).getByRole("button", { name: "Timing" })` |
| `ui/tests/e2e/find.spec.ts`, `ui/tests/e2e/follow.spec.ts` | any selector on `h2` or `section` | the same text through `[data-margin]`; run them and change only what fails |
| `ui/tests/perf/reader.spec.ts` | toolbar `Edit` button `/^Mute( \d+ words)?$/`; toggle `/^Unsure words/` with text `Unsure words (N)` | toolbar `Selection` button `/^Mute( \d+ words)?$/`; toggle `/ unsure$/` with text `N unsure` |

- [ ] **Step 21: Gate, build, browser tests**

Run: `uv run just check` (paste the last line), `uv run just ui-build`, then `cd ui && npx playwright test tests/e2e --project chromium` and `--project webkit`.
Expected: all pass in both.

- [ ] **Step 22: Look at it**

Run: `uv run python scratch/ui_shots.py --label t3 reader reader-urdu reader-english`
Expected: 12 PNGs. Check: the margin sits left of every turn in all three languages, nameplates in their speaker colours, times tabular, ticks to scale; the Urdu text column hugs its right edge; the first words appear in the first screen on 390x844 (critique: "no words on the first phone screen"); at 390 the margin is one line above each turn; the bar wraps without clipping a target.

- [ ] **Step 23: Commit**

```bash
git add ui/src/features/transcript/speakers.ts ui/src/features/edit/corrections.ts \
  ui/src/features/edit/SelectionToolbar.tsx ui/src/features/edit/InlineCorrect.tsx \
  ui/src/features/transcript/UnsureNav.tsx ui/src/features/transcript/VersionPicker.tsx \
  ui/src/features/transcript/readerKeys.ts ui/src/features/shell/keys.ts ui/src/features/shell/KeySheet.tsx \
  ui/src/components/ui/kbd.tsx ui/src/features/transcript/TranscriptView.tsx \
  ui/src/features/transcript/transcript.css ui/src/features/transcript/TranscriptPage.tsx \
  ui/src/features/edit/EditBar.tsx ui/src/features/library/describe.ts ui/src/features/player/Player.tsx \
  ui/src/App.tsx ui/tests/unit/corrections.test.ts ui/tests/unit/reader.test.tsx \
  ui/tests/unit/correction.test.tsx ui/tests/unit/confidence.test.tsx ui/tests/unit/edit.test.tsx \
  ui/tests/unit/transcript.test.tsx ui/tests/e2e/reader.spec.ts ui/tests/e2e/correction.spec.ts \
  ui/tests/e2e/edit.spec.ts ui/tests/e2e/bounds.spec.ts ui/tests/e2e/find.spec.ts \
  ui/tests/e2e/follow.spec.ts ui/tests/perf/reader.spec.ts
git rm ui/src/features/edit/CorrectDialog.tsx ui/src/features/transcript/UnsureToggle.tsx
git add -A -- dsj/ui/static/
git commit -m "feat(ui): reader margin, selection toolbar and Correct in place"
```

---

### Task 4: The reader's menu, the bleep drawer, the timing dock

**Files:**
- Create (shadcn): `ui/src/components/ui/sheet.tsx`
- Create: `ui/src/features/bleep/useMatches.ts`, `ui/src/features/bleep/BleepDrawer.tsx`, `ui/src/features/transcript/MoreMenu.tsx`
- Modify: `ui/src/features/bleep/BleepPanel.tsx` (matches and the render job come in as props; no outer card), `ui/src/features/transcript/TranscriptPage.tsx` (`EditablePage`), `ui/src/features/edit/TimingStrip.tsx` (its `section` styling)
- Test: `ui/tests/unit/menu.test.tsx` (new), `ui/tests/unit/bleep.test.tsx`, `ui/tests/unit/render.test.tsx`, `ui/tests/e2e/bleep.spec.ts`, `ui/tests/e2e/render.spec.ts`, `ui/tests/e2e/editable.ts`

**Interfaces:**
- Consumes: Task 3's `Page` `tools` slot, `SelectionToolbar`'s `onTiming`, `useSelection`; Task 2's `useMediaQuery`, `TOUCH`.
- Produces:
  - `useMatches(transcriptId: number, editor: Editor, reading: Reading): MatchesState`, `type MatchesState = { found: Matches | null; setFound: (next: Matches) => void; again: () => void }`.
  - `BleepPanel` props gain `matches: MatchesState`, `started: RenderJob | null`, `onStarted: (job: RenderJob) => void`.
  - `BleepDrawer({ open, onOpenChange, children })`.
  - `MoreMenu({ matchCount: number; onBleep: () => void; timingWord: number | null; onTiming: (word: number) => void; extra?: ReactNode })` (Task 6 passes Export through `extra`).
  - e2e helper `openBleep(page: Page): Promise<Locator>` in `ui/tests/e2e/editable.ts`, returning the "Words to bleep" region.

- [ ] **Step 1: Load impeccable: read /Users/moiz/.claude/skills/impeccable/reference/craft-floor.md before editing**

Read it in full; build to it without announcing its checklist.

- [ ] **Step 2: Add the sheet primitive**

Run: `cd ui && npx shadcn@4.21.0 add sheet --dry-run`, then `npx shadcn@4.21.0 add sheet`. Confirm with `grep -n "^export\|^function\|side" src/components/ui/sheet.tsx` that it exports `Sheet`, `SheetContent` (with a `side` prop taking `"right"` and `"bottom"`), `SheetHeader`, `SheetTitle`, `SheetDescription`; use the generated names if they differ.

- [ ] **Step 3: Write the failing menu test**

Create `ui/tests/unit/menu.test.tsx`:

```tsx
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { MoreMenu } from "../../src/features/transcript/MoreMenu";
import { stubMatchMedia } from "./media";
import { choose } from "./menus";

beforeEach(() => stubMatchMedia());
afterEach(cleanup);

describe("the reader's menu", () => {
  it("badges Bleep only when the word lists found something", async () => {
    const { rerender } = render(<MoreMenu matchCount={0} onBleep={() => undefined} timingWord={null} onTiming={() => undefined} />);
    act(() => fireEvent.click(screen.getByRole("button", { name: "More" })));
    expect((await screen.findByRole("menuitem", { name: /^Bleep/ })).textContent).toBe("Bleep");
    rerender(<MoreMenu matchCount={3} onBleep={() => undefined} timingWord={null} onTiming={() => undefined} />);
    expect(screen.getByRole("menuitem", { name: /^Bleep/ }).textContent).toContain("3");
  });

  it("offers Timing only for one selected word, and opens the drawer on Bleep", async () => {
    const opened: string[] = [];
    render(<MoreMenu matchCount={0} onBleep={() => opened.push("bleep")} timingWord={4} onTiming={(w) => opened.push(`timing ${w}`)} />);
    act(() => fireEvent.click(screen.getByRole("button", { name: "More" })));
    choose(await screen.findByRole("menuitem", { name: /^Timing/ }));
    act(() => fireEvent.click(screen.getByRole("button", { name: "More" })));
    choose(await screen.findByRole("menuitem", { name: /^Bleep/ }));
    expect(opened).toEqual(["timing 4", "bleep"]);
  });
});
```

Run: `cd ui && npx vitest run tests/unit/menu.test.tsx`
Expected: FAIL, `Failed to resolve import "../../src/features/transcript/MoreMenu"`.

- [ ] **Step 4: Write `ui/src/features/bleep/useMatches.ts`**

```ts
// The words to bleep (#84), looked for while the reader is open, not only
// while the drawer is: the menu's Bleep item carries a badge exactly when the
// lists found something (Hashiya spec, Reader).

import { useCallback, useEffect, useState } from "react";

import { fromThrown, showError } from "@/features/errors/appError";
import type { Reading } from "@/features/transcript/document";
import type { Editor } from "@/lib/editOps";
import { findMatches, type Matches } from "./matches";

export type MatchesState = {
  found: Matches | null;
  setFound: (next: Matches) => void;
  /** Look again: after a word is added to the user's list. */
  again: () => void;
};

/** Looked for again when the words change (a word retyped, #83) or `again` is called; a mute changes neither. */
export function useMatches(transcriptId: number, editor: Editor, reading: Reading): MatchesState {
  const [found, setFound] = useState<Matches | null>(null);
  const [looked, setLooked] = useState(0);
  useEffect(() => {
    let live = true;
    findMatches(transcriptId, editor.content).then(
      (next) => {
        if (live) setFound(next);
      },
      (thrown: unknown) => {
        if (live) showError(fromThrown(thrown, `/api/transcripts/${transcriptId}/matches`));
      },
    );
    return () => {
      live = false;
    };
  }, [transcriptId, editor, reading, looked]);
  const again = useCallback(() => setLooked((n) => n + 1), []);
  return { found, setFound, again };
}
```

- [ ] **Step 5: Give `BleepPanel` its matches and its render job from outside**

In `ui/src/features/bleep/BleepPanel.tsx`:
1. Add to `Props`: `matches: MatchesState;` `started: RenderJob | null;` `onStarted: (job: RenderJob) => void;` and import `type MatchesState` from `./useMatches`.
2. Delete `const [found, setFound] = useState...`, `const [looked, setLooked] = useState(0);`, `const [started, setStarted] = useState...` and the `useEffect` that called `findMatches`; read `const { found, setFound, again } = matches;` and keep `const job = useRender(started);`.
3. In `render`, `.then(setStarted, ...)` becomes `.then(onStarted, ...)`; in `add`, `setLooked((n) => n + 1)` becomes `again()`.
4. The outer element becomes `<section aria-label="Words to bleep" className="flex flex-col gap-4 text-sm">`, and the inner heading row keeps only the **Mute all** button, right-aligned (`<div className="flex justify-end">`): the drawer's title names the panel.

The render job lives in the page now, so closing the drawer while a render runs and opening it again shows the job where it is.

- [ ] **Step 6: Write `ui/src/features/bleep/BleepDrawer.tsx`**

```tsx
import type { ReactNode } from "react";

import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { TOUCH, useMediaQuery } from "@/lib/media";

/**
 * Bleeping, out of the reader's way (Hashiya spec, Reader: "a drawer from the
 * right, a bottom sheet on the phone"; critique: "~350 px of tools before the
 * first word").
 */
export function BleepDrawer({ open, onOpenChange, children }: { open: boolean; onOpenChange: (open: boolean) => void; children: ReactNode }) {
  const touch = useMediaQuery(TOUCH);
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side={touch ? "bottom" : "right"} className={touch ? "max-h-[85dvh] overflow-y-auto" : "w-full overflow-y-auto sm:max-w-md"}>
        <SheetHeader>
          <SheetTitle>Bleep</SheetTitle>
          <SheetDescription>
            Words your lists match, muted as a render would mute them. Muting is an edit: Cmd+Z takes it back, and the recording is never changed.
          </SheetDescription>
        </SheetHeader>
        <div className="px-4 pb-6">{children}</div>
      </SheetContent>
    </Sheet>
  );
}
```

- [ ] **Step 7: Write `ui/src/features/transcript/MoreMenu.tsx`**

```tsx
import { Ellipsis } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";

type Props = {
  /** How many words the lists matched; the Bleep item is badged when this is more than 0. */
  matchCount: number;
  onBleep: () => void;
  /** The one selected word Timing would open, or null when none or several are selected. */
  timingWord: number | null;
  onTiming: (word: number) => void;
  /** More items: Export (Task 6). */
  extra?: ReactNode;
};

/** The reader's menu (Hashiya spec, Reader: "a menu with Timing, Bleep, Export"). */
export function MoreMenu({ matchCount, onBleep, timingWord, onTiming, extra }: Props) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            variant="ghost"
            size="icon"
            aria-label="More"
            className="size-11 text-field-foreground hover:bg-white/10 hover:text-field-foreground"
          />
        }
      >
        <Ellipsis aria-hidden />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-60">
        <DropdownMenuItem disabled={timingWord === null} onClick={() => timingWord !== null && onTiming(timingWord)}>
          Timing
          {timingWord === null && <span className="ml-auto text-xs text-muted-foreground">select one word</span>}
        </DropdownMenuItem>
        <DropdownMenuItem onClick={onBleep}>
          Bleep
          {matchCount > 0 && (
            <span className="ml-auto rounded-full bg-gold px-2 text-xs font-semibold text-primary-foreground tabular-nums">
              {matchCount}
            </span>
          )}
        </DropdownMenuItem>
        {extra}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
```

- [ ] **Step 8: Wire the menu, the drawer and the timing dock into `EditablePage`**

In `ui/src/features/transcript/TranscriptPage.tsx`, inside `EditablePage`:
1. Add state and the matches: `const [bleeping, setBleeping] = useState(false);`, `const [rendering, setRendering] = useState<RenderJob | null>(null);`, `const matches = useMatches(transcriptId, editor, edit.reading);` (imports: `useMatches` from `@/features/bleep/useMatches`, `BleepDrawer` from `@/features/bleep/BleepDrawer`, `type RenderJob` from `@/features/bleep/render`, `MoreMenu` from `./MoreMenu`).
2. The `tools` prop becomes:

```tsx
      tools={
        <>
          <EditBar editor={editor} saving={saving} />
          <MoreMenu
            matchCount={matches.found?.matches.length ?? 0}
            onBleep={() => setBleeping(true)}
            timingWord={selected !== null && selected.first === selected.last ? selected.first : null}
            onTiming={setTiming}
          />
        </>
      }
```

3. Replace the inline `TimingStrip` with the dock, above the player rail:

```tsx
      {timing !== null && timing < edit.first.length && (
        <div className="fixed inset-x-0 z-30 border-t bg-card shadow-lg shadow-black/10" style={{ bottom: "var(--dsj-player-height, 0px)" }}>
          <div className="mx-auto w-full max-w-5xl px-3 py-3 sm:px-6">
            <TimingStrip
              editor={editor}
              content={content}
              edit={edit}
              word={timing}
              recordingId={opened.recording.id}
              controls={controls}
              onClose={() => setTiming(null)}
            />
          </div>
        </div>
      )}
```

4. Replace the inline `BleepPanel` with the drawer:

```tsx
      <BleepDrawer open={bleeping} onOpenChange={setBleeping}>
        <BleepPanel
          transcriptId={transcriptId}
          editor={editor}
          content={content}
          edit={edit}
          renderable={renderable}
          padS={editable.padS}
          controls={controls}
          matches={matches}
          started={rendering}
          onStarted={setRendering}
        />
      </BleepDrawer>
```

In `ui/src/features/edit/TimingStrip.tsx`, the `section`'s class drops `rounded-lg border p-3` (the dock is the frame): `className="text-sm"`.

- [ ] **Step 9: Add the e2e drawer helper**

Append to `ui/tests/e2e/editable.ts`:

```ts
/** Open the bleep drawer from the reader's menu, and return its panel. */
export async function openBleep(page: Page) {
  await page.getByRole("button", { name: "More" }).click();
  await page.getByRole("menuitem", { name: /^Bleep/ }).click();
  const panel = page.getByRole("region", { name: "Words to bleep" });
  await panel.waitFor();
  return panel;
}
```

- [ ] **Step 10: Move the old bleep tests into the drawer**

| File | Was | Now |
|---|---|---|
| `ui/tests/unit/bleep.test.tsx`, `ui/tests/unit/render.test.tsx` | the panel is on the page at once | before any panel query: `act(() => fireEvent.click(await screen.findByRole("button", { name: "More" })))`, then `choose(await screen.findByRole("menuitem", { name: /^Bleep/ }))` (import `choose` from `./menus`), then `await screen.findByRole("region", { name: "Words to bleep" })`; the `h3 "Words to bleep"` query, if any, becomes the dialog title `Bleep` |
| `ui/tests/e2e/bleep.spec.ts`, `ui/tests/e2e/render.spec.ts` | `page.getByRole("region", { name: "Words to bleep" })` | `const panel = await openBleep(page);` (import from `./editable.ts`); `page.getByRole("toolbar", { name: "Edit" }).getByRole("status")` is unchanged |

- [ ] **Step 11: Run the unit tests**

Run: `cd ui && npx vitest run tests/unit/menu.test.tsx tests/unit/bleep.test.tsx tests/unit/render.test.tsx`
Expected: PASS.

- [ ] **Step 12: Gate, build, browser tests**

Run: `uv run just check` (paste the last line), `uv run just ui-build`, then `cd ui && npx playwright test tests/e2e/bleep.spec.ts tests/e2e/render.spec.ts tests/e2e/bounds.spec.ts --project chromium` and `--project webkit`.
Expected: all pass. bleep.spec's fade timing is measured with the drawer closed again; if it fails only with the drawer open, close it (`page.keyboard.press("Escape")`) before playing, and say so in the commit body.

- [ ] **Step 13: Look at it**

Run: `uv run python scratch/ui_shots.py --label t4 reader menu bleep`
Expected: 12 PNGs. In the `menu` shots, the menu sits under the More button inside the window, Timing says why it is off, and the Bleep badge, when the lists matched, is gold with ink figures. Check: no bleep panel above the transcript, and the first words start right under the bar; the More button sits at the bar's right beside Settings; the drawer comes from the right at 1440 and from the bottom at 390, its rows' buttons are 44 px tall on the phone, and its text is ink on the card, not grey on grey.

- [ ] **Step 14: Commit**

```bash
git add ui/src/components/ui/sheet.tsx ui/src/features/bleep/useMatches.ts ui/src/features/bleep/BleepDrawer.tsx \
  ui/src/features/bleep/BleepPanel.tsx ui/src/features/transcript/MoreMenu.tsx \
  ui/src/features/transcript/TranscriptPage.tsx ui/src/features/edit/TimingStrip.tsx \
  ui/tests/unit/menu.test.tsx ui/tests/unit/bleep.test.tsx ui/tests/unit/render.test.tsx \
  ui/tests/e2e/bleep.spec.ts ui/tests/e2e/render.spec.ts ui/tests/e2e/editable.ts
git add -A -- dsj/ui/static/
git commit -m "feat(ui): reader menu, bleep drawer with a badge, timing dock"
```

---
### Task 5: Speaker names, and the speaker EditOp

**Files:**
- Modify: `dsj/hatao.py` (`Document.names`; `validate`, `mute`, `delete`, `move`, `dumps`, `loads`)
- Modify: `dsj/ui/edits.py` (names kept on a content save; `save_names`; `Opened.legend`)
- Modify: `dsj/ui/schemas.py` (`Edits.names`, `NamesUpdate`), `dsj/ui/routes/marks.py` (`_wire`, `PUT /api/transcripts/{id}/names`)
- Modify: `ui/src/api/schema.d.ts` (generated by `just api`)
- Modify: `ui/src/lib/editOps.ts` (`SpeakerOp`)
- Create: `ui/src/features/edit/speaker.ts`, `ui/src/features/transcript/Nameplate.tsx`
- Modify: `ui/src/features/edit/readContent.ts` (`speakerLabels`), `ui/src/features/edit/editing.ts` (`Editable.names`, `saveNames`), `ui/src/features/transcript/TranscriptPage.tsx` (`EditablePage` passes names and the nameplate), `ui/src/features/transcript/transcript.css` (nameplate button)
- Test: `tests/test_hatao.py`, `tests/test_ui_edits.py`, `ui/tests/unit/speaker.test.ts` (new), `ui/tests/unit/reader.test.tsx`, `ui/tests/e2e/names.spec.ts` (new)

**Interfaces:**
- Consumes: Task 3's `TranscriptView` `names` and `nameplate` props, `Names`, `displayName`; `Latest`, `useLatest` from `editing.ts`.
- Produces:
  - Python: `hatao.Document(sources, content, names={})`; `edits.save_names(transcript_id: int, names: Mapping[str, str]) -> Opened`; `Opened.legend: tuple[str, ...]` (the transcript's own speaker labels); route `PUT /api/transcripts/{transcript_id}/names` taking `NamesUpdate { names: dict[str, str] }` and answering `Edits` (which now carries `names: dict[str, str]`).
  - TS: `type SpeakerOp = { kind: "speaker"; start: number; stop: number; entries: Entry[] }` in the `EditOp` union; `speakerChange(content: Content, start: number, stop: number, speaker: string | null): SpeakerOp | null`; `governingParagraph(content: Content, index: number): number`; `speakerAt(content: Content, index: number): string | null`; `newSpeakerLabel(labels: readonly string[]): string`; `speakerLabels(content: Content, legend: readonly string[] | undefined): string[] | undefined`; `Editable.names: Latest<Names>`; `saveNames(transcriptId: number, names: Names): Promise<Names>`; `Nameplate({ label, name, onRename })`.

- [ ] **Step 1: Load impeccable: read /Users/moiz/.claude/skills/impeccable/reference/craft-floor.md before editing**

Read it in full; build to it without announcing its checklist.

- [ ] **Step 2: File the issue (AGENTS.md rule 1)**

Run: `gh issue create --title "hatao: speaker names table in the edit list (Hashiya A)" --body "Optional names map in the dsj-edits file, kept by every change and save; PUT /api/transcripts/{id}/names. Plan: docs/superpowers/plans/2026-10-07-hashiya-review-mode.md, Task 5."`
Expected: an issue URL. Use its number in the code comments below where they say `#NAMES`; replace `#NAMES` with it.

- [ ] **Step 3: Write the failing hatao tests**

Append to `tests/test_hatao.py`:

```python
# -- speaker names (#NAMES) -------------------------------------------------------


def _named() -> Document:
    return Document(
        {"0": "/elsewhere/rec.mov"},
        (
            Paragraph("SPEAKER_00"), Item("0", 0.0, 0.5, " hi"),
            Paragraph("SPEAKER_01"), Item("0", 0.5, 0.5, " yo"),
        ),
        {"SPEAKER_00": "Ali"},
    )


def test_speaker_names_come_back_from_the_file_and_survive_every_change() -> None:
    back = hatao.loads(hatao.dumps(_named()))
    assert back.names == {"SPEAKER_00": "Ali"}
    assert hatao.mute(back, 1, 2).names == {"SPEAKER_00": "Ali"}
    assert hatao.delete(back, 3, 4).names == {"SPEAKER_00": "Ali"}
    assert hatao.move(back, 2, 4, 0).names == {"SPEAKER_00": "Ali"}


def test_a_list_with_no_names_is_written_exactly_as_before() -> None:
    plain = Document(
        {"0": "/elsewhere/rec.mov"}, (Paragraph("SPEAKER_00"), Item("0", 0.0, 0.5, " hi"))
    )
    assert "names" not in json.loads(hatao.dumps(plain))
    assert hatao.loads(hatao.dumps(plain)).names == {}


@pytest.mark.parametrize("names", [{"SPEAKER_00": "  "}, {"": "Ali"}])
def test_a_blank_name_or_label_is_refused_by_name(names: dict[str, str]) -> None:
    with pytest.raises(InvalidDocument, match="speaker name"):
        hatao.validate(Document({"0": "/x"}, (Paragraph("SPEAKER_00"),), names))


def test_names_that_are_not_text_are_refused_on_load() -> None:
    raw = json.loads(hatao.dumps(_named()))
    raw["names"] = {"SPEAKER_00": 3}
    with pytest.raises(InvalidDocument, match="names"):
        hatao.loads(json.dumps(raw))
```

Run: `uv run pytest tests/test_hatao.py -q -k "name"`
Expected: FAIL, `TypeError: Document.__init__() takes 3 positional arguments but 4 were given`.

- [ ] **Step 4: Add the names table to `dsj/hatao.py`**

1. `from dataclasses import dataclass, field, replace`.
2. `Document` becomes:

```python
@dataclass(frozen=True)
class Document:
    """Sources by id, each an absolute path, the entries that play from them, and speaker names.

    `names` maps a speaker label (a paragraph's `speaker`) to the name a person
    gave it in the app (#NAMES, Hashiya spec "Speakers are renamable").
    Optional and additive: a file without it is the version 1 file it always
    was, written byte for byte as before, and a dsj older than this ignores the
    key. Paragraphs keep their labels; only what the page shows changes.
    """

    sources: Mapping[str, str]
    content: tuple[Entry, ...]
    names: Mapping[str, str] = field(default_factory=dict[str, str])
```

3. In `validate`, after the sources loop:

```python
    for label, name in doc.names.items():
        if not label or not name.strip():
            raise InvalidDocument(
                f"speaker name {name!r} for label {label!r}: both must be non-empty text; "
                f"leave a speaker out of `names` to show the diarizer's own label"
            )
```

4. `mute`, `delete` and `move` build their result with `replace(doc, content=...)` instead of `Document(doc.sources, ...)`, so the names ride along:
   - `mute`: `return validate(replace(doc, content=content))`
   - `delete`: `return validate(replace(doc, content=doc.content[:start] + doc.content[stop:]))`
   - `move`: `return validate(replace(doc, content=rest[:at] + block + rest[at:]))`
5. In `dumps`, the object written becomes:

```python
    out: dict[str, Any] = {
        "format": FORMAT,
        "version": FORMAT_VERSION,
        "sources": {key: path for key, path in doc.sources.items() if key in used},
        "content": [_entry_json(entry) for entry in doc.content],
    }
    # Only when there are names, so a list nobody renamed is the file it always was.
    if doc.names:
        out["names"] = dict(doc.names)
    return json.dumps(out, ensure_ascii=False)
```

6. In `loads`, before the final `return`:

```python
    names = top.get("names", {})
    if not isinstance(names, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in cast("dict[Any, Any]", names).items()
    ):
        raise InvalidDocument(f"`names` must map speaker labels to names, both text: {names!r}")
    entries = tuple(_entry(i, entry) for i, entry in enumerate(cast("list[Any]", content)))
    return validate(Document(cast("dict[str, str]", paths), entries, cast("dict[str, str]", names)))
```

   (replacing the two lines that built `entries` and returned).

Run: `uv run pytest tests/test_hatao.py -q`
Expected: PASS, every test in the file.

- [ ] **Step 5: Write the failing route tests**

Append to `tests/test_ui_edits.py`:

```python
# -- speaker names (#NAMES) -------------------------------------------------------


def test_a_name_given_to_a_speaker_is_kept_and_sent_back(seeded: dict[str, Any]) -> None:
    client = page()
    route = f"/api/transcripts/{seeded['id']}"
    assert client.get(f"{route}/edits").json()["names"] == {}
    reply = client.put(f"{route}/names", json={"names": {"SPEAKER_00": "  Ali  "}})
    assert reply.status_code == 200, reply.text
    assert reply.json()["names"] == {"SPEAKER_00": "Ali"}
    assert page().get(f"{route}/edits").json()["names"] == {"SPEAKER_00": "Ali"}
    # In the file `dsj hatao` reads, beside the library.
    assert hatao.load(edits_path(seeded["json"])).names == {"SPEAKER_00": "Ali"}


def test_saving_the_words_keeps_the_names(seeded: dict[str, Any]) -> None:
    client = page()
    route = f"/api/transcripts/{seeded['id']}"
    client.put(f"{route}/names", json={"names": {"SPEAKER_01": "Sara"}})
    content = client.get(f"{route}/edits").json()["content"]
    content[2]["muted"] = True
    saved = client.put(f"{route}/edits", json={"content": content}).json()
    assert saved["names"] == {"SPEAKER_01": "Sara"}


def test_a_blank_name_gives_the_speaker_its_own_label_back(seeded: dict[str, Any]) -> None:
    client = page()
    route = f"/api/transcripts/{seeded['id']}/names"
    client.put(route, json={"names": {"SPEAKER_00": "Ali", "SPEAKER_01": "Sara"}})
    cleared = client.put(route, json={"names": {"SPEAKER_00": "", "SPEAKER_01": "Sara"}}).json()
    assert cleared["names"] == {"SPEAKER_01": "Sara"}
```

Run: `uv run pytest tests/test_ui_edits.py -q -k "name"`
Expected: FAIL, `KeyError: 'names'`.

- [ ] **Step 6: Save names in `dsj/ui/edits.py`**

1. Add `"save_names"` to `__all__`, and `from collections.abc import Mapping`.
2. `Opened` gains, after `duration_s`:

```python
    # The transcript's own speaker labels, in its order: what "Speaker n" counts by.
    legend: tuple[str, ...] = ()
```

3. Add:

```python
def _legend(payload: dict[str, Any]) -> tuple[str, ...]:
    """The transcript's speaker labels, text only: an old file's non-text entries are skipped."""
    return tuple(s for s in cast("list[Any]", payload.get("speakers") or []) if isinstance(s, str))
```

4. In `open_edits`, the saved branch keeps the file's names: `doc = hatao.validate(hatao.Document({SOURCE: str(row.media.resolve())}, saved.content, saved.names))`, and the return becomes `return Opened(doc, edited_at, _confidences(payload, doc), row.duration_s, _legend(payload))`.
5. Replace `save_edits` with a shared writer and two callers:

```python
def _save(transcript_id: int, content: tuple[hatao.Entry, ...], names: Mapping[str, str]) -> Opened:
    """Write `content` and `names` as the transcript's edit list, whole or not at all."""
    row = _row(transcript_id)
    payload = _payload(row, transcript_id)
    doc = hatao.validate(hatao.Document({SOURCE: str(row.media.resolve())}, content, dict(names)))
    path = edits_path(row.json_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    hatao.save(doc, path)
    edited_at = _edited_at(path)
    # So the library list can say this transcript was corrected by hand (#83).
    with Library.open() as library:
        library.mark_edited(transcript_id, edited_at)
    return Opened(doc, edited_at, _confidences(payload, doc), row.duration_s, _legend(payload))


def save_edits(transcript_id: int, content: tuple[hatao.Entry, ...]) -> Opened:
    """Save the page's entries as the transcript's edit list, keeping the speaker names it has.

    Raises:
        NoSuchTranscript: no such transcript, or its JSON file is gone.
        dsj.hatao.InvalidDocument: the entries are broken, named; nothing is written.
    """
    row = _row(transcript_id)
    path = edits_path(row.json_path)
    names = hatao.load(path).names if path.is_file() else {}
    return _save(transcript_id, content, names)


def save_names(transcript_id: int, names: Mapping[str, str]) -> Opened:
    """Save the names a person gave the speakers (#NAMES), keeping the entries as they are.

    Names are trimmed, and a blank one is left out, so that speaker shows its
    own label ("Speaker 2") again.

    Raises:
        NoSuchTranscript: no such transcript, or its JSON file is gone.
        dsj.hatao.InvalidDocument: a label is blank; nothing is written.
    """
    opened = open_edits(transcript_id)
    kept = {label: name.strip() for label, name in names.items() if name.strip()}
    return _save(transcript_id, opened.doc.content, kept)
```

- [ ] **Step 7: Carry names on the wire**

In `dsj/ui/schemas.py`: add `"NamesUpdate"` to `__all__`; in `Edits`, after `content`:

```python
    # The names a person gave the speakers, by label (#NAMES); {} when none.
    names: dict[str, str]
```

and after `EditsUpdate`:

```python
class NamesUpdate(BaseModel):
    """Every speaker's name, by label, in place of the ones before; a blank name clears one."""

    names: dict[str, str]
```

In `dsj/ui/routes/marks.py`: import `NamesUpdate`; in `_wire`, pass `names=dict(opened.doc.names)` to `Edits(...)`; and add the route:

```python
@router.put("/transcripts/{transcript_id}/names")
def save_names(transcript_id: str, update: NamesUpdate) -> Edits:
    """Save the speakers' names in the transcript's edit list, the words untouched (#NAMES)."""
    return _wire(edits.save_names(_id(transcript_id), update.names))
```

Run: `uv run pytest tests/test_ui_edits.py tests/test_hatao.py -q`
Expected: PASS.

- [ ] **Step 8: Regenerate the page's types**

Run: `uv run just api`
Expected: `ui/src/api/schema.d.ts` gains `names: { [key: string]: string }` on `Edits` and the `NamesUpdate` schema and the `/names` path.

- [ ] **Step 9: Write the failing speaker test**

Create `ui/tests/unit/speaker.test.ts`:

```ts
// Who said a stretch, changed as an edit (Hashiya spec, Review mode: "Speaker
// changes are a new EditOp kind that splits the speaker's paragraph at the
// sentence boundary and sets the speaker").
import { describe, expect, it } from "vitest";

import { readContent, speakerLabels } from "../../src/features/edit/readContent";
import { governingParagraph, newSpeakerLabel, speakerAt, speakerChange } from "../../src/features/edit/speaker";
import { type Content, Editor, type Entry, type Item } from "../../src/lib/editOps";
import { lint } from "../../src/lib/linter";

function item(sourceStart: number, length: number, text: string): Item {
  return { kind: "item", source: "0", sourceStart, length, text, muted: false, confidence: 0.9 };
}
const para = (speaker: string | null): Entry => ({ kind: "paragraph", speaker, language: "ur" });

// Two sentences: SPEAKER_00 says "alpha bravo charlie", SPEAKER_01 "delta echo".
const CONTENT: Content = [
  para("SPEAKER_00"),
  item(0, 0.2, ""),
  item(0.2, 0.3, " alpha"),
  item(0.6, 0.3, " bravo"),
  item(1.0, 0.3, " charlie"),
  para("SPEAKER_01"),
  item(2.0, 0.4, " delta"),
  item(2.5, 0.4, " echo"),
];
const LEGEND = ["SPEAKER_00", "SPEAKER_01"];
const SOURCES = new Set(["0"]);

function turns(content: Content): [string | undefined, string][] {
  const { reading } = readContent(content, LEGEND);
  return reading.turns.map((t) => [t.speaker === null ? undefined : reading.speakers[t.speaker], t.text]);
}

function apply(content: Content, start: number, stop: number, speaker: string): Content {
  const op = speakerChange(content, start, stop, speaker);
  if (op === null) throw new Error("no change");
  const editor = new Editor(content, { check: (c) => lint(c, SOURCES) });
  editor.applyEdit(op);
  return editor.content;
}

describe("speakerChange", () => {
  it("sets a whole sentence's speaker on its own paragraph mark", () => {
    const op = speakerChange(CONTENT, 2, 5, "SPEAKER_01");
    expect(op).toMatchObject({ kind: "speaker", start: 0, stop: 5 });
    expect(turns(apply(CONTENT, 2, 5, "SPEAKER_01"))).toEqual([["SPEAKER_01", " alpha bravo charlie delta echo"]]);
  });

  it("splits a sentence at a stretch inside it, and the rest keeps its speaker", () => {
    expect(turns(apply(CONTENT, 3, 4, "SPEAKER_01"))).toEqual([
      ["SPEAKER_00", " alpha"],
      ["SPEAKER_01", " bravo"],
      ["SPEAKER_00", " charlie"],
      ["SPEAKER_01", " delta echo"],
    ]);
  });

  it("sets every sentence a stretch runs across", () => {
    expect(turns(apply(CONTENT, 4, 8, "SPEAKER_02"))).toEqual([
      ["SPEAKER_00", " alpha bravo"],
      ["SPEAKER_02", " charlie delta echo"],
    ]);
  });

  it("is undone in one step, back to the list as it was", () => {
    const op = speakerChange(CONTENT, 3, 4, "SPEAKER_01");
    if (op === null) throw new Error("no change");
    const editor = new Editor(CONTENT);
    editor.applyEdit(op);
    editor.undo();
    expect(editor.content).toEqual(CONTENT);
  });

  it("changes nothing when the stretch already has that speaker", () => {
    expect(speakerChange(CONTENT, 2, 5, "SPEAKER_00")).toBeNull();
  });

  it("keeps each paragraph's language on the marks it adds", () => {
    const after = apply(CONTENT, 3, 4, "SPEAKER_01");
    expect(after.filter((e) => e.kind === "paragraph").every((e) => e.kind === "paragraph" && e.language === "ur")).toBe(true);
  });
});

describe("who speaks where", () => {
  it("finds the paragraph that governs an entry, and its speaker", () => {
    expect(governingParagraph(CONTENT, 7)).toBe(5);
    expect(speakerAt(CONTENT, 3)).toBe("SPEAKER_00");
  });

  it("makes a label for a new speaker that no speaker has", () => {
    expect(newSpeakerLabel(["SPEAKER_00", "SPEAKER_01"])).toBe("SPEAKER_02");
    // senko numbered a real two-speaker clip SPEAKER_01 and SPEAKER_02 (document.ts).
    expect(newSpeakerLabel(["SPEAKER_01", "SPEAKER_02"])).toBe("SPEAKER_00");
  });

  it("reads a label the list uses and the legend lacks as one more speaker, in order of first use", () => {
    const after = apply(CONTENT, 4, 8, "SPEAKER_02");
    expect(speakerLabels(after, LEGEND)).toEqual(["SPEAKER_00", "SPEAKER_01", "SPEAKER_02"]);
    expect(speakerLabels([para(null), item(0, 1, " hi")], undefined)).toBeUndefined();
  });
});
```

Run: `cd ui && npx vitest run tests/unit/speaker.test.ts`
Expected: FAIL, `Failed to resolve import "../../src/features/edit/speaker"`.

- [ ] **Step 10: Add `SpeakerOp` to `ui/src/lib/editOps.ts`**

After `RetimeOp`:

```ts
/**
 * Put `entries` in place of entries [start, stop): the paragraph marks that
 * say who said a stretch, changed or added so someone else said it (Hashiya
 * spec, Review mode, Ctrl+1 to Ctrl+9). The words and their times are
 * untouched. features/edit/speaker.ts builds it.
 */
export type SpeakerOp = { kind: "speaker"; start: number; stop: number; entries: Entry[] };
```

The union line becomes `export type EditOp = MuteOp | FlagOp | DismissOp | CorrectOp | RetimeOp | SpeakerOp;`, and `KINDS` gains, after `retime`:

```ts
  speaker: {
    apply: (content, op) => splice(content, op.start, op.stop, op.entries),
    invert: (before, op) => ({
      kind: "speaker",
      start: op.start,
      stop: op.start + op.entries.length,
      entries: before.slice(op.start, op.stop),
    }),
    describe: () => "speaker",
  },
```

- [ ] **Step 11: Write `ui/src/features/edit/speaker.ts`**

```ts
// Who said a stretch of the edit list, and the edit that changes it (Hashiya
// spec, Review mode: "Speaker changes are a new EditOp kind that splits the
// speaker's paragraph at the sentence boundary and sets the speaker").
//
// A paragraph mark governs every item after it up to the next mark, and the
// list built from a transcript has one mark per sentence (dsj/hatao.py,
// from_transcript). So a whole sentence changes speaker by changing its own
// mark; a stretch inside one gets a mark of its own in front of it, and a
// mark after it hands what follows back to the speaker it had. Each added
// mark copies the language of the one it splits.

import type { Content, Entry, Paragraph, SpeakerOp } from "@/lib/editOps";

/** The index of the paragraph mark governing entry `index`: the nearest at or before it, or -1. */
export function governingParagraph(content: Content, index: number): number {
  for (let i = Math.min(index, content.length - 1); i >= 0; i -= 1) {
    if (content[i]?.kind === "paragraph") return i;
  }
  return -1;
}

/** Who says entry `index`, by label, or null. */
export function speakerAt(content: Content, index: number): string | null {
  const entry = content[governingParagraph(content, index)];
  return entry?.kind === "paragraph" ? entry.speaker : null;
}

/** Whether any item in [from, to) has words. */
function wordsIn(content: Content, from: number, to: number): boolean {
  for (let i = from; i < to; i += 1) {
    const entry = content[i];
    if (entry?.kind === "item" && entry.text !== "") return true;
  }
  return false;
}

/** Whether words follow `index` before the next paragraph mark. */
function continues(content: Content, index: number): boolean {
  for (let i = index; i < content.length; i += 1) {
    const entry = content[i];
    if (entry?.kind === "paragraph") return false;
    if (entry?.kind === "item" && entry.text !== "") return true;
  }
  return false;
}

/**
 * The edit that makes `speaker` say entries [start, stop), which open on a
 * word, or null when they already all have that speaker.
 */
export function speakerChange(content: Content, start: number, stop: number, speaker: string | null): SpeakerOp | null {
  const p = governingParagraph(content, start);
  const governing = content[p];
  if (governing?.kind !== "paragraph") throw new RangeError(`entry ${start} has no paragraph mark before it`);
  const after = content[governingParagraph(content, stop - 1)] as Paragraph;
  // A stretch that opens where its paragraph's words open changes that mark;
  // one that opens later gets a mark of its own.
  const opensParagraph = !wordsIn(content, p + 1, start);
  const from = opensParagraph ? p : start;
  // A stretch inside a sentence that already has this speaker, all the way through: nothing to split.
  if (!opensParagraph && governing.speaker === speaker && after.speaker === speaker) return null;
  const out: Entry[] = opensParagraph ? [] : [{ ...governing, speaker }];
  let changed = !opensParagraph;
  for (let i = from; i < stop; i += 1) {
    const entry = content[i] as Entry;
    if (entry.kind === "paragraph") {
      if (entry.speaker !== speaker) changed = true;
      out.push({ ...entry, speaker });
    } else {
      out.push(entry);
    }
  }
  if (!changed) return null;
  if (continues(content, stop)) out.push({ ...after });
  return { kind: "speaker", start: from, stop, entries: out };
}

/** A label for a new speaker: the first SPEAKER_nn no speaker has. */
export function newSpeakerLabel(labels: readonly string[]): string {
  for (let n = 0; ; n += 1) {
    const label = `SPEAKER_${String(n).padStart(2, "0")}`;
    if (!labels.includes(label)) return label;
  }
}
```

- [ ] **Step 12: Read new labels as speakers in `ui/src/features/edit/readContent.ts`**

Add:

```ts
/**
 * The transcript's legend, then any label the list uses that the legend
 * lacks, in order of first use: a speaker a person added in Review (Ctrl+3 on
 * a two-speaker call) reads as "Speaker 3". Undefined when neither has a label,
 * so an unlabelled transcript still breaks paragraphs at pauses (document.ts GAP_S).
 */
export function speakerLabels(content: Content, legend: readonly string[] | undefined): string[] | undefined {
  const labels = [...(legend ?? [])];
  const known = new Set(labels);
  for (const entry of content) {
    if (entry.kind === "paragraph" && entry.speaker !== null && !known.has(entry.speaker)) {
      known.add(entry.speaker);
      labels.push(entry.speaker);
    }
  }
  return legend === undefined && labels.length === 0 ? undefined : labels;
}
```

and at the top of `readContent`, rename the parameter to `legend: string[] | undefined` and add `const speakers = speakerLabels(content, legend);` as its first line; the rest of the function already reads `speakers`.

Run: `cd ui && npx vitest run tests/unit/speaker.test.ts tests/unit/edit.test.tsx tests/unit/editOps.test.ts`
Expected: PASS (`editOps.test.ts`'s compile check still finds `export type EditOp =` and `const KINDS: Kinds = {`).

- [ ] **Step 13: Keep the names beside the editor in `ui/src/features/edit/editing.ts`**

Add `import type { Names } from "@/features/transcript/speakers";`. `Editable` gains:

```ts
  /** The speakers' names, by label (#NAMES), as last saved. */
  names: Latest<Names>;
```

`loadEditable` builds it: `names: new Latest<Names>(data.names),`. Add:

```ts
/** Save every speaker's name; the server's answer is what is kept. Throws ApiError in the server's words. */
export async function saveNames(transcriptId: number, names: Names): Promise<Names> {
  const route = `/api/transcripts/${transcriptId}/names`;
  const { data, error, response } = await api.PUT("/api/transcripts/{transcript_id}/names", {
    params: { path: { transcript_id: String(transcriptId) } },
    body: { names: { ...names } },
  });
  if (data === undefined) throw new ApiError(fromBody(error, response, route));
  return data.names;
}
```

- [ ] **Step 14: Write `ui/src/features/transcript/Nameplate.tsx`**

```tsx
import { useState } from "react";

type Props = {
  label: string;
  name: string;
  onRename: (label: string, name: string) => void;
};

/**
 * A speaker's nameplate, renamable where it stands (Hashiya spec, Reader:
 * "click a nameplate, type a name"; critique: "Speaker N not nameable").
 * Enter keeps the name, Esc or leaving the field keeps the old one, and an
 * emptied field gives the speaker its own label back.
 */
export function Nameplate({ label, name, onRename }: Props) {
  const [editing, setEditing] = useState(false);
  if (!editing) {
    return (
      <button type="button" className="nameplate -mx-1 rounded px-1 text-left hover:bg-muted" aria-label={`${name}, rename`} onClick={() => setEditing(true)}>
        {name}
      </button>
    );
  }
  return (
    <input
      autoFocus
      aria-label={`Name for ${name}`}
      defaultValue={name}
      dir="auto"
      className="nameplate w-full rounded border border-input bg-card px-1"
      onFocus={(event) => event.currentTarget.select()}
      onBlur={() => setEditing(false)}
      onKeyDown={(event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          onRename(label, event.currentTarget.value);
          setEditing(false);
        } else if (event.key === "Escape") {
          setEditing(false);
        }
      }}
    />
  );
}
```

In `ui/src/features/transcript/transcript.css`, add (a nameplate button on a touch screen is a 44 px target):

```css
.transcript .margin button.nameplate {
  font: inherit;
  font-weight: 650;
  cursor: text;
}

@media (pointer: coarse) {
  .transcript .margin button.nameplate {
    min-height: 44px;
  }
}
```

- [ ] **Step 15: Give `EditablePage` the names and the nameplate**

In `ui/src/features/transcript/TranscriptPage.tsx`, inside `EditablePage` (import `useCallback`, `saveNames`, `Nameplate`, `type Names`):

```tsx
  const names = useLatest(editable.names);
  const rename = useCallback(
    (label: string, name: string) => {
      const next: Record<string, string> = { ...names };
      if (name.trim() === "") delete next[label];
      else next[label] = name.trim();
      saveNames(transcriptId, next).then(
        (saved) => editable.names.set(saved),
        (thrown: unknown) => showError(fromThrown(thrown, `/api/transcripts/${transcriptId}/names`)),
      );
    },
    [names, transcriptId, editable.names],
  );
  const nameplate = useCallback(
    (_speaker: number, label: string, name: string) => <Nameplate label={label} name={name} onRename={rename} />,
    [rename],
  );
```

and pass `names={names}` and `nameplate={nameplate}` to `Page`. `useCallback` keeps both stable, so the memoised `TranscriptView` redraws only when a name changes.

- [ ] **Step 16: Pin the rename in the reader test**

Every unit test that answers `GET /api/transcripts/{id}/edits` must now send `names: {}` beside `pad_s`, or the reader reads names from `undefined`: find them with `grep -n "pad_s: 0.1" ui/tests/unit/*.tsx` (bleep, correction, edit, render, transcript, reader) and add it to each.

Append to the `describe("the reader")` block of `ui/tests/unit/reader.test.tsx` (and in its fetch mock, answer `PUT /api/transcripts/7/names` with `Response.json({ content: CONTENT, names: body.names, pad_s: 0.1, edited_at: null, spans: [], unrenderable: null })` where `body` is `await request.json()`; the `GET /edits` reply gains `names: {}`):

```tsx
  it("renames a speaker from the margin, everywhere they speak", async () => {
    render(<TranscriptPage recording={2} transcript={7} />);
    fireEvent.click(await screen.findByRole("button", { name: "Speaker 1, rename" }));
    const field = screen.getByRole("textbox", { name: "Name for Speaker 1" });
    fireEvent.change(field, { target: { value: "Ali" } });
    fireEvent.keyDown(field, { key: "Enter" });
    expect(await screen.findByRole("button", { name: "Ali, rename" })).toBeTruthy();
    const put = fetchMock.mock.calls.map(([r]) => r).find((r) => r.method === "PUT" && r.url.endsWith("/names"));
    expect(put).toBeDefined();
  });
```

Run: `cd ui && npx vitest run tests/unit/reader.test.tsx`
Expected: PASS.

- [ ] **Step 17: Pin it in the browser**

Create `ui/tests/e2e/names.spec.ts`:

```ts
// Naming a speaker in the reader (Hashiya spec, Reader), in real chromium and
// Playwright's webkit against the real `dsj ui`: the name shows on every turn
// of that speaker, and survives a reload because it is in the edit list.
import { expect, test } from "@playwright/test";

import { editableTranscript } from "./editable.ts";
import { readerUrl, scratchDir, seed, tone } from "./seed.ts";

test("a speaker renamed in the margin is renamed everywhere, and stays renamed", async ({ page }, info) => {
  const dir = scratchDir();
  const seconds = 9 + info.project.name.length / 10;
  const seeded = seed(
    editableTranscript(tone(dir, seconds, `names-${info.project.name}.wav`), [
      ["alpha", "bravo"],
      ["charlie", "delta"],
      ["echo", "foxtrot"],
    ]),
    dir,
  );
  await page.goto(readerUrl(seeded));
  await page.getByRole("button", { name: "Speaker 1, rename" }).first().click();
  const field = page.getByRole("textbox", { name: "Name for Speaker 1" });
  await field.fill("Ali");
  await field.press("Enter");
  // Turns 1 and 3 are SPEAKER_00's (editableTranscript alternates speakers).
  await expect(page.getByRole("button", { name: "Ali, rename" })).toHaveCount(2);
  await page.reload();
  await expect(page.getByRole("button", { name: "Ali, rename" })).toHaveCount(2);
  await expect(page.getByRole("button", { name: "Speaker 2, rename" })).toHaveCount(1);
});
```

- [ ] **Step 18: Gate, build, browser tests**

Run: `uv run just check` (paste the last line), `uv run just ui-build`, `cd ui && npx playwright test tests/e2e/names.spec.ts --project chromium` and `--project webkit`.
Expected: all pass.

- [ ] **Step 19: Look at it**

Run: `uv run python scratch/ui_shots.py --label t5 reader reader-urdu`
Expected: 8 PNGs. Check: the nameplates read as names in their colours, not as buttons with borders; at 390 they sit in the slim margin line and are tall enough to tap.

- [ ] **Step 20: Commit**

```bash
git add dsj/hatao.py dsj/ui/edits.py dsj/ui/schemas.py dsj/ui/routes/marks.py ui/src/api/schema.d.ts \
  ui/src/lib/editOps.ts ui/src/features/edit/speaker.ts ui/src/features/edit/readContent.ts \
  ui/src/features/edit/editing.ts ui/src/features/transcript/Nameplate.tsx \
  ui/src/features/transcript/TranscriptPage.tsx ui/src/features/transcript/transcript.css \
  tests/test_hatao.py tests/test_ui_edits.py ui/tests/unit/speaker.test.ts ui/tests/unit/reader.test.tsx \
  ui/tests/unit/bleep.test.tsx ui/tests/unit/correction.test.tsx ui/tests/unit/edit.test.tsx \
  ui/tests/unit/render.test.tsx ui/tests/unit/transcript.test.tsx ui/tests/e2e/names.spec.ts
git add -A -- dsj/ui/static/
git commit -m "feat: speaker names in the edit list, and a speaker EditOp"
```

---

### Task 6: Export from the reader's menu

**Files:**
- Modify: `dsj/ui/edits.py` (`as_payload`, `display_name`), `dsj/ui/routes/marks.py` (`GET /api/transcripts/{id}/export/{fmt}`)
- Modify: `ui/src/api/schema.d.ts` (generated)
- Create: `ui/src/features/transcript/exportFile.ts`
- Modify: `ui/src/features/transcript/TranscriptPage.tsx` (`MoreMenu`'s `extra`)
- Test: `tests/test_ui_export.py` (new), `ui/tests/unit/export.test.ts` (new)

**Interfaces:**
- Consumes: Task 5's `Opened.legend`, `Document.names`; Task 4's `MoreMenu({ extra })`; `dsj.likho.EXPORTERS`.
- Produces: Python `edits.display_name(label: str | None, labels: Sequence[str], names: Mapping[str, str]) -> str | None` (Task 10's reference export uses it) and `edits.labels_of(opened: Opened) -> list[str]`; `edits.as_payload(opened: Opened) -> dict[str, Any]`; TS `type ExportFormat = "srt" | "vtt" | "txt"`, `exportTranscript(transcriptId: number, format: ExportFormat, title: string): Promise<void>`.

- [ ] **Step 1: Load impeccable: read /Users/moiz/.claude/skills/impeccable/reference/craft-floor.md before editing**

Read it in full; build to it without announcing its checklist.

- [ ] **Step 2: File the issue (AGENTS.md rule 1)**

Run: `gh issue create --title "ui: export the edited transcript as SRT, WebVTT or text (Hashiya A)" --body "GET /api/transcripts/{id}/export/{fmt}: dsj likho's exporters over the edit list, corrections and speaker names included. Plan: docs/superpowers/plans/2026-10-07-hashiya-review-mode.md, Task 6."` and put its number where the code says `#EXPORT`.

- [ ] **Step 3: Write the failing route test**

Create `tests/test_ui_export.py`:

```python
"""The edited transcript exported from the reader's menu (#EXPORT).

The same recording and transcript as tests/test_ui_edits.py: two seconds of
tone ffmpeg makes and two sentences written here, never a real recording.
"""

from __future__ import annotations

from typing import Any

import pytest

# pytest puts tests/ on the path (no __init__.py; tests/test_diarize_gate.py imports
# gate_helpers the same way).
from test_ui_edits import page, seeded  # noqa: F401  (the fixture)


def test_an_export_carries_the_corrections_and_the_names(
    seeded: dict[str, Any],  # noqa: F811
) -> None:
    client = page()
    route = f"/api/transcripts/{seeded['id']}"
    content = client.get(f"{route}/edits").json()["content"]
    there = next(i for i, e in enumerate(content) if e.get("text") == " there")
    content[there]["text"] = " their"
    client.put(f"{route}/edits", json={"content": content})
    client.put(f"{route}/names", json={"names": {"SPEAKER_00": "Ali"}})
    reply = client.get(f"{route}/export/srt")
    assert reply.status_code == 200, reply.text
    name = f'attachment; filename="transcript-{seeded["id"]}.srt"'
    assert reply.headers["content-disposition"] == name
    assert "Hello their." in reply.text
    assert "Ali" in reply.text
    # The second speaker has no name, so they are the diarizer's second speaker.
    assert "Speaker 2" in reply.text


@pytest.mark.parametrize("fmt", ["vtt", "txt"])
def test_every_likho_format_exports(seeded: dict[str, Any], fmt: str) -> None:  # noqa: F811
    reply = page().get(f"/api/transcripts/{seeded['id']}/export/{fmt}")
    assert reply.status_code == 200
    assert "Fine." in reply.text


def test_a_format_likho_does_not_write_is_404(seeded: dict[str, Any]) -> None:  # noqa: F811
    reply = page().get(f"/api/transcripts/{seeded['id']}/export/docx")
    assert reply.status_code == 404
    assert "srt" in reply.json()["message"]


def test_nothing_is_written_beside_the_recording(seeded: dict[str, Any]) -> None:  # noqa: F811
    page().get(f"/api/transcripts/{seeded['id']}/export/srt")
    assert sorted(p.name for p in seeded["audio"].parent.iterdir()) == ["talk.json", "talk.wav"]
```

If pyright (`just typecheck`, the tests config) refuses the cross-module import, move `page`, `tokens` and `seeded` from `tests/test_ui_edits.py` into `tests/conftest.py` unchanged and drop the import line; both test files then find them there.

Run: `uv run pytest tests/test_ui_export.py -q`
Expected: FAIL, 404 on `/export/srt`.

- [ ] **Step 4: Build likho's payload from the edit list in `dsj/ui/edits.py`**

Add `"as_payload"`, `"display_name"`, `"labels_of"` to `__all__`, `import re` and `from collections.abc import Sequence`, then:

```python
# A diarizer's own label, which the page shows as "Speaker n" by its place in
# the transcript's list (ui/src/features/transcript/document.ts, speakerName).
_DIARIZER_LABEL = re.compile(r"SPEAKER_\d+")


def labels_of(opened: Opened) -> list[str]:
    """The transcript's speaker labels, then any the list uses that it lacks, in order of first use.

    The page reads speakers the same way (readContent.ts, speakerLabels), so a
    speaker a person added in Review is "Speaker 3" in both.
    """
    labels = list(opened.legend)
    for entry in opened.doc.content:
        if isinstance(entry, hatao.Paragraph) and entry.speaker and entry.speaker not in labels:
            labels.append(entry.speaker)
    return labels


def display_name(label: str | None, labels: Sequence[str], names: Mapping[str, str]) -> str | None:
    """The name a person gave `label`, else "Speaker n" for a diarizer's label, else the label."""
    if label is None:
        return None
    if label in names:
        return names[label]
    if _DIARIZER_LABEL.fullmatch(label) and label in labels:
        return f"Speaker {list(labels).index(label) + 1}"
    return label


def as_payload(opened: Opened) -> dict[str, Any]:
    """The edit list as a transcript dsj likho can write (#EXPORT).

    One sentence per paragraph mark, its words as edited (a correction, #83,
    reads as corrected), each speaker under the name a person gave them.
    Paragraphs with no words are left out, as likho leaves them out.
    """
    labels = labels_of(opened)
    sentences: list[dict[str, Any]] = []
    tokens: list[dict[str, Any]] | None = None
    speaker: int | None = None

    def close() -> None:
        if tokens:
            sentences.append({
                "start": tokens[0]["t"],
                "end": max(t["e"] for t in tokens),
                "text": "".join(t["w"] for t in tokens),
                "speaker": speaker,
                "tokens": tokens,
            })

    for entry in opened.doc.content:
        if isinstance(entry, hatao.Paragraph):
            close()
            tokens = []
            speaker = None if entry.speaker is None else labels.index(entry.speaker)
            continue
        if tokens is not None and entry.text:
            tokens.append({"t": entry.source_start, "e": entry.source_end, "w": entry.text})
    close()
    payload: dict[str, Any] = {"sentences": sentences}
    if labels:
        payload["speakers"] = [display_name(label, labels, opened.doc.names) for label in labels]
    return payload
```

`close` reads the enclosing `tokens` and `speaker` at call time, which is after each paragraph's words are in.

- [ ] **Step 5: Add the route to `dsj/ui/routes/marks.py`**

Add `from fastapi import Response` beside `APIRouter, HTTPException`, `from dsj import likho`, and:

```python
@router.get(
    "/transcripts/{transcript_id}/export/{fmt}",
    response_class=Response,
    responses={200: {"content": {"text/plain": {}, "text/vtt": {}}}},
)
def export(transcript_id: str, fmt: str) -> Response:
    """The transcript as edited, as SRT, WebVTT or plain text, by dsj likho's own writers (#EXPORT).

    A download, by the transcript's id: nothing is written on this machine,
    and no path reaches the page (#112 rule 5).
    """
    write = likho.EXPORTERS.get(fmt)
    if write is None:
        known = ", ".join(sorted(likho.EXPORTERS))
        raise HTTPException(404, f"There is no export format {fmt!r}; there are {known}.")
    found = _id(transcript_id)
    text = write(edits.as_payload(edits.open_edits(found)))
    return Response(
        content=text,
        media_type="text/vtt; charset=utf-8" if fmt == "vtt" else "text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="transcript-{found}.{fmt}"'},
    )
```

Run: `uv run pytest tests/test_ui_export.py -q` then `uv run just api`.
Expected: PASS; `schema.d.ts` gains the export path.

- [ ] **Step 6: Write the failing page test**

Create `ui/tests/unit/export.test.ts`:

```ts
import { afterEach, describe, expect, it, vi } from "vitest";

const fetchMock = vi.hoisted(() => {
  const mock = vi.fn<(request: Request) => Promise<Response>>();
  globalThis.fetch = mock as unknown as typeof fetch;
  return mock;
});

import { exportTranscript } from "../../src/features/transcript/exportFile";

afterEach(() => vi.restoreAllMocks());

describe("exportTranscript", () => {
  it("downloads the server's text under the recording's title", async () => {
    fetchMock.mockResolvedValue(new Response("1\n00:00:00,200 --> 00:00:00,900\nHello.\n", { headers: { "content-type": "text/plain" } }));
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();
    const clicked: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(this.download);
    });
    await exportTranscript(7, "srt", "Sat 20 Sep, 9:42 am");
    expect(new URL(fetchMock.mock.calls[0]?.[0].url ?? "").pathname).toBe("/api/transcripts/7/export/srt");
    expect(clicked).toEqual(["Sat 20 Sep, 9.42 am.srt"]);
  });
});
```

Run: `cd ui && npx vitest run tests/unit/export.test.ts`
Expected: FAIL, `Failed to resolve import "../../src/features/transcript/exportFile"`.

- [ ] **Step 7: Write `ui/src/features/transcript/exportFile.ts`**

```ts
// The transcript as edited, downloaded from the reader's menu (#EXPORT):
// dsj likho's own SRT, WebVTT or text, worked out on the server from the edit
// list, so corrections and speaker names are in it. Fetched, not linked: a
// link sends no Authorization header, and only the media routes take the
// token in the query (#59).

import { api } from "@/api/client";
import { ApiError, fromBody } from "@/features/errors/appError";

export type ExportFormat = "srt" | "vtt" | "txt";

/** `title` as a file name: the characters Finder or a phone refuses in one become a dot or a space. */
function fileStem(title: string): string {
  return title.replace(/:/g, ".").replace(/[/\\*?"<>|]+/g, " ").trim() || "transcript";
}

export async function exportTranscript(transcriptId: number, format: ExportFormat, title: string): Promise<void> {
  const route = `/api/transcripts/${transcriptId}/export/${format}`;
  const { data, error, response } = await api.GET("/api/transcripts/{transcript_id}/export/{fmt}", {
    params: { path: { transcript_id: String(transcriptId), fmt: format } },
    parseAs: "text",
  });
  if (data === undefined) throw new ApiError(fromBody(error, response, route));
  const url = URL.createObjectURL(new Blob([data], { type: "text/plain;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `${fileStem(title)}.${format}`;
  link.click();
  // Let the download start before the address goes.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
```

Run: `cd ui && npx vitest run tests/unit/export.test.ts`
Expected: PASS.

- [ ] **Step 8: Put Export in the menu**

In `EditablePage` (`ui/src/features/transcript/TranscriptPage.tsx`), pass `MoreMenu` an `extra` (imports: `DropdownMenuItem`, `DropdownMenuLabel`, `DropdownMenuSeparator` from `@/components/ui/dropdown-menu`; `exportTranscript`, `type ExportFormat` from `./exportFile`):

```tsx
            extra={
              <>
                <DropdownMenuSeparator />
                <DropdownMenuLabel>Export as edited</DropdownMenuLabel>
                {(
                  [
                    ["srt", "Subtitles (SRT)"],
                    ["vtt", "Subtitles (WebVTT)"],
                    ["txt", "Text"],
                  ] as [ExportFormat, string][]
                ).map(([format, label]) => (
                  <DropdownMenuItem
                    key={format}
                    onClick={() =>
                      exportTranscript(transcriptId, format, fileName(opened.recording.path)).catch((thrown: unknown) =>
                        showError(fromThrown(thrown, `/api/transcripts/${transcriptId}/export/${format}`)),
                      )
                    }
                  >
                    {label}
                  </DropdownMenuItem>
                ))}
              </>
            }
```

(Task 8 swaps `fileName(opened.recording.path)` for the recording's display title.)

- [ ] **Step 9: Gate, build**

Run: `uv run just check` (paste the last line), `uv run just ui-build`.
Expected: green.

- [ ] **Step 10: Look at it**

Run: `uv run python scratch/ui_shots.py --label t6 menu`
Expected: 4 PNGs. Check: "Export as edited" is a quiet label over three items, the menu still fits the 390 px window without sideways scroll, and every item is a full-width row.

- [ ] **Step 11: Commit**

```bash
git add dsj/ui/edits.py dsj/ui/routes/marks.py ui/src/api/schema.d.ts ui/src/features/transcript/exportFile.ts \
  ui/src/features/transcript/TranscriptPage.tsx tests/test_ui_export.py ui/tests/unit/export.test.ts
git add -A -- dsj/ui/static/
git commit -m "feat: export the edited transcript as SRT, WebVTT or text"
```

(`tests/conftest.py` too, if Step 3 moved the fixture there.)

---

### Task 7: Library backend: titles, a language tag, review progress

**Files:**
- Modify: `dsj/ui/store.py` (schema version 5: `recordings.title`, `transcripts.urdu_share`; `set_title`; `backfill_urdu_share`)
- Create: `dsj/ui/review.py` (where a review lives, and how far it got)
- Modify: `dsj/ui/schemas.py` (`Recording.title`, `Transcript.language_tag`, `review_checked`, `review_total`, `TitleUpdate`, `LanguageTag`), `dsj/ui/routes/recording.py` (`PATCH /api/recordings/{id}`; the tag and the progress on each row)
- Modify: `ui/src/api/schema.d.ts` (generated)
- Test: `tests/test_ui_library.py`, `tests/test_library.py`, `tests/test_import.py`, `tests/test_ui_edits.py`; every ui test fixture with a `RecordingRow` or `TranscriptRow` literal: `ui/tests/unit/bleep.test.tsx`, `correction.test.tsx`, `edit.test.tsx`, `library.test.tsx`, `video.test.tsx`, `render.test.tsx`, `transcript.test.tsx`, `transcribe.test.tsx`, `rail.test.tsx`, `reader.test.tsx`

**Interfaces:**
- Consumes: `edits_path` (its key names the review file too).
- Produces: `store.Recording.title: str | None`, `store.Transcript.urdu_share: float | None`, `Library.set_title(recording_id: int, title: str | None) -> Recording`, `Library.backfill_urdu_share() -> int`; `review.review_path(json_path: Path) -> Path`, `review.progress(json_path: Path) -> tuple[int, int] | None`; wire `Recording.title`, `Transcript.language_tag: "urdu" | "mixed" | "english" | null`, `Transcript.review_checked`, `Transcript.review_total`; route `PATCH /api/recordings/{recording_id}` taking `TitleUpdate { title: str | None }` and answering `Recording`.

- [ ] **Step 1: File the issue (AGENTS.md rule 1)**

Run: `gh issue create --title "library: recording titles, a script share, review progress (Hashiya A)" --body "Schema v5 adds recordings.title and transcripts.urdu_share; PATCH /api/recordings/{id}; language_tag and review progress on each transcript row. Plan: docs/superpowers/plans/2026-10-07-hashiya-review-mode.md, Task 7."` and put its number where the code says `#LIBRARY`.

- [ ] **Step 2: Write the failing library tests**

Append to `tests/test_ui_library.py`:

```python
# -- titles, a language tag, review progress (#LIBRARY) --------------------------


def test_a_title_is_set_trimmed_kept_and_cleared(two_recordings: dict[str, Path]) -> None:
    client = page()
    row = client.get("/api/recordings").json()[0]
    assert row["title"] is None
    reply = client.patch(f"/api/recordings/{row['id']}", json={"title": "  Sunday call  "})
    assert reply.status_code == 200, reply.text
    assert reply.json()["title"] == "Sunday call"
    assert page().get("/api/recordings").json()[0]["title"] == "Sunday call"
    assert client.patch(f"/api/recordings/{row['id']}", json={"title": ""}).json()["title"] is None


def test_a_title_for_no_such_recording_is_404_and_a_long_one_is_422(
    two_recordings: dict[str, Path],
) -> None:
    client = page()
    assert client.patch("/api/recordings/999", json={"title": "x"}).status_code == 404
    rid = client.get("/api/recordings").json()[0]["id"]
    assert client.patch(f"/api/recordings/{rid}", json={"title": "x" * 201}).status_code == 422


def test_each_transcript_says_whether_it_is_urdu_mixed_or_english(tmp_path: Path) -> None:
    urdu_audio = wav(tmp_path / "urdu.wav", 550)
    urdu = transcript(
        tmp_path / "urdu.json", urdu_audio, LATER,
        sentences=[{
            "start": 0.0, "end": 1.0, "tokens": [],
            "text": " آج صبح ہم نے دیکھا",  # noqa: RUF001
        }],
    )
    mixed = transcript(tmp_path / "mixed.json", wav(tmp_path / "mixed.wav", 660), LATER)
    english = transcript(tmp_path / "english.json", wav(tmp_path / "english.wav", 770), LATER)
    with Library.open() as library:
        library.record_run(urdu, engine="whisper", language="ur")
        library.record_run(mixed, engine="whisper", language="ur")  # --roman-urdu writes Latin
        library.record_run(english, engine="parakeet")
    tags = {
        row["path"].rsplit("/", 1)[-1]: row["transcripts"][0]["language_tag"]
        for row in page().get("/api/recordings").json()
    }
    assert tags == {"urdu.wav": "urdu", "mixed.wav": "mixed", "english.wav": "english"}


def test_review_progress_is_none_until_a_review_exists(two_recordings: dict[str, Path]) -> None:
    from dsj.ui.review import review_path

    row = page().get("/api/recordings").json()[0]
    first = row["transcripts"][0]
    assert (first["review_checked"], first["review_total"]) == (None, None)
    path = review_path(two_recordings["unlabelled"])
    path.parent.mkdir(parents=True, exist_ok=True)
    states = ["checked", "unchecked", "checked"]
    path.write_text(json.dumps({"segments": [{"state": state} for state in states]}))
    again = page().get("/api/recordings").json()[0]["transcripts"][0]
    assert (again["review_checked"], again["review_total"]) == (2, 3)
```

Append to `tests/test_library.py`:

```python
def test_a_version_3_library_gains_titles_and_script_shares_and_keeps_its_rows(
    tmp_path: Path,
) -> None:
    """Schema 4 adds recordings.title, 5 transcripts.urdu_share (#LIBRARY)."""
    media = tmp_path / "old.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
         "sine=frequency=440:duration=1", str(media)],
        check=True,
    )
    with Library.open() as library:
        rid = library.add_recording(media).id
    with sqlite3.connect(store.library_path()) as con:
        con.execute("ALTER TABLE recordings DROP COLUMN title")
        con.execute("ALTER TABLE transcripts DROP COLUMN urdu_share")
        con.execute("PRAGMA user_version = 3")
    with Library.open() as library:
        found = library.recording(rid)
        assert found is not None and found.title is None
        assert library.set_title(rid, "Kept").title == "Kept"
    with sqlite3.connect(store.library_path()) as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == store.SCHEMA_VERSION == 5
```

(`tests/test_library.py` already imports `sqlite3`, `subprocess`, `Path`, `store` and `Library`.)

Run: `uv run pytest tests/test_ui_library.py tests/test_library.py -q -k "title or tag or progress or version_3"`
Expected: FAIL (`KeyError: 'title'`, `no such column: title`).

- [ ] **Step 3: Take the library to version 5 in `dsj/ui/store.py`**

1. `SCHEMA_VERSION = 5`, and extend the comment above it: "version 4 `recordings.title` and version 5 `transcripts.urdu_share` (#LIBRARY)".
2. In `_SCHEMA`, add `title TEXT,` after `unreadable TEXT,` in `recordings` (before the `CHECK`), and `urdu_share REAL` after `last_edited_at TEXT` in `transcripts` (with the comma after `last_edited_at TEXT`).
3. `_MIGRATIONS` gains:

```python
    # A title a person gave the recording in the app (#LIBRARY). NULL for every
    # row: the page derives one from the file's name until someone types one.
    3: "ALTER TABLE recordings ADD COLUMN title TEXT",
    # The share of the transcript's letters in Urdu script, 0 to 1, which the
    # library row's language tag reads (#LIBRARY). NULL until the list fills it
    # in (Library.backfill_urdu_share), once per transcript.
    4: "ALTER TABLE transcripts ADD COLUMN urdu_share REAL",
```

4. `_RECORDING_COLUMNS` ends `"r.first_seen, r.missing, r.unreadable, r.title"`; `_TRANSCRIPT_COLUMNS` ends `"mark_count, language, last_edited_at, urdu_share"`.
5. `Recording` gains `title: str | None = None` (a comment: "The title a person gave it in the app (#LIBRARY), else None: the page derives one."); `_recording` passes `title=row[10]`. `Transcript` gains `urdu_share: float | None = None` (comment: "The share of its letters in Urdu script, 0 to 1, or None until read."); `_transcript` passes `urdu_share=row[11]`.
6. Add, beside `_counts`:

```python
# Urdu's script blocks: Arabic, its Supplement and Extended-A, and the two
# Presentation Forms blocks (ui/src/lib/script.ts reads the same ranges).
_URDU_LETTER = re.compile("[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")


def _urdu_share(payload: dict[str, Any]) -> float:
    """The share of the transcript's letters in Urdu script, to three places; 0 with no letters."""
    letters = urdu = 0
    for sentence in cast("list[dict[str, Any]]", payload.get("sentences") or []):
        for ch in str(sentence.get("text") or ""):
            if ch.isalpha():
                letters += 1
                if _URDU_LETTER.match(ch):
                    urdu += 1
    return round(urdu / letters, 3) if letters else 0.0
```

   and `import re` at the top.
7. `_insert_transcript` writes it: add `urdu_share` to the column list and `_urdu_share(payload)` to the values (nine `?`). `_refresh_transcript` sets it: `"... mark_count = ?, urdu_share = ? WHERE id = ?"` with `_urdu_share(payload)` before `transcript_id`.
8. Add to `Library`, under writing:

```python
    def set_title(self, recording_id: int, title: str | None) -> Recording:
        """Give a recording a title of its own, or None to let the page derive one (#LIBRARY).

        Raises:
            LibraryError: if there is no recording with this id.
        """
        with self._db:
            changed = self._db.execute(
                "UPDATE recordings SET title = ? WHERE id = ?", (title, recording_id)
            ).rowcount
        if changed == 0:
            raise LibraryError(f"the library has no recording with id {recording_id}.")
        return self._must_recording(recording_id)

    def backfill_urdu_share(self) -> int:
        """Read the script share of every transcript that has none yet; returns how many it filled.

        Once per transcript: a library from before version 5 pays one read of
        each JSON file, on the first listing after the upgrade. A file that is
        gone or unreadable is left NULL and read again next time.
        """
        rows = self._db.execute(
            "SELECT id, json_path FROM transcripts WHERE urdu_share IS NULL"
        ).fetchall()
        filled = 0
        with self._db:
            for transcript_id, json_path in rows:
                try:
                    payload = _read_payload(Path(json_path))
                except NotATranscript:
                    continue
                self._db.execute(
                    "UPDATE transcripts SET urdu_share = ? WHERE id = ?",
                    (_urdu_share(payload), transcript_id),
                )
                filled += 1
        return filled
```

- [ ] **Step 4: Keep the older migration tests honest**

The fresh schema now has both new columns, so a test that hand-builds an older library must drop them too:
- `tests/test_import.py`, the test that sets `PRAGMA user_version = 1` and asserts `== store_mod.SCHEMA_VERSION == 3`: add `con.execute("ALTER TABLE recordings DROP COLUMN title")` and `con.execute("ALTER TABLE transcripts DROP COLUMN urdu_share")` beside its two `DROP COLUMN` lines, and change `== 3` to `== 5`.
- `tests/test_ui_edits.py`, `test_a_version_2_library_gains_last_edited_at_and_keeps_its_rows`: add the same two `DROP COLUMN` lines, and change `== 3` to `== 5`.
- `tests/test_import.py`, `test_a_reader_waiting_on_a_migration_finds_it_done`, runs migration 1 alone and is unchanged.

- [ ] **Step 5: Write `dsj/ui/review.py`'s first part**

```python
"""A transcript's review (Hashiya spec, Review mode): which sentences a person has checked.

This first part says where a review lives and how far it has got, for the
library list (#LIBRARY). The review document itself, its routes and the
answer-key export are added with Review mode's backend.

A review is filed beside the library in `reviews/`, under the same key as the
transcript's edit list (dsj/ui/edits.py, edits_path): the transcript JSON's
path, so a rebuilt library finds it again, and never beside the recording.

Plain Python, no fastapi.
"""

from __future__ import annotations

__all__ = ["progress", "review_path"]

import json
import logging
from pathlib import Path
from typing import Any, cast

from dsj.ui.edits import edits_path
from dsj.ui.store import library_path

_log = logging.getLogger(__name__)


def review_path(json_path: Path) -> Path:
    """Where the review of the transcript at `json_path` is kept."""
    return library_path().parent / "reviews" / edits_path(json_path).name


def progress(json_path: Path) -> tuple[int, int] | None:
    """How many of the review's sentences are checked, and how many it has; None with no review.

    A review file that cannot be read is logged and left out of the list: the
    library still lists every recording, and opening the review says what is
    wrong with it.
    """
    path = review_path(json_path)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        segments = cast("list[dict[str, Any]]", raw["segments"])
        checked = sum(1 for s in segments if s.get("state") == "checked")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        _log.warning("the review at %s could not be read for the library list: %s", path, exc)
        return None
    return checked, len(segments)
```

- [ ] **Step 6: Carry it on the wire**

In `dsj/ui/schemas.py`: add `"LanguageTag"` and `"TitleUpdate"` to `__all__`; add

```python
# What the library row calls a transcript's language (Hashiya spec, Library):
# worked out from its run and its script by dsj/ui/routes/recording.py.
type LanguageTag = Literal["urdu", "mixed", "english"]
```

`Transcript` gains:

```python
    # Urdu, mixed or English, or None when nothing says (#LIBRARY).
    language_tag: LanguageTag | None
    # How far its review got, or both None when nobody has reviewed it.
    review_checked: int | None
    review_total: int | None
```

`Recording` gains `title: str | None` (comment: "A title a person gave it, else None: the page derives one from the file's name."), and add:

```python
class TitleUpdate(BaseModel):
    """A recording's title; empty or None takes it away, so the page derives one again."""

    title: str | None = Field(default=None, max_length=200)
```

In `dsj/ui/routes/recording.py`:

```python
from dsj.ui.review import progress
from dsj.ui.schemas import LanguageTag, Recording, TitleUpdate, Transcript

# A transcript is Urdu when half its letters or more are in Urdu script, and
# mixed when a twentieth are, or when it was run as Urdu and written in Latin
# letters (--roman-urdu sets language "ur"). Set from the measured scripts on
# #148's public Urdu-English podcast (README, "The model matters more than it
# looks"; .agents/skills/dsj/references/engines.md): whisper-large-v3-turbo
# writes 3% Urdu script under --roman-urdu and 78% under --language ur, the
# full model 61 to 63% either way. English runs write none.
URDU_SHARE = 0.5
MIXED_SHARE = 0.05


def _language_tag(t: store_mod.Transcript) -> LanguageTag | None:
    """Urdu, mixed or English, for the library row; None for an old row not yet read."""
    share = t.urdu_share
    if share is not None and share >= URDU_SHARE:
        return "urdu"
    # parakeet and sherpa read European languages only (engines.md).
    if t.engine in ("parakeet", "sherpa"):
        return "english"
    if t.language == "ur" or (share is not None and share >= MIXED_SHARE):
        return "mixed"
    return None if share is None else "english"
```

In `_row`, each `Transcript(...)` gains (compute `done = progress(t.json_path)` first, inside the comprehension via a helper):

```python
def _transcript_row(t: store_mod.Transcript) -> Transcript:
    done = progress(t.json_path)
    return Transcript(
        id=t.id,
        finished_at=t.finished_at,
        engine=t.engine,
        model=t.model,
        diarized=t.diarized,
        speaker_count=t.speaker_count,
        mark_count=t.mark_count,
        language=t.language,
        last_edited_at=t.last_edited_at,
        language_tag=_language_tag(t),
        review_checked=None if done is None else done[0],
        review_total=None if done is None else done[1],
    )
```

and `_row` uses `transcripts=[_transcript_row(t) for t in library.transcripts(rec.id)]` and passes `title=rec.title`. In `recordings()`, call `library.backfill_urdu_share()` after `library.refresh_missing()`. Add:

```python
@router.patch("/recordings/{recording_id}")
def retitle(recording_id: str, update: TitleUpdate) -> Recording:
    """Give a recording a title of its own, or take it away with an empty one (#LIBRARY)."""
    if not (recording_id.isascii() and recording_id.isdigit()):
        raise HTTPException(404, f"There is no recording {recording_id!r} in the library.")
    title = (update.title or "").strip() or None
    with Library.open() as library:
        if library.recording(int(recording_id)) is None:
            raise HTTPException(404, f"There is no recording {recording_id} in the library.")
        return _row(library, library.set_title(int(recording_id), title))
```

Run: `uv run pytest tests/test_ui_library.py tests/test_library.py tests/test_import.py tests/test_ui_edits.py -q`
Expected: PASS.

- [ ] **Step 7: Regenerate the types and fix every fixture**

Run: `uv run just api`. Then in each ui test file listed under **Files**, add `title: null,` after `unreadable: null,` in every `RecordingRow` literal (and in the inline JSON recordings the fetch mocks answer with), and `language_tag: null, review_checked: null, review_total: null,` after `last_edited_at: null` in every `TranscriptRow` literal. Find them with `grep -n "unreadable: null\|last_edited_at: null" ui/tests/unit/*.ts*`.

Run: `cd ui && ./node_modules/.bin/tsc --noEmit && npx vitest run`
Expected: no type errors; all unit tests pass.

- [ ] **Step 8: Gate and build**

Run: `uv run just check` (paste the last line), then `uv run just ui-build` (the regenerated `schema.d.ts` is under `ui/src`).
Expected: green. The page looks the same; Task 8 draws the new fields.

- [ ] **Step 9: Commit**

```bash
git add dsj/ui/store.py dsj/ui/review.py dsj/ui/schemas.py dsj/ui/routes/recording.py ui/src/api/schema.d.ts \
  tests/test_ui_library.py tests/test_library.py tests/test_import.py tests/test_ui_edits.py \
  ui/tests/unit/bleep.test.tsx ui/tests/unit/correction.test.tsx ui/tests/unit/edit.test.tsx \
  ui/tests/unit/library.test.tsx ui/tests/unit/video.test.tsx ui/tests/unit/render.test.tsx \
  ui/tests/unit/transcript.test.tsx ui/tests/unit/transcribe.test.tsx ui/tests/unit/rail.test.tsx \
  ui/tests/unit/reader.test.tsx
git add -A -- dsj/ui/static/
git commit -m "feat(library): titles, a language tag and review progress per row"
```

---

### Task 8: The library page: readable titles, rows, versions, search, states

**Files:**
- Create (shadcn): `ui/src/components/ui/collapsible.tsx`, `ui/src/components/ui/skeleton.tsx`
- Create: `ui/src/features/library/title.ts`, `ui/src/features/library/RecordingRow.tsx`, `ui/src/features/library/retitle.ts`
- Modify: `ui/src/features/library/LibraryPage.tsx` (whole file), `ui/src/features/library/describe.ts` (`languageLabel`, `progressLabel`), `ui/src/features/transcribe/TranscribeControl.tsx` (`label` prop), `ui/src/features/transcript/TranscriptPage.tsx` (title and export name)
- Test: `ui/tests/unit/title.test.ts` (new), `ui/tests/unit/library.test.tsx`, `ui/tests/e2e/journeys.spec.ts`, `ui/tests/e2e/reader.spec.ts`, `ui/tests/e2e/correction.spec.ts`, `ui/tests/e2e/capability.spec.ts`

**Interfaces:**
- Consumes: Task 7's wire fields and `PATCH /api/recordings/{id}`; Task 3's `speakerColour`, `versionLabel`; Task 2's `AppBar`.
- Produces: `stampOf(name: string): Date | null`, `whenTitle(when: Date, now?: Date): string`, `displayTitle(row: Pick<RecordingRow, "title" | "path">, now?: Date): string`; `retitle(recordingId: number, title: string): Promise<RecordingRow>`; `languageLabel(tag): string | null`, `progressLabel(t: TranscriptRow): string | null`; `TranscribeControl({ recording, label? })`.

- [ ] **Step 1: Load impeccable: read /Users/moiz/.claude/skills/impeccable/reference/craft-floor.md before editing**

Read it in full; build to it without announcing its checklist.

- [ ] **Step 2: Add the primitives**

Run, from `ui/`: `npx shadcn@4.21.0 add collapsible skeleton --dry-run`, then `npx shadcn@4.21.0 add collapsible skeleton`. Confirm `Collapsible`, `CollapsibleTrigger`, `CollapsibleContent` and `Skeleton` with `grep -n "^export" src/components/ui/collapsible.tsx src/components/ui/skeleton.tsx`.

- [ ] **Step 3: Write the failing title test**

Create `ui/tests/unit/title.test.ts`:

```ts
// A recording's readable title (Hashiya spec, Library: "default from the
// file's timestamp, e.g. 'Sat 20 Sep, 9:42 am', else the filename").
import { describe, expect, it } from "vitest";

import { displayTitle, stampOf } from "../../src/features/library/title";

// 7 Oct 2025: the same year as most stamps below, so they print without one.
const NOW = new Date(2025, 9, 7, 12, 0);

describe("displayTitle", () => {
  it.each([
    ["Screen Recording 2025-09-20 at 9.42.00 AM.mov", "Sat 20 Sep, 9:42 am"],
    ["Screen Recording 2025-09-20 at 12.10.00 AM.mov", "Sat 20 Sep, 12:10 am"],
    ["20250920_094234.m4a", "Sat 20 Sep, 9:42 am"],
    ["2025-09-20 21.05.10.m4a", "Sat 20 Sep, 9:05 pm"],
    ["Recording 2024-03-05T21-05.wav", "Tue 5 Mar 2024, 9:05 pm"],
    ["standup.wav", "standup.wav"],
  ])("%s reads as %s", (name, title) => {
    expect(displayTitle({ title: null, path: `/Users/me/Recordings/${name}` }, NOW)).toBe(title);
  });

  it("prefers a title a person gave it", () => {
    expect(displayTitle({ title: "Sunday call", path: "/r/20250920_094234.m4a" }, NOW)).toBe("Sunday call");
  });
});

describe("stampOf", () => {
  it.each(["20251340_101010.m4a", "2025-02-30 10.00.m4a", "2025-09-20 at 13.00.00 PM.mov", "notes 2025.txt"])(
    "finds no date in %s",
    (name) => {
      expect(stampOf(name)).toBeNull();
    },
  );
});
```

Run: `cd ui && npx vitest run tests/unit/title.test.ts`
Expected: FAIL, `Failed to resolve import "../../src/features/library/title"`.

- [ ] **Step 4: Write `ui/src/features/library/title.ts`**

```ts
// A recording's title as the library shows it (Hashiya spec, Library: "a
// readable title (default from the file's timestamp, e.g. 'Sat 20 Sep, 9:42
// am', else the filename; renamable inline)"; critique: "a library of
// filenames").
//
// Recorders name a file by when it started, in a handful of shapes: macOS's
// "Screen Recording 2025-09-20 at 9.42.00 AM.mov", phone recorders'
// "20250920_094234.m4a", "2025-09-20 09.42.34.m4a" and
// "Recording 2025-09-20T21-05.wav". The stamp is read as this Mac's local
// time, which is what the recorder wrote.

import { fileName } from "./describe";
import type { RecordingRow } from "./types";

const STAMP = /(\d{4})-?(\d{2})-?(\d{2})(?:\s+at\s+|[ _T])(\d{1,2})[.:-]?(\d{2})(?:[.:-]?(\d{2}))?(?:\s*([AaPp])\.?[Mm]\.?)?/;
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** When a file's name says it was recorded, or null when it says nothing a real date can be made of. */
export function stampOf(name: string): Date | null {
  const found = STAMP.exec(name);
  if (found === null) return null;
  const year = Number(found[1]);
  const month = Number(found[2]);
  const day = Number(found[3]);
  let hour = Number(found[4]);
  const minute = Number(found[5]);
  const half = found[7]?.toLowerCase();
  if (half !== undefined) {
    if (hour < 1 || hour > 12) return null;
    hour = (hour % 12) + (half === "p" ? 12 : 0);
  }
  if (month < 1 || month > 12 || hour > 23 || minute > 59) return null;
  const when = new Date(year, month - 1, day, hour, minute);
  // 30 February rolls over into March: a date that moved was not a date.
  return when.getMonth() === month - 1 && when.getDate() === day ? when : null;
}

/** "Sat 20 Sep, 9:42 am", with the year when it is not this one. */
export function whenTitle(when: Date, now: Date = new Date()): string {
  const year = when.getFullYear() === now.getFullYear() ? "" : ` ${when.getFullYear()}`;
  const hour = when.getHours() % 12 || 12;
  const half = when.getHours() < 12 ? "am" : "pm";
  const minute = String(when.getMinutes()).padStart(2, "0");
  return `${DAYS[when.getDay()] ?? ""} ${when.getDate()} ${MONTHS[when.getMonth()] ?? ""}${year}, ${hour}:${minute} ${half}`;
}

/** The title a person gave the recording, else when its file's name says it was made, else that name. */
export function displayTitle(row: Pick<RecordingRow, "title" | "path">, now?: Date): string {
  if (row.title) return row.title;
  const name = fileName(row.path);
  const when = stampOf(name);
  return when === null ? name : whenTitle(when, now);
}
```

Run: `cd ui && npx vitest run tests/unit/title.test.ts`
Expected: PASS.

- [ ] **Step 5: Add the row's words to `ui/src/features/library/describe.ts`**

```ts
const LANGUAGES = { urdu: "Urdu", mixed: "Mixed", english: "English" } as const;

/** "Urdu", "Mixed" or "English" (Hashiya spec, Library), or null when nothing says. */
export function languageLabel(tag: TranscriptRow["language_tag"]): string | null {
  return tag === null ? null : LANGUAGES[tag];
}

/** "212 of 252 checked", or null when nobody has reviewed it. */
export function progressLabel(t: TranscriptRow): string | null {
  if (t.review_checked === null || t.review_total === null) return null;
  return `${t.review_checked.toLocaleString("en")} of ${t.review_total.toLocaleString("en")} checked`;
}
```

- [ ] **Step 6: Write `ui/src/features/library/retitle.ts`**

```ts
// Renaming a recording (Hashiya spec, Library: "renamable inline").

import { api } from "@/api/client";
import { ApiError, fromBody } from "@/features/errors/appError";
import type { RecordingRow } from "./types";

/** Give a recording a title; an empty one takes it away. Its row as the server now has it. */
export async function retitle(recordingId: number, title: string): Promise<RecordingRow> {
  const route = `/api/recordings/${recordingId}`;
  const { data, error, response } = await api.PATCH("/api/recordings/{recording_id}", {
    params: { path: { recording_id: String(recordingId) } },
    body: { title },
  });
  if (data === undefined) throw new ApiError(fromBody(error, response, route));
  return data;
}
```

- [ ] **Step 7: Give `TranscribeControl` a label**

In `ui/src/features/transcribe/TranscribeControl.tsx`, the signature becomes `export function TranscribeControl({ recording, label = "Transcribe" }: { recording: RecordingRow; label?: string })` and the button reads `{label}` instead of `Transcribe`; its classes become `className="h-11 sm:h-9"` (44 px on the phone).

- [ ] **Step 8: Write `ui/src/features/library/RecordingRow.tsx`**

```tsx
import { Pencil } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { fromThrown, showError } from "@/features/errors/appError";
import { isFinished, useJobFor } from "@/features/transcribe/jobs";
import { TranscribeControl } from "@/features/transcribe/TranscribeControl";
import { speakerColour } from "@/features/transcript/speakers";
import { transcriptHref } from "@/lib/route";
import {
  durationLabel,
  fileName,
  languageLabel,
  marksLabel,
  pictureNote,
  progressLabel,
  sizeLabel,
  speakersLabel,
  versionLabel,
  whenLabel,
} from "./describe";
import { relinkRecording } from "./imports";
import { retitle } from "./retitle";
import { displayTitle } from "./title";
import type { RecordingRow, TranscriptRow } from "./types";

/** Speakers as coloured dots, one a speaker up to six (Hashiya spec, Library). */
function SpeakerDots({ count }: { count: number }) {
  return (
    <span className="flex items-center gap-1" aria-label={`${count} ${count === 1 ? "speaker" : "speakers"}`}>
      {Array.from({ length: Math.min(count, 6) }, (_, i) => (
        <span key={i} aria-hidden className="size-2.5 rounded-full" style={{ background: speakerColour(i) }} />
      ))}
      {count > 6 && <span aria-hidden>+{count - 6}</span>}
    </span>
  );
}

function Title({ row, title, href, onChanged }: { row: RecordingRow; title: string; href: string | null; onChanged: () => void }) {
  const [renaming, setRenaming] = useState(false);
  if (renaming) {
    return (
      <input
        autoFocus
        aria-label="Title"
        defaultValue={title}
        dir="auto"
        className="relative z-10 w-full rounded-md border border-input bg-background px-2 py-1 font-reading text-lg"
        onFocus={(event) => event.currentTarget.select()}
        onBlur={() => setRenaming(false)}
        onKeyDown={(event) => {
          if (event.key === "Escape") setRenaming(false);
          if (event.key !== "Enter") return;
          event.preventDefault();
          const typed = event.currentTarget.value.trim();
          // The title it shows without one is not a title someone typed.
          const next = typed === displayTitle({ title: null, path: row.path }) ? "" : typed;
          retitle(row.id, next).then(onChanged, (thrown: unknown) => showError(fromThrown(thrown, `/api/recordings/${row.id}`)));
          setRenaming(false);
        }}
      />
    );
  }
  return (
    <div className="flex min-w-0 items-center gap-1">
      {href === null ? (
        <span className="truncate font-reading text-lg font-semibold">{title}</span>
      ) : (
        // The whole row opens the latest transcript (critique: "grey line as
        // the only link"): the link's box is stretched over the row, and the
        // row's own controls sit above it.
        <a href={href} className="truncate font-reading text-lg font-semibold after:absolute after:inset-0 after:rounded-xl">
          {title}
        </a>
      )}
      <Button variant="ghost" size="icon" aria-label={`Rename ${title}`} className="relative z-10 size-11 shrink-0 text-muted-foreground sm:size-9" onClick={() => setRenaming(true)}>
        <Pencil aria-hidden className="size-4" />
      </Button>
    </div>
  );
}

function Versions({ recording, transcripts }: { recording: number; transcripts: TranscriptRow[] }) {
  return (
    <Collapsible className="relative z-10 mt-2">
      <CollapsibleTrigger className="min-h-11 text-sm text-muted-foreground underline-offset-4 hover:underline sm:min-h-0">
        {transcripts.length === 1 ? "1 earlier version" : `${transcripts.length} earlier versions`}
      </CollapsibleTrigger>
      <CollapsibleContent>
        <ul className="mt-1 flex flex-col gap-1 text-sm">
          {transcripts.map((t) => (
            <li key={t.id}>
              <a href={transcriptHref(recording, t.id)} className="inline-flex min-h-11 items-center underline-offset-4 hover:underline sm:min-h-0">
                {versionLabel(t)}
              </a>
            </li>
          ))}
        </ul>
      </CollapsibleContent>
    </Collapsible>
  );
}

function Details({ row, latest, running }: { row: RecordingRow; latest: TranscriptRow | undefined; running: boolean }) {
  const picture = pictureNote(row.video_codec);
  return (
    <Collapsible className="relative z-10 mt-1">
      <CollapsibleTrigger className="min-h-11 text-sm text-muted-foreground underline-offset-4 hover:underline sm:min-h-0">Details</CollapsibleTrigger>
      <CollapsibleContent>
        <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          {latest !== undefined && (
            <>
              <dt className="text-muted-foreground">Made</dt>
              <dd>{versionLabel(latest)}</dd>
              <dt className="text-muted-foreground">Model</dt>
              <dd className="break-all">{latest.model}</dd>
              <dt className="text-muted-foreground">Speakers</dt>
              <dd>{speakersLabel(latest)}</dd>
              <dt className="text-muted-foreground">Marks</dt>
              <dd>{marksLabel(latest)}</dd>
              {latest.last_edited_at !== null && (
                <>
                  <dt className="text-muted-foreground">Edited</dt>
                  <dd>{whenLabel(latest.last_edited_at)}</dd>
                </>
              )}
            </>
          )}
          <dt className="text-muted-foreground">File</dt>
          <dd className="font-mono text-xs break-all select-text">{row.path}</dd>
          {sizeLabel(row.size_bytes) !== null && (
            <>
              <dt className="text-muted-foreground">Size</dt>
              <dd>{sizeLabel(row.size_bytes)}</dd>
            </>
          )}
        </dl>
        {picture !== null && <p className="mt-1 text-sm text-muted-foreground">{picture}</p>}
        {latest !== undefined && !running && (
          <div className="mt-2">
            <TranscribeControl recording={row} label="Transcribe again" />
          </div>
        )}
      </CollapsibleContent>
    </Collapsible>
  );
}

/**
 * One recording as a conversation, not a file (Hashiya spec, Library): a
 * readable title, its length, its language, its speakers as dots, and how far
 * its review got, or Transcribe when it has no transcript. The whole row
 * opens the latest transcript; older ones fold under "2 earlier versions",
 * model names under Details.
 */
export function RecordingRowItem({ row, onChanged }: { row: RecordingRow; onChanged: () => void }) {
  const title = displayTitle(row);
  const [latest, ...earlier] = row.transcripts;
  const job = useJobFor(row.id);
  const running = job !== undefined && !isFinished(job);
  const length = durationLabel(row.duration_s);
  const language = latest === undefined ? null : languageLabel(latest.language_tag);
  const progress = latest === undefined ? null : progressLabel(latest);
  const done = latest !== undefined && latest.review_total !== null && latest.review_checked === latest.review_total;
  const [relinking, setRelinking] = useState(false);
  return (
    <li
      aria-label={title}
      data-missing={row.missing || undefined}
      className="relative rounded-xl border border-border bg-card px-4 py-3 text-card-foreground transition-colors hover:border-input focus-within:border-input"
    >
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <Title row={row} title={title} href={latest === undefined ? null : transcriptHref(row.id, latest.id)} onChanged={onChanged} />
          <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground tabular-nums">
            {length !== null && <span>{length}</span>}
            {language !== null && <span className="rounded-full border border-border px-2 text-xs">{language}</span>}
            {latest?.speaker_count != null && latest.speaker_count > 0 && <SpeakerDots count={latest.speaker_count} />}
            {progress !== null && <span className={done ? "text-checked" : undefined}>{progress}</span>}
          </p>
          {row.missing && (
            <p className="relative z-10 mt-1 flex items-center gap-2 text-sm text-muted-foreground">
              Not where it was last seen.
              <Button
                variant="outline"
                size="sm"
                className="h-11 sm:h-7"
                disabled={relinking}
                onClick={() => {
                  setRelinking(true);
                  relinkRecording(row.id).then(
                    (found) => {
                      setRelinking(false);
                      if (found !== null) onChanged();
                    },
                    (thrown: unknown) => {
                      setRelinking(false);
                      showError(fromThrown(thrown, `/api/recordings/${row.id}/relink`));
                    },
                  );
                }}
              >
                Relink
              </Button>
            </p>
          )}
          {row.unreadable !== null && (
            <p className="mt-1 text-sm text-muted-foreground select-text" role="note">
              ffmpeg could not read this file: {row.unreadable}
            </p>
          )}
        </div>
        {(latest === undefined || running) && (
          <div className="relative z-10 shrink-0">
            <TranscribeControl recording={row} />
          </div>
        )}
      </div>
      {earlier.length > 0 && <Versions recording={row.id} transcripts={earlier} />}
      <Details row={row} latest={latest} running={running} />
      <span className="sr-only">{fileName(row.path)}</span>
    </li>
  );
}
```

- [ ] **Step 9: Rewrite `ui/src/features/library/LibraryPage.tsx`**

```tsx
import { Search } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError, fromBody, fromThrown, showError } from "@/features/errors/appError";
import { AppBar } from "@/features/shell/AppBar";
import { useFinishedCount } from "@/features/transcribe/jobs";
import { fileName } from "./describe";
import { importRecording } from "./imports";
import { RecordingRowItem } from "./RecordingRow";
import { displayTitle } from "./title";
import type { RecordingRow } from "./types";

const ROUTE = "/api/recordings";

// The list is one local request, and a flash of placeholder is worse than a
// few milliseconds of nothing (#57 section 11.7). So the skeleton shows only
// when the answer is late enough to be seen waiting: 300 ms, the commonly
// cited edge of a delay people notice.
const SKELETON_AFTER_MS = 300;

type Loaded = { state: "loading" } | { state: "failed" } | { state: "ready"; rows: RecordingRow[] };

async function loadRecordings(): Promise<RecordingRow[]> {
  const { data, error, response } = await api.GET(ROUTE);
  if (data === undefined) throw new ApiError(fromBody(error, response, ROUTE));
  return data;
}

/** True once `on` has stayed true for `ms`. */
function useLate(on: boolean, ms: number): boolean {
  const [late, setLate] = useState(false);
  useEffect(() => {
    if (!on) {
      setLate(false);
      return;
    }
    const timer = setTimeout(() => setLate(true), ms);
    return () => clearTimeout(timer);
  }, [on, ms]);
  return late;
}

/** Titles and file names holding every word of `query`, in any order and case. */
function matches(row: RecordingRow, query: string): boolean {
  const haystack = `${displayTitle(row)} ${fileName(row.path)}`.toLocaleLowerCase();
  return query
    .toLocaleLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((word) => haystack.includes(word));
}

/**
 * The library's front door (#110): the Mac's own file dialog, opened by the
 * server. The gold primary, in the bar, and again in the empty library,
 * where its waiting line sits on the ground rather than the blue field.
 */
function AddRecording({ onAdded, onField = true }: { onAdded: () => void; onField?: boolean }) {
  const [asking, setAsking] = useState(false);
  const run = () => {
    setAsking(true);
    importRecording().then(
      (row) => {
        setAsking(false);
        if (row !== null) onAdded();
      },
      (thrown: unknown) => {
        setAsking(false);
        showError(fromThrown(thrown, "/api/recordings/import"));
      },
    );
  };
  return (
    <>
      <Button disabled={asking} onClick={run} className="h-11 bg-gold px-4 font-semibold text-primary-foreground hover:bg-gold/90">
        Add recording
      </Button>
      {asking && (
        <span className={`basis-full px-2 text-sm sm:basis-auto ${onField ? "text-field-muted" : "text-muted-foreground"}`} role="status">
          Choose a file in the dialog. It may be behind this window.
        </span>
      )}
    </>
  );
}

/**
 * Every recording dsj knows, newest first (#156), as conversations: readable
 * titles, search, and the way a new one comes in (#110).
 */
export function LibraryPage() {
  const [loaded, setLoaded] = useState<Loaded>({ state: "loading" });
  // Read again when a transcription started from this page finishes (#113),
  // and when a recording is added, found again or renamed.
  const finished = useFinishedCount();
  const [changed, setChanged] = useState(0);
  const reload = useCallback(() => setChanged((n) => n + 1), []);
  const [query, setQuery] = useState("");
  const late = useLate(loaded.state === "loading", SKELETON_AFTER_MS);
  useEffect(() => {
    let live = true;
    loadRecordings().then(
      (rows) => {
        if (live) setLoaded({ state: "ready", rows });
      },
      (thrown: unknown) => {
        if (!live) return;
        setLoaded({ state: "failed" });
        showError(fromThrown(thrown, ROUTE));
      },
    );
    return () => {
      live = false;
    };
  }, [finished, changed]);

  const shown = loaded.state === "ready" ? loaded.rows.filter((row) => matches(row, query)) : [];
  return (
    <>
      <AppBar>
        <h1 className="sr-only">Library</h1>
        <label className="relative order-last flex min-w-0 basis-full items-center sm:order-none sm:basis-auto sm:flex-1 sm:max-w-sm">
          <Search aria-hidden className="pointer-events-none absolute left-3 size-4 text-field-muted" />
          <input
            type="search"
            aria-label="Search titles"
            placeholder="Search titles"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="h-11 w-full rounded-lg border border-white/20 bg-white/10 pr-3 pl-9 text-field-foreground placeholder:text-field-muted"
          />
        </label>
        <AddRecording onAdded={reload} />
      </AppBar>
      <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-3 px-3 py-6 sm:px-6">
        {loaded.state === "loading" ? (
          late && (
            <ul aria-label="Loading recordings" className="flex flex-col gap-2">
              {[0, 1, 2, 3].map((i) => (
                <li key={i} className="rounded-xl border border-border bg-card px-4 py-3">
                  <Skeleton className="h-6 w-2/3" />
                  <Skeleton className="mt-2 h-4 w-1/3" />
                </li>
              ))}
            </ul>
          )
        ) : loaded.state === "failed" ? (
          <p className="text-muted-foreground">The library could not be read.</p>
        ) : loaded.rows.length === 0 ? (
          <section className="mx-auto mt-16 flex max-w-md flex-col items-start gap-3">
            <h2 className="font-reading text-2xl font-semibold">No recordings yet</h2>
            <p className="text-muted-foreground">
              Add a recording from this Mac. dsj reads it where it is, transcribes it here, and nothing leaves the machine.
            </p>
            <AddRecording onAdded={reload} onField={false} />
          </section>
        ) : shown.length === 0 ? (
          <p className="text-muted-foreground">No title has “{query.trim()}” in it.</p>
        ) : (
          <ul className="flex flex-col gap-2" aria-label="Recordings">
            {shown.map((row) => (
              <RecordingRowItem key={row.id} row={row} onChanged={reload} />
            ))}
          </ul>
        )}
      </main>
    </>
  );
}
```

- [ ] **Step 10: Use the title in the reader**

In `ui/src/features/transcript/TranscriptPage.tsx`, import `displayTitle` from `@/features/library/title`; the `<h1>` in `Page` reads `{displayTitle(recording)}`, and the export call in `EditablePage` passes `displayTitle(opened.recording)` instead of `fileName(...)`.

- [ ] **Step 11: Move the library tests to the new rows**

In `ui/tests/unit/library.test.tsx` (the `describe` helpers for `durationLabel` and friends stay):

| Test | Was | Now |
|---|---|---|
| "lists every recording..." | listitem names `review.mov`, `standup.m4a` | unchanged (neither name holds a date) |
| "shows date, engine and model for each transcript" | one grey line holds all of it | open Details: `fireEvent.click(within(review).getByRole("button", { name: "Details" }))`, then the Made line holds "2026" and "whisper", the Model line the model id, and the row's tag reads "Urdu" when `language_tag: "urdu"` is set on that fixture |
| "shows an adopted transcript's engine as unknown, and one speaker as 1 speaker" | grey line | in Details: Made ends "unknown engine"; Speakers reads "1 speaker" |
| "Find this file" | button `Find this file` | button `Relink` |
| any test on `Transcribe` | every row has one | only a row with no transcripts shows `Transcribe`; a transcribed row's Details shows `Transcribe again` |
| "The library is empty." | text | heading `No recordings yet` and a second `Add recording` button |

and add:

```tsx
  it("titles a recording from its file's timestamp, and renames it inline", async () => {
    const seen = serve([{ ...ROWS[0], path: "/r/20250920_094234.m4a" }]);
    seen.mockImplementation(async (request: Request) => {
      const path = new URL(request.url).pathname;
      if (path === "/api/jobs") return Response.json([]);
      if (request.method === "PATCH") return Response.json({ ...ROWS[0], title: "Sunday call" });
      return Response.json([{ ...ROWS[0], path: "/r/20250920_094234.m4a" }]);
    });
    render(<LibraryPage />);
    const row = await screen.findByRole("listitem", { name: /^Sat 20 Sep/ });
    fireEvent.click(within(row).getByRole("button", { name: /^Rename/ }));
    const field = screen.getByRole("textbox", { name: "Title" });
    fireEvent.change(field, { target: { value: "Sunday call" } });
    fireEvent.keyDown(field, { key: "Enter" });
    await vi.waitFor(() => expect(seen.mock.calls.some(([r]) => r.method === "PATCH")).toBe(true));
  });

  it("filters by title as you type, and says when nothing matches", async () => {
    serve(ROWS);
    render(<LibraryPage />);
    await screen.findByRole("listitem", { name: "review.mov" });
    fireEvent.change(screen.getByRole("searchbox", { name: "Search titles" }), { target: { value: "stand" } });
    expect(screen.queryByRole("listitem", { name: "review.mov" })).toBeNull();
    expect(screen.getByRole("listitem", { name: "standup.m4a" })).toBeTruthy();
    fireEvent.change(screen.getByRole("searchbox", { name: "Search titles" }), { target: { value: "zzz" } });
    expect(screen.getByText(/No title has/)).toBeTruthy();
  });

  it("shows review progress, and older versions folded", async () => {
    serve([{ ...ROWS[0], transcripts: [
      { ...transcript({ id: 9 }), review_checked: 212, review_total: 252 },
      transcript({ id: 8 }),
      transcript({ id: 7 }),
    ] }]);
    render(<LibraryPage />);
    const row = await screen.findByRole("listitem", { name: "review.mov" });
    expect(within(row).getByText("212 of 252 checked")).toBeTruthy();
    expect(within(row).getByRole("button", { name: "2 earlier versions" })).toBeTruthy();
    expect(within(row).getByRole("link", { name: "review.mov" }).getAttribute("href")).toBe("/?recording=2&transcript=9");
  });
```

(The `transcript()` fixture helper gains `language_tag: null, review_checked: null, review_total: null` from Task 7.)

In the e2e specs, a transcript link found by its model text (`a[href=...]` with `toContainText("parakeet-tdt-0.6b-v3")` in `reader.spec.ts`; `getByRole("link", { name: /parakeet-tdt-0\.6b-v3/ })` in `correction.spec.ts`; the library steps of `journeys.spec.ts` and `capability.spec.ts`) becomes the row's title link: `page.getByRole("listitem", { name }).getByRole("link", { name })` where `name` is the file name the spec seeded; "edited" is now in the row's Details (`Edited` line), which `correction.spec.ts` opens with the Details button before asserting.

- [ ] **Step 12: Run the unit tests**

Run: `cd ui && npx vitest run tests/unit/title.test.ts tests/unit/library.test.tsx tests/unit/transcribe.test.tsx`
Expected: PASS.

- [ ] **Step 13: Gate, build, browser tests**

Run: `uv run just check` (paste the last line), `uv run just ui-build`, `cd ui && npx playwright test tests/e2e --project chromium` and `--project webkit`.
Expected: all pass.

- [ ] **Step 14: Look at it**

Run: `uv run python scratch/ui_shots.py --label t8 library`
Expected: 4 PNGs. Check: titles in Literata, length and tag and speaker dots on one tabular line, no model id in a row, "Add recording" the only gold thing on the page, search in the bar (its own row at 390), rows at least 44 px of target for Rename, Details and versions on the phone. The seeded library has no review yet, so no progress shows; Task 15's shots show it.

- [ ] **Step 15: Commit**

```bash
git add ui/src/components/ui/collapsible.tsx ui/src/components/ui/skeleton.tsx ui/src/features/library/title.ts \
  ui/src/features/library/RecordingRow.tsx ui/src/features/library/retitle.ts \
  ui/src/features/library/LibraryPage.tsx ui/src/features/library/describe.ts \
  ui/src/features/transcribe/TranscribeControl.tsx ui/src/features/transcript/TranscriptPage.tsx \
  ui/tests/unit/title.test.ts ui/tests/unit/library.test.tsx ui/tests/e2e/journeys.spec.ts \
  ui/tests/e2e/reader.spec.ts ui/tests/e2e/correction.spec.ts ui/tests/e2e/capability.spec.ts
git add -A -- dsj/ui/static/
git commit -m "feat(library): readable titles, rows as conversations, search"
```

---
### Task 9: The Transcribe dialog asks what is spoken

**Files:**
- Modify: `dsj/ui/jobs.py` (`transcript_path` keeps a Roman Urdu run apart from an Urdu run)
- Create (shadcn): `ui/src/components/ui/radio-group.tsx`
- Create: `ui/src/features/transcribe/choices.ts`
- Modify: `ui/src/features/transcribe/TranscribeDialog.tsx` (whole file)
- Test: `tests/test_jobs.py`, `ui/tests/unit/choices.test.ts` (new), `ui/tests/unit/transcribe.test.tsx`

**Interfaces:**
- Consumes: `loadEngines`, `startJob`, `type Engine`, `type TranscribeRequest` from `jobs.ts`; Task 8's `displayTitle`; `durationLabel`.
- Produces: Python `transcript_path(recording_id, engine, model, language, *, roman_urdu: bool = False) -> Path`; TS `type ChoiceId = "mixed" | "urdu" | "english" | "unsure"`, `type Choice`, `CHOICES: readonly Choice[]`, `type Advanced`, `requestFor(choice: Choice, advanced: Advanced): TranscribeRequest`, `expectedLabel(durationS: number | null, speed: number): string | null`. The seam for sub-project B: the Advanced "Engine" list is every engine `/api/engines` sends, so a cloud engine appears there with no change to the dialog's structure.

- [ ] **Step 1: Load impeccable: read /Users/moiz/.claude/skills/impeccable/reference/craft-floor.md before editing**

Read it in full; build to it without announcing its checklist.

- [ ] **Step 2: File the issue (AGENTS.md rule 1)**

Run: `gh issue create --title "ui: a Roman Urdu run overwrites an Urdu run of the same recording" --body "transcript_path(recording_id, engine, model, language) names both whisper --roman-urdu and whisper --language ur runs '<id>-whisper-<model>-ur.json', so the second replaces the first and Review never has a second opinion. Fix: a -roman suffix. Plan: docs/superpowers/plans/2026-10-07-hashiya-review-mode.md, Task 9."` and put its number where the code says `#ROMAN`.

- [ ] **Step 3: Write the failing path test**

Append to `tests/test_jobs.py`:

```python
def test_a_roman_urdu_run_and_an_urdu_run_of_one_recording_keep_their_own_transcripts() -> None:
    """Both are whisper in language "ur"; their words differ, so their files must (#ROMAN)."""
    model = "mlx-community/whisper-large-v3-turbo"
    urdu = jobs_mod.transcript_path(3, "whisper", model, "ur")
    roman = jobs_mod.transcript_path(3, "whisper", model, "ur", roman_urdu=True)
    assert urdu.name == "3-whisper-whisper-large-v3-turbo-ur.json"
    assert roman.name == "3-whisper-whisper-large-v3-turbo-ur-roman.json"
```

Run: `uv run pytest tests/test_jobs.py -q -k roman_urdu_run`
Expected: FAIL, `unexpected keyword argument 'roman_urdu'`.

- [ ] **Step 4: Fix `transcript_path` in `dsj/ui/jobs.py`**

```python
def transcript_path(
    recording_id: int, engine: str, model: str, language: str | None, *, roman_urdu: bool = False
) -> Path:
    """Where a run from the page writes its transcript: one file per recording and settings.

    Beside the library, not beside the recording: the page never writes into
    the owner's folders. Named by what decides the transcript's contents, so a
    second run with other settings keeps the first one's file, and a run
    repeated with the same settings writes the same path, where its checkpoint
    lets it resume (dsj/checkpoint.py keys that file to `out`).

    A Roman Urdu run is whisper in language "ur" with a prompt, so without its
    own suffix it took the same name as a plain Urdu run and replaced it
    (#ROMAN): the Transcribe dialog offers both, and Review's second opinion
    needs both kept. A Roman Urdu run started before this fix resumes from
    nothing once, under the new name.
    """
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(model).name or model).strip("._") or "model"
    stem = f"{recording_id}-{engine}-{name}" + (f"-{language}" if language else "")
    stem += "-roman" if roman_urdu else ""
    return library_path().parent / "transcripts" / f"{stem}.json"
```

and at its call site in `Jobs.start`: `out = transcript_path(recording_id, engine, model, language, roman_urdu=request.roman_urdu)`.

Run: `uv run pytest tests/test_jobs.py -q`
Expected: PASS.

- [ ] **Step 5: Add the radio primitive**

Run: `cd ui && npx shadcn@4.21.0 add radio-group --dry-run`, then `npx shadcn@4.21.0 add radio-group`. Confirm `RadioGroup` and `RadioGroupItem` with `grep -n "^export" src/components/ui/radio-group.tsx`.

- [ ] **Step 6: Write the failing choices test**

Create `ui/tests/unit/choices.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { type Advanced, CHOICES, expectedLabel, requestFor } from "../../src/features/transcribe/choices";

const PLAIN: Advanced = { engine: null, model: "", prompt: "", diarize: true, requireDiarize: false, startOver: false };
const pick = (id: string) => CHOICES.find((c) => c.id === id) ?? (CHOICES[0] as (typeof CHOICES)[number]);

describe("what each answer runs", () => {
  it("runs mixed Urdu and English, and not sure, as whisper with Roman Urdu", () => {
    for (const id of ["mixed", "unsure"]) {
      expect(requestFor(pick(id), PLAIN)).toMatchObject({ engine: "whisper", roman_urdu: true, language: null });
    }
  });

  it("runs mostly Urdu as whisper in Urdu, and English as parakeet", () => {
    expect(requestFor(pick("urdu"), PLAIN)).toMatchObject({ engine: "whisper", roman_urdu: false, language: "ur" });
    expect(requestFor(pick("english"), PLAIN)).toMatchObject({ engine: "parakeet", roman_urdu: false, language: null, prompt: null });
  });

  it("lets an engine chosen in Advanced override the answer, without the answer's whisper settings", () => {
    expect(requestFor(pick("mixed"), { ...PLAIN, engine: "parakeet" })).toMatchObject({ engine: "parakeet", roman_urdu: false, language: null });
  });

  it("carries the advanced options into the request", () => {
    expect(requestFor(pick("mixed"), { ...PLAIN, model: " m ", prompt: " p ", diarize: false, requireDiarize: true, startOver: true })).toMatchObject({
      model: "m",
      prompt: "p",
      diarize: false,
      require_diarize: false,
      start_over: true,
    });
  });
});

describe("expectedLabel", () => {
  it("says how long from the file's length and the engine's measured speed", () => {
    expect(expectedLabel(2520, 1.71)).toBe("About 25 minutes for this 42-minute recording");
    expect(expectedLabel(2520, 13)).toBe("About 3 minutes for this 42-minute recording");
    expect(expectedLabel(30, 13)).toBe("About 1 minute for this 1-minute recording");
    expect(expectedLabel(null, 13)).toBeNull();
  });
});
```

Run: `cd ui && npx vitest run tests/unit/choices.test.ts`
Expected: FAIL, `Failed to resolve import "../../src/features/transcribe/choices"`.

- [ ] **Step 7: Write `ui/src/features/transcribe/choices.ts`**

```ts
// "What's spoken?" (Hashiya spec, Transcribe; critique: "Transcribe asks for
// flags, not the question: defaults parakeet for Urdu"). Each answer runs
// what the measurements say is best for it (README, "Which mode, by error
// rate", #184 and #236, word error rate against public hand-checked sets):
//
//   mixed Urdu and English: whisper turbo --roman-urdu, 30 to 33% on #148's
//     podcast, against 46 to 57% for --language ur;
//   mostly Urdu: whisper --language ur, 21 to 23% on UrduSpeech's set,
//     against 41 to 43% for --roman-urdu;
//   English or European: parakeet, 4.9% on an Earnings-22 call at about 13x
//     realtime (whisper with the language detected: 4.5%, at 5 to 6x);
//   not sure: as mixed, the owner's usual speech.
//
// The speeds are the slowest measured for each mode, so the estimate errs
// long (.agents/skills/dsj/references/engines.md, "whisper speed"):
// --roman-urdu 1.71x (the owner's 13.1 min Urdu and English file, 8ff5871);
// --language ur 1.99x (#148's podcast, turbo); parakeet about 13x (that
// file's engine table). Speaker labelling is included in the first, so the
// estimate covers it.

import type { Engine, TranscribeRequest } from "./jobs";

type EngineName = Engine["name"];

export type ChoiceId = "mixed" | "urdu" | "english" | "unsure";

export type Choice = {
  id: ChoiceId;
  label: string;
  engine: EngineName;
  roman_urdu: boolean;
  language: string | null;
  /** Measured times realtime, the slowest seen. */
  speed: number;
  /** What the dialog says it will use. */
  says: string;
};

export const CHOICES: readonly Choice[] = [
  { id: "mixed", label: "Mixed Urdu and English", engine: "whisper", roman_urdu: true, language: null, speed: 1.71, says: "whisper, writing Urdu in Roman letters" },
  { id: "urdu", label: "Mostly Urdu", engine: "whisper", roman_urdu: false, language: "ur", speed: 1.99, says: "whisper, writing Urdu script" },
  { id: "english", label: "English or European languages", engine: "parakeet", roman_urdu: false, language: null, speed: 13, says: "parakeet" },
  { id: "unsure", label: "Not sure", engine: "whisper", roman_urdu: true, language: null, speed: 1.71, says: "whisper with Roman Urdu, which handles both" },
];

/** The folded options (Hashiya spec, Transcribe: "model, prompt, skip speaker labels, fail if labelling fails, start over"). */
export type Advanced = {
  /** An engine picked by hand, or null to use the answer's. */
  engine: EngineName | null;
  model: string;
  prompt: string;
  diarize: boolean;
  requireDiarize: boolean;
  startOver: boolean;
};

export function requestFor(choice: Choice, advanced: Advanced): TranscribeRequest {
  const engine = advanced.engine ?? choice.engine;
  // An engine picked by hand runs as itself: the answer's Roman Urdu and
  // language belong to the answer's engine (--roman-urdu would turn parakeet
  // back into whisper, dsj/suno.py roman_urdu).
  const own = engine === choice.engine;
  return {
    engine,
    model: advanced.model.trim() || null,
    language: own ? choice.language : null,
    prompt: engine === "whisper" ? advanced.prompt.trim() || null : null,
    roman_urdu: own && choice.roman_urdu,
    diarize: advanced.diarize,
    require_diarize: advanced.diarize && advanced.requireDiarize,
    start_over: advanced.startOver,
  };
}

/** "About 25 minutes for this 42-minute recording", or null when its length is not known. */
export function expectedLabel(durationS: number | null, speed: number): string | null {
  if (durationS === null || durationS <= 0 || speed <= 0) return null;
  const minutes = Math.max(1, Math.round(durationS / speed / 60));
  const length = Math.max(1, Math.round(durationS / 60));
  return `About ${minutes} ${minutes === 1 ? "minute" : "minutes"} for this ${length}-minute recording`;
}
```

Run: `cd ui && npx vitest run tests/unit/choices.test.ts`
Expected: PASS.

- [ ] **Step 8: Rewrite `ui/src/features/transcribe/TranscribeDialog.tsx`**

```tsx
import { useEffect, useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { fromThrown, showError } from "@/features/errors/appError";
import type { RecordingRow } from "@/features/library/types";
import { displayTitle } from "@/features/library/title";
import { type Advanced, CHOICES, type ChoiceId, expectedLabel, requestFor } from "./choices";
import { type Engine, loadEngines, startJob } from "./jobs";

const AS_ANSWERED = "as-answered";

/**
 * Transcribe, asking the owner's question first (Hashiya spec, Transcribe):
 * what is spoken. The answer picks the engine and settings; the dialog says
 * which, and how long it should take. Everything else folds under Advanced.
 */
export function TranscribeDialog({ recording, onClose }: { recording: RecordingRow; onClose: () => void }) {
  const [engines, setEngines] = useState<Engine[] | null>(null);
  const [answer, setAnswer] = useState<ChoiceId>("mixed");
  const [advanced, setAdvanced] = useState<Advanced>({ engine: null, model: "", prompt: "", diarize: true, requireDiarize: false, startOver: false });
  const [sending, setSending] = useState(false);
  const ids = useId();

  useEffect(() => {
    let live = true;
    loadEngines().then(
      (listed) => {
        if (live) setEngines(listed);
      },
      (thrown: unknown) => {
        if (!live) return;
        onClose();
        showError(fromThrown(thrown, "/api/engines"));
      },
    );
    return () => {
      live = false;
    };
  }, [onClose]);

  if (engines === null) return null;
  const choice = CHOICES.find((c) => c.id === answer) ?? (CHOICES[0] as (typeof CHOICES)[number]);
  const request = requestFor(choice, advanced);
  const engine = engines.find((e) => e.name === request.engine);
  const unavailable = engines.filter((e) => e.reason !== null);
  const expected = advanced.engine === null ? expectedLabel(recording.duration_s, choice.speed) : null;
  const set = <K extends keyof Advanced>(key: K, value: Advanced[K]) => setAdvanced({ ...advanced, [key]: value });

  const start = () => {
    setSending(true);
    startJob(recording.id, request).then(
      () => onClose(),
      (thrown: unknown) => {
        // Refused (another run holds the machine, the file is gone): the
        // server's sentence says why, in the error dialog.
        onClose();
        showError(fromThrown(thrown));
      },
    );
  };

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-lg">
        <DialogHeader className="pr-8">
          <DialogTitle className="text-balance">Transcribe {displayTitle(recording)}</DialogTitle>
          <DialogDescription>Runs on this Mac. Nothing leaves it.</DialogDescription>
        </DialogHeader>

        <fieldset className="flex flex-col gap-1">
          <legend id={`${ids}-what`} className="mb-2 font-medium">
            What's spoken?
          </legend>
          <RadioGroup aria-labelledby={`${ids}-what`} value={answer} onValueChange={(picked) => setAnswer(picked as ChoiceId)}>
            {CHOICES.map((c) => (
              <label key={c.id} className="flex min-h-11 cursor-pointer items-center gap-3 rounded-lg px-2 hover:bg-muted">
                <RadioGroupItem value={c.id} />
                {c.label}
              </label>
            ))}
          </RadioGroup>
        </fieldset>

        <p role="status" className="text-sm">
          Uses {advanced.engine === null ? choice.says : advanced.engine}.{expected !== null && ` ${expected}.`}
        </p>
        {engine?.reason != null && (
          <Collapsible className="text-sm text-muted-foreground">
            <span>{engine.name} can't run on this Mac. </span>
            <CollapsibleTrigger className="underline underline-offset-4">Why</CollapsibleTrigger>
            <CollapsibleContent className="mt-1 select-text">{engine.reason}</CollapsibleContent>
          </Collapsible>
        )}

        <Collapsible>
          <CollapsibleTrigger className="min-h-11 text-sm font-medium underline-offset-4 hover:underline">Advanced</CollapsibleTrigger>
          <CollapsibleContent className="mt-2 flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor={`${ids}-engine`}>Engine</Label>
              {/* Every engine the server lists, so a new one (a cloud engine, sub-project B) appears here with no change to this dialog. */}
              <Select
                items={[{ value: AS_ANSWERED, label: `As answered (${choice.engine})` }, ...engines.map((e) => ({ value: e.name, label: e.name }))]}
                value={advanced.engine ?? AS_ANSWERED}
                onValueChange={(picked) => {
                  const next = engines.find((e) => e.name === picked && e.reason === null);
                  set("engine", next === undefined ? null : next.name);
                }}
              >
                <SelectTrigger id={`${ids}-engine`} className="h-11">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={AS_ANSWERED}>As answered ({choice.engine})</SelectItem>
                  {engines.map((e) => (
                    <SelectItem key={e.name} value={e.name} disabled={e.reason !== null}>
                      {e.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor={`${ids}-model`}>Model</Label>
              <Input
                id={`${ids}-model`}
                value={advanced.model}
                placeholder={engine?.default_model ?? ""}
                onChange={(event) => set("model", event.target.value)}
                spellCheck={false}
              />
            </div>
            {request.engine === "whisper" && (
              <div className="flex flex-col gap-2">
                <Label htmlFor={`${ids}-prompt`}>Prompt</Label>
                <Textarea id={`${ids}-prompt`} value={advanced.prompt} onChange={(event) => set("prompt", event.target.value)} />
              </div>
            )}
            <Toggle id={`${ids}-diarize`} label="Skip speaker labels" checked={!advanced.diarize} onChange={(skip) => set("diarize", !skip)} />
            {advanced.diarize && (
              <Toggle id={`${ids}-require`} label="Fail if speakers cannot be labelled" checked={advanced.requireDiarize} onChange={(v) => set("requireDiarize", v)} />
            )}
            <Toggle id={`${ids}-over`} label="Start over, not from where an earlier run stopped" checked={advanced.startOver} onChange={(v) => set("startOver", v)} />
            {unavailable.map((e) => (
              // One grey line an engine, its reason on request (spec, Transcribe).
              <Collapsible key={e.name} className="text-sm text-muted-foreground" data-unavailable={e.name}>
                <span>{e.name} can't run on this Mac. </span>
                <CollapsibleTrigger className="underline underline-offset-4">Why</CollapsibleTrigger>
                <CollapsibleContent className="mt-1 select-text">{e.reason}</CollapsibleContent>
              </Collapsible>
            ))}
          </CollapsibleContent>
        </Collapsible>

        <DialogFooter>
          <Button variant="outline" className="h-11 sm:h-9" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={start} disabled={sending || engine?.reason !== null} className="h-11 bg-gold font-semibold text-primary-foreground hover:bg-gold/90 sm:h-9">
            Start
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Toggle({ id, label, checked, onChange }: { id: string; label: string; checked: boolean; onChange: (checked: boolean) => void }) {
  return (
    <div className="flex min-h-11 items-center gap-2">
      <Switch id={id} checked={checked} onCheckedChange={(next: boolean) => onChange(next)} />
      <Label htmlFor={id}>{label}</Label>
    </div>
  );
}
```

`engine?.reason !== null` is true while `engine` is undefined (an engine the server does not list), which keeps Start off; that is intended.

- [ ] **Step 9: Move the dialog tests to the question**

In `ui/tests/unit/transcribe.test.tsx`, the tests of the job's progress words (`hasFraction`, `progressLine`, the running bar) stay. Replace the dialog tests (the ones that press the `parakeet`/`whisper`/`sherpa` toggle buttons, type in Language, switch Roman Urdu, read the "reports no progress" note) with these, which use the file's `serve`, `RECORDING` and `ENGINES`, and `choose` from `./menus` (the file's `RECORDING` gains `title: null` from Task 7, and its `duration_s` becomes `2520` for these):

```tsx
describe("the Transcribe dialog", () => {
  async function open(): Promise<Request[]> {
    const sent: Request[] = [];
    serve({
      "GET /api/jobs": () => Response.json([]),
      "GET /api/engines": () => Response.json(ENGINES),
      "POST /api/recordings/4/transcribe": async (request) => {
        sent.push(request.clone());
        return Response.json(job({ engine: "whisper" }), { status: 202 });
      },
    });
    render(<TranscribeControl recording={{ ...RECORDING, duration_s: 2520 }} />);
    fireEvent.click(screen.getByRole("button", { name: "Transcribe" }));
    await screen.findByRole("radiogroup", { name: "What's spoken?" });
    return sent;
  }

  it("asks what is spoken first, says what it will use and how long, and runs it", async () => {
    const sent = await open();
    expect(screen.getByRole("status").textContent).toBe(
      "Uses whisper, writing Urdu in Roman letters. About 25 minutes for this 42-minute recording.",
    );
    fireEvent.click(screen.getByRole("button", { name: "Start" }));
    await vi.waitFor(() => expect(sent).toHaveLength(1));
    expect(await sent[0]?.json()).toMatchObject({ engine: "whisper", roman_urdu: true, language: null, diarize: true });
  });

  it("runs English on parakeet, and mostly Urdu on whisper in Urdu", async () => {
    const sent = await open();
    choose(screen.getByRole("radio", { name: "English or European languages" }));
    expect(screen.getByRole("status").textContent).toContain("Uses parakeet. About 3 minutes");
    choose(screen.getByRole("radio", { name: "Mostly Urdu" }));
    fireEvent.click(screen.getByRole("button", { name: "Start" }));
    await vi.waitFor(() => expect(sent).toHaveLength(1));
    expect(await sent[0]?.json()).toMatchObject({ engine: "whisper", roman_urdu: false, language: "ur" });
  });

  it("folds everything else under Advanced, and an engine that cannot run is one grey line", async () => {
    await open();
    expect(screen.queryByLabelText("Model")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Advanced" }));
    expect(screen.getByLabelText("Model")).toBeTruthy();
    expect(screen.getByText("sherpa can't run on this Mac.")).toBeTruthy();
    expect(screen.queryByText(/sherpa-onnx will not import here/)).toBeNull();
  });

  it("carries Skip speaker labels into the request", async () => {
    const sent = await open();
    fireEvent.click(screen.getByRole("button", { name: "Advanced" }));
    fireEvent.click(screen.getByRole("switch", { name: "Skip speaker labels" }));
    fireEvent.click(screen.getByRole("button", { name: "Start" }));
    await vi.waitFor(() => expect(sent).toHaveLength(1));
    expect(await sent[0]?.json()).toMatchObject({ diarize: false, require_diarize: false });
  });
});
```

Run: `cd ui && npx vitest run tests/unit/transcribe.test.tsx tests/unit/choices.test.ts`
Expected: PASS. If a radio does not take the `choose` click in jsdom, fire `fireEvent.click` on its `label` instead, and note it in the test's comment.

- [ ] **Step 10: Gate, build**

Run: `uv run just check` (paste the last line), `uv run just ui-build`.
Expected: green.

- [ ] **Step 11: Look at it**

Run: `uv run python scratch/ui_shots.py --label t9 transcribe`
Expected: 4 PNGs of the dialog. Check: the question is the first thing under the title; the four answers are 44 px rows; the "Uses ..." line names the engine and the time; Advanced is folded; Start is the one gold button; the title does not run under the close button; at 390 the dialog fits without sideways scroll.

- [ ] **Step 12: Commit**

```bash
git add dsj/ui/jobs.py tests/test_jobs.py ui/src/components/ui/radio-group.tsx ui/src/features/transcribe/choices.ts \
  ui/src/features/transcribe/TranscribeDialog.tsx ui/tests/unit/choices.test.ts ui/tests/unit/transcribe.test.tsx
git add -A -- dsj/ui/static/
git commit -m "feat(ui): Transcribe asks what is spoken and picks the engine"
```

---

### Task 10: Review backend: the review document, the answer key, stale edit lists

**Files:**
- Modify: `dsj/ui/schemas.py` (review models)
- Modify: `dsj/ui/edits.py` (`transcript_sha`; the sha an edit list was made from, kept beside it; a stale list moved aside; `Opened.replaced`)
- Modify: `dsj/ui/review.py` (read, save, reference)
- Create: `dsj/ui/routes/review.py`
- Modify: `dsj/ui/server.py` (include the router), `dsj/ui/errors.py` (`InvalidReview` 422, `ReviewIncomplete` 409), `dsj/ui/routes/marks.py` (`_wire` sends `replaced`)
- Modify: `ui/src/api/schema.d.ts` (generated)
- Test: `tests/test_ui_review.py` (new)

**Interfaces:**
- Consumes: Task 5's `edits.save_edits`, `Opened.legend`; Task 6's `edits.labels_of`, `edits.display_name`; Task 7's `review.review_path`, `review.progress`.
- Produces:
  - Wire models: `ReviewSegment { start: float; end: float; state: "unchecked" | "checked"; flags: list["unclear" | "not_speech" | "overlap" | "cut_off"]; speaker: str | None; edited: bool }`, `ReviewCorrection { at: str; start: float; end: float; before: str; after: str }`, `ReviewDocument { version: 1; transcript_sha: str; review_pass: "every" | "likely"; cursor_s: float; started_at: str; updated_at: str; segments: list[ReviewSegment]; corrections: list[ReviewCorrection] }` (no field has a default, so FastAPI writes one schema for both directions and the page has one type), `Review { document: ReviewDocument | None; transcript_sha: str }`, `ReferenceRequest { allow_partial: bool = False }`, `ReferenceWritten { files: list[str]; segments: int; unchecked: int }`; `Edits.replaced: str | None`.
  - Routes: `GET /api/transcripts/{id}/review -> Review`, `PUT /api/transcripts/{id}/review` (body `ReviewDocument`) `-> ReviewDocument`, `POST /api/transcripts/{id}/reference` (body `ReferenceRequest`) `-> ReferenceWritten`.
  - Files: `<library dir>/reviews/<key>.json`; `<transcript stem>.reference.json` and `<transcript stem>.reference.txt` beside the transcript JSON; `<library dir>/edits/<key>.source.json` beside each edit list.
  - The seam for C: every correction made in Review is in `ReviewDocument.corrections`, before and after.

- [ ] **Step 1: File the issues (AGENTS.md rule 1)**

Run: `gh issue create --title "ui: Review mode backend: review document and answer-key export (Hashiya A)" --body "GET/PUT /api/transcripts/{id}/review, POST /api/transcripts/{id}/reference writing <name>.reference.json and .txt beside the transcript. Plan: docs/superpowers/plans/2026-10-07-hashiya-review-mode.md, Task 10."`, and, for the discovered defect:
`gh issue create --title "ui: an edit list outlives a re-transcription and is applied to the new words" --body "edits_path keys the list by the transcript JSON's path; a run from the app with the same settings writes the same path (dsj/ui/jobs.py transcript_path), so the old list, with the old words, opens over the new transcript. Fix: keep the sha of the transcript beside each saved list; on a mismatch move the list aside and start fresh. Found while planning Review mode's resume (Review Focus 4)."`
Put their numbers where the code says `#REVIEW` and `#STALE`.

- [ ] **Step 2: Write the failing review tests**

Create `tests/test_ui_review.py`:

```python
"""Review mode's backend (#REVIEW): review document, answer key, stale edit list (#STALE).

The recording and transcript are tests/test_ui_edits.py's: two seconds of
tone ffmpeg makes and two sentences written here, " Hello there." from 0.2 to
0.9 s by SPEAKER_00 and " Fine." from 1.2 to 1.6 s by SPEAKER_01.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

# pytest puts tests/ on the path (no __init__.py), as tests/test_diarize_gate.py relies on.
# If Task 6 moved page, tokens and seeded into tests/conftest.py, write
# `from conftest import page, tokens` instead: `seeded` then comes from conftest.
from test_ui_edits import page, seeded, tokens  # noqa: F401  (the fixture)

from dsj.ui.edits import edits_path
from dsj.ui.review import review_path


def sha(seeded: dict[str, Any]) -> str:  # noqa: F811
    return hashlib.sha256(seeded["json"].read_bytes()).hexdigest()


def document(digest: str, *states: str, flags: tuple[list[str], ...] = ([], [])) -> dict[str, Any]:
    spans = [(0.2, 0.9), (1.2, 1.6)]
    return {
        "version": 1,
        "transcript_sha": digest,
        "review_pass": "every",
        "cursor_s": 1.2,
        "started_at": "2026-10-07T10:00:00+00:00",
        "updated_at": "2026-10-07T10:05:00+00:00",
        "segments": [
            {"start": a, "end": b, "state": state, "flags": flag, "speaker": None, "edited": False}
            for (a, b), state, flag in zip(spans, states, flags, strict=False)
        ],
        "corrections": [],
    }


def test_a_transcript_with_no_review_says_so_and_names_its_own_sha(
    seeded: dict[str, Any],  # noqa: F811
) -> None:
    reply = page().get(f"/api/transcripts/{seeded['id']}/review")
    assert reply.status_code == 200, reply.text
    assert reply.json() == {"document": None, "transcript_sha": sha(seeded)}


def test_a_saved_review_comes_back_and_lives_beside_the_library(
    seeded: dict[str, Any],  # noqa: F811
) -> None:
    client = page()
    route = f"/api/transcripts/{seeded['id']}/review"
    saved = client.put(route, json=document(sha(seeded), "checked", "unchecked"))
    assert saved.status_code == 200, saved.text
    assert client.get(route).json()["document"]["segments"][0]["state"] == "checked"
    assert review_path(seeded["json"]).is_file()
    assert sorted(p.name for p in seeded["audio"].parent.iterdir()) == ["talk.json", "talk.wav"]
    # And the library row shows how far it got.
    listed = client.get("/api/recordings").json()[0]["transcripts"][0]
    assert (listed["review_checked"], listed["review_total"]) == (1, 2)


def test_overlapping_segments_are_refused_by_name(seeded: dict[str, Any]) -> None:  # noqa: F811
    broken = document(sha(seeded), "unchecked", "unchecked")
    broken["segments"][1]["start"] = 0.5
    reply = page().put(f"/api/transcripts/{seeded['id']}/review", json=broken)
    assert reply.status_code == 422
    assert reply.json()["error"] == "InvalidReview"
    assert "segment 1" in reply.json()["message"]


def test_an_answer_key_is_refused_while_sentences_are_unchecked_and_says_how_many(
    seeded: dict[str, Any],  # noqa: F811
) -> None:
    client = page()
    route = f"/api/transcripts/{seeded['id']}"
    client.put(f"{route}/review", json=document(sha(seeded), "checked", "unchecked"))
    reply = client.post(f"/api/transcripts/{seeded['id']}/reference", json={})
    assert reply.status_code == 409
    assert reply.json()["error"] == "ReviewIncomplete"
    assert "1 of 2 sentences are not checked" in reply.json()["message"]
    partial = client.post(f"{route}/reference", json={"allow_partial": True})
    assert partial.status_code == 200, partial.text
    assert partial.json() == {
        "files": ["talk.reference.json", "talk.reference.txt"], "segments": 2, "unchecked": 1,
    }
    key = json.loads((seeded["json"].parent / "talk.reference.json").read_text())
    assert key["complete"] is False


def test_the_answer_key_holds_the_corrected_words_names_and_flags(
    seeded: dict[str, Any],  # noqa: F811
) -> None:
    client = page()
    route = f"/api/transcripts/{seeded['id']}"
    content = client.get(f"{route}/edits").json()["content"]
    next(e for e in content if e.get("text") == " there")["text"] = " their"
    client.put(f"{route}/edits", json={"content": content})
    client.put(f"{route}/names", json={"names": {"SPEAKER_00": "Ali"}})
    both = document(sha(seeded), "checked", "checked", flags=([], ["overlap"]))
    client.put(f"{route}/review", json=both)
    assert client.post(f"{route}/reference", json={}).status_code == 200
    key = json.loads((seeded["json"].parent / "talk.reference.json").read_text())
    assert key["format"] == "dsj-reference"
    assert key["transcript"] == "talk.json"
    assert key["model"] == "mlx-community/parakeet-tdt-0.6b-v3"
    assert key["complete"] is True
    assert [(s["speaker"], s["text"], s["flags"]) for s in key["segments"]] == [
        ("Ali", "Hello their.", []),
        ("Speaker 2", "Fine.", ["overlap"]),
    ]
    text = (seeded["json"].parent / "talk.reference.txt").read_text()
    assert text == "[0:00] Ali: Hello their.\n[0:01] Speaker 2: Fine. (overlapping talk)\n"


def test_transcribed_again_the_old_edit_list_is_moved_aside_not_applied(
    seeded: dict[str, Any],  # noqa: F811
) -> None:
    """Review Focus 4: a run from the app with the same settings writes the same JSON path."""
    client = page()
    route = f"/api/transcripts/{seeded['id']}"
    content = client.get(f"{route}/edits").json()["content"]
    next(e for e in content if e.get("text") == " there")["text"] = " their"
    client.put(f"{route}/edits", json={"content": content})
    old = sha(seeded)
    client.put(f"{route}/review", json=document(old, "checked", "checked"))

    payload = dict(seeded["payload"])
    payload["sentences"] = [
        {"start": 0.2, "end": 0.9, "speaker": 0, "text": " Hello world.",
         "tokens": tokens((0.2, 0.5, " Hello", 0.99), (0.56, 0.8, " world", 0.9),
                          (0.8, 0.88, ".", 0.97))},
        {"start": 1.2, "end": 1.6, "speaker": 1, "text": " Fine.",
         "tokens": tokens((1.2, 1.5, " Fine", 0.9), (1.5, 1.6, ".", 0.95))},
    ]
    seeded["json"].write_text(json.dumps(payload))

    edits = client.get(f"{route}/edits").json()
    words = "".join(e["text"] for e in edits["content"] if e["kind"] == "item")
    assert "world" in words and "their" not in words
    assert edits["replaced"] is not None and "made again" in edits["replaced"]
    listed = edits_path(seeded["json"])
    aside = listed.with_name(f"{listed.stem}.{old[:12]}.json")
    assert aside.is_file()
    # The review is kept; the page sees its sha no longer matches and re-checks by span.
    review = client.get(f"{route}/review").json()
    assert review["document"]["transcript_sha"] == old
    assert review["transcript_sha"] == sha(seeded) != old
```

Run: `uv run pytest tests/test_ui_review.py -q`
Expected: FAIL, 404 on `/review`.

- [ ] **Step 3: Add the review models to `dsj/ui/schemas.py`**

Add `"Review"`, `"ReviewCorrection"`, `"ReviewDocument"`, `"ReviewFlag"`, `"ReviewPass"`, `"ReviewSegment"`, `"ReferenceRequest"`, `"ReferenceWritten"`, `"SegmentState"` to `__all__`, and:

```python
# Review mode (Hashiya spec). No field below has a default, on purpose: a
# model that is both sent and accepted with defaults is split by FastAPI into
# "-Input" and "-Output" schemas, and the page would have two types for one
# document. The page always sends every field.

# What a person can say about a sentence besides its words (spec, Ctrl+U and Ctrl+F).
type ReviewFlag = Literal["unclear", "not_speech", "overlap", "cut_off"]
# Every sentence in order (for answer keys), or only the likely errors.
type ReviewPass = Literal["every", "likely"]
type SegmentState = Literal["unchecked", "checked"]


class ReviewSegment(BaseModel):
    """One sentence of a review, by its span of the recording, which every edit keeps."""

    start: float
    end: float
    state: SegmentState
    flags: list[ReviewFlag]
    # The speaker label a person set for it in Review (Ctrl+1 to Ctrl+9), else None.
    speaker: str | None
    # Whether a person changed its words in Review.
    edited: bool


class ReviewCorrection(BaseModel):
    """One change of words made in Review, before and after: sub-project C's learning data."""

    at: str
    start: float
    end: float
    before: str
    after: str


class ReviewDocument(BaseModel):
    """A transcript's review: its sentences and their state, the pass, and where the person was."""

    version: Literal[1]
    # The sha256 of the transcript JSON the review was made against: when the
    # transcript is made again, the page re-checks the sentences by span.
    transcript_sha: str
    review_pass: ReviewPass
    # Where the person was, in seconds, so leaving and coming back resumes there.
    cursor_s: float
    started_at: str
    updated_at: str
    segments: list[ReviewSegment]
    corrections: list[ReviewCorrection]


class Review(BaseModel):
    """A transcript's review, or None, and the sha of the transcript as it is now."""

    document: ReviewDocument | None
    transcript_sha: str


class ReferenceRequest(BaseModel):
    """Save the answer key; with `allow_partial`, even while sentences are unchecked."""

    allow_partial: bool = False


class ReferenceWritten(BaseModel):
    """The answer key's files (names only, beside the transcript), and how much of it is checked."""

    files: list[str]
    segments: int
    unchecked: int
```

`Edits` gains:

```python
    # Why the saved list was put aside and this one built fresh, or None (#STALE).
    replaced: str | None
```

- [ ] **Step 4: Keep the transcript's sha beside each edit list in `dsj/ui/edits.py`**

1. Add `"transcript_sha"` to `__all__`; `import json`, `import os` are already there or added; `from dsj.atomic import atomic_write_text`.
2. `Opened` gains `replaced: str | None = None` (after `legend`), commented: "Why a saved list was put aside, when the transcript was made again (#STALE)."
3. Add:

```python
def transcript_sha(json_path: Path) -> str:
    """The sha256 of the transcript JSON's bytes: what an edit list and a review are made from."""
    return hashlib.sha256(json_path.read_bytes()).hexdigest()


def _source_path(path: Path) -> Path:
    """Where the sha of the transcript an edit list was made from is kept (#STALE)."""
    return path.with_name(f"{path.stem}.source.json")


def _made_from(path: Path) -> str | None:
    """The sha the list at `path` was saved against, or None for a list saved before #STALE."""
    try:
        return str(json.loads(_source_path(path).read_text(encoding="utf-8"))["transcript_sha"])
    except FileNotFoundError:
        return None


def _put_aside(path: Path, made_from: str) -> str:
    """Move a stale list and its note aside, never deleting them; the sentence the page shows."""
    aside = path.with_name(f"{path.stem}.{made_from[:12]}.json")
    os.replace(path, aside)  # noqa: PTH105
    os.replace(_source_path(path), aside.with_name(f"{aside.stem}.source.json"))  # noqa: PTH105
    return (
        "This transcript was made again after it was last edited, so the old edits no longer "
        f"fit its words. They are kept beside the library as {aside.name}; this list starts "
        "again from the new transcript."
    )
```

4. In `open_edits`, before `if path.is_file():`:

```python
    replaced: str | None = None
    made_from = _made_from(path) if path.is_file() else None
    if made_from is not None and made_from != transcript_sha(row.json_path):
        replaced = _put_aside(path, made_from)
```

   and the return passes `replaced=replaced`. A list saved before this change has no note and is trusted as before; its next save writes one.
5. In `_save`, after `hatao.save(doc, path)`:

```python
    made_from = json.dumps({"transcript_sha": transcript_sha(row.json_path)})
    atomic_write_text(_source_path(path), made_from, fsync=True)
```

In `dsj/ui/routes/marks.py`, `_wire` passes `replaced=opened.replaced`.

- [ ] **Step 5: Complete `dsj/ui/review.py`**

Rewrite `dsj/ui/review.py` as: the docstring, imports, constants and classes below; then Task 7's `review_path` and `progress`, unchanged; then the functions after them below. The import block covers everything `review_path` and `progress` use.

```python
"""A transcript's review (Hashiya spec, Review mode, #REVIEW), and the answer key it becomes.

A review says which of a transcript's sentences a person has checked against
the audio, what they flagged, which speaker they set, and where they were. It
is a document of its own, beside the library in `reviews/`, under the same
key as the transcript's edit list (dsj/ui/edits.py, edits_path): the
transcript JSON's path, so a rebuilt library finds it again. It never holds
words: the words are the edit list's, where Review's corrections go, so the
reader shows them too. A sentence is a span of the recording, which every edit
keeps (a correction keeps its stretch's ends, #83), so the review survives
later corrections.

The answer key is written beside the transcript JSON, as
`<name>.reference.json` (the sentences with their spans, speakers, final words
and flags, and the transcript and model they were checked against) and a plain
`<name>.reference.txt`. Scoring against it is sub-project E.

Plain Python, no fastapi: the routes are dsj/ui/routes/review.py.
"""

from __future__ import annotations

__all__ = [
    "InvalidReview",
    "ReviewIncomplete",
    "progress",
    "read_review",
    "reference",
    "review_path",
    "save_review",
]

import json
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from dsj import hatao
from dsj.atomic import atomic_write_text
from dsj.suno import clock
from dsj.ui import edits
from dsj.ui.edits import NoSuchTranscript, edits_path, transcript_sha
from dsj.ui.schemas import ReferenceWritten, ReviewDocument, ReviewSegment
from dsj.ui.store import Library, library_path

_log = logging.getLogger(__name__)

# Half a millisecond: dsj/hatao.py rounds times to the millisecond.
EPS = 0.0005

_FLAG_WORDS = {
    "unclear": "can't make it out",
    "not_speech": "not speech",
    "overlap": "overlapping talk",
    "cut_off": "cut off",
}


class InvalidReview(ValueError):
    """A review document that is broken. The message names the segment and what is wrong."""


class ReviewIncomplete(ValueError):
    """An answer key asked for while sentences are unchecked, without allow_partial."""
```

(here, Task 7's `review_path` and `progress`), then:

```python
def _json_path(transcript_id: int) -> Path:
    with Library.open() as library:
        found = library.transcript(transcript_id)
    if found is None:
        raise NoSuchTranscript(f"There is no transcript {transcript_id} in the library.")
    if not found.json_path.is_file():
        raise NoSuchTranscript(
            f"Transcript {transcript_id} was last seen at {found.json_path}, and that file is "
            f"gone. The library is only an index; the JSON file is the transcript."
        )
    return found.json_path


def read_review(transcript_id: int) -> tuple[ReviewDocument | None, str]:
    """The transcript's review, or None, and the sha of the transcript as it is now.

    Raises:
        NoSuchTranscript: no such transcript, or its JSON file is gone.
        InvalidReview: the saved review cannot be read, named.
    """
    json_path = _json_path(transcript_id)
    path = review_path(json_path)
    digest = transcript_sha(json_path)
    if not path.is_file():
        return None, digest
    try:
        return ReviewDocument.model_validate_json(path.read_text(encoding="utf-8")), digest
    except ValueError as exc:
        raise InvalidReview(f"The review at {path} cannot be read: {exc}") from exc


def _check(document: ReviewDocument) -> None:
    """Raise naming the first segment that is not a span after the one before it."""
    reached = 0.0
    for index, segment in enumerate(document.segments):
        if not (0 <= segment.start < segment.end):
            raise InvalidReview(
                f"segment {index} runs from {segment.start} to {segment.end} s; it must "
                f"start at 0 or later and end after it starts"
            )
        if segment.start < reached - EPS:
            raise InvalidReview(
                f"segment {index} starts at {segment.start} s, inside the segment before it, which "
                f"ends at {reached} s"
            )
        reached = segment.end


def save_review(transcript_id: int, document: ReviewDocument) -> ReviewDocument:
    """Save the page's review in place of the last one, whole or not at all.

    Raises:
        NoSuchTranscript: no such transcript, or its JSON file is gone.
        InvalidReview: a segment is broken, named; nothing is written.
    """
    _check(document)
    path = review_path(_json_path(transcript_id))
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, document.model_dump_json(), fsync=True)
    return document


def _texts(
    content: Sequence[hatao.Entry], segments: Sequence[ReviewSegment]
) -> list[tuple[str, str | None]]:
    """Each segment's words and the label of who says its first word, in one pass.

    The list's items and the segments are both in time order, so one walk
    covers a 2.5 h call's 1,500 sentences without searching the list for each.
    """
    out: list[tuple[str, str | None]] = [("", None) for _ in segments]
    started = [False] * len(segments)
    k = 0
    speaker: str | None = None
    for entry in content:
        if isinstance(entry, hatao.Paragraph):
            speaker = entry.speaker
            continue
        if not entry.text:
            continue
        while k < len(segments) and entry.source_start >= segments[k].end - EPS:
            k += 1
        if k == len(segments):
            break
        if entry.source_start < segments[k].start - EPS:
            continue
        text, who = out[k]
        out[k] = (text + entry.text, who if started[k] else speaker)
        started[k] = True
    return out


def _plain(segments: list[dict[str, Any]]) -> str:
    """The answer key as text: one line a sentence, `[m:ss] Name: words (flags)`."""
    lines: list[str] = []
    for s in segments:
        who = f"{s['speaker']}: " if s["speaker"] else ""
        flags = cast("list[str]", s["flags"])
        said = f" ({', '.join(_FLAG_WORDS[f] for f in flags)})" if flags else ""
        unchecked = "" if s["checked"] else " [not checked]"
        lines.append(f"[{clock(float(s['start']))}] {who}{s['text']}{said}{unchecked}")
    return "\n".join(lines) + "\n"


def reference(transcript_id: int, *, allow_partial: bool = False) -> ReferenceWritten:
    """Write the review as the transcript's answer key, beside the transcript JSON.

    Raises:
        NoSuchTranscript: no such transcript, or its JSON file is gone.
        ReviewIncomplete: there is no review, or sentences are unchecked and
            `allow_partial` is not set; it says how many.
    """
    document, _ = read_review(transcript_id)
    if document is None:
        raise ReviewIncomplete(
            "This transcript has no review yet. Open Review, check its sentences, then save "
            "the answer key."
        )
    total = len(document.segments)
    unchecked = sum(1 for s in document.segments if s.state != "checked")
    if unchecked and not allow_partial:
        raise ReviewIncomplete(
            f"{unchecked} of {total} sentences are not checked yet. Finish the pass, or save "
            f"a partial answer key, which says it is partial."
        )
    opened = edits.open_edits(transcript_id)
    labels = edits.labels_of(opened)
    json_path = _json_path(transcript_id)
    with Library.open() as library:
        row = library.transcript(transcript_id)
    assert row is not None  # _json_path found it
    segments = [
        {
            "start": s.start,
            "end": s.end,
            "speaker": edits.display_name(who, labels, opened.doc.names),
            "label": who,
            "text": text.strip(),
            "flags": list(s.flags),
            "checked": s.state == "checked",
        }
        for s, (text, who) in zip(
            document.segments, _texts(opened.doc.content, document.segments), strict=True
        )
    ]
    key = {
        "format": "dsj-reference",
        "version": 1,
        "transcript": json_path.name,
        "engine": row.engine,
        "model": row.model,
        "reviewed_against": document.transcript_sha,
        "made_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "complete": unchecked == 0,
        "segments": segments,
    }
    as_json = json_path.with_name(f"{json_path.stem}.reference.json")
    as_text = json_path.with_name(f"{json_path.stem}.reference.txt")
    atomic_write_text(as_json, json.dumps(key, ensure_ascii=False, indent=1), fsync=True)
    atomic_write_text(as_text, _plain(segments), fsync=True)
    return ReferenceWritten(files=[as_json.name, as_text.name], segments=total, unchecked=unchecked)
```

`review_path` uses `library_path` and `edits_path`, and `progress` uses `_log`, `json` and `cast`, so every import above is used; `uv run ruff check dsj/ui/review.py` confirms it.

- [ ] **Step 6: Write `dsj/ui/routes/review.py` and register it**

```python
"""Review mode's routes (#REVIEW): read and save a transcript's review, and write its answer key.

The work is in dsj/ui/review.py; this file only turns requests into its calls.
"""

from __future__ import annotations

__all__ = ["router"]

from fastapi import APIRouter, HTTPException

from dsj.ui import review
from dsj.ui.schemas import ReferenceRequest, ReferenceWritten, Review, ReviewDocument

router = APIRouter(prefix="/api")


def _id(transcript_id: str) -> int:
    """The id as a number, or the same 404 the transcript route gives for anything else."""
    if not (transcript_id.isascii() and transcript_id.isdigit()):
        raise HTTPException(404, f"There is no transcript {transcript_id!r} in the library.")
    return int(transcript_id)


@router.get("/transcripts/{transcript_id}/review")
def read_review(transcript_id: str) -> Review:
    """The transcript's review, or none, and the sha of the transcript as it is now."""
    document, digest = review.read_review(_id(transcript_id))
    return Review(document=document, transcript_sha=digest)


@router.put("/transcripts/{transcript_id}/review")
def save_review(transcript_id: str, document: ReviewDocument) -> ReviewDocument:
    """Save the page's review in place of the last one, or refuse it whole, naming the segment."""
    return review.save_review(_id(transcript_id), document)


@router.post("/transcripts/{transcript_id}/reference")
def write_reference(transcript_id: str, request: ReferenceRequest) -> ReferenceWritten:
    """Write the answer key beside the transcript; refused while unchecked, unless allow_partial."""
    return review.reference(_id(transcript_id), allow_partial=request.allow_partial)
```

In `dsj/ui/server.py`: `from dsj.ui.routes import jobs, marks, media, recording, review` and `app.include_router(review.router)` after `marks`. In `dsj/ui/errors.py`: `from dsj.ui.review import InvalidReview, ReviewIncomplete`, and in `STATUS`:

```python
    # A review document that is broken, named (#REVIEW).
    InvalidReview: 422,
    # An answer key while sentences are unchecked: the request was fine, the review is not done.
    ReviewIncomplete: 409,
```

Run: `uv run pytest tests/test_ui_review.py tests/test_ui_edits.py tests/test_ui_library.py tests/test_ui_errors.py -q`
Expected: PASS.

- [ ] **Step 7: Regenerate the page's types, gate, build**

Run: `uv run just api`, then `uv run just check` (paste the last line), then `uv run just ui-build`.
Expected: `schema.d.ts` has `ReviewDocument`, `ReviewSegment`, `ReviewCorrection`, `Review`, `ReferenceRequest`, `ReferenceWritten` (one each, no `-Input`/`-Output`), and `Edits.replaced`; the gate is green. Unit-test fetch mocks that answer `/edits` add `replaced: null` beside `names: {}` if `tsc` or a test asks for it (`grep -n "pad_s: 0.1" ui/tests/unit/*.tsx`).

- [ ] **Step 8: Commit**

```bash
git add dsj/ui/schemas.py dsj/ui/edits.py dsj/ui/review.py dsj/ui/routes/review.py dsj/ui/routes/marks.py \
  dsj/ui/server.py dsj/ui/errors.py ui/src/api/schema.d.ts tests/test_ui_review.py
git add -A -- dsj/ui/static/
git commit -m "feat: review document, answer-key export, stale edit lists kept aside"
```

(Stage the ui test files too if Step 7 touched them.)

---

### Task 11: The review model

**Files:**
- Create: `ui/src/features/review/model.ts`
- Test: `ui/tests/unit/review-model.test.ts` (new)

**Interfaces:**
- Consumes: Task 10's generated types `ReviewDocument`, `ReviewSegment`, `ReviewCorrection`; `textOf` and `correction` from `features/edit/correct.ts`; `Content`.
- Produces (all from `@/features/review/model`):
  - types `ReviewDocument`, `Segment`, `Flag`, `ReviewPass`, `ReviewCorrection`, `Span = { start: number; end: number }`, `Range = { start: number; stop: number }`, `WordIndex`, `Resumed = { segments: Segment[]; cursor: number; lost: number }`, `Split = { segments: Segment[] } | { refused: string }`, `Counts = { checked: number; total: number; edited: number; flagged: number; reassigned: number }`.
  - constants `SAME_SPAN_S = 0.05`, `BEFORE_S = 0.3`, `AFTER_S = 0.2`, `RESUME_BACK_S = 1.5`.
  - functions `sentenceSpans(content): Span[]`, `freshSegments(content): Segment[]`, `wordIndex(content): WordIndex`, `entryRange(words, span): Range | null`, `segmentText(content, words, span): string`, `indexAt(segments, seconds): number`, `resume(saved: ReviewDocument | null, content, sha: string): Resumed`, `splitAt(content, segments, index, caret): Split`, `mergeWithPrevious(segments, index): Segment[] | null`, `toggleFlag(segment, flag): Segment`, `likelyErrors(content, words, segments, cutoff: number | null, disagree: ReadonlySet<number>): number[]`, `passOrder(count: number, pass, likely: readonly number[]): number[]`, `step(order, current, by: 1 | -1): number | null`, `counts(segments): Counts`, `timeLeft(checkedAtMs: readonly number[], remaining: number): string | null`, `documentOf(fields): ReviewDocument`.

- [ ] **Step 1: Load impeccable: read /Users/moiz/.claude/skills/impeccable/reference/craft-floor.md before editing**

Read it in full; build to it without announcing its checklist.

- [ ] **Step 2: Write the failing model test**

Create `ui/tests/unit/review-model.test.ts`:

```ts
// Review mode's model (Hashiya spec, Review mode), and Review Focus 2 to 5.
import { describe, expect, it } from "vitest";

import { correction } from "../../src/features/edit/correct";
import {
  counts,
  entryRange,
  freshSegments,
  likelyErrors,
  mergeWithPrevious,
  passOrder,
  type ReviewDocument,
  resume,
  type Segment,
  segmentText,
  sentenceSpans,
  splitAt,
  step,
  timeLeft,
  wordIndex,
} from "../../src/features/review/model";
import type { Content, Entry, Item } from "../../src/lib/editOps";

function item(sourceStart: number, length: number, text: string, confidence: number | null = 0.95): Item {
  return { kind: "item", source: "0", sourceStart, length, text, muted: false, confidence };
}
const para = (speaker: string): Entry => ({ kind: "paragraph", speaker, language: null });

// Three sentences. The third has a word in two pieces, " questi" "on".
const CONTENT: Content = [
  para("SPEAKER_00"),
  item(0, 0.2, "", null),
  item(0.2, 0.3, " alpha"),
  item(0.6, 0.3, " bravo"),
  item(1.0, 0.3, " charlie", 0.2),
  item(1.3, 0.3, " delta"),
  item(1.6, 0.4, "", null),
  para("SPEAKER_01"),
  item(2.0, 0.4, " echo"),
  para("SPEAKER_00"),
  item(3.0, 0.3, " a"),
  item(3.3, 0.2, " questi"),
  item(3.5, 0.1, "on"),
];

const seg = (start: number, end: number, extra: Partial<Segment> = {}): Segment => ({
  start, end, state: "unchecked", flags: [], speaker: null, edited: false, ...extra,
});

describe("segments", () => {
  it("are the list's sentences, from first word to last word's end", () => {
    expect(sentenceSpans(CONTENT)).toEqual([
      { start: 0.2, end: 1.6 },
      { start: 2.0, end: 2.4 },
      { start: 3.0, end: 3.6 },
    ]);
    expect(freshSegments(CONTENT)[0]).toEqual(seg(0.2, 1.6));
  });

  it("know their words and the entries holding them", () => {
    const words = wordIndex(CONTENT);
    expect(entryRange(words, { start: 0.2, end: 1.6 })).toEqual({ start: 2, stop: 6 });
    expect(segmentText(CONTENT, words, { start: 3.0, end: 3.6 })).toBe("a question");
    expect(entryRange(words, { start: 5, end: 6 })).toBeNull();
  });
});

describe("a correction that changes the word count (Review Focus 2)", () => {
  it("keeps the sentence's span, shows the new words, leaves the neighbours, and is not applied twice", () => {
    const words = wordIndex(CONTENT);
    const span = { start: 0.2, end: 1.6 };
    const range = entryRange(words, { start: 1.0, end: 1.3 });
    if (range === null) throw new Error("no charlie");
    const op = correction(CONTENT, range.start, range.stop, "Charles Darwin");
    const after = [...CONTENT.slice(0, op.start), ...op.entries, ...CONTENT.slice(op.stop)];
    const again = wordIndex(after);
    expect(segmentText(after, again, span)).toBe("alpha bravo Charles Darwin delta");
    expect(segmentText(after, again, { start: 2.0, end: 2.4 })).toBe("echo");
    expect(sentenceSpans(after)).toEqual(sentenceSpans(CONTENT));
    // What the box shows is now what the list says: checking again changes nothing.
    expect(segmentText(after, again, span).trim() === "alpha bravo Charles Darwin delta").toBe(true);
  });
});

describe("splitAt (Review Focus 3)", () => {
  const segments = freshSegments(CONTENT);
  // "alpha bravo charlie delta": alpha 0-5, bravo 6-11, charlie 12-19, delta 20-25.
  it.each([
    [5, 0.6],
    [6, 0.6],
    [8, 0.6],
    [10, 1.0],
    [19, 1.3],
  ])("splits at the word boundary nearest caret %i, at %f s", (caret, at) => {
    const split = splitAt(CONTENT, segments, 0, caret);
    if ("refused" in split) throw new Error(split.refused);
    expect(split.segments.slice(0, 2)).toEqual([seg(0.2, at), seg(at, 1.6)]);
    expect(split.segments).toHaveLength(4);
  });

  it.each([0, 2, 25])("refuses caret %i, which snaps to the sentence's own start or end", (caret) => {
    const split = splitAt(CONTENT, segments, 0, caret);
    expect("refused" in split && split.refused).toMatch(/between two words/);
  });

  it("refuses a one-word sentence, and a word in two pieces is one word", () => {
    expect(splitAt(CONTENT, segments, 1, 2)).toEqual({ refused: "This sentence is one word, so there is nowhere to split it." });
    const pieces = splitAt(CONTENT, segments, 2, 5);
    if ("refused" in pieces) throw new Error(pieces.refused);
    expect(pieces.segments[2]).toEqual(seg(3.0, 3.3));
  });
});

describe("merging", () => {
  it("joins a sentence to the one before, unchecked, keeping both sets of flags", () => {
    const merged = mergeWithPrevious([seg(0.2, 1.6, { state: "checked", flags: ["overlap"] }), seg(2.0, 2.4, { flags: ["unclear"] })], 1);
    expect(merged).toEqual([seg(0.2, 2.4, { flags: ["overlap", "unclear"] })]);
    expect(mergeWithPrevious([seg(0, 1)], 0)).toBeNull();
  });
});

describe("resume (Review Focus 4)", () => {
  const saved = (sha: string, segments: Segment[], cursor = 2.0): ReviewDocument => ({
    version: 1, transcript_sha: sha, review_pass: "every", cursor_s: cursor,
    started_at: "x", updated_at: "x", segments, corrections: [],
  });

  it("starts fresh with no review", () => {
    expect(resume(null, CONTENT, "s1")).toEqual({ segments: freshSegments(CONTENT), cursor: 0, lost: 0 });
  });

  it("takes the saved review as it is when the transcript is the one it was made against, at the same sentence", () => {
    const segments = [seg(0.2, 1.0, { state: "checked" }), seg(1.0, 1.6), seg(2.0, 2.4), seg(3.0, 3.6)];
    expect(resume(saved("s1", segments), CONTENT, "s1")).toEqual({ segments, cursor: 2, lost: 0 });
  });

  it("transcribed again: keeps what still matches by span, and counts the checked ones that do not", () => {
    // The second sentence moved by 0.03 s, inside SAME_SPAN_S: still the same sentence.
    const old = [seg(0.2, 1.6, { state: "checked", flags: ["overlap"] }), seg(2.0, 2.43, { state: "checked" }), seg(3.0, 3.6, { state: "checked" })];
    const back = resume(saved("old", old), CONTENT, "new");
    expect(back.segments.map((s) => s.state)).toEqual(["checked", "checked", "checked"]);
    expect(back.segments[0]?.flags).toEqual(["overlap"]);
    const moved = [seg(0.2, 1.4, { state: "checked" }), seg(2.0, 2.4, { state: "checked" })];
    const again = resume(saved("old", moved), CONTENT, "new");
    expect(again.segments.map((s) => s.state)).toEqual(["unchecked", "checked", "unchecked"]);
    expect(again.lost).toBe(1);
    expect(again.cursor).toBe(1);
  });
});

describe("passes and likely errors", () => {
  const segments = [seg(0.2, 1.6), seg(2.0, 2.4, { flags: ["cut_off"] }), seg(3.0, 3.6)];
  it("finds unsure words, flags and disagreements", () => {
    const words = wordIndex(CONTENT);
    expect(likelyErrors(CONTENT, words, segments, 0.3, new Set())).toEqual([0, 1]);
    expect(likelyErrors(CONTENT, words, segments, null, new Set([2]))).toEqual([1, 2]);
  });

  it("orders a pass and steps through it", () => {
    expect(passOrder(3, "every", [1])).toEqual([0, 1, 2]);
    expect(passOrder(3, "likely", [0, 2])).toEqual([0, 2]);
    expect(step([0, 2], 0, 1)).toBe(2);
    expect(step([0, 2], 1, 1)).toBe(2);
    expect(step([0, 2], 2, 1)).toBeNull();
    expect(step([0, 2], 2, -1)).toBe(0);
  });

  it("counts what the pass did", () => {
    expect(counts([seg(0, 1, { state: "checked", edited: true }), seg(1, 2, { flags: ["unclear"], speaker: "SPEAKER_01" })])).toEqual({
      checked: 1, total: 2, edited: 1, flagged: 1, reassigned: 1,
    });
  });
});

describe("timeLeft", () => {
  it("says nothing until three checks give a pace, then goes by the median gap", () => {
    expect(timeLeft([0, 10_000], 100)).toBeNull();
    // Gaps of 10 s, 12 s and a 300 s coffee break: the median is 12 s.
    expect(timeLeft([0, 10_000, 22_000, 322_000], 250)).toBe("about 50 min left");
    expect(timeLeft([0, 10_000, 20_000], 600)).toBe("about 1 h 40 min left");
    expect(timeLeft([0, 1000, 2000], 10)).toBe("under a minute left");
  });
});

describe("a 2.5 h call (Review Focus 5)", () => {
  it("builds its 1,500 sentences, their index and their likely errors in under 50 ms", () => {
    const long: Entry[] = [];
    let t = 0;
    for (let s = 0; s < 1500; s += 1) {
      long.push(para(`SPEAKER_0${s % 4}`));
      for (let w = 0; w < 21; w += 1) {
        long.push(item(t, 0.28, ` w${w}`, w === 7 ? 0.1 : 0.95));
        t += 0.2886;
      }
    }
    const began = performance.now();
    const segments = freshSegments(long);
    const words = wordIndex(long);
    const likely = likelyErrors(long, words, segments, 0.3, new Set());
    const took = performance.now() - began;
    expect(segments).toHaveLength(1500);
    expect(likely).toHaveLength(1500);
    expect(took).toBeLessThan(50);
  });
});
```

Run: `cd ui && npx vitest run tests/unit/review-model.test.ts`
Expected: FAIL, `Failed to resolve import "../../src/features/review/model"`.

- [ ] **Step 3: Write `ui/src/features/review/model.ts`**

```ts
// Review mode's model (Hashiya spec, Review mode): the sentences being
// checked, by their span of the recording; splitting and merging them; the
// two passes; which sentences are likely errors; and picking a review up
// again. Pure: no React, no fetch.
//
// A segment is a span of time, not a run of entries, because every edit
// keeps time: a correction keeps its stretch's start and end (#83), a speaker
// change moves only paragraph marks, and a split cuts at a word's start. So a
// segment saved before an edit names the same words after it, and the edit
// list stays the one home of the words.

import type { components } from "@/api/schema";
import { textOf } from "@/features/edit/correct";
import type { Content } from "@/lib/editOps";

export type ReviewDocument = components["schemas"]["ReviewDocument"];
export type Segment = components["schemas"]["ReviewSegment"];
export type ReviewCorrection = components["schemas"]["ReviewCorrection"];
export type Flag = Segment["flags"][number];
export type ReviewPass = ReviewDocument["review_pass"];

export type Span = { start: number; end: number };
export type Range = { start: number; stop: number };

// Half a millisecond: dsj/hatao.py rounds times to the millisecond.
const EPS = 0.0005;

// Two spans are one sentence across a re-transcription when both ends agree
// this closely, in seconds: about one parakeet frame (0.08 s) less a margin,
// so a sentence that moved by a word is not taken for the old one.
export const SAME_SPAN_S = 0.05;

// Arriving on a sentence plays it from just before to just after (spec), and
// resuming after typing backs up (spec, Tab).
export const BEFORE_S = 0.3;
export const AFTER_S = 0.2;
export const RESUME_BACK_S = 1.5;

/** Each sentence of the list: from its paragraph mark's first word to its last word's end. */
export function sentenceSpans(content: Content): Span[] {
  const out: Span[] = [];
  let open: Span | null = null;
  for (const entry of content) {
    if (entry.kind === "paragraph") {
      if (open !== null) out.push(open);
      open = null;
      continue;
    }
    if (entry.text === "") continue;
    const end = entry.sourceStart + entry.length;
    if (open === null) open = { start: entry.sourceStart, end };
    else open.end = Math.max(open.end, end);
  }
  if (open !== null) out.push(open);
  return out;
}

export function freshSegments(content: Content): Segment[] {
  return sentenceSpans(content).map(({ start, end }): Segment => ({ start, end, state: "unchecked", flags: [], speaker: null, edited: false }));
}

/**
 * Every item with words, as its entry index and its start, in list order.
 * The list plays in order (ui/src/lib/linter.ts holds it), so the starts are
 * sorted and a segment's words are found by binary search.
 */
export type WordIndex = { at: Uint32Array; start: Float64Array };

export function wordIndex(content: Content): WordIndex {
  const at: number[] = [];
  const start: number[] = [];
  content.forEach((entry, index) => {
    if (entry.kind === "item" && entry.text !== "") {
      at.push(index);
      start.push(entry.sourceStart);
    }
  });
  return { at: Uint32Array.from(at), start: Float64Array.from(start) };
}

function firstFrom(starts: Float64Array, seconds: number): number {
  let lo = 0;
  let hi = starts.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if ((starts[mid] ?? 0) < seconds) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** The entries holding a span's words: from its first word item to one past its last; null when it has none. */
export function entryRange(words: WordIndex, span: Span): Range | null {
  const lo = firstFrom(words.start, span.start - EPS);
  const hi = firstFrom(words.start, span.end - EPS);
  if (hi <= lo) return null;
  return { start: words.at[lo] ?? 0, stop: (words.at[hi - 1] ?? 0) + 1 };
}

/** A span's words as the box shows them, or "" when it has none. */
export function segmentText(content: Content, words: WordIndex, span: Span): string {
  const range = entryRange(words, span);
  return range === null ? "" : textOf(content, range.start, range.stop);
}

/** The segment at or after `seconds`: where a saved cursor resumes. */
export function indexAt(segments: readonly Span[], seconds: number): number {
  const found = segments.findIndex((s) => s.end > seconds + EPS);
  return found < 0 ? Math.max(0, segments.length - 1) : found;
}

export type Resumed = { segments: Segment[]; cursor: number; lost: number };

/**
 * The review to pick up: the saved one as it is when the transcript is the
 * one it was made against; else this transcript's sentences, each keeping
 * what a saved one with the same span said (Review Focus 4: a run from the
 * app with the same settings writes the same file). `lost` counts the checked
 * sentences that no longer match, for the page to say.
 */
export function resume(saved: ReviewDocument | null, content: Content, sha: string): Resumed {
  if (saved !== null && saved.transcript_sha === sha) {
    return { segments: saved.segments, cursor: indexAt(saved.segments, saved.cursor_s), lost: 0 };
  }
  const fresh = freshSegments(content);
  if (saved === null) return { segments: fresh, cursor: 0, lost: 0 };
  const used = new Set<number>();
  let k = 0;
  const segments = fresh.map((segment) => {
    while (k < saved.segments.length && (saved.segments[k]?.start ?? 0) < segment.start - SAME_SPAN_S) k += 1;
    const old = saved.segments[k];
    if (old === undefined || Math.abs(old.start - segment.start) > SAME_SPAN_S || Math.abs(old.end - segment.end) > SAME_SPAN_S) {
      return segment;
    }
    used.add(k);
    return { ...segment, state: old.state, flags: [...old.flags], speaker: old.speaker, edited: old.edited };
  });
  const lost = saved.segments.filter((s, i) => s.state === "checked" && !used.has(i)).length;
  return { segments, cursor: indexAt(segments, saved.cursor_s), lost };
}

export type Split = { segments: Segment[] } | { refused: string };

const BETWEEN = "Put the cursor between two words: a sentence splits where one word ends and the next begins, not at its start or its end.";

/**
 * Split segment `index` at `caret`, a place in the text the box shows
 * (spec: "time split at the matching word boundary"). A caret in the gap
 * between two words splits there; inside a word, at the nearer edge of that
 * word (Review Focus 3). An edge that is the sentence's own start or end, and
 * a one-word sentence, are refused with a sentence saying why. A word in
 * pieces (" questi" "on") is one word, as the reader reads it.
 */
export function splitAt(content: Content, segments: readonly Segment[], index: number, caret: number): Split {
  const segment = segments[index];
  const range = segment === undefined ? null : entryRange(wordIndex(content), segment);
  if (segment === undefined || range === null) return { refused: "This sentence has no words to split." };
  // Each word's first letter in the joined text, and its start in the recording.
  let raw = "";
  const opens: { at: number; time: number }[] = [];
  for (let e = range.start; e < range.stop; e += 1) {
    const entry = content[e];
    if (entry?.kind !== "item" || entry.text === "") continue;
    if (opens.length === 0 || /^\s/.test(entry.text)) {
      opens.push({ at: raw.length + (/^\s*/.exec(entry.text)?.[0].length ?? 0), time: entry.sourceStart });
    }
    raw += entry.text;
  }
  if (opens.length < 2) return { refused: "This sentence is one word, so there is nowhere to split it." };
  const lead = raw.length - raw.trimStart().length;
  const text = raw.trim();
  const begins = opens.map((o) => o.at - lead);
  const ends = begins.map((_, k) => (k + 1 < begins.length ? text.slice(0, begins[k + 1]).trimEnd().length : text.length));
  // Boundary k sits before word k; 0 and begins.length are the sentence's own ends.
  let k = -1;
  for (let b = 1; b < begins.length; b += 1) {
    if (caret >= (ends[b - 1] ?? 0) && caret <= (begins[b] ?? 0)) {
      k = b;
      break;
    }
  }
  if (k < 0) {
    const inside = begins.findIndex((b, w) => caret > b && caret < (ends[w] ?? 0));
    if (inside >= 0) k = caret - (begins[inside] ?? 0) <= (ends[inside] ?? 0) - caret ? inside : inside + 1;
    else k = caret <= (begins[0] ?? 0) ? 0 : begins.length;
  }
  if (k <= 0 || k >= begins.length) return { refused: BETWEEN };
  const at = opens[k]?.time ?? segment.start;
  const first: Segment = { ...segment, end: at, state: "unchecked" };
  const second: Segment = { ...segment, start: at, state: "unchecked" };
  return { segments: [...segments.slice(0, index), first, second, ...segments.slice(index + 1)] };
}

/** Segment `index` joined to the one before it, to be checked again; null for the first. */
export function mergeWithPrevious(segments: readonly Segment[], index: number): Segment[] | null {
  const previous = segments[index - 1];
  const current = segments[index];
  if (index < 1 || previous === undefined || current === undefined) return null;
  const merged: Segment = {
    start: previous.start,
    end: current.end,
    state: "unchecked",
    flags: [...new Set([...previous.flags, ...current.flags])],
    speaker: previous.speaker ?? current.speaker,
    edited: previous.edited || current.edited,
  };
  return [...segments.slice(0, index - 1), merged, ...segments.slice(index + 1)];
}

export function toggleFlag(segment: Segment, flag: Flag): Segment {
  const flags = segment.flags.includes(flag) ? segment.flags.filter((f) => f !== flag) : [...segment.flags, flag];
  return { ...segment, flags };
}

/**
 * The likely errors (spec, "Passes"): a sentence with an unsure word (under
 * the engine's cut-off, ui/src/features/transcript/confidence.ts), a flag, or
 * a disagreement with the second opinion. One walk over each span's entries.
 */
export function likelyErrors(
  content: Content,
  words: WordIndex,
  segments: readonly Segment[],
  cutoff: number | null,
  disagree: ReadonlySet<number>,
): number[] {
  const out: number[] = [];
  segments.forEach((segment, index) => {
    if (segment.flags.length > 0 || disagree.has(index)) {
      out.push(index);
      return;
    }
    const range = cutoff === null ? null : entryRange(words, segment);
    if (range === null || cutoff === null) return;
    for (let e = range.start; e < range.stop; e += 1) {
      const entry = content[e];
      if (entry?.kind === "item" && entry.text !== "" && entry.confidence !== null && entry.confidence < cutoff) {
        out.push(index);
        return;
      }
    }
  });
  return out;
}

/** The segments a pass visits, in order. */
export function passOrder(count: number, pass: ReviewPass, likely: readonly number[]): number[] {
  return pass === "likely" ? [...likely] : Array.from({ length: count }, (_, i) => i);
}

/** The next (or previous) segment of `order` after (or before) `current`, or null at the end. */
export function step(order: readonly number[], current: number, by: 1 | -1): number | null {
  if (by > 0) return order.find((i) => i > current) ?? null;
  return [...order].reverse().find((i) => i < current) ?? null;
}

export type Counts = { checked: number; total: number; edited: number; flagged: number; reassigned: number };

/** What the pass did, for its end (spec, "Finishing"). */
export function counts(segments: readonly Segment[]): Counts {
  return {
    checked: segments.filter((s) => s.state === "checked").length,
    total: segments.length,
    edited: segments.filter((s) => s.edited).length,
    flagged: segments.filter((s) => s.flags.length > 0).length,
    reassigned: segments.filter((s) => s.speaker !== null).length,
  };
}

/**
 * Time left at the current pace (spec, top bar): the median gap between this
 * session's checks, so one long pause does not double the estimate. Nothing
 * until three checks make a pace.
 */
export function timeLeft(checkedAtMs: readonly number[], remaining: number): string | null {
  if (checkedAtMs.length < 3 || remaining <= 0) return null;
  const gaps = checkedAtMs
    .slice(1)
    .map((t, k) => t - (checkedAtMs[k] ?? t))
    .sort((a, b) => a - b);
  const median = gaps[gaps.length >> 1] ?? 0;
  const minutes = Math.round((median * remaining) / 60_000);
  if (minutes < 1) return "under a minute left";
  if (minutes < 60) return `about ${minutes} min left`;
  return `about ${Math.floor(minutes / 60)} h ${minutes % 60} min left`;
}

/** The document the page saves. */
export function documentOf(fields: {
  sha: string;
  pass: ReviewPass;
  cursorS: number;
  startedAt: string;
  segments: readonly Segment[];
  corrections: readonly ReviewCorrection[];
}): ReviewDocument {
  return {
    version: 1,
    transcript_sha: fields.sha,
    review_pass: fields.pass,
    cursor_s: fields.cursorS,
    started_at: fields.startedAt,
    updated_at: new Date().toISOString(),
    segments: [...fields.segments],
    corrections: [...fields.corrections],
  };
}
```

`timeLeft([0, 10_000, 22_000, 322_000], 250)`: gaps 10 s, 12 s, 300 s, median 12 s, 12 × 250 = 3,000 s = 50 min. `timeLeft([0, 10_000, 20_000], 600)`: median 10 s, 6,000 s = 100 min, "about 1 h 40 min left".

- [ ] **Step 4: Run it**

Run: `cd ui && npx vitest run tests/unit/review-model.test.ts`
Expected: PASS. If a `splitAt` case fails, print `begins` and `ends` for "alpha bravo charlie delta" (expected `[0, 6, 12, 20]` and `[5, 11, 19, 25]`) before changing the rule.

- [ ] **Step 5: Gate, build**

Run: `uv run just check` (paste the last line), `uv run just ui-build` (a new file under `ui/src`).

- [ ] **Step 6: Look at it**

Run: `uv run python scratch/ui_shots.py --label t11 library reader`
Expected: 8 PNGs. This task draws nothing new; check that both pages look exactly as the last task left them, with no error dialog and nothing shifted, at both sizes and in both schemes.

- [ ] **Step 7: Commit**

```bash
git add ui/src/features/review/model.ts ui/tests/unit/review-model.test.ts
git add -A -- dsj/ui/static/
git commit -m "feat(review): segments by span, split, merge, passes, resume"
```

---

### Task 12: The second opinion

**Files:**
- Create: `ui/src/features/review/secondOpinion.ts`
- Test: `ui/tests/unit/second-opinion.test.ts` (new)

**Interfaces:**
- Consumes: `read`, `parseTranscript`, `type Reading` from `features/transcript/document.ts`; `firstStrong` from `@/lib/script`; Task 11's `Span`; `RecordingRow`, `TranscriptRow`; `api`.
- Produces: `type Opinions = { words: string[][]; differs: (boolean[] | null)[]; disagree: Set<number> }`, `opinionWords(other: Reading, spans: readonly Span[]): string[][]`, `normalize(word: string): string`, `differing(mine: readonly string[], theirs: readonly string[]): boolean[]`, `sameScript(a: string, b: string): boolean`, `secondOpinion(other: Reading | null, spans: readonly Span[], mine: readonly string[]): Opinions`, `otherTranscript(recording: RecordingRow, transcriptId: number): TranscriptRow | null`, `loadReading(transcriptId: number): Promise<Reading>`.

- [ ] **Step 1: Load impeccable: read /Users/moiz/.claude/skills/impeccable/reference/craft-floor.md before editing**

Read it in full; build to it without announcing its checklist.

- [ ] **Step 2: Write the failing test**

Create `ui/tests/unit/second-opinion.test.ts`:

```ts
// The other transcript's reading of the same span (Hashiya spec, Review mode).
import { describe, expect, it } from "vitest";

import type { RecordingRow, TranscriptRow } from "../../src/features/library/types";
import { differing, normalize, opinionWords, otherTranscript, sameScript, secondOpinion } from "../../src/features/review/secondOpinion";
import { read, type Sentence } from "../../src/features/transcript/document";

function sentence(start: number, words: string[], step = 0.4): Sentence {
  const tokens = words.map((w, i) => ({ t: +(start + i * step).toFixed(2), w }));
  return { start, end: +(start + words.length * step).toFixed(2), text: tokens.map((t) => t.w).join(""), tokens };
}

// The other engine cut its sentences elsewhere: one sentence across both spans.
const OTHER = read({ audio: "a", model: "whisper", sentences: [sentence(0.2, [" alpha", " bravo", " Charlie,", " delta", " echo"])] });

describe("opinionWords", () => {
  it("gives each span the other reading's words whose middle falls inside it", () => {
    // Words at 0.2, 0.6, 1.0, 1.4, 1.8, each 0.4 s: their middles are 0.4, 0.8, 1.2, 1.6, 2.0 (the last ends at the sentence's end, 2.2).
    expect(opinionWords(OTHER, [{ start: 0.2, end: 1.3 }, { start: 1.3, end: 2.4 }])).toEqual([
      ["alpha", "bravo", "Charlie,"],
      ["delta", "echo"],
    ]);
  });
});

describe("differing", () => {
  it("marks the other's words that are not in the longest run of equal words, case and punctuation aside", () => {
    expect(differing(["alpha", "bravo", "charlie"], ["alpha", "brave", "Charlie,"])).toEqual([false, true, false]);
    expect(differing(["a", "b"], ["a", "x", "b"])).toEqual([false, true, false]);
  });

  it("folds Arabic letter variants and short vowels, so one Urdu word in two spellings is the same word", () => {
    expect(normalize("كيا")).toBe(normalize("کیا"));
    expect(normalize("کَیا")).toBe(normalize("کیا"));
  });
});

describe("sameScript", () => {
  it("compares only readings in one script: Roman Urdu against Urdu script underlines nothing", () => {
    expect(sameScript("kya hua", "کیا ہوا")).toBe(false);
    expect(sameScript("kya hua", "kia hua")).toBe(true);
  });
});

describe("secondOpinion", () => {
  it("underlines only where both are in one script, and counts a disagreement", () => {
    const opinions = secondOpinion(OTHER, [{ start: 0.2, end: 1.3 }, { start: 1.3, end: 2.4 }], ["alpha bravo charlie", "دیلٹا ایکو"]);
    expect(opinions.differs).toEqual([[false, false, false], null]);
    expect([...opinions.disagree]).toEqual([]);
    expect(secondOpinion(null, [{ start: 0, end: 1 }], ["x"]).words).toEqual([[]]);
  });
});

describe("otherTranscript", () => {
  const t = (id: number): TranscriptRow =>
    ({ id, finished_at: "x", engine: "whisper", model: "m", diarized: null, speaker_count: null, mark_count: null, language: null, last_edited_at: null, language_tag: null, review_checked: null, review_total: null });
  it("is the newest other transcript of the same recording, or none", () => {
    const row = { transcripts: [t(9), t(7), t(3)] } as unknown as RecordingRow;
    expect(otherTranscript(row, 7)?.id).toBe(9);
    expect(otherTranscript(row, 9)?.id).toBe(7);
    expect(otherTranscript({ transcripts: [t(7)] } as unknown as RecordingRow, 7)).toBeNull();
  });
});
```

Run: `cd ui && npx vitest run tests/unit/second-opinion.test.ts`
Expected: FAIL, `Failed to resolve import "../../src/features/review/secondOpinion"`.

- [ ] **Step 3: Write `ui/src/features/review/secondOpinion.ts`**

```ts
// The second opinion (Hashiya spec, Review mode): "when another transcript of
// the same recording exists, its reading of the same time span appears in
// grey as a second opinion; where both are in the same script, the words that
// differ are underlined." It also feeds the "Likely errors" pass.
//
// Aligned by time, not by text: two engines cut sentences in different
// places, but a word said at 12.3 s is at 12.3 s in both. A word of the other
// reading belongs to the span its middle falls in, so a word across a boundary
// is counted once. The other transcript is loaded by the routes the reader
// already uses; nothing new is asked of the server.

import { api } from "@/api/client";
import { ApiError, fromBody } from "@/features/errors/appError";
import type { RecordingRow, TranscriptRow } from "@/features/library/types";
import { parseTranscript, read, type Reading } from "@/features/transcript/document";
import { firstStrong } from "@/lib/script";
import type { Span } from "./model";

export type Opinions = {
  /** The other reading's words, one list a span. */
  words: string[][];
  /** Which of those words differ from this transcript's, or null where the scripts differ. */
  differs: (boolean[] | null)[];
  /** The spans where the two disagree on a word: likely errors. */
  disagree: Set<number>;
};

/** The other reading's words for each span, in one walk (both are in time order). */
export function opinionWords(other: Reading, spans: readonly Span[]): string[][] {
  const { start, end, turn, offset, length } = other.words;
  const out: string[][] = spans.map(() => []);
  let k = 0;
  for (let w = 0; w < start.length; w += 1) {
    const middle = ((start[w] ?? 0) + (end[w] ?? 0)) / 2;
    while (k < spans.length && middle >= (spans[k]?.end ?? 0)) k += 1;
    if (k === spans.length) break;
    if (middle < (spans[k]?.start ?? 0)) continue;
    const from = offset[w] ?? 0;
    const text = other.turns[turn[w] ?? 0]?.text.slice(from, from + (length[w] ?? 0)).trim();
    if (text) out[k]?.push(text);
  }
  return out;
}

/**
 * A word as compared: case and punctuation dropped, short vowels (harakat)
 * dropped, and the Arabic letter forms Urdu writes otherwise folded to Urdu's
 * (ي and ى to ی, ك to ک), as dsj/hatao.py `normalize` folds them for bleeping.
 */
export function normalize(word: string): string {
  return word
    .normalize("NFC")
    .toLocaleLowerCase()
    .replace(/[ً-ٰٟ]/g, "")
    .replace(/[يى]/g, "ی")
    .replace(/ك/g, "ک")
    .replace(/[\p{P}\p{S}]/gu, "");
}

/** Which of `theirs` are not in the longest common run of equal words with `mine`. */
export function differing(mine: readonly string[], theirs: readonly string[]): boolean[] {
  const a = mine.map(normalize);
  const b = theirs.map(normalize);
  const n = a.length;
  const m = b.length;
  // Sentences are short (a few dozen words; the longest the perf fixture has is 412 tokens), so a table is fine.
  const table = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i -= 1) {
    const row = table[i] as Uint16Array;
    const below = table[i + 1] as Uint16Array;
    for (let j = m - 1; j >= 0; j -= 1) {
      row[j] = a[i] === b[j] ? (below[j + 1] ?? 0) + 1 : Math.max(below[j] ?? 0, row[j + 1] ?? 0);
    }
  }
  const same = new Array<boolean>(m).fill(false);
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      same[j] = true;
      i += 1;
      j += 1;
    } else if ((table[i + 1]?.[j] ?? 0) >= (table[i]?.[j + 1] ?? 0)) {
      i += 1;
    } else {
      j += 1;
    }
  }
  return same.map((s, k) => !s && b[k] !== "");
}

/** Both readings open in the same script: only then is a word-by-word comparison meaningful. */
export function sameScript(a: string, b: string): boolean {
  const script = firstStrong(a);
  return script !== "none" && script === firstStrong(b);
}

/** The second opinion for every span, given this transcript's text of each. */
export function secondOpinion(other: Reading | null, spans: readonly Span[], mine: readonly string[]): Opinions {
  if (other === null) return { words: spans.map(() => []), differs: spans.map(() => null), disagree: new Set() };
  const words = opinionWords(other, spans);
  const disagree = new Set<number>();
  const differs = words.map((theirs, k) => {
    const own = mine[k] ?? "";
    if (theirs.length === 0 || !sameScript(own, theirs.join(" "))) return null;
    const marks = differing(own.split(/\s+/).filter(Boolean), theirs);
    if (marks.some(Boolean)) disagree.add(k);
    return marks;
  });
  return { words, differs, disagree };
}

/** The newest other transcript of the same recording, or null (the library lists them newest first). */
export function otherTranscript(recording: RecordingRow, transcriptId: number): TranscriptRow | null {
  return recording.transcripts.find((t) => t.id !== transcriptId) ?? null;
}

/** Another transcript's words, read as the reader reads them. Throws ApiError in the server's words. */
export async function loadReading(transcriptId: number): Promise<Reading> {
  const route = `/api/transcripts/${transcriptId}`;
  const { data, error, response } = await api.GET("/api/transcripts/{transcript_id}", {
    params: { path: { transcript_id: String(transcriptId) } },
  });
  if (data === undefined) throw new ApiError(fromBody(error, response, route));
  return read(parseTranscript(data));
}
```

- [ ] **Step 4: Run it**

Run: `cd ui && npx vitest run tests/unit/second-opinion.test.ts`
Expected: PASS. (The first `opinionWords` case: the last word "echo" ends at the sentence's end, 2.2, so its middle is 2.0, inside the second span.)

- [ ] **Step 5: Gate, build**

Run: `uv run just check` (paste the last line), `uv run just ui-build`.

- [ ] **Step 6: Look at it**

Run: `uv run python scratch/ui_shots.py --label t12 library reader`
Expected: 8 PNGs. This task draws nothing new; check that both pages look exactly as the last task left them, with no error dialog and nothing shifted, at both sizes and in both schemes.

- [ ] **Step 7: Commit**

```bash
git add ui/src/features/review/secondOpinion.ts ui/tests/unit/second-opinion.test.ts
git add -A -- dsj/ui/static/
git commit -m "feat(review): second opinion aligned by time, differing words marked"
```

---

### Task 13: Review mode on the laptop

**Files:**
- Modify: `ui/src/lib/route.ts` (the review route), `ui/src/App.tsx` (render it)
- Create: `ui/src/features/review/keymap.ts`, `ui/src/features/review/reviewApi.ts`, `ui/src/features/review/useReviewSession.ts`, `ui/src/features/review/ReviewDesk.tsx`, `ui/src/features/review/FinishPanel.tsx`, `ui/src/features/review/ReviewPage.tsx`, `ui/src/features/review/review.css`
- Modify: `ui/src/features/shell/keys.ts` (`REVIEW_SHEET`, `FOOTER_KEYS`, R in `READER_SHEET`), `ui/src/features/transcript/readerKeys.ts` (R), `ui/src/features/transcript/TranscriptPage.tsx` (the gold Review button; the stale-list note), `ui/src/features/edit/editing.ts` (`Editable.replaced`)
- Test: `ui/tests/unit/keymap.test.ts` (new), `ui/tests/unit/review.test.tsx` (new), `ui/tests/unit/route.test.ts`

**Interfaces:**
- Consumes: Task 11's model, Task 12's `secondOpinion`, `otherTranscript`, `loadReading`; Task 10's routes and types; Task 5's `speakerChange`, `newSpeakerLabel`, `speakerAt`, `speakerLabels`, `Editable.names`; Task 3's `openTranscript`, `KeysItem`, `showKeys`, `displayName`, `speakerColour`; Task 2's `Player` (no article), `PlayerControls`, `stepSpeed`; Task 8's `displayTitle`.
- Produces:
  - `route.ts`: `Route` gains `{ page: "review"; recording: number; transcript: number }`; `reviewHref(recording: number, transcript: number): string`.
  - `keymap.ts`: `type Action` (kinds `check`, `previous`, `toggle`, `replay`, `slower`, `faster`, `speaker` with `n`, `second`, `unclear`, `flags`, `flag` with `flag: Flag`, `split`, `merge`, `nextLikely`, `previousLikely`, `keys`, `leave`), `actionFor(event): Action | null`.
  - `reviewApi.ts`: `loadReview(transcriptId): Promise<{ document: ReviewDocument | null; sha: string }>`, `saveAnswerKey(transcriptId, allowPartial): Promise<ReferenceWritten>`, `useReviewSave(transcriptId, document): { state: SaveState; flush(): Promise<void> }`.
  - `useReviewSession(args): Session`, with `type Session` and `type SentenceView` as below (Task 14's card draws the same `Session`); `Session.pause()` stops playback while typing.
  - `ReviewPage({ recording, transcript, navigate? })`, `ReviewDesk({ session, title, back, transcriptId })`, `FinishPanel({ transcriptId, progress, back })`, and from `ReviewDesk.tsx` `FLAGS: [Flag, string][]` and `SecondOpinion({ second })`, which Task 14's card reuses.

- [ ] **Step 1: Load impeccable: read /Users/moiz/.claude/skills/impeccable/reference/craft-floor.md before editing**

Read it in full; build to it without announcing its checklist.

- [ ] **Step 2: Write the failing keymap and route tests**

Create `ui/tests/unit/keymap.test.ts`:

```ts
// Review's keys, exactly the spec's table (Hashiya spec, Review mode).
import { describe, expect, it } from "vitest";

import { actionFor } from "../../src/features/review/keymap";

type Press = { key: string; code: string; ctrlKey?: boolean; shiftKey?: boolean; metaKey?: boolean; altKey?: boolean; isComposing?: boolean };
const press = (p: Press) => actionFor({ ctrlKey: false, shiftKey: false, metaKey: false, altKey: false, isComposing: false, ...p });

describe("the review keys", () => {
  it.each([
    [{ key: "Enter", code: "Enter" }, { kind: "check" }],
    [{ key: "Enter", code: "Enter", shiftKey: true }, { kind: "previous" }],
    [{ key: "Tab", code: "Tab" }, { kind: "toggle" }],
    [{ key: "Tab", code: "Tab", shiftKey: true }, { kind: "replay" }],
    [{ key: ",", code: "Comma", ctrlKey: true }, { kind: "slower" }],
    [{ key: ".", code: "Period", ctrlKey: true }, { kind: "faster" }],
    [{ key: "1", code: "Digit1", ctrlKey: true }, { kind: "speaker", n: 1 }],
    [{ key: "9", code: "Digit9", ctrlKey: true }, { kind: "speaker", n: 9 }],
    [{ key: "g", code: "KeyG", ctrlKey: true }, { kind: "second" }],
    [{ key: "u", code: "KeyU", ctrlKey: true }, { kind: "unclear" }],
    [{ key: "f", code: "KeyF", ctrlKey: true }, { kind: "flags" }],
    [{ key: "s", code: "KeyS", ctrlKey: true }, { kind: "split" }],
    [{ key: "m", code: "KeyM", ctrlKey: true }, { kind: "merge" }],
    [{ key: "j", code: "KeyJ", ctrlKey: true }, { kind: "nextLikely" }],
    [{ key: "J", code: "KeyJ", ctrlKey: true, shiftKey: true }, { kind: "previousLikely" }],
    [{ key: "/", code: "Slash", ctrlKey: true }, { kind: "keys" }],
    [{ key: "Escape", code: "Escape" }, { kind: "leave" }],
  ] as [Press, object][])("%o is %o", (p, action) => {
    expect(press(p)).toEqual(action);
  });

  it("works by the key's place, so the Urdu input source reaches every action", () => {
    // With the Urdu input source the G key types گ and the digit row types Urdu digits.
    expect(press({ key: "گ", code: "KeyG", ctrlKey: true })).toEqual({ kind: "second" });
    expect(press({ key: "۲", code: "Digit2", ctrlKey: true })).toEqual({ kind: "speaker", n: 2 });
  });

  it("leaves the browser's Cmd keys, Ctrl+0, Ctrl+Space, plain typing and an open composition alone", () => {
    expect(press({ key: "s", code: "KeyS", metaKey: true })).toBeNull();
    expect(press({ key: "0", code: "Digit0", ctrlKey: true })).toBeNull();
    expect(press({ key: " ", code: "Space", ctrlKey: true })).toBeNull();
    expect(press({ key: "a", code: "KeyA" })).toBeNull();
    expect(press({ key: "a", code: "KeyA", ctrlKey: true })).toBeNull();
    expect(press({ key: "Enter", code: "Enter", isComposing: true })).toBeNull();
  });
});
```

Append to `ui/tests/unit/route.test.ts` (and add `reviewHref` to its import):

```ts
describe("the review route", () => {
  it("is a transcript's address with review=1, and round-trips", () => {
    expect(reviewHref(2, 7)).toBe("/?recording=2&transcript=7&review=1");
    expect(readRoute("?recording=2&transcript=7&review=1")).toEqual({ page: "review", recording: 2, transcript: 7 });
    expect(readRoute("?recording=2&transcript=7&review=0")).toEqual({ page: "transcript", recording: 2, transcript: 7 });
  });
});
```

Run: `cd ui && npx vitest run tests/unit/keymap.test.ts tests/unit/route.test.ts`
Expected: FAIL (`keymap` not found; `reviewHref` not exported).

- [ ] **Step 3: Write `ui/src/features/review/keymap.ts`**

```ts
// Review's keys, exactly the spec's table (Hashiya spec, Review mode). They
// keep clear of the Mac's text-field keys (Ctrl+A, E, K, B: emacs moves inside
// a text box), the browser's Cmd keys, and Ctrl+Space, which switches input
// sources and which an Urdu typist uses. Ctrl+F is the one text-field key
// taken: the flag menu matters more than a one-character move inside a short
// sentence, and the key sheet says so (keys.ts, REVIEW_SHEET).
//
// Ctrl keys go by `event.code`, the key's place on the keyboard, not by
// `event.key`, the letter it types: with the Urdu input source the G key types
// گ and the digit row Urdu digits, and every action must still be in reach.
// A key pressed while an input method is composing is the input method's.

import type { Flag } from "./model";

export type Action =
  | { kind: "check" }
  | { kind: "previous" }
  | { kind: "toggle" }
  | { kind: "replay" }
  | { kind: "slower" }
  | { kind: "faster" }
  | { kind: "speaker"; n: number }
  | { kind: "second" }
  | { kind: "unclear" }
  | { kind: "flags" }
  | { kind: "flag"; flag: Flag }
  | { kind: "split" }
  | { kind: "merge" }
  | { kind: "nextLikely" }
  | { kind: "previousLikely" }
  | { kind: "keys" }
  | { kind: "leave" };

type Press = Pick<KeyboardEvent, "key" | "code" | "ctrlKey" | "shiftKey" | "metaKey" | "altKey" | "isComposing">;

export function actionFor(event: Press): Action | null {
  if (event.isComposing || event.metaKey || event.altKey) return null;
  if (!event.ctrlKey) {
    if (event.key === "Enter") return { kind: event.shiftKey ? "previous" : "check" };
    if (event.key === "Tab") return { kind: event.shiftKey ? "replay" : "toggle" };
    if (event.key === "Escape") return { kind: "leave" };
    return null;
  }
  const digit = /^Digit([1-9])$/.exec(event.code);
  if (digit !== null) return { kind: "speaker", n: Number(digit[1]) };
  switch (event.code) {
    case "Comma":
      return { kind: "slower" };
    case "Period":
      return { kind: "faster" };
    case "KeyG":
      return { kind: "second" };
    case "KeyU":
      return { kind: "unclear" };
    case "KeyF":
      return { kind: "flags" };
    case "KeyS":
      return { kind: "split" };
    case "KeyM":
      return { kind: "merge" };
    case "KeyJ":
      return { kind: event.shiftKey ? "previousLikely" : "nextLikely" };
    case "Slash":
      return { kind: "keys" };
    default:
      return null;
  }
}
```

- [ ] **Step 4: Add the review route to `ui/src/lib/route.ts`**

```ts
export type Route =
  | { page: "library" }
  | { page: "transcript"; recording: number; transcript: number }
  | { page: "review"; recording: number; transcript: number };
```

`readRoute`'s last line becomes:

```ts
  // Review is the same transcript, checked sentence by sentence (Hashiya spec, Review mode).
  return params.get("review") === "1" ? { page: "review", recording, transcript } : { page: "transcript", recording, transcript };
```

and add:

```ts
/** The address of one transcript's review. */
export function reviewHref(recording: number, transcript: number): string {
  return `${transcriptHref(recording, transcript)}&review=1`;
}
```

Update the comment at the top of the file: three pages now, the third a transcript's review. Run: `cd ui && npx vitest run tests/unit/keymap.test.ts tests/unit/route.test.ts`
Expected: PASS.

- [ ] **Step 5: Add Review's keys to `ui/src/features/shell/keys.ts`**

Add `{ keys: ["R"], does: "Review this transcript, sentence by sentence" },` to `READER_SHEET.keys` after Space, and:

```ts
export const REVIEW_SHEET: Sheet = {
  title: "Keys in Review",
  keys: [
    { keys: ["Enter"], does: "Mark checked (with any edits), go to the next sentence, play it" },
    { keys: ["⇧", "Enter"], does: "Previous sentence" },
    { keys: ["Tab"], does: "Play or pause (playing again backs up 1.5 s)" },
    { keys: ["⇧", "Tab"], does: "Replay the sentence from its start" },
    { keys: ["Ctrl", ","], does: "Slower (0.75x, 1x, 1.25x, 1.5x)" },
    { keys: ["Ctrl", "."], does: "Faster" },
    { keys: ["Ctrl", "1 to 9"], does: "This sentence was said by speaker n" },
    { keys: ["Ctrl", "G"], does: "Take the second opinion's reading" },
    { keys: ["Ctrl", "U"], does: "Flag: can't make it out (adds [?] at the cursor when text is selected or empty)" },
    { keys: ["Ctrl", "F"], does: "Flag menu: not speech, overlapping talk, cut off" },
    { keys: ["Ctrl", "S"], does: "Split the sentence at the cursor" },
    { keys: ["Ctrl", "M"], does: "Merge with the previous sentence" },
    { keys: ["Ctrl", "J"], does: "Next likely error" },
    { keys: ["Ctrl", "⇧", "J"], does: "Previous likely error" },
    { keys: ["Ctrl", "/"], does: "This sheet" },
    { keys: ["Esc"], does: "Leave review (progress is saved)" },
  ],
  notes: [
    "Ctrl+F moves the cursor one character forward in a Mac text field. Here it opens the flag menu instead: flags matter more than a one-character move in a short sentence, and the arrow key still moves the cursor.",
    "Ctrl+1 to Ctrl+9 reach this page unless the Mac's \"Switch to Desktop n\" shortcuts are on (System Settings, Keyboard, Keyboard Shortcuts, Mission Control).",
    "Ctrl+Space is left alone: it switches input sources, which typing Urdu needs. The keys work by their place on the keyboard, so they work with the Urdu input source too.",
    "Every change is saved as you go; leaving and coming back resumes at the same sentence.",
  ],
};

/** The five keys the review footer always shows (spec: "a footer line always shows the five most used keys"). */
export const FOOTER_KEYS: readonly Key[] = [
  { keys: ["Enter"], does: "checked" },
  { keys: ["⇧", "Enter"], does: "back" },
  { keys: ["Tab"], does: "play" },
  { keys: ["Ctrl", "1 to 9"], does: "speaker" },
  { keys: ["Ctrl", "/"], does: "all keys" },
];
```

- [ ] **Step 6: Write `ui/src/features/review/reviewApi.ts`**

```ts
// Review mode's requests (#REVIEW): the review document, saved as it
// changes, and the answer key.

import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/api/client";
import type { components } from "@/api/schema";
import type { SaveState } from "@/features/edit/editing";
import { ApiError, fromBody, fromThrown, showError } from "@/features/errors/appError";
import type { ReviewDocument } from "./model";

export type ReferenceWritten = components["schemas"]["ReferenceWritten"];

// A short wait before saving, so a run of Enter presses is one request, not one each.
const SAVE_AFTER_MS = 400;

export async function loadReview(transcriptId: number): Promise<{ document: ReviewDocument | null; sha: string }> {
  const route = `/api/transcripts/${transcriptId}/review`;
  const { data, error, response } = await api.GET("/api/transcripts/{transcript_id}/review", {
    params: { path: { transcript_id: String(transcriptId) } },
  });
  if (data === undefined) throw new ApiError(fromBody(error, response, route));
  return { document: data.document, sha: data.transcript_sha };
}

async function putReview(transcriptId: number, document: ReviewDocument): Promise<void> {
  const route = `/api/transcripts/${transcriptId}/review`;
  const { data, error, response } = await api.PUT("/api/transcripts/{transcript_id}/review", {
    params: { path: { transcript_id: String(transcriptId) } },
    body: document,
  });
  if (data === undefined) throw new ApiError(fromBody(error, response, route));
}

/** Write the answer key beside the transcript. Throws ApiError in the server's words (409 while unchecked). */
export async function saveAnswerKey(transcriptId: number, allowPartial: boolean): Promise<ReferenceWritten> {
  const route = `/api/transcripts/${transcriptId}/reference`;
  const { data, error, response } = await api.POST("/api/transcripts/{transcript_id}/reference", {
    params: { path: { transcript_id: String(transcriptId) } },
    body: { allow_partial: allowPartial },
  });
  if (data === undefined) throw new ApiError(fromBody(error, response, route));
  return data;
}

/**
 * Save the review after every change, as the edit list is saved (editing.ts
 * useSave): one request at a time, always the newest document. `flush` waits
 * until what is on screen is saved, for leaving. The document the review
 * opened with is not sent until something changes.
 */
export function useReviewSave(transcriptId: number, document: ReviewDocument): { state: SaveState; flush: () => Promise<void> } {
  const [state, setState] = useState<SaveState>("saved");
  const latest = useRef(document);
  latest.current = document;
  const sent = useRef(document);
  const flying = useRef<Promise<void> | null>(null);

  const send = useCallback((): Promise<void> => {
    if (flying.current !== null) return flying.current;
    const run = (async () => {
      while (latest.current !== sent.current) {
        const next = latest.current;
        setState("saving");
        try {
          await putReview(transcriptId, next);
          sent.current = next;
        } catch (thrown) {
          setState("failed");
          showError(fromThrown(thrown, `/api/transcripts/${transcriptId}/review`));
          return;
        }
      }
      setState("saved");
    })().finally(() => {
      flying.current = null;
    });
    flying.current = run;
    return run;
  }, [transcriptId]);

  useEffect(() => {
    if (document === sent.current) return;
    const timer = setTimeout(() => void send(), SAVE_AFTER_MS);
    return () => clearTimeout(timer);
  }, [document, send]);

  useEffect(() => {
    // Leaving with a change unsaved asks first, as the reader does.
    const leaving = (event: BeforeUnloadEvent) => {
      if (latest.current !== sent.current) event.preventDefault();
    };
    window.addEventListener("beforeunload", leaving);
    return () => window.removeEventListener("beforeunload", leaving);
  }, []);

  return { state, flush: send };
}
```

- [ ] **Step 7: Write `ui/src/features/review/useReviewSession.ts`**

```ts
// One review in progress (Hashiya spec, Review mode): the sentence in hand,
// what each key does to it, and the document saved as it changes. The laptop
// desk (ReviewDesk.tsx) and the phone card (ReviewCard.tsx) draw the same
// session.
//
// Where edits go (spec): a change of words is the reader's own CorrectOp over
// the sentence's entries, so it shows in the reader and keeps its link to the
// audio; a change of speaker is a SpeakerOp. Both go through the one Editor,
// so the reader's Cmd+Z takes them back. The review document holds spans,
// states, flags, the pass and the cursor, never words.

import { type RefObject, useMemo, useRef, useState } from "react";

import { correction } from "@/features/edit/correct";
import { type Editable, type SaveState, useContent, useLatest } from "@/features/edit/editing";
import { speakerLabels } from "@/features/edit/readContent";
import { newSpeakerLabel, speakerAt, speakerChange } from "@/features/edit/speaker";
import type { PlayerControls } from "@/features/player/Player";
import { speedLabel, stepSpeed } from "@/features/player/speed";
import { showKeys } from "@/features/shell/KeySheet";
import { REVIEW_SHEET } from "@/features/shell/keys";
import { cutoffFor } from "@/features/transcript/confidence";
import type { Reading, TranscriptDoc } from "@/features/transcript/document";
import { displayName, speakerColour } from "@/features/transcript/speakers";
import type { Action } from "./keymap";
import {
  AFTER_S,
  BEFORE_S,
  type Counts,
  counts,
  documentOf,
  entryRange,
  likelyErrors,
  mergeWithPrevious,
  passOrder,
  RESUME_BACK_S,
  resume,
  type ReviewCorrection,
  type ReviewDocument,
  type ReviewPass,
  type Segment,
  segmentText,
  splitAt,
  step,
  timeLeft,
  toggleFlag,
  wordIndex,
} from "./model";
import { useReviewSave } from "./reviewApi";
import { secondOpinion } from "./secondOpinion";

export type Caret = { start: number; end: number };

export type SentenceView = {
  index: number;
  segment: Segment;
  text: string;
  /** Who says it: the label, the name a person gave it, and its colour. */
  label: string | null;
  name: string | null;
  colour: string | undefined;
};

export type Session = {
  current: SentenceView | null;
  before: SentenceView[];
  after: SentenceView[];
  text: string;
  setText: (text: string) => void;
  /** Typing pauses playback (spec). */
  pause: () => void;
  second: { words: string[]; differs: boolean[] | null } | null;
  pass: ReviewPass;
  setPass: (pass: ReviewPass) => void;
  likelyCount: number;
  progress: Counts;
  timeLeft: string | null;
  notice: string | null;
  flagging: boolean;
  setFlagging: (open: boolean) => void;
  finished: boolean;
  saving: SaveState;
  speakers: { label: string; name: string; colour: string | undefined }[];
  act: (action: Action, caret?: Caret) => void;
};

type Args = {
  transcriptId: number;
  doc: TranscriptDoc;
  editable: Editable;
  /** The edit list's own save state (editing.ts useSave), so leaving waits for it. */
  editsSaving: SaveState;
  saved: ReviewDocument | null;
  sha: string;
  other: Reading | null;
  controls: RefObject<PlayerControls | null>;
  /** Where Esc goes, once everything is saved. */
  onLeave: () => void;
};

// Two sentences before and after the one in hand (spec).
const CONTEXT = 2;
// How long leaving waits for the edit list's last save, at most.
const LEAVE_WAIT_MS = 5000;

function lostNotice(lost: number): string {
  return `The transcript was made again since this review was saved. ${lost} checked ${
    lost === 1 ? "sentence no longer matches and is" : "sentences no longer match and are"
  } unchecked again.`;
}

export function useReviewSession({ transcriptId, doc, editable, editsSaving, saved, sha, other, controls, onLeave }: Args): Session {
  const { editor } = editable;
  const content = useContent(editor);
  const names = useLatest(editable.names);
  const words = useMemo(() => wordIndex(content), [content]);
  const [opening] = useState(() => resume(saved, editor.content, sha));
  const [segments, setSegments] = useState<Segment[]>(opening.segments);
  const [index, setIndex] = useState(opening.cursor);
  const [pass, setPass] = useState<ReviewPass>(saved?.review_pass ?? "every");
  const [fixes, setFixes] = useState<ReviewCorrection[]>(saved?.corrections ?? []);
  const [startedAt] = useState(() => saved?.started_at ?? new Date().toISOString());
  const [notice, setNotice] = useState<string | null>(opening.lost > 0 ? lostNotice(opening.lost) : null);
  const [flagging, setFlagging] = useState(false);
  const [finished, setFinished] = useState(false);
  const checkedAt = useRef<number[]>([]);
  const editsNow = useRef(editsSaving);
  editsNow.current = editsSaving;

  const labels = useMemo(() => speakerLabels(content, doc.speakers) ?? [], [content, doc.speakers]);
  const texts = useMemo(() => segments.map((s) => segmentText(content, words, s)), [segments, content, words]);
  const opinions = useMemo(() => secondOpinion(other, segments, texts), [other, segments, texts]);
  const likely = useMemo(
    () => likelyErrors(content, words, segments, cutoffFor(doc.model), opinions.disagree),
    [content, words, segments, doc.model, opinions.disagree],
  );
  const order = useMemo(() => passOrder(segments.length, pass, likely), [segments.length, pass, likely]);

  const segment = segments[index];
  const shown = texts[index] ?? "";
  // The box holds what is typed; a new sentence, or new words in this one,
  // start it again from what the list says.
  const [typed, setTyped] = useState({ shown, index, text: shown });
  const text = typed.shown === shown && typed.index === index ? typed.text : shown;
  const setText = (next: string) => setTyped({ shown, index, text: next });

  const document = useMemo(
    () => documentOf({ sha, pass, cursorS: segments[index]?.start ?? 0, startedAt, segments, corrections: fixes }),
    [sha, pass, segments, index, startedAt, fixes],
  );
  const { state: saving, flush } = useReviewSave(transcriptId, document);

  const view = (i: number): SentenceView | null => {
    const s = segments[i];
    if (s === undefined) return null;
    const range = entryRange(words, s);
    const label = range === null ? s.speaker : speakerAt(content, range.start);
    const at = label === null ? -1 : labels.indexOf(label);
    return {
      index: i,
      segment: s,
      text: texts[i] ?? "",
      label,
      name: at < 0 ? null : displayName(labels, names, at),
      colour: speakerColour(at < 0 ? null : at),
    };
  };

  const go = (to: number, list: readonly Segment[], play = true) => {
    setIndex(to);
    setFlagging(false);
    const s = list[to];
    if (play && s !== undefined) controls.current?.hear(Math.max(0, s.start - BEFORE_S), s.end + AFTER_S);
  };

  /** Put what the box says into the edit list, if it changed. True when it did. */
  const commit = (): boolean => {
    if (segment === undefined || text.trim() === shown.trim()) return false;
    const range = entryRange(wordIndex(editor.content), segment);
    if (range === null) {
      setNotice("This sentence has no words left to correct here. Undo in the reader brings them back.");
      return false;
    }
    editor.applyEdit(correction(editor.content, range.start, range.stop, text));
    // Every change of words, before and after: sub-project C's learning data (spec, "Seam for C").
    setFixes((list) => [...list, { at: new Date().toISOString(), start: segment.start, end: segment.end, before: shown, after: text.trim() }]);
    return true;
  };

  const leave = async () => {
    commit();
    await flush();
    const until = Date.now() + LEAVE_WAIT_MS;
    while (editsNow.current !== "saved" && Date.now() < until) await new Promise((resolve) => setTimeout(resolve, 50));
    onLeave();
  };

  const act = (action: Action, caret?: Caret) => {
    if (segment === undefined) return;
    switch (action.kind) {
      case "check": {
        const edited = commit();
        const next = segments.map((s, i) => (i === index ? { ...s, state: "checked" as const, edited: s.edited || edited } : s));
        setSegments(next);
        checkedAt.current.push(Date.now());
        const to = step(order, index, 1);
        if (to === null) {
          setFinished(true);
          controls.current?.pause();
        } else {
          go(to, next);
        }
        return;
      }
      case "previous": {
        commit();
        const to = step(order, index, -1);
        if (to === null) setNotice("This is the first sentence of the pass.");
        else go(to, segments);
        return;
      }
      case "toggle":
        controls.current?.toggle(RESUME_BACK_S);
        return;
      case "replay":
        controls.current?.hear(Math.max(0, segment.start - BEFORE_S), segment.end + AFTER_S);
        return;
      case "slower":
      case "faster": {
        const player = controls.current;
        if (player === null) return;
        const next = stepSpeed(player.speed(), action.kind === "faster" ? 1 : -1);
        player.setSpeed(next);
        setNotice(`Playing at ${speedLabel(next)}`);
        return;
      }
      case "speaker": {
        const label =
          action.n - 1 < labels.length ? labels[action.n - 1] : action.n - 1 === labels.length ? newSpeakerLabel(labels) : undefined;
        if (label === undefined) {
          setNotice(`There are ${labels.length} speakers. Ctrl+${labels.length + 1} adds a new one.`);
          return;
        }
        commit();
        const range = entryRange(wordIndex(editor.content), segment);
        if (range === null) return;
        const op = speakerChange(editor.content, range.start, range.stop, label);
        if (op !== null) editor.applyEdit(op);
        setSegments(segments.map((s, i) => (i === index ? { ...s, speaker: label } : s)));
        const all = labels.includes(label) ? labels : [...labels, label];
        setNotice(`Said by ${displayName(all, names, all.indexOf(label)) ?? label}`);
        return;
      }
      case "second": {
        const theirs = opinions.words[index] ?? [];
        if (theirs.length === 0) setNotice("There is no second opinion for this sentence.");
        else setText(theirs.join(" "));
        return;
      }
      case "unclear": {
        setSegments(segments.map((s, i) => (i === index && !s.flags.includes("unclear") ? { ...s, flags: [...s.flags, "unclear" as const] } : s)));
        if (caret !== undefined && caret.end > caret.start) setText(`${text.slice(0, caret.start)}[?]${text.slice(caret.end)}`);
        else if (text.trim() === "") setText("[?]");
        setNotice("Flagged: can't make it out");
        return;
      }
      case "flags":
        setFlagging(true);
        return;
      case "flag":
        setSegments(segments.map((s, i) => (i === index ? toggleFlag(s, action.flag) : s)));
        setFlagging(false);
        return;
      case "split": {
        // The caret counts from the box's start; the words' text has no space in front.
        const lead = text.length - text.trimStart().length;
        commit();
        const result = splitAt(editor.content, segments, index, Math.max(0, (caret?.start ?? 0) - lead));
        if ("refused" in result) {
          setNotice(result.refused);
          return;
        }
        setSegments(result.segments);
        setNotice("Split in two. Both halves are to be checked.");
        return;
      }
      case "merge": {
        if (index === 0) {
          setNotice("This is the first sentence; there is none before it to merge with.");
          return;
        }
        commit();
        const merged = mergeWithPrevious(segments, index);
        if (merged === null) return;
        setSegments(merged);
        go(index - 1, merged, false);
        setNotice("Merged with the sentence before.");
        return;
      }
      case "nextLikely":
      case "previousLikely": {
        const to = step(likely, index, action.kind === "nextLikely" ? 1 : -1);
        if (to === null) {
          setNotice(action.kind === "nextLikely" ? "No likely error after this one." : "No likely error before this one.");
          return;
        }
        commit();
        go(to, segments);
        return;
      }
      case "keys":
        showKeys(REVIEW_SHEET);
        return;
      case "leave":
        void leave();
        return;
    }
  };

  const remaining = order.filter((i) => segments[i]?.state !== "checked").length;
  const views = (from: number, to: number) =>
    Array.from({ length: Math.max(0, to - from) }, (_, k) => view(from + k)).filter((v): v is SentenceView => v !== null);
  return {
    current: view(index),
    before: views(Math.max(0, index - CONTEXT), index),
    after: views(index + 1, Math.min(segments.length, index + 1 + CONTEXT)),
    text,
    setText,
    pause: () => controls.current?.pause(),
    second: other === null ? null : { words: opinions.words[index] ?? [], differs: opinions.differs[index] ?? null },
    pass,
    setPass,
    likelyCount: likely.length,
    progress: counts(segments),
    timeLeft: timeLeft(checkedAt.current, remaining),
    notice,
    flagging,
    setFlagging,
    finished,
    saving,
    speakers: labels.map((label, i) => ({ label, name: displayName(labels, names, i) ?? label, colour: speakerColour(i) })),
    act,
  };
}
```

Switching the pass to "likely" with no likely errors leaves an empty order; the next `check` finds no next sentence and finishes the pass, which is right: that pass has nothing in it.

- [ ] **Step 8: Write the desk, its styles and the finish panel**

`ui/src/features/review/review.css`:

```css
/* Review's sentence in hand (Hashiya spec): the only thing at full contrast,
   large, already in an edit box. Urdu in Nastaliq at 1.3x, as in the reader. */
.review-box {
  width: 100%;
  min-height: 4.75rem;
  field-sizing: content;
  resize: none;
  padding: 0.75rem 1rem;
  border: 2px solid var(--gold-ink);
  border-radius: 0.75rem;
  background: var(--card);
  color: var(--foreground);
  font: 400 1.5rem/1.6 var(--font-reading);
  unicode-bidi: plaintext;
}

.review-box:lang(ur) {
  font-family: var(--font-urdu);
  font-size: 1.95rem;
  line-height: 2.1;
}

/* The sentences around it, and the second opinion: readable (4.5:1, palette.test.ts), plainly not the one in hand. */
.review-context {
  color: var(--dim);
  font: 400 1.0625rem/1.65 var(--font-reading);
  unicode-bidi: plaintext;
}

.review-context:lang(ur) {
  font-family: var(--font-urdu);
  font-size: 1.38rem;
  line-height: 2.1;
}

.review-tick {
  display: block;
  height: 3px;
  border-radius: 2px;
  inline-size: max(3px, var(--tick, 0%));
  background: var(--speaker, var(--muted-foreground));
}
```

`ui/src/features/review/FinishPanel.tsx`:

```tsx
import { useState } from "react";

import { Button, buttonVariants } from "@/components/ui/button";
import { fromThrown, showError } from "@/features/errors/appError";
import { cn } from "@/lib/utils";
import type { Counts } from "./model";
import { type ReferenceWritten, saveAnswerKey } from "./reviewApi";

/**
 * The end of a pass (Hashiya spec, "Finishing"): what it did, and two ways
 * on. "Save as answer key" writes `<name>.reference.json` and `.txt` beside
 * the transcript; with sentences still unchecked it asks first, and the key
 * says it is partial.
 */
export function FinishPanel({ transcriptId, progress, back }: { transcriptId: number; progress: Counts; back: string }) {
  const [written, setWritten] = useState<ReferenceWritten | null>(null);
  const [asking, setAsking] = useState(false);
  const unchecked = progress.total - progress.checked;
  const save = (partial: boolean) => {
    setAsking(false);
    saveAnswerKey(transcriptId, partial).then(setWritten, (thrown: unknown) =>
      showError(fromThrown(thrown, `/api/transcripts/${transcriptId}/reference`)),
    );
  };
  const rows: [string, string][] = [
    ["Checked", `${progress.checked.toLocaleString("en")} of ${progress.total.toLocaleString("en")}`],
    ["Words changed", progress.edited.toLocaleString("en")],
    ["Flagged", progress.flagged.toLocaleString("en")],
    ["Speaker changed", progress.reassigned.toLocaleString("en")],
  ];
  return (
    <main className="mx-auto flex w-full max-w-xl flex-1 flex-col gap-6 px-3 py-12 sm:px-6">
      <h2 className="font-reading text-3xl font-semibold">This pass is done</h2>
      <dl className="grid grid-cols-[auto_1fr] gap-x-8 gap-y-2 text-lg tabular-nums">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-muted-foreground">{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      {written !== null && (
        <p role="status" className="text-checked">
          Saved {written.files.join(" and ")} beside the transcript
          {written.unchecked > 0 ? `, with ${written.unchecked.toLocaleString("en")} sentences marked not checked` : ""}.
        </p>
      )}
      {asking && (
        <div role="group" aria-label="Partial answer key" className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4">
          <p>
            {unchecked.toLocaleString("en")} {unchecked === 1 ? "sentence is" : "sentences are"} not checked yet. Save a partial
            answer key? It says it is partial.
          </p>
          <div className="flex gap-3">
            <Button className="h-11" onClick={() => save(true)}>
              Save partial
            </Button>
            <Button variant="outline" className="h-11" onClick={() => setAsking(false)}>
              Not now
            </Button>
          </div>
        </div>
      )}
      <div className="flex flex-wrap gap-3">
        <a href={back} className={cn(buttonVariants({ variant: "outline" }), "h-11 px-4")}>
          Back to the transcript
        </a>
        <Button
          className="h-11 bg-gold px-4 font-semibold text-primary-foreground hover:bg-gold/90"
          onClick={() => (unchecked > 0 ? setAsking(true) : save(false))}
        >
          Save as answer key
        </Button>
      </div>
    </main>
  );
}
```

`ui/src/features/review/ReviewDesk.tsx`:

```tsx
import { type CSSProperties, useEffect, useRef } from "react";

import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Kbd } from "@/components/ui/kbd";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { atLabel } from "@/features/bleep/matches";
import type { SaveState } from "@/features/edit/editing";
import { AppBar } from "@/features/shell/AppBar";
import { KeysItem } from "@/features/shell/KeySheet";
import { FOOTER_KEYS, REVIEW_SHEET } from "@/features/shell/keys";
import { langOf } from "@/lib/script";
import { FinishPanel } from "./FinishPanel";
import { actionFor } from "./keymap";
import type { Flag, ReviewPass } from "./model";
import type { SentenceView, Session } from "./useReviewSession";
import "./review.css";

const SAVE_TEXT: Record<SaveState, string> = { saved: "Saved", saving: "Saving…", failed: "Not saved" };

export const FLAGS: [Flag, string][] = [
  ["unclear", "Can't make it out"],
  ["not_speech", "Not speech"],
  ["overlap", "Overlapping talk"],
  ["cut_off", "Cut off"],
];

// A sentence of 15 s fills the margin's tick.
const TICK_FULL_S = 15;

function style(view: SentenceView): CSSProperties {
  const seconds = view.segment.end - view.segment.start;
  return { "--speaker": view.colour, "--tick": `${Math.min(100, (seconds / TICK_FULL_S) * 100)}%` } as CSSProperties;
}

function Context({ view }: { view: SentenceView }) {
  return (
    <div data-review-sentence className="grid grid-cols-[9.5rem_minmax(0,1fr)] gap-x-7" style={style(view)}>
      <div className="flex flex-col gap-0.5 pt-1 text-xs text-dim tabular-nums">
        {view.name !== null && <span>{view.name}</span>}
        <span>{atLabel(view.segment.start)}</span>
      </div>
      <p className="review-context" dir="auto" lang={langOf(view.text)}>
        {view.text}
      </p>
    </div>
  );
}

/** The second opinion: the other transcript's words for this span, the differing ones underlined. */
export function SecondOpinion({ second }: { second: NonNullable<Session["second"]> }) {
  if (second.words.length === 0) return <p className="text-sm text-dim">The other transcript has nothing here.</p>;
  return (
    <p className="review-context" dir="auto" lang={langOf(second.words.join(" "))}>
      <span className="sr-only">Second opinion: </span>
      {second.words.map((word, k) => (
        <span key={k}>
          {k > 0 && " "}
          {second.differs?.[k] ? <span className="underline decoration-dotted decoration-2 underline-offset-4">{word}</span> : word}
        </span>
      ))}
    </p>
  );
}

/**
 * Review mode on a Mac (Hashiya spec, "Laptop, keyboard-first"): the
 * sentence in hand in the middle, large, in an edit box that keeps the focus
 * the whole time; two sentences either side, dimmed; the margin beside it;
 * the second opinion beneath; progress, the pass and time left in the bar;
 * the five most used keys in the footer.
 */
export function ReviewDesk({ session, title, back, transcriptId }: { session: Session; title: string; back: string; transcriptId: number }) {
  const box = useRef<HTMLTextAreaElement>(null);
  const current = session.current;
  useEffect(() => {
    box.current?.focus();
  }, [current?.index, session.flagging]);

  const bar = (
    <AppBar back settings={<KeysItem sheet={REVIEW_SHEET} />}>
      <h1 className="min-w-0 flex-1 truncate font-reading text-lg font-semibold">Review · {title}</h1>
      <span role="status" aria-live="polite" className="text-sm text-field-foreground tabular-nums">
        {session.progress.checked.toLocaleString("en")} of {session.progress.total.toLocaleString("en")} checked
      </span>
      {session.timeLeft !== null && <span className="text-sm text-field-muted">{session.timeLeft}</span>}
      <ToggleGroup
        aria-label="Pass"
        variant="outline"
        size="sm"
        spacing={0}
        value={[session.pass]}
        onValueChange={(picked: string[]) => {
          if (picked[0] === "every" || picked[0] === "likely") session.setPass(picked[0] as ReviewPass);
        }}
        className="text-field-foreground"
      >
        <ToggleGroupItem value="every" className="h-9">
          Every sentence
        </ToggleGroupItem>
        <ToggleGroupItem value="likely" className="h-9">
          Likely errors ({session.likelyCount.toLocaleString("en")})
        </ToggleGroupItem>
      </ToggleGroup>
      <span className="min-w-16 text-sm text-field-muted">{SAVE_TEXT[session.saving]}</span>
    </AppBar>
  );

  if (session.finished) {
    return (
      <>
        {bar}
        <FinishPanel transcriptId={transcriptId} progress={session.progress} back={back} />
      </>
    );
  }
  return (
    <>
      {bar}
      <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col justify-center gap-5 px-3 py-8 sm:px-6">
        {session.before.map((view) => (
          <Context key={view.index} view={view} />
        ))}
        {current !== null && (
          <section data-review-sentence aria-label="Sentence being checked" className="grid grid-cols-[9.5rem_minmax(0,1fr)] gap-x-7" style={style(current)}>
            <div className="flex flex-col items-start gap-1.5 pt-2 text-sm tabular-nums">
              {current.name !== null && (
                <span className="font-semibold" style={{ color: current.colour }}>
                  {current.name}
                </span>
              )}
              <span className="text-muted-foreground">
                {atLabel(current.segment.start)} · {(current.segment.end - current.segment.start).toFixed(1)} s
              </span>
              <span className="review-tick" aria-hidden />
              <span className={current.segment.state === "checked" ? "text-checked" : "text-muted-foreground"}>
                {current.segment.state === "checked" ? "Checked" : "Not checked yet"}
              </span>
              {current.segment.flags.map((flag) => (
                <span key={flag} className="rounded-full border border-border px-2 text-xs">
                  {FLAGS.find(([f]) => f === flag)?.[1]}
                </span>
              ))}
              <DropdownMenu open={session.flagging} onOpenChange={session.setFlagging}>
                <DropdownMenuTrigger render={<Button variant="ghost" size="sm" className="-ml-2 h-8 text-muted-foreground" />}>
                  Flag
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start">
                  {FLAGS.map(([flag, label]) => (
                    <DropdownMenuItem key={flag} onClick={() => session.act({ kind: "flag", flag })}>
                      {label}
                      {current.segment.flags.includes(flag) && <span className="ml-auto text-xs text-muted-foreground">on</span>}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
            <div className="flex min-w-0 flex-col gap-3">
              <textarea
                ref={box}
                aria-label="What was said"
                className="review-box"
                dir="auto"
                lang={langOf(session.text)}
                spellCheck={false}
                value={session.text}
                onChange={(event) => session.setText(event.target.value)}
                onInput={() => session.pause()}
                onKeyDown={(event) => {
                  const action = actionFor(event.nativeEvent);
                  if (action === null) return;
                  event.preventDefault();
                  session.act(action, { start: event.currentTarget.selectionStart, end: event.currentTarget.selectionEnd });
                }}
              />
              {session.second !== null && <SecondOpinion second={session.second} />}
            </div>
          </section>
        )}
        {session.after.map((view) => (
          <Context key={view.index} view={view} />
        ))}
        <p role="status" aria-live="polite" className="min-h-6 text-sm text-muted-foreground">
          {session.notice}
        </p>
      </main>
      <footer className="mx-auto flex w-full max-w-4xl flex-wrap gap-x-5 gap-y-1 px-3 pb-3 text-xs text-muted-foreground sm:px-6">
        {FOOTER_KEYS.map((key) => (
          <span key={key.does} className="flex items-center gap-1">
            {key.keys.map((k) => (
              <Kbd key={k}>{k}</Kbd>
            ))}
            {key.does}
          </span>
        ))}
      </footer>
    </>
  );
}
```

- [ ] **Step 9: Write `ui/src/features/review/ReviewPage.tsx`**

```tsx
import { useEffect, useMemo, useRef, useState } from "react";

import { type Editable, useSave } from "@/features/edit/editing";
import { fromThrown, showError } from "@/features/errors/appError";
import { displayTitle } from "@/features/library/title";
import { Player, type PlayerControls } from "@/features/player/Player";
import { AppBar } from "@/features/shell/AppBar";
import { read, type Reading } from "@/features/transcript/document";
import { type Opened, openTranscript } from "@/features/transcript/TranscriptPage";
import { transcriptHref } from "@/lib/route";
import type { ReviewDocument } from "./model";
import { ReviewDesk } from "./ReviewDesk";
import { loadReview } from "./reviewApi";
import { loadReading, otherTranscript } from "./secondOpinion";
import { useReviewSession } from "./useReviewSession";

type Loaded =
  | { state: "loading" }
  | { state: "failed" }
  | { state: "ready"; opened: Opened; review: { document: ReviewDocument | null; sha: string } };

type Props = {
  recording: number;
  transcript: number;
  /** Where leaving goes; the tests pass their own. */
  navigate?: (href: string) => void;
};

/** Review mode (Hashiya spec): one transcript, checked sentence by sentence against its audio. */
export function ReviewPage({ recording, transcript, navigate = (href) => window.location.assign(href) }: Props) {
  const [loaded, setLoaded] = useState<Loaded>({ state: "loading" });
  const [other, setOther] = useState<Reading | null>(null);
  useEffect(() => {
    let live = true;
    Promise.all([openTranscript(recording, transcript), loadReview(transcript)]).then(
      ([opened, review]) => {
        if (!live) return;
        setLoaded({ state: "ready", opened, review });
        const another = otherTranscript(opened.recording, transcript);
        // A second opinion that cannot be read is said once and left out; the review goes on without it.
        if (another !== null) {
          loadReading(another.id).then(
            (reading) => {
              if (live) setOther(reading);
            },
            (thrown: unknown) => {
              if (live) showError(fromThrown(thrown, `/api/transcripts/${another.id}`));
            },
          );
        }
      },
      (thrown: unknown) => {
        if (!live) return;
        setLoaded({ state: "failed" });
        showError(fromThrown(thrown, `/api/transcripts/${transcript}/review`));
      },
    );
    return () => {
      live = false;
    };
  }, [recording, transcript]);

  const back = transcriptHref(recording, transcript);
  if (loaded.state !== "ready") {
    return (
      <>
        <AppBar back>
          <h1 className="min-w-0 flex-1 truncate font-reading text-lg font-semibold">Review</h1>
        </AppBar>
        {loaded.state === "failed" && (
          <main className="mx-auto w-full max-w-3xl px-3 py-6 sm:px-6">
            <p className="text-muted-foreground">This review could not be opened.</p>
          </main>
        )}
      </>
    );
  }
  const { opened } = loaded;
  if (!("editor" in opened.editable)) {
    return (
      <>
        <AppBar back>
          <h1 className="min-w-0 flex-1 truncate font-reading text-lg font-semibold">Review · {displayTitle(opened.recording)}</h1>
        </AppBar>
        <main className="mx-auto flex w-full max-w-3xl flex-col gap-3 px-3 py-6 sm:px-6">
          <p>This transcript cannot be reviewed: {opened.editable.reason}</p>
          <a href={back} className="underline underline-offset-4">
            Back to the transcript
          </a>
        </main>
      </>
    );
  }
  return (
    <InSession opened={opened} editable={opened.editable} transcriptId={transcript} review={loaded.review} other={other} back={back} navigate={navigate} />
  );
}

type InSessionProps = {
  opened: Opened;
  editable: Editable;
  transcriptId: number;
  review: { document: ReviewDocument | null; sha: string };
  other: Reading | null;
  back: string;
  navigate: (href: string) => void;
};

function InSession({ opened, editable, transcriptId, review, other, back, navigate }: InSessionProps) {
  const controls = useRef<PlayerControls | null>(null);
  // Review's corrections and speaker changes are edits, saved as the reader saves them.
  const editsSaving = useSave(transcriptId, editable);
  const session = useReviewSession({
    transcriptId,
    doc: opened.doc,
    editable,
    editsSaving,
    saved: review.document,
    sha: review.sha,
    other,
    controls,
    onLeave: () => navigate(back),
  });
  const reading = useMemo(() => read(opened.doc), [opened.doc]);
  const title = displayTitle(opened.recording);
  return (
    <>
      <ReviewDesk session={session} title={title} back={back} transcriptId={transcriptId} />
      {opened.recording.missing ? (
        <p className="sticky bottom-0 bg-field px-4 py-3 text-sm text-field-foreground">
          The recording is not where it was last seen, so this review cannot play it. Last seen at{" "}
          <span className="font-mono break-all">{opened.recording.path}</span>
        </p>
      ) : (
        <Player recording={opened.recording} reading={reading} controls={controls} />
      )}
    </>
  );
}
```

In `ui/src/App.tsx`, render `<ReviewPage recording={route.recording} transcript={route.transcript} />` for `route.page === "review"` (import it from `@/features/review/ReviewPage`).

- [ ] **Step 10: Enter Review from the reader**

1. `ui/src/features/edit/editing.ts`: `Editable` gains `/** Why a saved list was put aside (#STALE), or null. */ replaced: string | null;`, and `loadEditable` sets `replaced: data.replaced`.
2. `ui/src/features/transcript/readerKeys.ts`: the signature becomes `useReaderKeys(controls, sheet, review?: string)`; inside `key`, add `else if (event.code === "KeyR" && review !== undefined) { event.preventDefault(); window.location.assign(review); }`; add `review` to the effect's dependencies.
3. `ui/src/features/transcript/TranscriptPage.tsx`, in `EditablePage`: `const review = reviewHref(opened.recording.id, transcriptId);` (import `reviewHref` from `@/lib/route`); `useReaderKeys(controls, READER_SHEET, review);`; the `tools` fragment gains, between `EditBar` and `MoreMenu`:

```tsx
          <a href={review} className={cn(buttonVariants(), "h-11 bg-gold px-4 font-semibold text-primary-foreground hover:bg-gold/90")}>
            Review
          </a>
```

   (imports: `buttonVariants` from `@/components/ui/button`, `cn` from `@/lib/utils`); and as the first child of `Page`:

```tsx
      {editable.replaced !== null && (
        <p role="note" className="mb-6 rounded-lg border border-border bg-card px-4 py-3 text-sm">
          {editable.replaced}
        </p>
      )}
```

Every unit-test mock of `GET /edits` answers `replaced: null` (Task 10, Step 7).

- [ ] **Step 11: Write the failing review test**

Create `ui/tests/unit/review.test.tsx`:

```tsx
// Review mode by keyboard, in jsdom against a mocked server (Hashiya spec, Review mode).
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fetchMock = vi.hoisted(() => {
  const mock = vi.fn<(request: Request) => Promise<Response>>();
  globalThis.fetch = mock as unknown as typeof fetch;
  return mock;
});

import { dismissError } from "../../src/features/errors/appError";
import { ReviewPage } from "../../src/features/review/ReviewPage";
import { takeToken } from "../../src/features/session/session";
import type { Content, Entry, Item } from "../../src/lib/editOps";
import { installHighlights } from "./highlights";
import { stubMatchMedia } from "./media";

function item(sourceStart: number, length: number, text: string, confidence: number | null = 0.95): Item {
  return { kind: "item", source: "0", sourceStart, length, text, muted: false, confidence };
}
const para = (speaker: string): Entry => ({ kind: "paragraph", speaker, language: null });

const CONTENT: Content = [
  para("SPEAKER_00"),
  item(0.2, 0.3, " alpha"),
  item(0.6, 0.3, " bravo"),
  item(1.0, 0.3, " charlie"),
  para("SPEAKER_01"),
  item(2.0, 0.4, " delta"),
  item(2.5, 0.4, " echo"),
  para("SPEAKER_00"),
  item(3.5, 0.4, " foxtrot"),
];
const DOC = {
  audio: "/rec/a.wav",
  model: "mlx-community/parakeet-tdt-0.6b-v3",
  speakers: ["SPEAKER_00", "SPEAKER_01"],
  sentences: [
    { start: 0.2, end: 1.3, speaker: 0, text: " alpha bravo charlie", tokens: [{ t: 0.2, w: " alpha", e: 0.5 }, { t: 0.6, w: " bravo", e: 0.9 }, { t: 1.0, w: " charlie", e: 1.3 }] },
    { start: 2.0, end: 2.9, speaker: 1, text: " delta echo", tokens: [{ t: 2.0, w: " delta", e: 2.4 }, { t: 2.5, w: " echo", e: 2.9 }] },
    { start: 3.5, end: 3.9, speaker: 0, text: " foxtrot", tokens: [{ t: 3.5, w: " foxtrot", e: 3.9 }] },
  ],
};
const RECORDING = {
  id: 2, path: "/rec/a.wav", title: null, size_bytes: 1, duration_s: 5, content_id: "c", audio_codec: "pcm",
  video_codec: null, first_seen: "x", missing: false, unreadable: null,
  transcripts: [{ id: 7, finished_at: "x", engine: "parakeet", model: "parakeet", diarized: true, speaker_count: 2, mark_count: null, language: null, last_edited_at: null, language_tag: "english", review_checked: null, review_total: null }],
};

let edits: Content[] = [];
let reviews: { segments: { state: string }[] }[] = [];
let saved: unknown = null;

beforeEach(() => {
  installHighlights();
  stubMatchMedia();
  HTMLMediaElement.prototype.play = () => Promise.resolve();
  HTMLMediaElement.prototype.pause = () => undefined;
  window.history.replaceState(null, "", "/?recording=2&transcript=7&review=1#t=a-token");
  takeToken();
  edits = [];
  reviews = [];
  saved = null;
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (request: Request) => {
    const path = new URL(request.url).pathname;
    const body: unknown = request.method === "GET" ? null : await request.json();
    if (path === "/api/recordings") return Response.json([RECORDING]);
    if (path === "/api/transcripts/7") return Response.json(DOC);
    if (path === "/api/transcripts/7/edits") {
      const content = request.method === "PUT" ? (body as { content: Content }).content : CONTENT;
      if (request.method === "PUT") edits.push(content);
      return Response.json({ content, names: {}, replaced: null, pad_s: 0.1, edited_at: null, spans: [], unrenderable: null });
    }
    if (path === "/api/transcripts/7/review") {
      if (request.method === "PUT") {
        reviews.push(body as { segments: { state: string }[] });
        return Response.json(body);
      }
      return Response.json({ document: saved, transcript_sha: "s1" });
    }
    if (path === "/api/transcripts/7/reference") return Response.json({ files: ["a.reference.json", "a.reference.txt"], segments: 3, unchecked: 0 });
    if (path === "/api/recording/2/waveform") return new Response(new Int8Array([-3, 3]));
    return Response.json({ detail: "Not Found" }, { status: 404 });
  });
});

afterEach(() => {
  cleanup();
  act(() => dismissError());
});

const box = () => screen.findByRole("textbox", { name: "What was said" }) as Promise<HTMLTextAreaElement>;
const key = (target: HTMLElement, init: KeyboardEventInit) =>
  act(() => {
    fireEvent.keyDown(target, init);
  });

describe("Review mode on a Mac", () => {
  it("checks a sentence with Enter, goes on, and plays the next from 0.3 s before it", async () => {
    render(<ReviewPage recording={2} transcript={7} />);
    const field = await box();
    expect(field.value).toBe("alpha bravo charlie");
    key(field, { key: "Enter", code: "Enter" });
    expect((await box()).value).toBe("delta echo");
    expect(screen.getByText("1 of 3 checked")).toBeTruthy();
    expect((document.querySelector("audio") as HTMLAudioElement).currentTime).toBeCloseTo(1.7, 5);
    await vi.waitFor(() => expect(reviews.at(-1)?.segments[0]?.state).toBe("checked"), { timeout: 2000 });
  });

  it("puts a changed sentence into the edit list once, and Shift+Enter goes back to it", async () => {
    render(<ReviewPage recording={2} transcript={7} />);
    key(await box(), { key: "Enter", code: "Enter" });
    const field = await box();
    fireEvent.change(field, { target: { value: "delta echo golf" } });
    key(field, { key: "Enter", code: "Enter" });
    await vi.waitFor(() => expect(edits).toHaveLength(1));
    expect(edits[0]?.filter((e) => e.kind === "item").map((e) => (e as Item).text)).toContain(" golf");
    key(await box(), { key: "Enter", code: "Enter", shiftKey: true });
    expect((await box()).value).toBe("delta echo golf");
    // Checking it again changes nothing: the box already says what the list says (Review Focus 2).
    key(await box(), { key: "Enter", code: "Enter" });
    await new Promise((resolve) => setTimeout(resolve, 600));
    expect(edits).toHaveLength(1);
  });

  it("sets who said a sentence with Ctrl+2", async () => {
    render(<ReviewPage recording={2} transcript={7} />);
    key(await box(), { key: "2", code: "Digit2", ctrlKey: true });
    await vi.waitFor(() => expect(edits).toHaveLength(1));
    expect(edits[0]?.[0]).toEqual({ kind: "paragraph", speaker: "SPEAKER_01", language: null });
    expect(screen.getByText("Said by Speaker 2")).toBeTruthy();
  });

  it("splits at the cursor with Ctrl+S and merges back with Ctrl+M", async () => {
    render(<ReviewPage recording={2} transcript={7} />);
    const field = await box();
    field.setSelectionRange(6, 6);
    key(field, { key: "s", code: "KeyS", ctrlKey: true });
    expect((await box()).value).toBe("alpha");
    expect(screen.getByText("0 of 4 checked")).toBeTruthy();
    key(await box(), { key: "Enter", code: "Enter" });
    expect((await box()).value).toBe("bravo charlie");
    key(await box(), { key: "m", code: "KeyM", ctrlKey: true });
    expect((await box()).value).toBe("alpha bravo charlie");
    expect(screen.getByText("0 of 3 checked")).toBeTruthy();
  });

  it("puts [?] over selected words with Ctrl+U and flags the sentence", async () => {
    render(<ReviewPage recording={2} transcript={7} />);
    const field = await box();
    field.setSelectionRange(0, 5);
    key(field, { key: "u", code: "KeyU", ctrlKey: true });
    expect((await box()).value).toBe("[?] bravo charlie");
    expect(screen.getAllByText("Can't make it out").length).toBeGreaterThan(0);
  });

  it("resumes at the sentence it was left on", async () => {
    saved = {
      version: 1, transcript_sha: "s1", review_pass: "every", cursor_s: 2.0, started_at: "x", updated_at: "x",
      segments: [
        { start: 0.2, end: 1.3, state: "checked", flags: [], speaker: null, edited: false },
        { start: 2.0, end: 2.9, state: "unchecked", flags: [], speaker: null, edited: false },
        { start: 3.5, end: 3.9, state: "unchecked", flags: [], speaker: null, edited: false },
      ],
      corrections: [],
    };
    render(<ReviewPage recording={2} transcript={7} />);
    expect((await box()).value).toBe("delta echo");
    expect(screen.getByText("1 of 3 checked")).toBeTruthy();
  });

  it("finishes the pass and saves the answer key", async () => {
    render(<ReviewPage recording={2} transcript={7} />);
    for (let i = 0; i < 3; i += 1) key(await box(), { key: "Enter", code: "Enter" });
    expect(await screen.findByRole("heading", { name: "This pass is done" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Save as answer key" }));
    expect(await screen.findByText(/Saved a.reference.json and a.reference.txt beside the transcript/)).toBeTruthy();
  });

  it("leaves for the transcript with Esc once everything is saved", async () => {
    const went: string[] = [];
    render(<ReviewPage recording={2} transcript={7} navigate={(href) => went.push(href)} />);
    key(await box(), { key: "Escape", code: "Escape" });
    await vi.waitFor(() => expect(went).toEqual(["/?recording=2&transcript=7"]));
  });
});
```

Run: `cd ui && npx vitest run tests/unit/review.test.tsx tests/unit/keymap.test.ts`
Expected: PASS. If the first test reads `currentTime` 0, check that `controls.current` was set (the `Player`'s effect ran) before changing the session.

- [ ] **Step 12: Gate, build**

Run: `uv run just check` (paste the last line), `uv run just ui-build`.

- [ ] **Step 13: Look at it**

Run: `uv run python scratch/ui_shots.py --label t13 review reader`
Expected: 8 PNGs; the 390 px review shots show the desk until Task 14, so judge the 1440 ones. Check: the sentence in hand is large, in a gold-edged box, the only text at full contrast; two dim sentences above and below; the margin on its left with the speaker's name in colour, time, duration tick and state; progress and the pass switch in the bar; the footer's five keys; the reader's bar has one gold Review button and nothing else gold.

- [ ] **Step 14: Commit**

```bash
git add ui/src/lib/route.ts ui/src/App.tsx ui/src/features/review/keymap.ts ui/src/features/review/reviewApi.ts \
  ui/src/features/review/useReviewSession.ts ui/src/features/review/ReviewDesk.tsx \
  ui/src/features/review/FinishPanel.tsx ui/src/features/review/ReviewPage.tsx ui/src/features/review/review.css \
  ui/src/features/shell/keys.ts ui/src/features/transcript/readerKeys.ts \
  ui/src/features/transcript/TranscriptPage.tsx ui/src/features/edit/editing.ts \
  ui/tests/unit/keymap.test.ts ui/tests/unit/review.test.tsx ui/tests/unit/route.test.ts
git add -A -- dsj/ui/static/
git commit -m "feat(review): Review mode on the laptop, keyboard first"
```

---

### Task 14: Review mode on the phone

**Files:**
- Create: `ui/src/features/review/swipe.ts`, `ui/src/features/review/ReviewCard.tsx`
- Modify: `ui/src/features/review/ReviewPage.tsx` (pick the card on a touch screen or a narrow window)
- Test: `ui/tests/unit/swipe.test.ts` (new), `ui/tests/unit/review-phone.test.tsx` (new)

**Interfaces:**
- Consumes: Task 13's `Session` (with `pause`), `FinishPanel`, `FLAGS`, `SecondOpinion`; Task 2's `useMediaQuery`, `TOUCH`.
- Produces: `SWIPE_PX = 80`, `swipeOf(dx: number, dy: number): "left" | "right" | null`, `useSwipe(onSwipe: (way: "left" | "right") => void): { onPointerDown; onPointerUp; onPointerCancel }`; `ReviewCard({ session, title, back, transcriptId })`.

- [ ] **Step 1: Load impeccable: read /Users/moiz/.claude/skills/impeccable/reference/craft-floor.md before editing**

Read it in full; build to it without announcing its checklist.

- [ ] **Step 2: Write the failing tests**

Create `ui/tests/unit/swipe.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { SWIPE_PX, swipeOf } from "../../src/features/review/swipe";

describe("swipeOf", () => {
  it("is a mostly sideways drag of at least SWIPE_PX, named by its direction", () => {
    expect(swipeOf(-SWIPE_PX, 0)).toBe("left");
    expect(swipeOf(120, 30)).toBe("right");
  });

  it("is nothing for a short drag, a steep one, or a scroll", () => {
    expect(swipeOf(-40, 0)).toBeNull();
    expect(swipeOf(-120, 90)).toBeNull();
    expect(swipeOf(5, 300)).toBeNull();
  });
});
```

Create `ui/tests/unit/review-phone.test.tsx`: the same imports, fixtures (`item`, `para`, `CONTENT`, `DOC`, `RECORDING`), module variables, `beforeEach` and `afterEach` as `ui/tests/unit/review.test.tsx`, copied, except that `beforeEach` calls `stubMatchMedia((query) => query.includes("coarse"))`; then:

```tsx
describe("Review mode on a phone", () => {
  it("shows one sentence as a card with thumb-sized actions, and Checked, next goes on", async () => {
    render(<ReviewPage recording={2} transcript={7} />);
    await screen.findByRole("article", { name: "Sentence being checked" });
    expect((screen.getByRole("textbox", { name: "What was said" }) as HTMLTextAreaElement).value).toBe("alpha bravo charlie");
    expect(document.querySelectorAll("[data-review-sentence]")).toHaveLength(0);
    const next = screen.getByRole("button", { name: "Checked, next" });
    expect(next.className).toContain("h-12");
    fireEvent.click(next);
    expect(((await screen.findByRole("textbox", { name: "What was said" })) as HTMLTextAreaElement).value).toBe("delta echo");
    expect(screen.getByText("1 of 3 checked")).toBeTruthy();
  });

  it("reassigns a sentence with a speaker chip", async () => {
    render(<ReviewPage recording={2} transcript={7} />);
    fireEvent.click(await screen.findByRole("button", { name: "Speaker 2" }));
    await vi.waitFor(() => expect(edits).toHaveLength(1));
    expect(edits[0]?.[0]).toEqual({ kind: "paragraph", speaker: "SPEAKER_01", language: null });
  });

  it("goes back with Back", async () => {
    render(<ReviewPage recording={2} transcript={7} />);
    fireEvent.click(await screen.findByRole("button", { name: "Checked, next" }));
    fireEvent.click(await screen.findByRole("button", { name: "Back" }));
    expect(((await screen.findByRole("textbox", { name: "What was said" })) as HTMLTextAreaElement).value).toBe("alpha bravo charlie");
  });
});
```

Run: `cd ui && npx vitest run tests/unit/swipe.test.ts tests/unit/review-phone.test.tsx`
Expected: FAIL, `swipe` not found, and the desk is drawn instead of a card.

- [ ] **Step 3: Write `ui/src/features/review/swipe.ts`**

```ts
// Swipe left: checked and next; swipe right: back (Hashiya spec, "Phone and
// tablet, touch-first").
//
// A swipe is a mostly sideways drag of at least SWIPE_PX. 80 px is about a
// fifth of a 390 px phone's width: past any wobble of a tap, short of a
// thumb's full reach. A drag steeper than 0.6 (about 31 degrees) is a scroll.
// A drag that starts in the text box or on a button is theirs: selecting
// words, or pressing.

import { type PointerEvent, useRef } from "react";

export const SWIPE_PX = 80;
const STEEPEST = 0.6;

export function swipeOf(dx: number, dy: number): "left" | "right" | null {
  if (Math.abs(dx) < SWIPE_PX || Math.abs(dy) > Math.abs(dx) * STEEPEST) return null;
  return dx < 0 ? "left" : "right";
}

export function useSwipe(onSwipe: (way: "left" | "right") => void) {
  const from = useRef<{ x: number; y: number } | null>(null);
  return {
    onPointerDown: (event: PointerEvent<HTMLElement>) => {
      const target = event.target as Element;
      from.current = target.closest("textarea, button, a, [role=menu]") ? null : { x: event.clientX, y: event.clientY };
    },
    onPointerUp: (event: PointerEvent<HTMLElement>) => {
      const start = from.current;
      from.current = null;
      if (start === null) return;
      const way = swipeOf(event.clientX - start.x, event.clientY - start.y);
      if (way !== null) onSwipe(way);
    },
    onPointerCancel: () => {
      from.current = null;
    },
  };
}
```

- [ ] **Step 4: Write `ui/src/features/review/ReviewCard.tsx`**

```tsx
import { Flag as FlagIcon, Play, RotateCcw } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { atLabel } from "@/features/bleep/matches";
import { AppBar } from "@/features/shell/AppBar";
import { KeysItem } from "@/features/shell/KeySheet";
import { REVIEW_SHEET } from "@/features/shell/keys";
import { langOf } from "@/lib/script";
import { FinishPanel } from "./FinishPanel";
import type { ReviewPass } from "./model";
import { FLAGS, SecondOpinion } from "./ReviewDesk";
import { useSwipe } from "./swipe";
import type { Session } from "./useReviewSession";
import "./review.css";

/**
 * Review mode on a phone or tablet (Hashiya spec, "touch-first"): one
 * sentence a screen as a card, the margin as one line on top, the words below
 * (tap to edit; the keyboard opens), the second opinion beneath, a large
 * play and replay, a row of speaker chips, a flag button, progress at the
 * top. Swipe left for checked and next, right for back; the same two are
 * buttons in thumb reach above the player rail. Every target is 44 px or more.
 */
export function ReviewCard({ session, title, back, transcriptId }: { session: Session; title: string; back: string; transcriptId: number }) {
  const swipe = useSwipe((way) => session.act({ kind: way === "left" ? "check" : "previous" }));
  const [menu, setMenu] = useState(false);
  const current = session.current;
  const bar = (
    <AppBar back settings={<KeysItem sheet={REVIEW_SHEET} />}>
      <h1 className="sr-only">Review · {title}</h1>
      <span role="status" aria-live="polite" className="min-w-0 flex-1 truncate text-sm tabular-nums">
        {session.progress.checked.toLocaleString("en")} of {session.progress.total.toLocaleString("en")} checked
      </span>
      <ToggleGroup
        aria-label="Pass"
        variant="outline"
        spacing={0}
        value={[session.pass]}
        onValueChange={(picked: string[]) => {
          if (picked[0] === "every" || picked[0] === "likely") session.setPass(picked[0] as ReviewPass);
        }}
        className="text-field-foreground"
      >
        <ToggleGroupItem value="every" className="h-11 min-w-11">
          All
        </ToggleGroupItem>
        <ToggleGroupItem value="likely" className="h-11 min-w-11">
          Likely ({session.likelyCount.toLocaleString("en")})
        </ToggleGroupItem>
      </ToggleGroup>
    </AppBar>
  );
  if (session.finished) {
    return (
      <>
        {bar}
        <FinishPanel transcriptId={transcriptId} progress={session.progress} back={back} />
      </>
    );
  }
  return (
    <>
      {bar}
      <main className="flex w-full flex-1 flex-col gap-4 px-3 py-4">
        {current !== null && (
          <article
            {...swipe}
            aria-label="Sentence being checked"
            className="flex touch-pan-y flex-col gap-3 rounded-2xl border border-border bg-card p-4 shadow-sm shadow-black/5"
          >
            <p className="flex min-h-11 flex-wrap items-center gap-x-3 text-sm tabular-nums">
              {current.name !== null && (
                <span className="font-semibold" style={{ color: current.colour }}>
                  {current.name}
                </span>
              )}
              <span className="text-muted-foreground">{atLabel(current.segment.start)}</span>
              <span className={current.segment.state === "checked" ? "text-checked" : "text-muted-foreground"}>
                {current.segment.state === "checked" ? "Checked" : "Not checked yet"}
              </span>
            </p>
            <textarea
              aria-label="What was said"
              className="review-box"
              dir="auto"
              lang={langOf(session.text)}
              spellCheck={false}
              value={session.text}
              onChange={(event) => session.setText(event.target.value)}
              onInput={() => session.pause()}
            />
            {session.second !== null && <SecondOpinion second={session.second} />}
          </article>
        )}
        <div className="flex items-center justify-center gap-5">
          <Button variant="outline" aria-label="Replay" className="size-14 rounded-full" onClick={() => session.act({ kind: "replay" })}>
            <RotateCcw aria-hidden className="size-6" />
          </Button>
          <Button
            aria-label="Play or pause"
            className="size-16 rounded-full bg-gold text-primary-foreground hover:bg-gold/90"
            onClick={() => session.act({ kind: "toggle" })}
          >
            <Play aria-hidden className="size-7" />
          </Button>
          <DropdownMenu open={menu} onOpenChange={setMenu}>
            <DropdownMenuTrigger render={<Button variant="outline" aria-label="Flag" className="size-14 rounded-full" />}>
              <FlagIcon aria-hidden className="size-6" />
            </DropdownMenuTrigger>
            <DropdownMenuContent>
              {FLAGS.map(([flag, label]) => (
                <DropdownMenuItem key={flag} className="min-h-11" onClick={() => session.act({ kind: "flag", flag })}>
                  {label}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
        <div role="group" aria-label="Who said it" className="flex gap-2 overflow-x-auto pb-1">
          {session.speakers.map((speaker, i) => (
            <Button
              key={speaker.label}
              variant="outline"
              aria-pressed={current?.label === speaker.label}
              className="h-11 shrink-0 rounded-full border-2 px-4"
              style={{ borderColor: speaker.colour, color: speaker.colour }}
              onClick={() => session.act({ kind: "speaker", n: i + 1 })}
            >
              {speaker.name}
            </Button>
          ))}
          <Button variant="outline" className="h-11 shrink-0 rounded-full px-4" onClick={() => session.act({ kind: "speaker", n: session.speakers.length + 1 })}>
            New speaker
          </Button>
        </div>
        <p role="status" aria-live="polite" className="min-h-5 text-sm text-muted-foreground">
          {session.notice}
        </p>
      </main>
      <div className="sticky z-10 grid grid-cols-2 gap-2 bg-background/95 px-3 py-2 backdrop-blur" style={{ bottom: "var(--dsj-player-height, 0px)" }}>
        <Button variant="outline" className="h-12" onClick={() => session.act({ kind: "previous" })}>
          Back
        </Button>
        <Button className="h-12 bg-gold font-semibold text-primary-foreground hover:bg-gold/90" onClick={() => session.act({ kind: "check" })}>
          Checked, next
        </Button>
      </div>
    </>
  );
}
```

- [ ] **Step 5: Pick the layout in `ReviewPage.tsx`**

In `InSession`, add `const touch = useMediaQuery(TOUCH);` (import `TOUCH`, `useMediaQuery` from `@/lib/media`, and `ReviewCard` from `./ReviewCard`) and replace the `ReviewDesk` element with:

```tsx
      {touch ? (
        <ReviewCard session={session} title={title} back={back} transcriptId={transcriptId} />
      ) : (
        <ReviewDesk session={session} title={title} back={back} transcriptId={transcriptId} />
      )}
```

Run: `cd ui && npx vitest run tests/unit/swipe.test.ts tests/unit/review-phone.test.tsx tests/unit/review.test.tsx`
Expected: PASS.

- [ ] **Step 6: Gate, build**

Run: `uv run just check` (paste the last line), `uv run just ui-build`.

- [ ] **Step 7: Look at it**

Run: `uv run python scratch/ui_shots.py --label t14 review`
Expected: 4 PNGs. Check at 390x844: one card, its margin a line on top, the words large below, play and replay big and round, speaker chips in their colours, Back and Checked, next in thumb reach above the rail and nothing hidden behind it; at 1440 the desk as in Task 13.

- [ ] **Step 8: Commit**

```bash
git add ui/src/features/review/swipe.ts ui/src/features/review/ReviewCard.tsx ui/src/features/review/ReviewPage.tsx \
  ui/tests/unit/swipe.test.ts ui/tests/unit/review-phone.test.tsx
git add -A -- dsj/ui/static/
git commit -m "feat(review): Review mode on the phone, one card a sentence"
```

---

### Task 15: Browser journeys, and the 1,500-sentence fixture

**Files:**
- Modify: `ui/tests/perf/fixture.ts` (a shape parameter; `LONG_SHAPE`), `ui/tests/e2e/seed.ts` (`Seeded.transcriptPath`)
- Create: `ui/tests/perf/long.spec.ts`, `ui/tests/e2e/review.spec.ts`, `ui/tests/e2e/review-phone.spec.ts`
- Modify: `ui/tests/unit/perfFixture.test.ts`
- Maybe modify: `ui/src/features/transcript/transcript.css` (only if Step 7 measures p95 over 20 ms)

**Interfaces:**
- Consumes: everything above, through the real `dsj ui`.
- Produces: `type Shape = { sentences: number; tokens: number; turns: number; speakers: number }`, `syntheticTranscript(shape: Shape = SHAPE): Transcript`, `LONG_SHAPE: Shape = { sentences: 1500, tokens: 31500, turns: 344, speakers: 4 }`; `Seeded.transcriptPath: string`.

- [ ] **Step 1: Load impeccable: read /Users/moiz/.claude/skills/impeccable/reference/craft-floor.md before editing**

Read it in full; build to it without announcing its checklist.

- [ ] **Step 2: Give the fixture a shape**

In `ui/tests/perf/fixture.ts`:
1. After `SHAPE`, add:

```ts
export type Shape = { sentences: number; tokens: number; turns: number; speakers: number };

// A 2.5 h call (Hashiya spec, "Long recordings": about 1,500 sentences): the
// same mean of 21 tokens a sentence and the same share of turns (238 of 1,038)
// as SHAPE, with four speakers (PRODUCT.md: "two to four or more").
// 31,500 tokens at SECONDS_PER_TOKEN is 9,091 s, 2 h 31 min.
export const LONG_SHAPE: Shape = { sentences: 1500, tokens: 31500, turns: 344, speakers: 4 };
```

2. `sentenceLengths(rand)` becomes `sentenceLengths(rand: () => number, shape: Shape)`, using `shape.sentences` and `shape.tokens` where it used `SHAPE.sentences` and `SHAPE.tokens`; `turnStarts(rand)` becomes `turnStarts(rand: () => number, shape: Shape)`, using `shape.turns` and `shape.sentences`.
3. `syntheticTranscript()` becomes `syntheticTranscript(shape: Shape = SHAPE)`, passing `shape` to both, rotating `speaker = (speaker + 1) % shape.speakers`, and returning `speakers: Array.from({ length: shape.speakers }, (_, i) => \`SPEAKER_${String(i).padStart(2, "0")}\`)`. With `SHAPE` it is the very fixture it was, which `perfFixture.test.ts`'s existing cases hold.

Append to `ui/tests/unit/perfFixture.test.ts` (import `LONG_SHAPE`):

```ts
describe("the 2.5 h fixture", () => {
  const long = syntheticTranscript(LONG_SHAPE);
  it("has 1,500 sentences, 31,500 tokens, 344 turns and four speakers, and lasts about 2.5 h", () => {
    expect(long.sentences).toHaveLength(1500);
    expect(long.sentences.flatMap((s) => s.tokens)).toHaveLength(31500);
    const turns = long.sentences.filter((s, i) => i === 0 || s.speaker !== long.sentences[i - 1]?.speaker);
    expect(turns).toHaveLength(344);
    expect(long.speakers).toEqual(["SPEAKER_00", "SPEAKER_01", "SPEAKER_02", "SPEAKER_03"]);
    expect(long.sentences.at(-1)?.end ?? 0).toBeGreaterThan(9000);
  });
});
```

In `ui/tests/e2e/seed.ts`, `Seeded` becomes `{ recording: number; transcript: number; dir: string; transcriptPath: string }` and `put` returns `{ ...(JSON.parse(run.stdout) as { recording: number; transcript: number }), dir, transcriptPath: file }`.

Run: `cd ui && npx vitest run tests/unit/perfFixture.test.ts`
Expected: PASS, the old cases included.

- [ ] **Step 3: Write `ui/tests/e2e/review.spec.ts`**

```ts
// Review mode start to finish by keyboard (Hashiya spec, Testing), in real
// chromium and Playwright's webkit against the real `dsj ui`: R from the
// reader, Enter through every sentence with one corrected, one reassigned,
// one split and merged back and one flagged, then the answer key, whose files
// land beside the transcript. Over a tone; the words are made up.
import { existsSync, readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

import { editableTranscript } from "./editable.ts";
import { readerUrl, scratchDir, seed, tone } from "./seed.ts";

test("a transcript is reviewed by keyboard and saved as an answer key", async ({ page }, info) => {
  const dir = scratchDir();
  const name = `review-${info.project.name}.wav`;
  const seeded = seed(
    editableTranscript(tone(dir, 12 + info.project.name.length / 10, name), [
      ["alpha", "bravo", "charlie"],
      ["delta", "echo"],
      ["foxtrot", "golf", "hotel"],
    ]),
    dir,
  );
  await page.goto(readerUrl(seeded));
  await page.locator("article p").first().waitFor();
  await page.keyboard.press("r");
  await expect(page).toHaveURL(/review=1/);

  const box = page.getByRole("textbox", { name: "What was said" });
  await expect(box).toHaveValue("alpha bravo charlie");
  await expect(box).toBeFocused();

  // A correction: "charlie" was "Charles".
  await box.fill("alpha bravo Charles");
  await box.press("Enter");
  await expect(box).toHaveValue("delta echo");
  await expect(page.getByText("1 of 3 checked")).toBeVisible();

  // Said by the first speaker, not the second (editableTranscript alternates them).
  await box.press("Control+1");
  await expect(page.getByText("Said by Speaker 1")).toBeVisible();

  // Split after "delta", check the first half, and merge the second back into it.
  await box.evaluate((el: HTMLTextAreaElement) => el.setSelectionRange(5, 5));
  await box.press("Control+s");
  await expect(box).toHaveValue("delta");
  await box.press("Enter");
  await expect(box).toHaveValue("echo");
  await box.press("Control+m");
  await expect(box).toHaveValue("delta echo");
  await box.press("Enter");

  // Can't make it out.
  await expect(box).toHaveValue("foxtrot golf hotel");
  await box.press("Control+u");
  await box.press("Enter");

  await expect(page.getByRole("heading", { name: "This pass is done" })).toBeVisible();
  await page.getByRole("button", { name: "Save as answer key" }).click();
  await expect(page.getByRole("status").filter({ hasText: "beside the transcript" })).toBeVisible();
  const keyFile = seeded.transcriptPath.replace(/\.json$/, ".reference.json");
  expect(existsSync(keyFile)).toBe(true);
  const key = JSON.parse(readFileSync(keyFile, "utf8")) as {
    complete: boolean;
    segments: { text: string; speaker: string; flags: string[] }[];
  };
  expect(key.complete).toBe(true);
  expect(key.segments.map((s) => s.text)).toEqual(["alpha bravo Charles", "delta echo", "foxtrot golf hotel"]);
  expect(key.segments[1]?.speaker).toBe("Speaker 1");
  expect(key.segments[2]?.flags).toEqual(["unclear"]);

  // The correction shows in the reader, the sentence it replaced struck through in the margin
  // (Review corrects a whole sentence's words at once, so the whole sentence is the original).
  await page.getByRole("link", { name: "Back to the transcript" }).click();
  await expect(page.locator("article li [data-margin] del").first()).toHaveText("alpha bravo charlie");
});
```

- [ ] **Step 4: Write `ui/tests/e2e/review-phone.spec.ts`**

```ts
// Review mode in a phone-sized window, by touch (Hashiya spec, Testing: "the
// phone swipe path"): a swipe left checks and goes on, a swipe right goes
// back, a speaker chip reassigns, and every target is 44 px or more.
import { expect, test } from "@playwright/test";

import { editableTranscript } from "./editable.ts";
import { readerUrl, scratchDir, seed, tone } from "./seed.ts";

test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });

test("a sentence is checked by swiping, reassigned by a chip, and every target is thumb-sized", async ({ page }, info) => {
  const dir = scratchDir();
  const seeded = seed(
    editableTranscript(tone(dir, 10 + info.project.name.length / 10, `phone-${info.project.name}.wav`), [
      ["alpha", "bravo"],
      ["charlie", "delta"],
    ]),
    dir,
  );
  // The review's address is the reader's with review=1, before the token's #.
  await page.goto(readerUrl(seeded).replace("#", "&review=1#"));
  const card = page.getByRole("article", { name: "Sentence being checked" });
  const box = page.getByRole("textbox", { name: "What was said" });
  await expect(box).toHaveValue("alpha bravo");

  const swipe = async (dx: number) => {
    const b = await card.boundingBox();
    if (b === null) throw new Error("no card");
    // On the card's margin line, not in the text box, which keeps drags for selecting words.
    const y = b.y + 24;
    await page.mouse.move(b.x + b.width / 2, y);
    await page.mouse.down();
    await page.mouse.move(b.x + b.width / 2 + dx, y + 4, { steps: 8 });
    await page.mouse.up();
  };
  await swipe(-160);
  await expect(box).toHaveValue("charlie delta");
  await expect(page.getByText("1 of 2 checked")).toBeVisible();
  await swipe(160);
  await expect(box).toHaveValue("alpha bravo");

  await page.getByRole("button", { name: "Speaker 2" }).click();
  await expect(page.getByText("Said by Speaker 2")).toBeVisible();

  const small = await page.evaluate(() =>
    Array.from(document.querySelectorAll("main button, main a, [role=region][aria-label=Player] button, .sticky button"))
      .map((el) => el.getBoundingClientRect())
      .filter((r) => r.width > 0 && (r.width < 44 || r.height < 44)).length,
  );
  expect(small).toBe(0);
});
```

- [ ] **Step 5: Write `ui/tests/perf/long.spec.ts`**

```ts
// Review Focus 5 and the spec's "Long recordings": a 2.5 h call, 1,500
// sentences between four speakers, keeps the 20 ms p95 frame budget in the
// reader's scroll and in Review's step from sentence to sentence. Synthetic
// (fixture.ts), no audio: the frames are measured as text and layout alone.
import { expect, test } from "@playwright/test";

import { readerUrl, scratchDir, seed } from "../e2e/seed.ts";
import { LONG_SHAPE, syntheticTranscript } from "./fixture.ts";
import { FRAMES, P95_CEILING_MS, STEP_PX, scrollFrames, summarise } from "./sample.ts";

test("scrolling the reader over 1,500 sentences keeps p95 under 20 ms", async ({ page }) => {
  const dir = scratchDir();
  const seeded = seed({ ...syntheticTranscript(LONG_SHAPE), audio: `${dir}/none.wav` }, dir);
  await page.goto(readerUrl(seeded));
  await expect(page.locator("article p")).toHaveCount(LONG_SHAPE.turns);
  const dom = await page.evaluate(async () => {
    await document.fonts.ready;
    return { scrollHeight: document.documentElement.scrollHeight, viewport: window.innerHeight };
  });
  const frames = Math.min(FRAMES, Math.floor((dom.scrollHeight - dom.viewport) / STEP_PX));
  expect(frames).toBeGreaterThanOrEqual(150);
  const result = { ...dom, frames, ...summarise((await scrollFrames(page, frames)).slice(1)) };
  console.log(`long reader frame times: ${JSON.stringify(result)}`);
  expect(result.p95).toBeLessThanOrEqual(P95_CEILING_MS);
});

test("stepping through 300 of 1,500 sentences in Review keeps p95 under 20 ms, five sentences drawn", async ({ page }) => {
  const dir = scratchDir();
  const seeded = seed({ ...syntheticTranscript(LONG_SHAPE), audio: `${dir}/none.wav` }, dir);
  await page.goto(readerUrl(seeded).replace("#", "&review=1#"));
  const box = page.getByRole("textbox", { name: "What was said" });
  await expect(box).toBeFocused();
  expect(await page.locator("[data-review-sentence]").count()).toBeLessThanOrEqual(5);
  const times = await page.evaluate(
    () =>
      new Promise<number[]>((resolve) => {
        const field = document.querySelector("textarea") as HTMLTextAreaElement;
        const out: number[] = [];
        let last = performance.now();
        let n = 0;
        const frame = () => {
          const now = performance.now();
          out.push(now - last);
          last = now;
          field.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", code: "Enter", bubbles: true, cancelable: true }));
          if (++n < 300) requestAnimationFrame(frame);
          else resolve(out.slice(1));
        };
        requestAnimationFrame(frame);
      }),
  );
  const result = summarise(times);
  console.log(`review step frame times: ${JSON.stringify(result)}`);
  await expect(page.getByText(/^(299|300) of 1,500 checked$/)).toBeVisible();
  expect(result.p95).toBeLessThanOrEqual(P95_CEILING_MS);
});
```

- [ ] **Step 6: Run the browser journeys**

Run: `uv run just ui-build`, then `cd ui && npx playwright test tests/e2e/review.spec.ts tests/e2e/review-phone.spec.ts --project chromium` and `--project webkit`.
Expected: 2 passed in each. If the phone spec counts a small target, find which (run the same query in the page with `page.pause()`) and give it `h-11` or `size-11`; do not loosen the assertion.

- [ ] **Step 7: Run the long perf check**

Run: `cd ui && npx playwright test tests/perf/long.spec.ts --project perf`
Expected: 2 passed, frame times printed. If the reader's p95 is over 20 ms, add to `ui/src/features/transcript/transcript.css`:

```css
/* A 2.5 h call is 344 turns (ui/tests/perf/long.spec.ts): turns off screen
   skip layout and paint until they near the window. Cmd+F still finds text in
   them (content-visibility keeps it in the find index), and the playhead's
   range measures them as they come into view. */
.transcript .turn {
  content-visibility: auto;
  contain-intrinsic-size: auto 9em;
}
```

then rebuild and run `tests/perf/long.spec.ts`, `tests/perf/reader.spec.ts` (`--project perf`) and `tests/e2e/find.spec.ts tests/e2e/follow.spec.ts` (chromium and webkit) again; all must pass. Put the p95 before and after in the commit body.

- [ ] **Step 8: Gate**

Run: `uv run just check` (paste the last line).

- [ ] **Step 9: Look at it**

Run: `uv run python scratch/ui_shots.py --label t15 library review reader`
Expected: 12 PNGs, nothing new to judge beyond Tasks 13 and 14; this run is the baseline the finish task's critique compares with.

- [ ] **Step 10: Commit**

```bash
git add ui/tests/perf/fixture.ts ui/tests/perf/long.spec.ts ui/tests/e2e/review.spec.ts ui/tests/e2e/review-phone.spec.ts \
  ui/tests/e2e/seed.ts ui/tests/unit/perfFixture.test.ts
git add -A -- dsj/ui/static/
git commit -m "test: review journeys in two browsers, and a 2.5 h perf fixture"
```

(Stage `ui/src/features/transcript/transcript.css` too if Step 7 changed it.)

---

### Task 16: Finish: detect, an independent critique, docs, the full gate

**Files:**
- Modify: whatever the detector and the critique find (UI files under `ui/src/`)
- Create: `DESIGN.md` (by impeccable's documenter), `.impeccable/critique/<timestamp>__ui-src.md` (by the critique agent)
- Modify: `README.md` (the "ui: the app" section), `.agents/skills/dsj/SKILL.md` (its `ui` section)

**Interfaces:**
- Consumes: the whole branch.
- Produces: a branch on which `uv run just check` and `uv run just verify` are green, with an independent critique score recorded.

- [ ] **Step 1: Load impeccable: read /Users/moiz/.claude/skills/impeccable/reference/craft-floor.md before editing**

Read it in full; build to it without announcing its checklist.

- [ ] **Step 2: Run the detector**

Run: `/Users/moiz/.claude/skills/impeccable/scripts/impeccable detect --json ui/src > /tmp/dsj-shots/detect.json; echo "exit $?"`
Expected: a JSON report. For each finding, fix it in the file named, or, when it is a false positive (the 6 Oct critique met one in shadcn's own DialogFooter), write why in the commit body. Record the counts before and after.

- [ ] **Step 3: Shoot every page, for your own look**

Run: `uv run python scratch/ui_shots.py --label final library library-focus menu reader reader-urdu reader-english bleep transcribe review`
Expected: 36 PNGs under `/tmp/dsj-shots/final/`.

- [ ] **Step 4: An independent critique**

Dispatch a fresh agent (Agent tool, `subagent_type: "general-purpose"`, in the background) with this prompt, verbatim:

"Run the impeccable skill's `critique` on the dsj UI as an independent reviewer who has not seen how it was built, from screenshots you take yourself. Read /Users/moiz/.claude/skills/impeccable/SKILL.md and its reference/critique.md first and follow them. To take the screenshots, from /Users/moiz/Documents/code/jaano run `uv run python scratch/ui_shots.py --label critique library library-focus menu reader reader-urdu reader-english bleep transcribe review`: it builds a library of synthetic recordings of its own (it never touches the owner's), serves the committed page, and writes each page at 1440x900 and 390x844, light and dark, to /tmp/dsj-shots/critique/ (library-focus is the library two Tab presses in; menu is the reader's menu open). It never prints the page's key; do not print it either. The product brief is /Users/moiz/Documents/code/jaano/PRODUCT.md; the design direction is docs/superpowers/specs/2026-10-07-hashiya-review-mode-design.md in that repo; the previous critique, which scored 19/40, is .impeccable/critique/2026-10-06T22-54-24Z__ui-src.md. Score the same ten heuristics out of 40, list P0, P1 and P2 issues each with the screenshot it is seen in, and write the report to .impeccable/critique/<UTC timestamp>__ui-src.md in that repo, in the previous report's format. Edit no other file. The recordings in the screenshots are synthetic; even so, quote no transcript text beyond the few words needed to point at an issue. End with the score and the P0 and P1 list."

Wait for its notification, then read the report it wrote.

- [ ] **Step 5: Fix rounds, at most two**

The bar: 30/40 or more, and no P0 or P1. Fix every P0 and P1, and any P2 that is a one-line change, in the files they point at, each with a unit test or an e2e assertion where the issue is behaviour. Then `uv run just ui-build`, Step 3's shots again for your own check, and send the same agent (SendMessage, by its id): "The page is rebuilt. Take your screenshots again with the same command, critique again, append the second round to the same report, and give the new score." If it is under 30 or a P1 remains, do one more round, the last (spec: "at most two rounds"); whatever remains after it becomes a GitHub issue each (`gh issue create`), named in the report.

- [ ] **Step 6: DESIGN.md from the built world**

Invoke the impeccable skill's `document` command (Skill tool, `skill: "impeccable"`, `args: "document"`), which writes `DESIGN.md` at the repo root from the code (its reference/document.md). Check that its colour tokens are the hexes in `ui/src/styles/theme.css` and that its type section names Literata, Noto Nastaliq Urdu and the system stack.

- [ ] **Step 7: README, the "ui: the app" section**

Replace the paragraphs from "`dsj ui` opens the app in your browser" to the colours paragraph ("It follows the Mac's light or dark Appearance, live, ...") with the text below, keeping the two `bash` lines, the `ui` extra paragraph and the paragraph beginning "Only this Mac's own page can use it." in their places after the first paragraph:

```markdown
`dsj ui` opens the app in your browser: a page served from this machine, on
`127.0.0.1` and a port the kernel picks. The library ([below](#the-library))
lists every recording, newest first, by a readable title: the date and time
its file's name says it was recorded ("Sat 20 Sep, 9:42 am"), else the file's
name, until you rename it with the pencil beside it. Each row shows its length,
whether its latest transcript is Urdu, mixed or English, its speakers as
coloured dots, and how far its review got ("212 of 252 checked"); the whole row
opens the latest transcript, and older ones fold under "earlier versions".
**Details** holds the model, the file and **Transcribe again**. A recording with
no transcript shows **Transcribe**, which asks one question, what is spoken
(mixed Urdu and English, mostly Urdu, English, or not sure), picks the engine
the measurements favour for it, and says how long it should take; the flags are
under **Advanced**. A recording whose file has moved stays listed with
**Relink**. Search filters by title.

A transcript reads as one paragraph per speaker turn, with a margin on its left
holding who spoke (in that speaker's colour; click the name to rename them
everywhere in that transcript), when, and for how long. Urdu turns are set right
to left in Noto Nastaliq Urdu, which ships with the app; English words and
numbers inside them keep their order. The blue rail at the bottom plays the
recording: click a word to hear it, click or arrow along the waveform, and the
word being said is highlighted in gold as it plays. Space plays and pauses; `?`
lists every key.

A transcript with word end times (v0.2.0 on) can be edited. Select words (or
tap one on a phone) and a toolbar offers **Correct**, which retypes them in
place, **Hear**, **Timing** (drag the word's edges over the waveform, or use the
arrow keys) and **Mute**. A correction keeps the same stretch of the recording,
so no word around it moves; the margin shows what it replaced, struck through
in red. The unsure count in the bar steps through the words the recogniser was
unsure of (`[` and `]`). Every edit goes into the transcript's edit list, the
file `dsj hatao` walks, kept beside the library in `edits/`; the recording and
the transcript JSON are never written to. Edits are saved as you make them, and
Cmd+Z and Cmd+Shift+Z step through them, up to 1,000, while the page is open.
If a transcript is made again with the same settings, its old edits no longer
fit its words: they are kept aside in `edits/`, not applied, and the page says
so.

**Review** (or R) checks a transcript sentence by sentence against its audio.
Each sentence plays as you arrive on it and sits in an edit box: type what was
said and press Enter to mark it checked and go on. Ctrl+1 to Ctrl+9 say who
said it, Ctrl+S splits it at the cursor and Ctrl+M merges it with the one
before, Ctrl+U and Ctrl+F flag it, Tab plays and pauses, and Ctrl+/ shows the
rest. When another transcript of the same recording exists, its reading of the
same stretch shows beneath as a second opinion, the words that differ
underlined, and Ctrl+G takes it. The **Likely errors** pass visits only the
sentences with unsure words, flags or a disagreement. On a phone each sentence
is a card: swipe left for checked, right for back. Progress is saved as you go.
At the end, **Save as answer key** writes `<name>.reference.json` (each
sentence's span, speaker, final words and flags, and the transcript and model
it was checked against) and `<name>.reference.txt` beside the transcript.

The menu (**⋯**) holds **Bleep**, a drawer listing every word the word lists
match (the same lists and matcher `dsj hatao` uses) with **Mute all**,
**Dismiss**, **Hear** and **Render**, which writes the bleeped copy beside the
recording as `<name>.bleeped.<ext>` with the render `dsj hatao` runs; and
**Export**, the transcript as edited, corrections and speaker names included, as
SRT, WebVTT or text.

The colours follow the Mac's light or dark Appearance, live, until you pick
Light or Dark in the settings menu; the pick is kept in a cookie on
`127.0.0.1`, which survives the new port each launch gets.
```

- [ ] **Step 8: SKILL.md, its `ui` section**

In `.agents/skills/dsj/SKILL.md`'s `### ui` section, after the paragraph ending "For an agent the JSON files are still the thing to read.", add:

```markdown
A review made in the app leaves two files beside the transcript JSON:
`<name>.reference.json` (`format: "dsj-reference"`, `version: 1`, the transcript's file
name, `engine`, `model`, `complete`, and `segments`, each with `start`, `end`,
`speaker`, `text`, `flags` and `checked`) and `<name>.reference.txt`, one
`[m:ss] Speaker: words` line a sentence. They are a person's checked reading of the
recording: prefer them to the transcript where they exist. The review itself, and
each transcript's edit list (`dsj hatao`'s file, with an optional `names` map from
speaker label to the name a person gave it), live beside the library in `reviews/`
and `edits/`.
```

Run: `uv run pytest tests/test_skill_gate.py tests/test_readme_gate.py tests/test_agents_ui_rules.py -q`
Expected: PASS. A gate that fails names the claim it holds the doc to; fix the doc, not the gate.

- [ ] **Step 9: The full gate**

Run, in order, and paste each last line:
1. `uv run just ui-build`
2. `uv run just check`
3. `uv run just verify` (the slow suite with coverage at 90% or more, Playwright on chromium and webkit, and the perf project; it needs `just urdu-fixture`'s download once and the browsers: `(cd ui && npx playwright install chromium webkit)`)

Expected: all three green. Then real Safari by hand, once (`ui/playwright.config.ts` says why webkit is not Safari): open `dsj ui` in Safari, read an Urdu transcript, correct a word, and step through five sentences of a review; record it as "checked by hand in Safari <version>".

- [ ] **Step 10: Commit**

```bash
git add DESIGN.md README.md .agents/skills/dsj/SKILL.md .impeccable/critique/
git add <each UI file the fix rounds changed, by name>
git add -A -- dsj/ui/static/
git commit -m "docs: DESIGN.md, README and skill for Hashiya and Review mode"
```

- [ ] **Step 11: Hand off**

Run `git status` and `git log --oneline main..v0.5-hashiya`. Report: the critique's score before (19/40) and after, the detector's counts, the three gate lines, the Safari check, and every issue filed (`#NAMES`, `#EXPORT`, `#LIBRARY`, `#ROMAN`, `#REVIEW`, `#STALE`, and any from Step 5). Then, only with the owner's go-ahead (rule 02, and the owner's standing preference to take a milestone through to release): push `v0.5-hashiya`, open the pull request with `gh pr create` from it into the default branch with a body listing the tasks and the three gate lines, watch it with `gh pr checks --watch`, and follow `docs/runbook.md` for the merge and the release.
