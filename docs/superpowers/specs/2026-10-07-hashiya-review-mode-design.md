# Hashiya: the app redesign and Review mode

Date: 7 Oct 2026. Status: approved direction (owner chose Hashiya on the impeccable decision page; Section 1 confirmed; "proceed autonomously" for the rest).

## Why

The owner saw `dsj ui` for the first time on 7 Oct and called it "very basic, very bare bones, robotic". An independent impeccable critique scored it 19/40 (Poor): stock shadcn with nothing added, Urdu laid out as English, the transcript buried under tools, a Transcribe dialog that asks for command-line flags, a library of filenames, and no keyboard path beyond undo. He also needs a fast way to check transcripts against their audio: typing 10 minutes of his own Urdu call from scratch was "too much work", and every accuracy number dsj has comes from public audio because there is no checked transcript of his voice (#182).

This spec covers sub-project A: the whole app in the Hashiya visual world, and Review mode. Sub-projects B (Gemini on Vertex AI as a draft engine), E (answer keys scored), D (speaker identity across recordings, voiceprints, search by person) and C (personal Roman Urdu spellings) get their own specs, in that order. A leaves clean seams for each (named below) and builds none of them.

## Who and how (from PRODUCT.md)

One person, mixed Urdu and English in one sentence, group calls with 2 to 4+ speakers, recordings up to 2.5 h. Mac with keyboard and headphones for 20 to 60 minute sessions; phone and tablet away from the desk, in the first version.

## The world: Hashiya

From the margins of Persian and Urdu manuscripts, where the main text (matn) sits in a ruled panel and corrections and commentary run in the margin (hashiya) beside it. Operate mode: the world lends type, palette, density and one signature move; layout, navigation and controls stay standard web controls.

- **Colour (committed, by region).** Deep blue field `#132447` owns the shell: top bar and player rail. Reading ground: pale cool white `#F3F5F9` in light, deep blue-black `#0D1730` in dark (never cream). Ink `#16203A` / `#E6EAF2`. Gold `#C8A24A`: playback highlight, keyboard focus, the one primary action per screen. Red `#B8402A`: corrections only. Green `#3E7A5C`: "checked" only. Six soft speaker colours, fixed per speaker index (D later makes them follow a named person). Exact tokens are chosen in the build and checked for contrast (WCAG AA for text, 3:1 for non-text); these hexes are the starting points.
- **Type.** Urdu: Noto Nastaliq Urdu (OFL, bundled locally, never a hosted font), about 1.3x the English size, line height about 2.1, right-aligned, `lang="ur"`. English: Literata (already bundled). Interface: the system UI stack. Times and counts in tabular figures.
- **Signature move: the margin.** A narrow column beside the text carries everything about the words: speaker nameplate in that speaker's colour, start time, a tick drawn as long as the sentence lasted, the review mark, and corrections with the original struck through in red. The text column carries only the words.
- **Raises kept from the round:** duration drawn to scale (from the dance score); colour owns regions (guide map); tabular figures and destructive actions isolated with space around them (console); a fixed nameplate and colour per speaker (character roster); in Review mode the sentence being checked is the only thing at full contrast (datamatics).
- **Calm by default.** Tools appear on selection or tap. Bleeping lives in a drawer. No help paragraphs in the page: one key sheet behind `?`.
- **Laptop and phone.** On the phone the margin folds into one slim line above each turn or sentence, targets are 44 px or more, the player rail sits at the bottom in thumb reach.

## Screens

### Library

- Top bar (blue): wordmark, search (filters by title now; full-text search is #68), "Add recording" as the gold primary.
- One row per recording: a readable title (default from the file's timestamp, e.g. "Sat 20 Sep, 9:42 am", else the filename; renamable inline), length, a language tag (Urdu, mixed, English, from the latest transcript), speaker count as coloured dots, and review progress ("212 of 252 checked") when a review exists.
- The whole row opens the latest transcript; older transcripts fold under "2 earlier versions". Model names live in a details disclosure, not the row.
- States: loading skeleton rows; empty library with "Add recording" as the next step; a missing or unreadable file shown as one quiet line with Relink.
- Rows of untranscribed recordings show "Transcribe" instead of progress.

### Reader

- Top bar: back, title, version picker (when there is more than one transcript), "Review" (gold primary), and a menu with Timing, Bleep, Export.
- The transcript comes first: no panels above it. One paragraph per speaker turn at a reading measure (about 68 characters for English); Urdu turns right-aligned in Nastaliq; mixed lines keep correct word order (`dir="auto"` per paragraph, `unicode-bidi: plaintext`).
- The margin on the start side of the column (left), the same side for Urdu and English turns, so the eye always finds who and when in one place.
- Selecting words (or tapping one on the phone) shows a small toolbar next to them: Correct (edits in place, no modal), Hear, Timing, Mute. The current Correct and Timing logic (#83, #85) is kept; only its presentation changes.
- "Unsure words" becomes a count with previous and next arrows in the top bar.
- Player rail (blue, about 56 px): play/pause, time, the waveform as the only scrubber with the played part tinted gold, speed. The browser's own audio bar is gone.
- Bleep: a drawer from the right (a bottom sheet on the phone) with a badge on its menu item only when it found matches.
- Speakers are renamable: click a nameplate, type a name; the name is stored in the transcript's edit document and shown everywhere in that transcript.

### Transcribe

- Asks the owner's question first: "What's spoken?" Mixed Urdu and English · Mostly Urdu · English or European languages · Not sure. The answer picks the engine and settings from the measured best (mixed: whisper turbo `--roman-urdu`; mostly Urdu: whisper `--language ur`; English: parakeet; not sure: whisper `--roman-urdu`), and the dialog says which it chose and the expected time from the file's length and the engine's measured speed.
- Advanced (folded): model, prompt, skip speaker labels, fail if labelling fails, start over.
- An engine that cannot run here is one grey line ("sherpa isn't installed on this Mac"), details on request.
- Seam for B: the engine list is data from `/api/engines`; when the Gemini engine exists it appears as a choice with a "cloud" mark and its cost estimate, with no change to this dialog's structure.

### Review mode (new)

Entered from the reader's "Review" button or `R`. The unit is the sentence from the transcript; the owner can split and merge.

**Laptop, keyboard-first.** The current sentence sits in the middle at full contrast, large, its text already in an edit box (focus is in the box the whole time). Two sentences before and after sit dimmed above and below for context. The margin beside the current sentence shows its speaker nameplate, time, duration tick and state. Beneath the text, when another transcript of the same recording exists, its reading of the same time span appears in grey as a second opinion; where both are in the same script, the words that differ are underlined. The top bar shows progress ("84 of 252 checked"), the pass, and time remaining at the current pace.

Arriving on a sentence plays it from 0.3 s before its start to 0.2 s after its end, then stops. Typing pauses playback; resuming backs up 1.5 s.

| Key | Action |
|---|---|
| Enter | Mark checked (with any edits), go to the next sentence, play it |
| Shift+Enter | Previous sentence |
| Tab | Play or pause (resume backs up 1.5 s) |
| Shift+Tab | Replay the sentence from its start |
| Ctrl+, / Ctrl+. | Slower / faster (0.75x, 1x, 1.25x, 1.5x) |
| Ctrl+1 to Ctrl+9 | This sentence was said by speaker n (works unless macOS "Switch to Desktop n" shortcuts are switched on) |
| Ctrl+G | Take the second opinion's reading |
| Ctrl+U | Flag: can't make it out (adds [?] at the cursor when text is selected or empty) |
| Ctrl+F | Flag menu: not speech, overlapping talk, cut off |
| Ctrl+S | Split the sentence at the cursor (time split at the matching word boundary) |
| Ctrl+M | Merge with the previous sentence |
| Ctrl+J / Ctrl+Shift+J | Next / previous likely error |
| Ctrl+/ | Key sheet |
| Esc | Leave review (progress is saved) |

These avoid the macOS text-field bindings (Ctrl+A/E/K/B/F... in text boxes are emacs keys: Ctrl+F is the one exception taken, because the flag menu matters more than one-character cursor movement inside a short sentence; record this trade in the key sheet), the browser's Cmd shortcuts, and Ctrl+Space (input-source switching, which an Urdu typist uses). A footer line always shows the five most used keys.

**Passes.** "Every sentence" (in order, for answer keys) and "Likely errors" (sentences with unsure words, disagreement with the second opinion, or flags). The pass is chosen on entry and switchable in the top bar.

**Phone and tablet, touch-first.** One sentence per screen as a card: margin line on top (nameplate, time), text below (tap to edit, the keyboard opens), second opinion beneath. A large play/replay button. Swipe left: checked and next; swipe right: back. A row of speaker chips to reassign. A flag button. Progress at the top. Every target 44 px or more.

**Finishing.** When the pass ends: counts of sentences checked, edited, flagged and reassigned, and two actions: "Back to the transcript" and "Save as answer key". The answer key is written beside the transcript as `<name>.reference.json` (segments with start, end, speaker, final text, flags, and the transcript and model it was reviewed from) and a plain `<name>.reference.txt`. Scoring against it is sub-project E.

**Where edits go.** A text change applies the existing CorrectOp to the edit list for that sentence's span, so corrections keep their link to the audio and show in the reader. Speaker changes are a new EditOp kind that splits the speaker's paragraph at the sentence boundary and sets the speaker. Review state (segments, checked or flagged, pass, position) is a separate review document per transcript, keyed by time span so it survives later corrections. Everything autosaves; leaving and returning resumes at the same sentence.

**Seam for C.** After a correction that only changes spelling (both words map to the same consonant key), Review mode will later offer "Always write X as Y?". A records the before and after of every correction in the review document so C has its learning data.

## Data and API

- `GET/PUT /api/transcripts/{id}/review`: the review document (segments with start, end, state, flags, speaker override; pass; cursor; started and updated times). Pydantic models in `dsj/ui/schemas.py`, types regenerated with `just api`.
- `POST /api/transcripts/{id}/reference`: writes the answer-key files beside the transcript; refuses when any segment is unchecked unless `allow_partial` is set, and says how many.
- `PATCH /api/recordings/{id}`: title.
- Speaker names: carried in the edit document's paragraph entries (`speaker` already holds a label) plus a names table in the edit document; hatao keeps reading paragraphs as before.
- Second opinion: the page loads the other transcript of the same recording (existing routes) and aligns its words to each segment by time.
- Long recordings: a 2.5 h call is about 1,500 sentences; the review list and the reader stay virtualized enough that the perf suite's p95 frame budget (20 ms) holds on a 1,500-sentence fixture.

## Accessibility

Keyboard-complete on the Mac; visible gold focus ring of at least 2 px; one level-1 heading per page and speaker turns as list items, not 56 headings; live region announcing review progress; RTL and mixed text correct; reduced motion respected; touch targets 44 px.

## Testing and finish

- Unit (vitest): review document model, split and merge timing, key map, second-opinion alignment, speaker EditOp apply and invert, title derivation from filenames.
- End to end (Playwright, chromium and webkit, laptop and phone viewports): review a fixture start to finish by keyboard; the phone swipe path; reader correction in place; Urdu turn alignment and font.
- Perf: the existing suite plus the 1,500-sentence review fixture.
- Python: routes and schemas for review, reference export and title.
- Design finish: impeccable detect on the changed UI; an independent agent runs impeccable critique on its own screenshots (laptop and phone, light and dark) and must score well above the 19/40 baseline; findings fixed in at most two rounds; DESIGN.md written from the built world by impeccable's documenter.
- Gates: `uv run just check` and `uv run just verify` green; CI green; release.

## Out of scope for A

The Gemini engine (B); scoring answer keys (E); voiceprints, cross-recording speaker identity and search by person (D); spelling conventions (C); full-text search (#68); cancel a running transcription (#72) unless it falls out of the Transcribe redesign for free.
