// The edit list's one way to change, and its undo (#66).
import { readFileSync } from "node:fs";
import path from "node:path";

import ts from "typescript";
import { describe, expect, it } from "vitest";

import { type Content, Editor, HISTORY_LIMIT, type Item, muteRange } from "../../src/lib/editOps";

const EDIT_OPS = path.resolve(import.meta.dirname, "../../src/lib/editOps.ts");

/** The type errors in editOps.ts once `change` has rewritten its text. */
function errorsWith(change: (source: string) => string): ts.Diagnostic[] {
  const options: ts.CompilerOptions = {
    target: ts.ScriptTarget.ES2023,
    module: ts.ModuleKind.ESNext,
    moduleResolution: ts.ModuleResolutionKind.Bundler,
    lib: ["lib.es2023.d.ts", "lib.dom.d.ts"],
    strict: true,
    noEmit: true,
    skipLibCheck: true,
    types: [],
  };
  const host = ts.createCompilerHost(options);
  const original = host.getSourceFile.bind(host);
  const text = change(readFileSync(EDIT_OPS, "utf8"));
  host.getSourceFile = (name, version, onError, create) =>
    path.resolve(name) === EDIT_OPS
      ? ts.createSourceFile(name, text, version)
      : original(name, version, onError, create);
  const program = ts.createProgram([EDIT_OPS], options, host);
  return [...program.getSyntacticDiagnostics(), ...program.getSemanticDiagnostics()];
}

/** `source` with `from` replaced by `to`, failing if `from` is not in it. */
function swap(source: string, from: string, to: string): string {
  expect(source).toContain(from);
  return source.replace(from, to);
}

const UNION = "export type EditOp =";
const REGISTRY = "const KINDS: Kinds = {";

describe("a kind of edit without its undo", () => {
  it("does not compile when it has no invert", () => {
    const errors = errorsWith((s) =>
      swap(
        swap(s, UNION, `${UNION} { kind: "probe" } |`),
        REGISTRY,
        `${REGISTRY}\n  probe: { apply: (content) => content, describe: () => "probe" },`,
      ),
    );
    const messages = errors.map((e) => ts.flattenDiagnosticMessageText(e.messageText, "\n"));
    expect(errors.map((e) => e.code)).toContain(2741);
    expect(messages.some((m) => m.includes("'invert' is missing"))).toBe(true);
  });

  it("does not compile when the union has it and the kinds do not", () => {
    const errors = errorsWith((s) => swap(s, UNION, `${UNION} { kind: "probe" } |`));
    const messages = errors.map((e) => ts.flattenDiagnosticMessageText(e.messageText, "\n"));
    expect(messages.some((m) => m.includes("'probe' is missing"))).toBe(true);
  });

  it("compiles when it has both, so the two failures above are the missing undo's", () => {
    const errors = errorsWith((s) =>
      swap(
        swap(s, UNION, `${UNION} { kind: "probe" } |`),
        REGISTRY,
        `${REGISTRY}\n  probe: { apply: (content) => content, invert: (_, op) => op, describe: () => "probe" },`,
      ),
    );
    expect(errors.map((e) => ts.flattenDiagnosticMessageText(e.messageText, "\n"))).toEqual([]);
  });
});

function item(sourceStart: number, text: string, muted = false): Item {
  return { kind: "item", source: "0", sourceStart, length: 0.3, text, muted, confidence: null };
}

/** A paragraph and four words, each followed by a pause. */
function words(): Content {
  return [
    { kind: "paragraph", speaker: null, language: null },
    item(0, " one"),
    item(0.3, ""),
    item(0.6, " two"),
    item(0.9, ""),
    item(1.2, " three"),
    item(1.5, ""),
    item(1.8, " four"),
  ];
}

function mutedTexts(content: Content): string[] {
  return content.filter((e) => e.kind === "item" && e.muted && e.text).map((e) => (e as Item).text);
}

