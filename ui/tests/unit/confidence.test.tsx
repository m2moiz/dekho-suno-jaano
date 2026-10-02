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
import { UnsureToggle } from "../../src/features/transcript/UnsureToggle";
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

describe("UnsureToggle", () => {
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
        <UnsureToggle reading={reading} model={model} article={article} />
        <TranscriptView reading={reading} articleRef={article} />
      </>,
    );
  }

  const SHAKY = [sentence(0, [[" one", 0.95], [" two", 0.2], [" three", 0.3]])];

  it("is off until switched on, then paints every unsure word, and clears when switched off", () => {
    mount(WHISPER, SHAKY);
    const toggle = screen.getByRole("button", { name: "Unsure words (2)" });
    expect(toggle.getAttribute("aria-pressed")).toBe("false");
    expect(registry.has(UNSURE)).toBe(false);
    act(() => fireEvent.click(toggle));
    expect(painted(registry, UNSURE)).toEqual(["two", "three"]);
    act(() => fireEvent.click(toggle));
    expect(registry.has(UNSURE)).toBe(false);
  });

  it("is not offered for a transcript with no confidence, or from an engine it has no cut-off for", () => {
    mount(WHISPER, [sentence(0, [[" no"], [" scores"]])]);
    expect(screen.queryByRole("button")).toBeNull();
    cleanup();
    mount("import:vtt", SHAKY);
    expect(screen.queryByRole("button")).toBeNull();
  });
});

// WCAG 2 contrast from the oklch() values in the stylesheets, so a colour
// changed there is checked here. oklch -> OKLab -> linear sRGB per Björn
// Ottosson's published matrices, then relative luminance.
function luminance(l: number, c: number, h: number): number {
  const a = c * Math.cos((h * Math.PI) / 180);
  const b = c * Math.sin((h * Math.PI) / 180);
  const l_ = (l + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m_ = (l - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s_ = (l - 0.0894841775 * a - 1.291485548 * b) ** 3;
  const clamp = (x: number) => Math.min(1, Math.max(0, x));
  const r = clamp(4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_);
  const g = clamp(-1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_);
  const bl = clamp(-0.0041960863 * l_ - 0.7034186147 * m_ + 1.707614701 * s_);
  return 0.2126 * r + 0.7152 * g + 0.0722 * bl;
}

function contrast(x: number[], y: number[]): number {
  const [hi, lo] = [luminance(x[0] ?? 0, x[1] ?? 0, x[2] ?? 0), luminance(y[0] ?? 0, y[1] ?? 0, y[2] ?? 0)].sort((p, q) => q - p);
  return ((hi ?? 0) + 0.05) / ((lo ?? 0) + 0.05);
}

/** The light and dark oklch() inside `light-dark(...)` on the line declaring `property` after `selector`. */
function pair(css: string, selector: string, property: string): [number[], number[]] {
  const block = css.slice(css.indexOf(selector));
  const line = new RegExp(`${property}:\\s*light-dark\\(([^;]+)\\);`).exec(block)?.[1] ?? "";
  const colours = Array.from(line.matchAll(/oklch\(([\d.]+) ([\d.]+) ([\d.]+)/g), (m) => [Number(m[1]), Number(m[2]), Number(m[3])]);
  if (colours.length !== 2) throw new Error(`no light-dark oklch pair for ${property} in ${selector}`);
  return [colours[0] ?? [], colours[1] ?? []];
}

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
