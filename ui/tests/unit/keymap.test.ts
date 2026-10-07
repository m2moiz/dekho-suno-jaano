// Review's keys, exactly the spec's table (Hashiya spec, Review mode).
import { describe, expect, it } from "vitest";

import { actionFor } from "../../src/features/review/keymap";

type Press = { key: string; code: string; ctrlKey?: boolean; shiftKey?: boolean; metaKey?: boolean; altKey?: boolean; isComposing?: boolean };
const press = (p: Press) => actionFor({ ctrlKey: false, shiftKey: false, metaKey: false, altKey: false, isComposing: false, ...p });

describe("the review keys", () => {
  it.each([
    [{ key: "Enter", code: "Enter" }, { kind: "check" }],
    [{ key: "Enter", code: "Enter", shiftKey: true }, { kind: "previous" }],
    [{ key: "Tab", code: "Tab" }, { kind: "toggle" }],
    [{ key: "Tab", code: "Tab", shiftKey: true }, { kind: "replay" }],
    [{ key: ",", code: "Comma", ctrlKey: true }, { kind: "slower" }],
    [{ key: ".", code: "Period", ctrlKey: true }, { kind: "faster" }],
    [{ key: "1", code: "Digit1", ctrlKey: true }, { kind: "speaker", n: 1 }],
    [{ key: "9", code: "Digit9", ctrlKey: true }, { kind: "speaker", n: 9 }],
    [{ key: "g", code: "KeyG", ctrlKey: true }, { kind: "second" }],
    [{ key: "u", code: "KeyU", ctrlKey: true }, { kind: "unclear" }],
    [{ key: "f", code: "KeyF", ctrlKey: true }, { kind: "flags" }],
    [{ key: "s", code: "KeyS", ctrlKey: true }, { kind: "split" }],
    [{ key: "m", code: "KeyM", ctrlKey: true }, { kind: "merge" }],
    [{ key: "j", code: "KeyJ", ctrlKey: true }, { kind: "nextLikely" }],
    [{ key: "J", code: "KeyJ", ctrlKey: true, shiftKey: true }, { kind: "previousLikely" }],
    [{ key: "/", code: "Slash", ctrlKey: true }, { kind: "keys" }],
    [{ key: "Escape", code: "Escape" }, { kind: "leave" }],
  ] as [Press, object][])("%o is %o", (p, action) => {
    expect(press(p)).toEqual(action);
  });

  it("works by the key's place, so the Urdu input source reaches every action", () => {
    // With the Urdu input source the G key types گ and the digit row types Urdu digits.
    expect(press({ key: "گ", code: "KeyG", ctrlKey: true })).toEqual({ kind: "second" });
    expect(press({ key: "۲", code: "Digit2", ctrlKey: true })).toEqual({ kind: "speaker", n: 2 });
  });

  it("leaves the browser's Cmd keys, Ctrl+0, Ctrl+Space, plain typing and an open composition alone", () => {
    expect(press({ key: "s", code: "KeyS", metaKey: true })).toBeNull();
    expect(press({ key: "0", code: "Digit0", ctrlKey: true })).toBeNull();
    expect(press({ key: " ", code: "Space", ctrlKey: true })).toBeNull();
    expect(press({ key: "a", code: "KeyA" })).toBeNull();
    expect(press({ key: "a", code: "KeyA", ctrlKey: true })).toBeNull();
    expect(press({ key: "Enter", code: "Enter", isComposing: true })).toBeNull();
  });

  it("leaves Option+Tab to the browser, which moves focus out of the box to the bar's controls", () => {
    expect(press({ key: "Tab", code: "Tab", altKey: true })).toBeNull();
    expect(press({ key: "Tab", code: "Tab", altKey: true, shiftKey: true })).toBeNull();
  });
});
