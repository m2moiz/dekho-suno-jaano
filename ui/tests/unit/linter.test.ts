// The edit list's check after every edit (#86).
import { describe, expect, it } from "vitest";

import { type Content, Editor, type Entry, type Item, muteRange } from "../../src/lib/editOps";
import { devCheck, InvalidContent, lint } from "../../src/lib/linter";

const SOURCES = new Set(["0"]);

function item(sourceStart: number, length: number, text: string, extra: Partial<Item> = {}): Item {
  return { kind: "item", source: "0", sourceStart, length, text, muted: false, confidence: null, ...extra };
}

const PARAGRAPH: Entry = { kind: "paragraph", speaker: null, language: "ur" };
const GOOD: Content = [PARAGRAPH, item(0, 0.2, ""), item(0.2, 0.3, " one"), item(0.5, 0.1, ""), item(0.6, 0.3, " two")];

function broken(index: number, change: Partial<Item>): Content {
  return GOOD.map((e, i) => (i === index && e.kind === "item" ? { ...e, ...change } : e));
}

describe("lint", () => {
  it("passes a list that plays its recording in order", () => {
    expect(() => lint(GOOD, SOURCES)).not.toThrow();
  });

  it.each([
    ["a negative length", broken(2, { length: -0.1 }), /entry 2 .*length is -0.1/],
    ["a start that is not a number", broken(2, { sourceStart: Number.NaN }), /entry 2 .*start is NaN/],
    ["a source the server never gave", broken(4, { source: "/etc/passwd" }), /entry 4 .*no such source/],
    ["a muted that is not true or false", broken(2, { muted: "yes" as unknown as boolean }), /entry 2 .*muted is "yes"/],
    ["a hole in the recording", broken(4, { sourceStart: 0.7 }), /entry 4 .*does not follow/],
    ["a word moved back in time", broken(4, { sourceStart: 0.1 }), /entry 4 .*does not follow/],
  ])("refuses %s, naming the entry", (_, content, message) => {
    expect(() => lint(content, SOURCES)).toThrow(InvalidContent);
    expect(() => lint(content, SOURCES)).toThrow(message);
  });

  it("refuses a list that opens with an item, and a language that is not a tag", () => {
    expect(() => lint(GOOD.slice(1), SOURCES)).toThrow(/entry 0 .*must open with a paragraph/);
    const named = [{ ...PARAGRAPH, language: "Urdu language" }, ...GOOD.slice(1)];
    expect(() => lint(named, SOURCES)).toThrow(/entry 0 .*not a language tag/);
  });

  it("lets two words overlap, as whisper's inferred ends do", () => {
    const overlapping = broken(2, { length: 0.5 });
    expect(() => lint(overlapping, SOURCES)).not.toThrow();
  });
});

describe("an Editor with the development check", () => {
  it("runs it in this build, which vitest makes a development one", () => {
    expect(devCheck(GOOD)).toBeTypeOf("function");
  });

  it("raises at the applyEdit that broke the list, and keeps the list as it was", () => {
    const editor = new Editor(GOOD, { check: devCheck(GOOD) });
    editor.applyEdit(muteRange(editor.content, 2, 3, true));
    const before = editor.content;
    // A caller with a bug: an edit that sets `muted` to something that is not one.
    const bad = { kind: "mute" as const, entries: [4], muted: ["yes" as unknown as boolean] };
    expect(() => editor.applyEdit(bad)).toThrow(/entry 4 .*muted is "yes"/);
    expect(editor.content).toBe(before);
    expect(editor.undoLabel()).toBe("mute");
  });
});