describe("Editor", () => {
  it("mutes through applyEdit and undoes and redoes it, one step each", () => {
    const editor = new Editor(words());
    const before = editor.content;
    editor.applyEdit(muteRange(editor.content, 3, 6, true));
    expect(mutedTexts(editor.content)).toEqual([" two", " three"]);
    expect(editor.undoLabel()).toBe("mute");
    expect(editor.undo()).toBe(true);
    expect(editor.content).toEqual(before);
    expect(editor.undo()).toBe(false);
    expect(editor.redo()).toBe(true);
    expect(mutedTexts(editor.content)).toEqual([" two", " three"]);
  });

  it("never changes the list it was given", () => {
    const start = words();
    const editor = new Editor(start);
    editor.applyEdit(muteRange(start, 1, 2, true));
    expect(mutedTexts(start)).toEqual([]);
  });

  it("undoes an unmute back to exactly what was muted before", () => {
    const editor = new Editor(words());
    editor.applyEdit(muteRange(editor.content, 1, 2, true));
    editor.applyEdit(muteRange(editor.content, 1, 8, false));
    expect(mutedTexts(editor.content)).toEqual([]);
    editor.undo();
    expect(mutedTexts(editor.content)).toEqual([" one"]);
  });

  it("drops what was undone once a new edit is made", () => {
    const editor = new Editor(words());
    editor.applyEdit(muteRange(editor.content, 1, 2, true));
    editor.undo();
    editor.applyEdit(muteRange(editor.content, 3, 4, true));
    expect(editor.canRedo()).toBe(false);
  });

  it(`goes back ${HISTORY_LIMIT} steps, at least the 100 #66 asks for`, () => {
    expect(HISTORY_LIMIT).toBeGreaterThanOrEqual(100);
    const editor = new Editor(words());
    const before = editor.content;
    for (let i = 0; i < HISTORY_LIMIT; i += 1) {
      editor.applyEdit(muteRange(editor.content, 1, 2, i % 2 === 0));
    }
    let undone = 0;
    while (editor.undo()) undone += 1;
    expect(undone).toBe(HISTORY_LIMIT);
    expect(editor.content).toEqual(before);
  });

  it("forgets the oldest step past its limit, and says so by stopping there", () => {
    const editor = new Editor(words(), { limit: 3 });
    for (const at of [1, 3, 5, 7]) editor.applyEdit(muteRange(editor.content, at, at + 1, true));
    let undone = 0;
    while (editor.undo()) undone += 1;
    expect(undone).toBe(3);
    expect(mutedTexts(editor.content)).toEqual([" one"]);
  });

  it("makes a whole gesture one undo step", () => {
    const editor = new Editor(words());
    const before = editor.content;
    editor.beginGesture();
    for (let i = 0; i < 20; i += 1) editor.applyEdit(muteRange(editor.content, 1 + (i % 7), 2 + (i % 7), i % 3 !== 0));
    editor.endGesture();
    expect(editor.undo()).toBe(true);
    expect(editor.content).toEqual(before);
    expect(editor.canUndo()).toBe(false);
    expect(editor.redo()).toBe(true);
    expect(editor.canRedo()).toBe(false);
  });

  it("tells each listener of every change, and of nothing else", () => {
    const editor = new Editor(words());
    let heard = 0;
    const stop = editor.subscribe(() => {
      heard += 1;
    });
    editor.applyEdit(muteRange(editor.content, 1, 2, true));
    editor.undo();
    editor.undo();
    editor.redo();
    stop();
    editor.redo();
    expect(heard).toBe(3);
  });

  it("refuses an edit its check rejects, leaving the list and the history as they were", () => {
    const editor = new Editor(words(), {
      check: (content) => {
        if (mutedTexts(content).includes(" four")) throw new Error("four may not be muted");
      },
    });
    editor.applyEdit(muteRange(editor.content, 1, 2, true));
    const before = editor.content;
    expect(() => editor.applyEdit(muteRange(editor.content, 7, 8, true))).toThrow("four may not be muted");
    expect(editor.content).toBe(before);
    expect(editor.undo()).toBe(true);
    expect(mutedTexts(editor.content)).toEqual([]);
  });
});
