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

/** A transcript that cannot be edited (#66): the same reading keys, none for editing. */
export const READ_ONLY_SHEET: Sheet = {
  title: "Keys in the reader",
  keys: READER_SHEET.keys.filter((key) => !key.keys.includes("⌘")),
  notes: ["Click a word to hear it from there. This transcript cannot be edited, so it has no undo."],
};
