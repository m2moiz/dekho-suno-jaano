import { type RefObject, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { unsureHighlight as wordsHighlight } from "@/features/transcript/confidence";
import { type Content, type Editor, HISTORY_LIMIT, muteRange } from "@/lib/editOps";
import type { EditReading } from "./readContent";
import { type Selected, selectedWords } from "./selection";
import type { SaveState } from "./editing";

export const MUTED = "dsj-muted";

/** The paragraphs' text nodes, by turn: the article's `p[data-turn]` children. */
export function turnTexts(root: Element): Text[] {
  const texts: Text[] = [];
  for (const p of root.querySelectorAll<HTMLElement>("p[data-turn]")) {
    if (p.firstChild instanceof Text) texts[Number(p.dataset["turn"])] = p.firstChild;
  }
  return texts;
}

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

/** A press on a button that acts on the selection must not clear it first. */
function keepSelection(event: { preventDefault: () => void }): void {
  event.preventDefault();
}

type Props = {
  editor: Editor;
  content: Content;
  edit: EditReading;
  selected: Selected | null;
  saving: SaveState;
};

/**
 * Undo, Redo, and what can be done to the words selected: above the
 * transcript, and in reach as it scrolls.
 */
export function EditBar({ editor, content, edit, selected, saving }: Props) {
  const undo = editor.undoLabel();
  const redo = editor.redoLabel();
  const range =
    selected === null
      ? null
      : { start: edit.first[selected.first] ?? 0, stop: edit.stop[selected.last] ?? 0 };
  const words = selected === null ? 0 : selected.last - selected.first + 1;
  return (
    <div
      role="toolbar"
      aria-label="Edit"
      className="sticky top-0 z-10 -mx-2 mb-6 flex flex-wrap items-center gap-2 bg-background/95 px-2 py-2 backdrop-blur"
    >
      <Button
        variant="outline"
        size="sm"
        disabled={undo === null}
        title={undo === null ? "Nothing to undo" : `Undo ${undo} (⌘Z)`}
        onClick={() => editor.undo()}
      >
        Undo
      </Button>
      <Button
        variant="outline"
        size="sm"
        disabled={redo === null}
        title={redo === null ? "Nothing to redo" : `Redo ${redo} (⇧⌘Z)`}
        onClick={() => editor.redo()}
      >
        Redo
      </Button>
      <span className="mx-1 h-5 w-px bg-border" aria-hidden />
      <Button
        variant="outline"
        size="sm"
        disabled={range === null}
        onMouseDown={keepSelection}
        title="Silence the selected words in the edit list; the recording is never changed"
        onClick={() => {
          if (range !== null) editor.applyEdit(muteRange(content, range.start, range.stop, true));
        }}
      >
        Mute{words > 1 ? ` ${words} words` : ""}
      </Button>
      <Button
        variant="outline"
        size="sm"
        disabled={range === null}
        onMouseDown={keepSelection}
        onClick={() => {
          if (range !== null) editor.applyEdit(muteRange(content, range.start, range.stop, false));
        }}
      >
        Unmute
      </Button>
      <span className="ml-auto text-sm text-muted-foreground" role="status">
        {SAVE_TEXT[saving]}
      </span>
      <p className="basis-full text-xs text-muted-foreground">
        Edits are saved as you make them. Undo goes back up to {HISTORY_LIMIT.toLocaleString("en")} steps
        while this page is open; closing or reloading it keeps the edits and forgets their undo.
      </p>
    </div>
  );
}
