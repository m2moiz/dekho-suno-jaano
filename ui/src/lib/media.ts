// Whether a CSS media query matches, as React state that follows it live: the
// phone layouts (Hashiya spec, "Laptop and phone") read `(pointer: coarse)`
// and widths through this, so a window dragged narrower changes layout at once.

import { useSyncExternalStore } from "react";

function supported(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function";
}

export function useMediaQuery(query: string): boolean {
  return useSyncExternalStore(
    (changed) => {
      if (!supported()) return () => undefined;
      const list = window.matchMedia(query);
      list.addEventListener("change", changed);
      return () => list.removeEventListener("change", changed);
    },
    () => supported() && window.matchMedia(query).matches,
  );
}

/** A touch screen, or a window as narrow as a phone: where the touch layouts take over. */
export const TOUCH = "(pointer: coarse), (max-width: 767px)";
