// Review mode on a phone or tablet (Hashiya spec, "Phone and tablet,
// touch-first"), in jsdom against the same mocked server as the desk's tests:
// one sentence as a card, worked by its buttons, by swipes, and by the
// desk's keys when a keyboard is there (F14).
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fetchMock = vi.hoisted(() => {
  const mock = vi.fn<(request: Request) => Promise<Response>>();
  globalThis.fetch = mock as unknown as typeof fetch;
  return mock;
});

import { dismissError } from "../../src/features/errors/appError";
import { ReviewPage } from "../../src/features/review/ReviewPage";
import { SWIPE_PX } from "../../src/features/review/swipe";
import { stubMatchMedia } from "./media";
import { box, items, key, serveReview, server, start } from "./reviewServer";

// A phone: a coarse pointer, so (pointer: fine) does not match.
const PHONE = (query: string) => query.includes("coarse");
// A Mac window dragged narrower than 768 px: the card, with a mouse and a keyboard.
const NARROW = (query: string) => query.includes("max-width") || query.includes("fine");

beforeEach(() => serveReview(fetchMock, PHONE));

afterEach(() => {
  cleanup();
  act(() => dismissError());
});

const card = () => screen.findByRole("article", { name: "Sentence being checked" });
const checkedNext = () => screen.getByRole("button", { name: "Checked, next" });

/** A drag across the card from (x, y) by (dx, dy), as a finger makes it, or as `pointerType` does. */
function drag(target: Element, dx: number, dy = 0, x = 300, y = 200, pointerType = "touch"): void {
  fireEvent.pointerDown(target, { clientX: x, clientY: y, pointerId: 1, pointerType });
  fireEvent.pointerUp(target, { clientX: x + dx, clientY: y + dy, pointerId: 1, pointerType });
}

