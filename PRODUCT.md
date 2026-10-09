# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

One person: the owner, who speaks Urdu mixed with English inside one sentence. He records group calls with friends (two to four or more speakers), voice notes, meetings and podcasts, up to about 2.5 hours long. He uses the app on a Mac with keyboard and headphones for focused 20 to 60 minute sessions, and on a phone or tablet away from the desk. He reads Urdu script, Roman Urdu and English, and writes Urdu in his own Roman spellings, which have no standard form.

## Product Purpose

dsj (dekho, suno, jaano: see, listen, know) turns his recordings into transcripts he can read in sync with the audio, search, correct and trust. Jobs, in order of frequency: transcribe a recording; read or skim it while hearing it; check and correct it sentence by sentence (both to fix real transcripts and to build checked answer keys that score transcription models); name the speakers and find what a given person said; bleep listed words out of a recording. Success: what was said is captured reliably and can be found again; the script it is written in does not matter, because he and AI agents read any script.

## Positioning

A private, local-first archive of his own spoken conversations, built around mixed Urdu and English, which mainstream transcription apps handle badly. Everything runs on his Mac unless he chooses a cloud model for a recording.

## Operating Context

- The app is `dsj ui`: a local web page served by the dsj CLI on his own machine, opened in his browser. The CLI does the transcription; the page reads, plays and edits.
- Recordings live in his Google Drive folder and in a local library; transcripts are JSON beside the audio, with a non-destructive edit list.
- Engines on the Mac: parakeet (fast, English and European languages), whisper turbo (Urdu and mixed speech), and others under evaluation; a cloud engine (Gemini on Vertex AI) is planned, allowed for any recording.
- Speed matters: a transcription slower than about 2x realtime is not useful to him.

## Capabilities and Constraints

- Exists today: library of recordings; reader with word-level highlight following the audio, click a word to hear it, speaker turns, low-confidence word tint, undo/redo with autosave; correct a stretch of words; adjust word timing; bleep words from lists and render; transcribe from the page; light and dark.
- Planned: Review mode (sentence-by-sentence checking, keyboard-first on the Mac and touch-first on the phone), cloud drafts, answer-key export, speaker names and voiceprints recognised across recordings, personal spelling conventions learned from corrections.
- Text is mixed-direction: Urdu script is right-to-left and must be set as such (Nastaliq-appropriate type, right-aligned turns), with English words and numbers inside it.
- Single user, no accounts, no sharing.

## Brand Commitments

The name dsj, from dekho, suno, jaano. Urdu words shown to him are written in Urdu script or Roman Urdu, never Devanagari. Copy is plain, honest and specific ("Runs on this Mac. Nothing leaves it."), never marketing.

## Evidence on Hand

- Real recordings and transcripts in his library (private: never quote them in public places).
- Public reference sets used for benchmarks: an Urdu-English podcast, an Urdu set and an English earnings call.
- No users, testimonials or press exist, and none should be invented.

## Product Principles

1. The words come first: reading and hearing what was said is the main experience; tools appear when they are needed.
2. Capture beats polish of script: never trade completeness of what was said for prettier spelling.
3. Fast for an expert, obvious for a first look: every action has a keyboard path on the Mac and a thumb-sized target on the phone.
4. Urdu is a first-class language, not a fallback.
5. Private by default; any cloud use is visible and chosen.

## Accessibility & Inclusion

Keyboard-complete on the Mac; touch targets at least 44 px on the phone; right-to-left and mixed-direction text set correctly; screen-reader structure that does not bury the transcript under repeated headings.
