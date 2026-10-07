// Swipe left: checked and next; swipe right: back (Hashiya spec, "Phone and
// tablet, touch-first").
//
// A swipe is a mostly sideways drag of at least SWIPE_PX. 80 px is about a
// fifth of a 390 px phone's width: past any wobble of a tap, short of a
// thumb's full reach. A drag steeper than 0.6 (about 31 degrees) is a scroll.
// Both are choices, not measurements. A drag that starts in the text box or
// on a button is theirs: selecting words, or pressing.

import { type PointerEvent, useRef } from "react";

export const SWIPE_PX = 80;
const STEEPEST = 0.6;

export function swipeOf(dx: number, dy: number): "left" | "right" | null {
  if (Math.abs(dx) < SWIPE_PX || Math.abs(dy) > Math.abs(dx) * STEEPEST) return null;
  return dx < 0 ? "left" : "right";
}

export function useSwipe(onSwipe: (way: "left" | "right") => void) {
  const from = useRef<{ x: number; y: number } | null>(null);
  return {
    onPointerDown: (event: PointerEvent<HTMLElement>) => {
      const target = event.target as Element;
      from.current = target.closest("textarea, button, a, [role=menu]") ? null : { x: event.clientX, y: event.clientY };
    },
    onPointerUp: (event: PointerEvent<HTMLElement>) => {
      const start = from.current;
      from.current = null;
      if (start === null) return;
      const way = swipeOf(event.clientX - start.x, event.clientY - start.y);
      if (way !== null) onSwipe(way);
    },
    onPointerCancel: () => {
      from.current = null;
    },
  };
}
