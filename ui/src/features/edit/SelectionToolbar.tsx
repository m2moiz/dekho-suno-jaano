import { type CSSProperties, type RefObject, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { Button } from "@/components/ui/button";
import type { PlayerControls } from "@/features/player/Player";
import { PLAYER_HEIGHT } from "@/features/player/playhead";
import { BAR_HEIGHT } from "@/features/shell/AppBar";
import { type Content, type Editor, muteRange } from "@/lib/editOps";
import { TOUCH, useMediaQuery } from "@/lib/media";
import { cn } from "@/lib/utils";
import type { EditReading } from "./readContent";
import { focusKeepingSelection, focusText, type Selected } from "./selection";

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

function heightOf(property: string): number {
  return Number.parseFloat(document.documentElement.style.getPropertyValue(property)) || 0;
}

/**
 * Above the selection, or below it when the bar is in the way, and never
 * under the bar or the rail: a selection scrolled partly out of sight keeps
 * its tools in sight at the nearer edge. Across, see `centre` below.
 */
function besideSelection(box: Box): CSSProperties {
  const bar = heightOf(BAR_HEIGHT);
  const rail = heightOf(PLAYER_HEIGHT);
  const above = box.top - HEIGHT_PX - 8;
  const wanted = above < bar + 4 ? box.bottom + 8 : above;
  const top = Math.max(bar + 4, Math.min(wanted, window.innerHeight - rail - HEIGHT_PX - 8));
  return { top };
}

/**
 * Move focus to the toolbar's first action when the selection on show was
 * made from the keyboard (`]`, `[`, or Shift and an arrow, once Shift is let
 * go), so its tools are one Tab-free step away (WCAG 2.1.1). A selection made
 * with the pointer, or put back by the page after Correct, leaves focus alone.
 */
function useKeyboardReach(bar: RefObject<HTMLDivElement | null>, shown: boolean, selected: Selected | null): void {
  // A selecting key pressed in the reader since the last selection appeared.
  const pending = useRef(false);
  // Shift and an arrow growing a selection: focus waits for Shift to come up.
  const growing = useRef(false);
  const shownNow = useRef(shown);
  shownNow.current = shown;
  useEffect(() => {
    const first = () => {
      const button = bar.current?.querySelector<HTMLElement>("button:not(:disabled)");
      if (button != null) focusKeepingSelection(button);
    };
    const down = (event: KeyboardEvent) => {
      const target = event.target as Element | null;
      // Typing, or Correct's form (its Cancel and Save put the words back themselves).
      if (target?.closest?.("input, textarea, select, [contenteditable], form")) {
        pending.current = false;
        return;
      }
      if (bar.current?.contains(target)) return;
      // Only the keys that select: `]` and `[`, and Shift with a key that moves.
      // Esc, Space and the rest select nothing, and a selection the page puts
      // back after one (Timing's Esc, Correct's Save) keeps focus where it is.
      if (event.shiftKey && /^(Arrow|Home|End|Page)/.test(event.key)) growing.current = true;
      else if (event.code === "BracketRight" || event.code === "BracketLeft") {
        pending.current = true;
        // Once the key's own handlers have run: a `]` that selected nothing new
        // (no unsure word, or the same one again) is settled here, so the
        // flag never waits for a selection the page makes later.
        const before = spotOf(window.getSelection());
        setTimeout(() => {
          if (!pending.current || !sameSpot(spotOf(window.getSelection()), before)) return;
          pending.current = false;
          if (shownNow.current) first();
        }, 0);
      }
    };
    const up = (event: KeyboardEvent) => {
      if (event.key !== "Shift" || !growing.current) return;
      growing.current = false;
      if (shownNow.current) first();
    };
    const pointer = () => {
      pending.current = false;
      growing.current = false;
    };
    // A key that selects while the toolbar is already up (`]` from one word to
    // the next) changes no state that would show it again.
    const changed = () => {
      if (!pending.current || growing.current || !shownNow.current) return;
      pending.current = false;
      first();
    };
    document.addEventListener("selectionchange", changed);
    window.addEventListener("keydown", down, true);
    window.addEventListener("keyup", up, true);
    window.addEventListener("pointerdown", pointer, true);
    return () => {
      window.removeEventListener("keydown", down, true);
      window.removeEventListener("keyup", up, true);
      window.removeEventListener("pointerdown", pointer, true);
      document.removeEventListener("selectionchange", changed);
    };
  }, [bar]);
  useEffect(() => {
    if (!shown || !pending.current || growing.current) return;
    pending.current = false;
    const button = bar.current?.querySelector<HTMLElement>("button:not(:disabled)");
    if (button != null) focusKeepingSelection(button);
  }, [bar, shown, selected]);
}

/** Where the page's selection is: its two ends, compared by node and offset. */
function spotOf(selection: Selection | null): readonly [Node | null, number, Node | null, number] {
  if (selection === null || selection.rangeCount === 0) return [null, 0, null, 0];
  const range = selection.getRangeAt(0);
  return [range.startContainer, range.startOffset, range.endContainer, range.endOffset];
}

function sameSpot(a: ReturnType<typeof spotOf>, b: ReturnType<typeof spotOf>): boolean {
  return a.every((part, i) => part === b[i]);
}

/** The paragraph a range is in: its start's, or, from an element (a triple-click), its first word's. */
function paragraphOf(range: Range, turn: number): HTMLElement | null {
  const node = range.startContainer;
  const element = node instanceof Element ? node : node.parentElement;
  return (
    element?.closest<HTMLElement>("p[data-turn]") ??
    (element?.closest("article") ?? document).querySelector<HTMLElement>(`p[data-turn="${turn}"]`)
  );
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
  const bar = useRef<HTMLDivElement>(null);
  // Centred over the selection and never off the window's sides, by the
  // toolbar's own width, which only the drawn toolbar knows ("Mute 12 words",
  // the one-turn note).
  useLayoutEffect(() => {
    const element = bar.current;
    if (element === null) return;
    if (box === null || touch) {
      // The phone's toolbar spans the window from its classes.
      element.style.left = "";
      return;
    }
    const width = element.offsetWidth;
    const left = Math.min(Math.max(8, box.left + box.width / 2 - width / 2), window.innerWidth - width - 8);
    element.style.left = `${Math.max(8, left)}px`;
  });
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
  useKeyboardReach(bar, selected !== null && box !== null, selected);
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
    const paragraph = paragraphOf(live, turn[selected.first] ?? 0);
    return paragraph ? { ...range, from, to, box: boxOf(live), paragraph } : null;
  };

  return createPortal(
    <div
      ref={bar}
      role="toolbar"
      aria-label="Selection"
      className={cn(
        "fixed z-40 flex items-center gap-1 rounded-xl border bg-popover p-1 text-popover-foreground shadow-lg shadow-black/15",
        touch ? "inset-x-2" : "",
      )}
      style={touch ? { bottom: `calc(var(${PLAYER_HEIGHT}, 0px) + 0.5rem)` } : besideSelection(box)}
      onKeyDown={(event) => {
        // Esc lets go of the selection and puts focus back in the text it was in.
        if (event.key !== "Escape") return;
        const selection = window.getSelection();
        const paragraph = selection !== null && selection.rangeCount > 0 ? paragraphOf(selection.getRangeAt(0), turn[selected.first] ?? 0) : null;
        selection?.removeAllRanges();
        focusText(paragraph);
      }}
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
