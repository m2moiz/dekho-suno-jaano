# Rulings I made while building v0.5.0 (for the owner)

Decisions taken without asking, so the build could run on its own. Each one can be reversed; say which.

# Pre-flight rulings (controller, 7 Oct 2026). Spec is binding; plan is its argument.
Each implementer applies every ruling that names its task. F-numbers refer to preflight.md in this folder.

- F1 (Tasks 2-16): run `just ui-build` BEFORE `uv run just check` in every UI task (check's ui-fresh fails on a stale build). Order: tests, ui-build, check, screenshots, commit.
- F2 (Tasks 3, 5, 13, 14): make every fixture loaded through loadEditable contiguous (no gaps between words), as ui/tests/unit/correction.test.tsx does.
- F3 (Task 3): corrections() marks only words changed by a CorrectOp (text differs from the original), never a neighbour, never a word only re-timed by a RetimeOp.
- F4 (Tasks 13, 15): Review applies a correction only to the words that differ (word-level diff inside the sentence), not one CorrectOp over the whole sentence; Task 15's e2e expects only the changed words struck through.
- F5 (Task 2): add a ResizeObserver stub in the unit-test setup and update App.test/library.test for the new loading state.
- F6 (Task 6): tests assert what the routes and likho actually emit: 404 body field is `detail`; VTT assertions check cue text after removing inline time tags. Do not change likho in this task.
- F7 (Task 16): the critique agent works in the worktree /Users/moiz/Documents/code/jaano-hashiya, never the main checkout.
- F8 (Tasks 1, 8): ui_shots seeds at least one recording with no transcript, so the transcribe page is reachable.
- F9 (all Python with Urdu): add `# noqa: RUF001` only on lines ruff actually flags; never a noqa that triggers RUF100.
- F10 (Tasks 5, 7, 9, 10, 13): file the issue with `gh issue create` at the step that names it and replace every `#TOKEN` placeholder with the real number before committing. Never leave a placeholder.
- F11 (Task 10): add `replaced: null` to every edits mock in the UI tests, unconditionally.
- F12 (Task 13): the Ctrl+F flag menu is fully keyboard usable: focus moves into the menu, arrows and Enter pick, Esc closes, focus returns to the text box afterwards.
- F13 (Task 13): spec wins: the pass is chosen on entry (a small chooser: Every sentence or Likely errors, keyboard reachable, remembering the last choice), and the top-bar pass switch is keyboard reachable.
- F14 (Tasks 13, 14): the phone card is used below 768 px wide, but the Review keymap also works on the card when a keyboard is present.
- F15 (Tasks 3, 4, 14): every target at 390 px wide is at least 44 px: bleep drawer rows, in-place Correct buttons, timing dock buttons included.
- F16 (Task 15): update journeys.spec so no assertion refers to controls that no longer exist.
- F17, F18 (Task 1): fix the expected counts to the real ones (11 script tests; clean worktree).
- F19 (all): where the plan's Interfaces or File Structure text disagrees with code produced by an earlier task, the code wins; note it in the report.
- F20 (Task 11): the "not applied twice" test applies the check twice and asserts the content is unchanged the second time.
- F21 (Tasks 10-14): share a test fixture or helper when the same block would otherwise be copied a second time; otherwise leave it.
- F22 (all UI): use the project's Input, Textarea, Button primitives instead of hand-built controls; any new primitive (slider, etc.) comes from `npx shadcn@4.21.0 add`.
- F23 (all UI): one gold primary action per screen; green only for "checked"; a save message is neutral.
- F24 (Task 9): spec wins: every engine from /api/engines renders as a choice with an optional "cloud" mark and optional cost line, so B adds Gemini without changing the dialog; not hidden under Advanced.
- F25 (Task 13): opening or resuming Review plays the current sentence on arrival (after the pass chooser), as the spec says.
- F26 (all): every new constant that cites a measurement also names the command that produced it.
- F27 (Task 13): the back arrow behaves like Esc: saves and returns to the transcript.
- F28 (Task 13): record before and after of corrections made in Review in the review document (seam C). Reader-side corrections are deferred to sub-project C. Cost if wrong: C starts without reader-edit history.
- R1 (all later UI tests): measure a mixed-script line by its extent (max right, min left over getClientRects), never by the first rect (Task 1 finding).
- R2 (all): the git hook blocks git add -A; stage the build as git add -u dsj/ui/static plus new asset files by name.
- R3 (all): the worktree .venv needs the sherpa extra for pyright: already installed (uv sync --offline --inexact --extra sherpa); do not remove it.
- R4 (Tasks 9-15, owner 7 Oct): run per-task Playwright e2e on chromium only (--project chromium). WebKit runs once, in Task 16's full just verify. If a brief says both engines, chromium satisfies it.

## Later rulings (progress.md)
Task 15b: ruling R5: try a short list of HTTPS ports, first free wins, never overwrite; in --tailnet mode a page goodbye does not shorten the idle stop
Task 15c: ruling R6: the one-time whole-review save when a pass is first picked (141,781 B) is accepted; #251 closes with the PR
RULING R7: a checked sentence stays checked across a transcript re-make only if its words are unchanged; an existing answer key is never overwritten without keeping the previous one; when the edit list goes outdated the review save stops too; library.db is backed up once before the v3 to v5 upgrade
