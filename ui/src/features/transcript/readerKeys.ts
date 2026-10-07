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
