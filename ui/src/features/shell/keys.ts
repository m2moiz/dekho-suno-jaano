// Every key the app answers, in one place per page, for the sheet behind `?`
// (Hashiya spec: "No help paragraphs in the page: one key sheet behind ?").

import { HISTORY_LIMIT } from "@/lib/editOps";

export type Key = { keys: string[]; does: string };
export type Sheet = { title: string; keys: readonly Key[]; notes: readonly string[] };

export const READER_SHEET: Sheet = {
  title: "Keys in the reader",
  keys: [
    { keys: ["Space"], does: "Play or pause" },
    { keys: ["R"], does: "Review this transcript, sentence by sentence" },
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

/** A transcript that cannot be edited (#66): the same reading keys, none for editing. */
export const READ_ONLY_SHEET: Sheet = {
  title: "Keys in the reader",
  // Review edits, so it is not offered either.
  keys: READER_SHEET.keys.filter((key) => !key.keys.includes("⌘") && !key.keys.includes("R")),
  notes: ["Click a word to hear it from there. This transcript cannot be edited, so it has no undo."],
};

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
    { keys: ["Ctrl", "U"], does: "Flag: can't make it out (puts [?] in place of the selected words, or in an empty box)" },
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
    "Tab plays and pauses inside the sentence's box. Option+Tab and Option+Shift+Tab move out of it to the page's other controls, such as the pass switch in the top bar.",
    "Every change is saved as you go; leaving and coming back resumes at the same sentence.",
    "On a tablet, tap the sentence once before using a keyboard: a touch screen does not put the cursor in it by itself, so the keys have nowhere to go until then.",
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
