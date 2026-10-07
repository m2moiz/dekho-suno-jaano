// The Hashiya palette (spec, "The world") held to WCAG AA in both schemes:
// 4.5:1 for text, 3:1 for a focus ring, a field's edge and the waveform. The
// spec's hexes were starting points; the tokens in theme.css are what passed.
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { contrast, pair, token } from "./contrast";

const theme = readFileSync(path.resolve(import.meta.dirname, "../../src/styles/theme.css"), "utf8");
const transcriptCss = readFileSync(
  path.resolve(import.meta.dirname, "../../src/features/transcript/transcript.css"),
  "utf8",
);
const SRC = path.resolve(import.meta.dirname, "../../src");
const SCHEMES = ["light", "dark"] as const;
// Every surface body text or gold-ink text can sit on, in either scheme.
const SURFACES = ["--background", "--card", "--popover", "--secondary", "--muted", "--accent"];
const SPEAKERS = [1, 2, 3, 4, 5, 6].map((n) => `--speaker-${n}`);

function measured(fg: string, bg: string, scheme: "light" | "dark"): number {
  return contrast(token(theme, fg, scheme), token(theme, bg, scheme));
}

describe("the Hashiya palette", () => {
  it.each(["--foreground", "--muted-foreground", "--dim", "--gold-ink", "--correction", "--checked", ...SPEAKERS])(
    "%s reads at 4.5:1 or more on the reading ground, light and dark",
    (name) => {
      for (const scheme of SCHEMES) expect(measured(name, "--background", scheme)).toBeGreaterThanOrEqual(4.5);
    },
  );

  it.each(["--foreground", "--muted-foreground", "--correction", "--gold-ink", ...SPEAKERS])(
    "%s reads at 4.5:1 or more on a card",
    (name) => {
      for (const scheme of SCHEMES) expect(measured(name, "--card", scheme)).toBeGreaterThanOrEqual(4.5);
    },
  );

  it.each(SURFACES)("--gold-ink reads at 4.5:1 or more on %s, light and dark", (surface) => {
    for (const scheme of SCHEMES) expect(measured("--gold-ink", surface, scheme)).toBeGreaterThanOrEqual(4.5);
  });

  it("plain gold fails as text on the pale ground, so text-gold stays on the blue field", () => {
    // The reason --gold-ink exists. If this ever passes, the rule below is moot.
    expect(measured("--gold", "--background", "light")).toBeLessThan(4.5);
    const offenders: string[] = [];
    const walk = (dir: string): void => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const file = path.join(dir, entry.name);
        if (entry.isDirectory()) walk(file);
        else if (/\.tsx?$/.test(entry.name)) {
          const text = readFileSync(file, "utf8");
          // `text-gold` alone, not `text-gold-ink`; a file that uses it also names the field.
          if (/(?<![\w-])text-gold(?![\w-])/.test(text) && !text.includes("bg-field")) offenders.push(file);
        }
      }
    };
    walk(SRC);
    expect(offenders).toEqual([]);
  });

  it("the playhead highlight's literals are --playhead, light and dark", () => {
    const [light, dark] = pair(transcriptCss, "::highlight(dsj-playhead)", "background-color");
    expect(light).toBe(token(theme, "--playhead", "light"));
    expect(dark).toBe(token(theme, "--playhead", "dark"));
  });

  it("shell text and gold read at 4.5:1 or more on the blue field", () => {
    for (const name of ["--field-foreground", "--field-muted", "--gold"]) {
      expect(measured(name, "--field", "light")).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("the primary action's ink reads at 4.5:1 or more on gold", () => {
    expect(measured("--primary-foreground", "--primary", "light")).toBeGreaterThanOrEqual(4.5);
  });

  it("the focus ring and a field's edge stand at 3:1 or more against the ground", () => {
    for (const scheme of SCHEMES) {
      expect(measured("--ring", "--background", scheme)).toBeGreaterThanOrEqual(3);
      expect(measured("--input", "--background", scheme)).toBeGreaterThanOrEqual(3);
    }
    expect(measured("--field-wave", "--field", "light")).toBeGreaterThanOrEqual(3);
  });

  it("keeps the ground cool, never cream: more blue than red in the light ground", () => {
    const ground = token(theme, "--background", "light");
    const red = parseInt(ground.slice(1, 3), 16);
    const blue = parseInt(ground.slice(5, 7), 16);
    expect(blue).toBeGreaterThan(red);
  });
});
