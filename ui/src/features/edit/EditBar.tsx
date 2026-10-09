import { Redo2, Undo2 } from "lucide-react";
import { type RefObject, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { FIELD_ICON_BUTTON } from "@/features/shell/field";
import { unsureHighlight as wordsHighlight } from "@/features/transcript/confidence";
import type { Reading } from "@/features/transcript/document";
import type { Content, Editor } from "@/lib/editOps";
import type { Correction } from "./corrections";
import type { SaveState } from "./editing";
import type { EditReading } from "./readContent";
import { type Selected, selectedWords, turnTexts } from "./selection";

export const MUTED = "dsj-muted";
export const CORRECTED = "dsj-corrected";

/** The words with a muted entry in them. */
export function mutedWords(edit: EditReading, content: Content): number[] {
  const out: number[] = [];
  for (let w = 0; w < edit.first.length; w += 1) {
    for (let i = edit.first[w] ?? 0; i < (edit.stop[w] ?? 0); i += 1) {
      const entry = content[i];
      if (entry?.kind === "item" && entry.muted && entry.text !== "") {
        out.push(w);
        break;
      }
    }
  }
  return out;
}

/** Paint every muted word, again after each change (`::highlight(dsj-muted)`). */
export function useMutedPaint(
  edit: EditReading,
  content: Content,
  article: RefObject<HTMLElement | null>,
): void {
  useEffect(() => {
    const root = article.current;
    if (root === null) return;
    const highlight = wordsHighlight(edit.reading, mutedWords(edit, content), turnTexts(root));
    CSS.highlights.set(MUTED, highlight);
    return () => {
      if (CSS.highlights.get(MUTED) === highlight) CSS.highlights.delete(MUTED);
    };
  }, [edit, content, article]);
}

/** The words selected in `article`, read again whenever the selection changes. */
export function useSelection(edit: EditReading, article: RefObject<HTMLElement | null>): Selected | null {
  const [selected, setSelected] = useState<Selected | null>(null);
  useEffect(() => {
    const changed = () => {
      const root = article.current;
      const next = root === null ? null : selectedWords(edit.reading, root);
      setSelected((was) => (was?.first === next?.first && was?.last === next?.last ? was : next));
    };
    changed();
    document.addEventListener("selectionchange", changed);
    return () => document.removeEventListener("selectionchange", changed);
  }, [edit, article]);
  return selected;
}

// Where a key press is typing, it is the field's to undo, not the transcript's.
const FIELDS = "input, textarea, select, [contenteditable]";

/**
 * Cmd+Z undoes and Cmd+Shift+Z redoes (Ctrl on other systems, and Ctrl+Y),
 * stepping only through edits: a caret move, a scroll or a playback tick is
 * never an edit, so there is nothing else in the history to step through.
 */
export function useUndoKeys(editor: Editor): void {
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.altKey) return;
      if ((event.target as Element | null)?.closest?.(FIELDS)) return;
      const k = event.key.toLowerCase();
      const redo = (k === "z" && event.shiftKey) || (k === "y" && event.ctrlKey && !event.metaKey);
      if (k !== "z" && !redo) return;
      event.preventDefault();
      if (redo) editor.redo();
      else editor.undo();
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [editor]);
}

const SAVE_TEXT: Record<SaveState, string> = {
  saved: "Saved",
  saving: "Saving…",
  failed: "Not saved",
};

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
 * hears it change. The save message is neutral, never green (green is "checked").
 */
export function EditBar({ editor, saving }: { editor: Editor; saving: SaveState }) {
  const undo = editor.undoLabel();
  const redo = editor.redoLabel();
  const said = saving !== "saved" || undo !== null || redo !== null;
  const quiet = FIELD_ICON_BUTTON;
  return (
    <div role="toolbar" aria-label="Edit" className="flex items-center">
      <Button
        variant="ghost"
        size="icon"
        aria-label="Undo"
        title={undo === null ? "Nothing to undo" : `Undo ${undo} (⌘Z)`}
        disabled={undo === null}
        className={quiet}
        onClick={() => editor.undo()}
      >
        <Undo2 aria-hidden />
      </Button>
      <Button
        variant="ghost"
        size="icon"
        aria-label="Redo"
        title={redo === null ? "Nothing to redo" : `Redo ${redo} (⇧⌘Z)`}
        disabled={redo === null}
        className={quiet}
        onClick={() => editor.redo()}
      >
        <Redo2 aria-hidden />
      </Button>
      <span role="status" className="min-w-16 px-1 text-sm text-field-muted">
        {said ? SAVE_TEXT[saving] : ""}
      </span>
    </div>
  );
}