describe("Review mode on a phone", () => {
  it("shows one sentence as a card with thumb-sized actions, and Checked, next goes on", async () => {
    await start();
    await card();
    expect((await box()).value).toBe("alpha bravo charlie");
    // One sentence: the desk's context sentences around it are not drawn.
    expect(screen.queryByText("delta echo")).toBeNull();
    // The keyboard does not pop up by itself on a touch screen.
    expect(document.activeElement).not.toBe(await box());
    const next = checkedNext();
    expect(next.className).toContain("h-12");
    fireEvent.click(next);
    expect((await box()).value).toBe("delta echo");
    expect(screen.getByText("1 of 3 checked")).toBeTruthy();
    await vi.waitFor(() => expect(server.reviews.at(-1)?.segments[0]?.state).toBe("checked"), { timeout: 2000 });
  });

  it("reassigns a sentence with a speaker chip, and the chip in use is pressed", async () => {
    await start();
    expect(screen.getByRole("button", { name: "Speaker 1" }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Speaker 2" }));
    await vi.waitFor(() => expect(server.edits).toHaveLength(1));
    expect(server.edits[0]?.[0]).toEqual({ kind: "paragraph", speaker: "SPEAKER_01", language: null });
    expect(screen.getByRole("button", { name: "Speaker 2" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("goes back with Back", async () => {
    await start();
    fireEvent.click(checkedNext());
    fireEvent.click(await screen.findByRole("button", { name: "Back" }));
    expect((await box()).value).toBe("alpha bravo charlie");
  });

  it("puts the words typed in the card into the edit list before Checked, next and before Back (no lost edits)", async () => {
    const field = await start();
    fireEvent.change(field, { target: { value: "alpha bravo charles" } });
    fireEvent.click(checkedNext());
    await vi.waitFor(() => expect(server.edits).toHaveLength(1));
    expect(items(server.edits[0]).map((e) => e.text)).toContain(" charles");
    fireEvent.change(await box(), { target: { value: "delta echo golf" } });
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect((await box()).value).toBe("alpha bravo charles");
    await vi.waitFor(() => expect(server.edits).toHaveLength(2));
    expect(items(server.edits[1]).map((e) => e.text)).toContain(" golf");
  });

  it("swipe left is Checked, next; swipe right is Back; a short or steep drag, or one in the text box, is neither", async () => {
    await start();
    const article = await card();
    drag(article, -SWIPE_PX - 20);
    expect((await box()).value).toBe("delta echo");
    drag(article, -40);
    drag(article, -120, 90);
    drag(await box(), -200);
    expect((await box()).value).toBe("delta echo");
    expect(screen.getByText("1 of 3 checked")).toBeTruthy();
    drag(article, SWIPE_PX + 20);
    expect((await box()).value).toBe("alpha bravo charlie");
  });

  it("a mouse drag across the card selects words and checks nothing (Task 14 review, I1)", async () => {
    await start();
    const article = await card();
    // Right to left over the second opinion or the margin line, as a mouse selecting words would.
    drag(article, -200, 0, 300, 200, "mouse");
    expect((await box()).value).toBe("alpha bravo charlie");
    expect(screen.getByText("0 of 3 checked")).toBeTruthy();
    // A second finger down mid-swipe is a pinch, not a swipe.
    fireEvent.pointerDown(article, { clientX: 300, clientY: 200, pointerId: 1, pointerType: "touch" });
    fireEvent.pointerDown(article, { clientX: 320, clientY: 260, pointerId: 2, pointerType: "touch" });
    fireEvent.pointerUp(article, { clientX: 100, clientY: 260, pointerId: 2, pointerType: "touch" });
    fireEvent.pointerUp(article, { clientX: 100, clientY: 200, pointerId: 1, pointerType: "touch" });
    expect((await box()).value).toBe("alpha bravo charlie");
    expect(screen.getByText("0 of 3 checked")).toBeTruthy();
  });

  it("flags the sentence from the flag button's menu, and shows the flag on the card", async () => {
    await start();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Flag" }));
    });
    fireEvent.click(await screen.findByRole("menuitemcheckbox", { name: "Overlapping talk" }));
    await vi.waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
    const article = await card();
    expect(article.textContent).toContain("Overlapping talk");
  });

  it("switches the pass from the bar, keeping the typed words", async () => {
    server.withOther = true;
    const field = await start();
    const likely = await screen.findByRole("button", { name: /Likely \(1\)/ });
    fireEvent.change(field, { target: { value: "alpha bravo charles" } });
    fireEvent.click(likely);
    expect((await box()).value).toBe("foxtrot");
    await vi.waitFor(() => expect(server.edits).toHaveLength(1));
    expect(items(server.edits[0]).map((e) => e.text)).toContain(" charles");
  });

  it("leaves by the bar's back arrow only once the typed words are saved (F27)", async () => {
    const went: string[] = [];
    const field = await start((href) => went.push(href));
    fireEvent.change(field, { target: { value: "alpha bravo charles" } });
    fireEvent.click(screen.getByRole("link", { name: "Back to the transcript" }));
    await vi.waitFor(() => expect(went).toEqual(["/?recording=2&transcript=7"]));
    expect(items(server.edits.at(-1)).map((e) => e.text)).toContain(" charles");
  });

  it("finishes the pass on the card and saves the answer key from the saved review", async () => {
    await start();
    for (let i = 0; i < 3; i += 1) {
      await card();
      fireEvent.click(checkedNext());
    }
    expect(await screen.findByRole("heading", { name: "This pass is done" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Save as answer key" }));
    expect(await screen.findByText(/Saved a.reference.json and a.reference.txt beside the transcript/)).toBeTruthy();
    expect(server.reviews.at(-1)?.segments.map((s) => s.state)).toEqual(["checked", "checked", "checked"]);
  });
});

describe("Review's keys on the card, when a keyboard is there (F14)", () => {
  it("in a narrow window the card holds the focus in its box, and the desk's keys work", async () => {
    stubMatchMedia(NARROW);
    const went: string[] = [];
    render(<ReviewPage recording={2} transcript={7} navigate={(href) => went.push(href)} />);
    fireEvent.click(await screen.findByRole("button", { name: /^Every sentence/ }));
    await card();
    const field = await box();
    expect(document.activeElement).toBe(field);
    key(field, { key: "Enter", code: "Enter" });
    expect((await box()).value).toBe("delta echo");
    expect(document.activeElement).toBe(await box());
    key(await box(), { key: "1", code: "Digit1", ctrlKey: true });
    await vi.waitFor(() => expect(server.edits).toHaveLength(1));
    expect(screen.getByText("Said by Speaker 1")).toBeTruthy();
    key(await box(), { key: "Enter", code: "Enter", shiftKey: true });
    expect((await box()).value).toBe("alpha bravo charlie");
    key(await box(), { key: "f", code: "KeyF", ctrlKey: true });
    expect(await screen.findByRole("menu")).toBeTruthy();
    key(await box(), { key: "Escape", code: "Escape" });
    await vi.waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
    expect(went).toEqual([]);
    key(await box(), { key: "Escape", code: "Escape" });
    await vi.waitFor(() => expect(went).toEqual(["/?recording=2&transcript=7"]));
  });

  it("on a tablet with a keyboard, once the box is tapped, Enter checks and Ctrl+S splits", async () => {
    const field = await start();
    await card();
    act(() => field.focus());
    key(field, { key: "Enter", code: "Enter" });
    expect((await box()).value).toBe("delta echo");
    const next = await box();
    next.setSelectionRange(6, 6);
    key(next, { key: "s", code: "KeyS", ctrlKey: true });
    expect((await box()).value).toBe("delta");
    expect(screen.getByText("1 of 4 checked")).toBeTruthy();
  });
});
