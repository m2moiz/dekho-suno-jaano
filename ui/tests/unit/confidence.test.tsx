import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import path from "node:path";
import { createRef } from "react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  CUTOFFS,
  cutoffFor,
  UNSURE,
  unsureHighlight,
  unsureWords,
} from "../../src/features/transcript/confidence";
import { read, type Sentence, type TranscriptDoc } from "../../src/features/transcript/document";
import { TranscriptView } from "../../src/features/transcript/TranscriptView";
import { UnsureNav } from "../../src/features/transcript/UnsureNav";
import { contrast, pair } from "./contrast";
import { type FakeHighlight, installHighlights, painted } from "./highlights";

type Piece = [w: string, c?: number];

function sentence(start: number, pieces: Piece[]): Sentence {
  const tokens = pieces.map(([w, c], i) => ({ t: start + i * 0.3, w, ...(c === undefined ? {} : { c }) }));
  return { start, end: start + pieces.length * 0.3, text: tokens.map((t) => t.w).join(""), tokens };
}

function doc(model: string, sentences: Sentence[]): TranscriptDoc {
  return { audio: "a.wav", model, sentences };
}

const WHISPER = "mlx-community/whisper-large-v3-turbo";

describe("cutoffFor", () => {
  it.each([
    [WHISPER, CUTOFFS.whisper],
    ["mlx-community/parakeet-tdt-0.6b-v3", CUTOFFS.parakeet],
    ["sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8", CUTOFFS.sherpa],
    ["import:srt", null],
    ["synthetic", null],
  ])("%s -> %s", (model, cutoff) => {
    expect(cutoffFor(model)).toBe(cutoff);
  });
});

describe("a word's confidence", () => {
  it("is its least sure token's, and NaN where the file has none", () => {
    const reading = read(doc(WHISPER, [sentence(0, [[" col", 0.9], ["umn", 0.2], [" here", 0.99], [" now"]])]));
    expect(Array.from(reading.words.confidence)).toEqual([
      expect.closeTo(0.2, 5),
      expect.closeTo(0.99, 5),
      Number.NaN,
    ]);
    expect(unsureWords(reading, 0.5)).toEqual([0]);
  });

  it("paints each unsure word without the space in front of it", () => {
    installHighlights();
    const reading = read(doc(WHISPER, [sentence(0, [[" sure", 0.99], [" shaky", 0.1], [" fine", 0.8], [" odd", 0.4]])]));
    document.body.innerHTML = `<p data-turn="0">${reading.turns[0]?.text}</p>`;
    const text = document.querySelector("p")?.firstChild as Text;
    const highlight = unsureHighlight(reading, unsureWords(reading, 0.5), [text]) as unknown as FakeHighlight;
    expect(Array.from(highlight, (r) => r.toString())).toEqual(["shaky", "odd"]);
  });
});

