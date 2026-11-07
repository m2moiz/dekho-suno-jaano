// The reader's keys (Hashiya spec; critique, Alex: "undo/redo only; Space
// scrolls"): Space plays or pauses, R opens Review, `?` opens the key sheet,
// Esc lets go of the selection. By `event.code` where a printed key could differ: with the
// Urdu input source the key labelled "/" types something else, and the
// sheet must still open.

import { type RefObject, useEffect } from "react";

import type { PlayerControls } from "@/features/player/Player";
import { SPEEDS } from "@/features/player/speed";
import { type Runners, showCommands } from "@/features/shell/CommandPalette";
import { showKeys } from "@/features/shell/KeySheet";
import type { Sheet } from "@/features/shell/keys";

// How far ← and → move the playhead (#88): a sentence or so at speech pace.
export const SKIP_S = 5;

// Where every key is someone else's: typing, and an open menu, list or dialog.
export const NOT_OURS = "input, textarea, select, [contenteditable], [role=menu], [role=dialog], [role=listbox]";
// What owns Space and Enter, and only those: pressing a button or a link, and
// a slider (the waveform, a timing edge). `]`, `[`, `?` and Esc still work
// with one of them focused.
export const PRESSABLE = "button, a, [role=button], [role=slider]";

export function isOurs(event: KeyboardEvent): boolean {
  if (event.metaKey || event.ctrlKey || event.altKey || event.isComposing) return false;
  const target = event.target as Element | null;
  if (target?.closest?.(NOT_OURS)) return false;
  const press = event.code === "Space" || event.key === " " || event.key === "Enter";
  return !(press && target?.closest?.(PRESSABLE));
}

/** One step along SPEEDS from the player's speed, or the same speed at either end. */
function stepSpeed(controls: PlayerControls, by: 1 | -1): void {
  const at = SPEEDS.indexOf(controls.speed());
  const next = SPEEDS[at + by];
  if (next !== undefined) controls.setSpeed(next);
}

/**
 * What each reader key does, by the id keys.ts gives it (#88): the `?` sheet
 * and the ⌘K palette list the keys, the palette runs these. A key without a
 * runner here is bound by another component and is listed only.
 */
export function readerRunners(
  controls: RefObject<PlayerControls | null>, sheet: Sheet, onReview?: () => void,
): Runners {
  const runners: Record<string, () => void> = {
    play: () => controls.current?.toggle(),
    back: () => controls.current?.skip(-SKIP_S),
    forward: () => controls.current?.skip(SKIP_S),
    slower: () => {
      if (controls.current !== null) stepSpeed(controls.current, -1);
    },
    faster: () => {
      if (controls.current !== null) stepSpeed(controls.current, 1);
    },
    release: () => window.getSelection()?.removeAllRanges(),
    sheet: () => showKeys(sheet),
    commands: () => showCommands(sheet, readerRunners(controls, sheet, onReview)),
  };
  if (onReview !== undefined) runners.review = onReview;
  return runners;
}

// The key code each reader command answers to, with no modifier unless said.
const CODES: Readonly<Record<string, string>> = {
  Space: "play",
  ArrowLeft: "back",
  ArrowRight: "forward",
  Comma: "slower",
  Period: "faster",
  KeyR: "review",
};

/** The reader's keys; with `onReview`, what R does (an editable transcript's: open Review once saved). */
export function useReaderKeys(controls: RefObject<PlayerControls | null>, sheet: Sheet, onReview?: () => void): void {
  useEffect(() => {
    const runners = readerRunners(controls, sheet, onReview);
    const key = (event: KeyboardEvent) => {
      // ⌘K (Ctrl+K elsewhere) opens the palette from anywhere but a typing box.
      if (event.code === "KeyK" && (event.metaKey || event.ctrlKey) && !event.altKey) {
        const target = event.target as Element | null;
        if (target?.closest?.("input, textarea, [contenteditable]")) return;
        event.preventDefault();
        runners.commands?.();
        return;
      }
      if (!isOurs(event)) return;
      if (event.code === "Slash" && event.shiftKey) {
        event.preventDefault();
        showKeys(sheet);
        return;
      }
      if (event.key === "Escape") {
        window.getSelection()?.removeAllRanges();
        return;
      }
      if (event.shiftKey) return;
      const id = CODES[event.code];
      const run = id === undefined ? undefined : runners[id];
      if (run === undefined) return;
      event.preventDefault();
      run();
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [controls, sheet, onReview]);
}
