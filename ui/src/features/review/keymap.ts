// Review's keys, exactly the spec's table (Hashiya spec, Review mode). They
// keep clear of the Mac's text-field keys (Ctrl+A, E, K, B: emacs moves inside
// a text box), the browser's Cmd keys, and Ctrl+Space, which switches input
// sources and which an Urdu typist uses. Ctrl+F is the one text-field key
// taken: the flag menu matters more than a one-character move inside a short
// sentence, and the key sheet says so (keys.ts, REVIEW_SHEET).
//
// Ctrl keys go by `event.code`, the key's place on the keyboard, not by
// `event.key`, the letter it types: with the Urdu input source the G key types
// گ and the digit row Urdu digits, and every action must still be in reach.
// A key pressed while an input method is composing is the input method's,
// and so is the Enter that ends a composition, which WebKit reports with
// isComposing false and keyCode 229 (Task 13 review, Minor 4).
// Option (Alt) is left to the browser too: Option+Tab moves focus out of the
// box to the bar's controls, the pass switch among them, while Tab plays.

import type { Flag } from "./model";

export type Action =
  | { kind: "check" }
  | { kind: "previous" }
  | { kind: "toggle" }
  | { kind: "replay" }
  | { kind: "slower" }
  | { kind: "faster" }
  | { kind: "speaker"; n: number }
  | { kind: "second" }
  | { kind: "unclear" }
  | { kind: "flags" }
  | { kind: "flag"; flag: Flag }
  | { kind: "split" }
  | { kind: "merge" }
  | { kind: "nextLikely" }
  | { kind: "previousLikely" }
  | { kind: "keys" }
  | { kind: "leave" };

type Press = Pick<KeyboardEvent, "key" | "code" | "ctrlKey" | "shiftKey" | "metaKey" | "altKey" | "isComposing" | "keyCode">;

export function actionFor(event: Press): Action | null {
  if (event.isComposing || event.keyCode === 229 || event.metaKey || event.altKey) return null;
  if (!event.ctrlKey) {
    if (event.key === "Enter") return { kind: event.shiftKey ? "previous" : "check" };
    if (event.key === "Tab") return { kind: event.shiftKey ? "replay" : "toggle" };
    if (event.key === "Escape") return { kind: "leave" };
    return null;
  }
  const digit = /^Digit([1-9])$/.exec(event.code);
  if (digit !== null) return { kind: "speaker", n: Number(digit[1]) };
  switch (event.code) {
    case "Comma":
      return { kind: "slower" };
    case "Period":
      return { kind: "faster" };
    case "KeyG":
      return { kind: "second" };
    case "KeyU":
      return { kind: "unclear" };
    case "KeyF":
      return { kind: "flags" };
    case "KeyS":
      return { kind: "split" };
    case "KeyM":
      return { kind: "merge" };
    case "KeyJ":
      return { kind: event.shiftKey ? "previousLikely" : "nextLikely" };
    case "Slash":
      return { kind: "keys" };
    default:
      return null;
  }
}