describe("UnsureNav", () => {
  let registry: Map<string, FakeHighlight>;
  beforeEach(() => {
    registry = installHighlights();
  });
  afterEach(() => {
    cleanup();
  });

  function mount(model: string, sentences: Sentence[]) {
    const reading = read(doc(model, sentences));
    const article = createRef<HTMLElement>();
    render(
      <>
        <UnsureNav reading={reading} model={model} article={article} />
        <TranscriptView reading={reading} articleRef={article} />
      </>,
    );
  }

  const SHAKY = [sentence(0, [[" one", 0.95], [" two", 0.2], [" three", 0.25]])];

  it("is off until switched on, then paints every unsure word, and clears when switched off", () => {
    mount(WHISPER, SHAKY);
    const toggle = screen.getByRole("button", { name: "2 unsure" });
    expect(toggle.getAttribute("aria-pressed")).toBe("false");
    expect(registry.has(UNSURE)).toBe(false);
    act(() => fireEvent.click(toggle));
    expect(painted(registry, UNSURE)).toEqual(["two", "three"]);
    act(() => fireEvent.click(toggle));
    expect(registry.has(UNSURE)).toBe(false);
  });

  it("selects the next unsure word with its arrow, and the previous one, wrapping round, switching the tint on", () => {
    mount(WHISPER, SHAKY);
    const next = screen.getByRole("button", { name: "Next unsure word" });
    act(() => fireEvent.click(next));
    expect(window.getSelection()?.toString()).toBe("two");
    expect(screen.getByRole("button", { name: "2 unsure" }).getAttribute("aria-pressed")).toBe("true");
    expect(painted(registry, UNSURE)).toEqual(["two", "three"]);
    act(() => fireEvent.click(next));
    expect(window.getSelection()?.toString()).toBe("three");
    act(() => fireEvent.click(next));
    expect(window.getSelection()?.toString()).toBe("two");
    act(() => fireEvent.click(screen.getByRole("button", { name: "Previous unsure word" })));
    expect(window.getSelection()?.toString()).toBe("three");
  });

  it("answers ] and [ from the page, but not from inside a text field", () => {
    mount(WHISPER, SHAKY);
    act(() => fireEvent.keyDown(document.body, { key: "]", code: "BracketRight" }));
    expect(window.getSelection()?.toString()).toBe("two");
    act(() => fireEvent.keyDown(document.body, { key: "[", code: "BracketLeft" }));
    expect(window.getSelection()?.toString()).toBe("three");
    const field = document.createElement("input");
    document.body.append(field);
    act(() => fireEvent.keyDown(field, { key: "]", code: "BracketRight" }));
    expect(window.getSelection()?.toString()).toBe("three");
    field.remove();
  });

  it("goes on from where it was after an edit renumbers the words: skip one, fix the next, ] goes to the one after", () => {
    const shaky = (third: number) => [sentence(0, [[" one", 0.95], [" two", 0.2], [" three", third], [" four", 0.1]])];
    const first = read(doc(WHISPER, shaky(0.25)));
    const article = createRef<HTMLElement>();
    const view = (reading: typeof first) => (
      <>
        <UnsureNav reading={reading} model={WHISPER} article={article} />
        <TranscriptView reading={reading} articleRef={article} />
      </>
    );
    const { rerender } = render(view(first));
    const next = () => act(() => fireEvent.keyDown(document.body, { key: "]", code: "BracketRight" }));
    next();
    expect(window.getSelection()?.toString()).toBe("two");
    next();
    expect(window.getSelection()?.toString()).toBe("three");
    // "three" corrected: sure now, and a new reading of the words.
    rerender(view(read(doc(WHISPER, shaky(1)))));
    next();
    expect(window.getSelection()?.toString()).toBe("four");
  });

  it("answers ] and [ with a button focused, the arrows' own included", () => {
    mount(WHISPER, SHAKY);
    const next = screen.getByRole("button", { name: "Next unsure word" });
    next.focus();
    act(() => fireEvent.keyDown(next, { key: "]", code: "BracketRight" }));
    expect(window.getSelection()?.toString()).toBe("two");
    act(() => fireEvent.keyDown(next, { key: "[", code: "BracketLeft" }));
    expect(window.getSelection()?.toString()).toBe("three");
  });

  it("is not offered for a transcript with no confidence, or from an engine it has no cut-off for", () => {
    mount(WHISPER, [sentence(0, [[" no"], [" scores"]])]);
    expect(screen.queryByRole("button")).toBeNull();
    cleanup();
    mount("import:vtt", SHAKY);
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("tinted text stays readable", () => {
  const ui = path.resolve(import.meta.dirname, "../../src");
  const transcript = readFileSync(path.join(ui, "features/transcript/transcript.css"), "utf8");
  const theme = readFileSync(path.join(ui, "styles/theme.css"), "utf8");
  const [textLight, textDark] = pair(theme, ":root", "--foreground");

  it.each(["::highlight(dsj-unsure)", "::highlight(dsj-playhead)"])(
    "%s keeps body text at 4.5:1 or more in light and in dark",
    (selector) => {
      const [tintLight, tintDark] = pair(transcript, selector, "background-color");
      expect(contrast(textLight, tintLight)).toBeGreaterThanOrEqual(4.5);
      expect(contrast(textDark, tintDark)).toBeGreaterThanOrEqual(4.5);
    },
  );
});
