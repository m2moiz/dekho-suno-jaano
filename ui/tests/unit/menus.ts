import { act, fireEvent } from "@testing-library/react";

/**
 * Pick a Base UI menu or select item as a real click does. A click alone picks
 * nothing in jsdom: Base UI's items also want the pointerdown a real click
 * starts with (found for the Select in playback-rate.test.tsx, #81).
 */
export function choose(item: HTMLElement): void {
  act(() => {
    fireEvent.pointerDown(item, { pointerType: "mouse" });
    fireEvent.click(item);
  });
}
