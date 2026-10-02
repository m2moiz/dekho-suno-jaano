import { cleanup, render, screen } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, describe, expect, it } from "vitest";

import { browserName, capabilityError, FLOOR, missingFeatures } from "../../src/features/errors/capability";
import { CapabilityGate } from "../../src/features/errors/CapabilityGate";

const SAFARI_27 =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) " +
  "Version/27.0 Safari/605.1.15";

/** A browser with everything the reader needs, which each test then takes from. */
function browser() {
  return {
    Highlight: class {},
    CSS: { highlights: new Map() } as { highlights?: unknown },
    document: {
      caretPositionFromPoint: () => null,
      caretRangeFromPoint: () => null,
    } as { caretPositionFromPoint?: unknown; caretRangeFromPoint?: unknown },
    navigator: { userAgent: SAFARI_27 },
  };
}

afterEach(cleanup);

function renderGate(win: ReturnType<typeof browser>) {
  return render(
    createElement(CapabilityGate, { win, children: createElement("p", null, "the transcript") }),
  );
}

describe("the capability check", () => {
  it("passes a browser that has everything, and renders the app", () => {
    const win = browser();
    expect(missingFeatures(win)).toEqual([]);
    renderGate(win);
    expect(screen.getByText("the transcript")).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("with CSS.highlights deleted, shows the dialog and renders no transcript", () => {
    const win = browser();
    delete win.CSS.highlights;
    renderGate(win);
    expect(screen.queryByText("the transcript")).toBeNull();
    const dialog = screen.getByRole("dialog");
    expect(dialog.textContent).toContain("CSS Custom Highlight API");
    expect(dialog.textContent).toContain("Safari 17.2, Chrome 105 or Firefox 140");
    expect(dialog.textContent).toContain("Safari 27.0");
  });

  it("with Highlight itself missing, says the same", () => {
    const win: Partial<ReturnType<typeof browser>> = browser();
    delete win.Highlight;
    expect(missingFeatures(win as ReturnType<typeof browser>)).toHaveLength(1);
  });

  it("with only caretPositionFromPoint deleted, works normally and shows no dialog", () => {
    const win = browser();
    delete win.document.caretPositionFromPoint;
    expect(capabilityError(win)).toBeNull();
    renderGate(win);
    expect(screen.getByText("the transcript")).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("with only caretRangeFromPoint deleted, as in Firefox before 150, works normally", () => {
    const win = browser();
    delete win.document.caretRangeFromPoint;
    expect(capabilityError(win)).toBeNull();
  });

  it("with both caret spellings deleted, shows the dialog", () => {
    const win = browser();
    delete win.document.caretPositionFromPoint;
    delete win.document.caretRangeFromPoint;
    renderGate(win);
    expect(screen.queryByText("the transcript")).toBeNull();
    const dialog = screen.getByRole("dialog");
    expect(dialog.textContent).toContain("caretPositionFromPoint");
    expect(dialog.textContent).toContain(FLOOR);
  });

  it("names both when both are missing", () => {
    const win = browser();
    delete win.CSS.highlights;
    delete win.document.caretPositionFromPoint;
    delete win.document.caretRangeFromPoint;
    expect(capabilityError(win)?.message).toMatch(/Highlight API.*, and .*caretPositionFromPoint/);
  });

  it("checks jsdom itself, which lacks the highlight API, and refuses it", () => {
    // The real window this suite runs in: no Highlight, no caret APIs.
    expect(capabilityError(window)).not.toBeNull();
  });
});

describe("browserName", () => {
  it.each([
    [SAFARI_27, "Safari 27.0"],
    [
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) " +
        "Chrome/104.0.0.0 Safari/537.36",
      "Chrome 104.0",
    ],
    ["Mozilla/5.0 (Macintosh; Intel Mac OS X 15.0; rv:139.0) Gecko/20100101 Firefox/139.0", "Firefox 139.0"],
    [
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) " +
        "Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
      "Edge 120.0",
    ],
  ])("reads %s as %s", (userAgent, name) => {
    expect(browserName(userAgent)).toBe(name);
  });
});
