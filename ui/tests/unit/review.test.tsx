// Review mode by keyboard, in jsdom against a mocked server (Hashiya spec, Review mode).
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fetchMock = vi.hoisted(() => {
  const mock = vi.fn<(request: Request) => Promise<Response>>();
  globalThis.fetch = mock as unknown as typeof fetch;
  return mock;
});

import { currentError, dismissError } from "../../src/features/errors/appError";
import { ReviewPage } from "../../src/features/review/ReviewPage";
import { KeySheet } from "../../src/features/shell/KeySheet";
import { wordsHash } from "../../src/features/review/model";
import { audio, box, item, items, key, listChangedElsewhere, savedElsewhere, serveReview, server, start } from "./reviewServer";

beforeEach(() => serveReview(fetchMock));

afterEach(() => {
  cleanup();
  act(() => dismissError());
});

describe("Review mode on a Mac", () => {
  it("asks for the pass first, with the one picked last focused, and plays nothing until one is picked (F13, F25)", async () => {
    document.cookie = "dsj-review-pass=likely; path=/";
    render(<ReviewPage recording={2} transcript={7} />);
    const likely = await screen.findByRole("button", { name: /^Likely errors/ });
    expect(document.activeElement).toBe(likely);
    expect(screen.queryByRole("textbox", { name: "What was said" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /^Every sentence/ }));
    const field = await box();
    expect(document.activeElement).toBe(field);
    expect(document.cookie).toContain("dsj-review-pass=every");
  });

  it("checks a sentence with Enter, goes on, and plays the next from 0.3 s before it", async () => {
    const field = await start();
    expect(field.value).toBe("alpha bravo charlie");
    key(field, { key: "Enter", code: "Enter" });
    expect((await box()).value).toBe("delta echo");
    expect(screen.getByText("1 of 3 checked")).toBeTruthy();
    expect(audio().currentTime).toBeCloseTo(1.7, 5);
    await vi.waitFor(() => expect(server.reviews.at(-1)?.segments[0]?.state).toBe("checked"), { timeout: 2000 });
  });

  it("puts only the changed words into the edit list, once, records them for C, and Shift+Enter goes back (F4, F28)", async () => {
    key(await start(), { key: "Enter", code: "Enter" });
    const field = await box();
    fireEvent.change(field, { target: { value: "delta echo golf" } });
    key(field, { key: "Enter", code: "Enter" });
    await vi.waitFor(() => expect(server.edits).toHaveLength(1));
    const words = items(server.edits[0]);
    expect(words.map((e) => e.text)).toContain(" golf");
    // delta was not retyped: it keeps its own time and its engine confidence.
    expect(words.find((e) => e.text === " delta")).toEqual(item(2.0, 0.4, " delta"));
    await vi.waitFor(() => expect(server.reviews.at(-1)?.corrections).toMatchObject([{ before: "echo", after: "echo golf" }]), { timeout: 2000 });
    key(await box(), { key: "Enter", code: "Enter", shiftKey: true });
    expect((await box()).value).toBe("delta echo golf");
    // Checking it again changes nothing: the box already says what the list says (Review Focus 2).
    key(await box(), { key: "Enter", code: "Enter" });
    await new Promise((resolve) => setTimeout(resolve, 600));
    expect(server.edits).toHaveLength(1);
  });

  it("says on the box, and once in the footer, that Tab plays and Option+Tab moves on (critique 7 Oct, P1-3)", async () => {
    const field = await start();
    const described = (field.getAttribute("aria-describedby") ?? "").split(" ").map((id) => document.getElementById(id)?.textContent ?? "");
    expect(described).toContain("Tab plays. F6 or Option+Tab moves to the other controls.");
    const footer = document.querySelector("footer");
    expect(footer?.textContent).toContain("F6");
  });

  it("sets who said a sentence with Ctrl+2", async () => {
    key(await start(), { key: "2", code: "Digit2", ctrlKey: true });
    await vi.waitFor(() => expect(server.edits).toHaveLength(1));
    expect(server.edits[0]?.[0]).toEqual({ kind: "paragraph", speaker: "SPEAKER_01", language: null });
    expect(screen.getByText("Said by Speaker 2")).toBeTruthy();
  });

  it("on the desk a pointer can check a sentence and say who said it, each speaker shown with its key (critique 7 Oct, P2-5)", async () => {
    await start();
    // One row of controls under the box; the margin holds facts only (critique round 2, P2-1).
    const row = screen.getByRole("toolbar", { name: "Sentence controls" });
    const margin = document.querySelector(".review-margin") as HTMLElement;
    expect(within(margin).queryAllByRole("button")).toEqual([]);
    expect(within(row).getByRole("button", { name: "New speaker" })).toBeTruthy();
    expect(within(row).getByRole("button", { name: /^Flag/ }).textContent).toContain("F");
    const who = within(row).getByRole("group", { name: "Who said it" });
    const second = within(who).getByRole("button", { name: /Speaker 2/ });
    expect(second.textContent).toContain("2");
    expect(second.getAttribute("aria-keyshortcuts")).toBe("Control+2");
    fireEvent.click(second);
    await vi.waitFor(() => expect(server.edits).toHaveLength(1));
    expect(screen.getByText("Said by Speaker 2")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Checked, next" }));
    expect(await screen.findByText("1 of 3 checked")).toBeTruthy();
  });

  it("splits at the cursor with Ctrl+S and merges back with Ctrl+M", async () => {
    const field = await start();
    field.setSelectionRange(6, 6);
    key(field, { key: "s", code: "KeyS", ctrlKey: true });
    expect((await box()).value).toBe("alpha");
    expect(screen.getByText("0 of 4 checked")).toBeTruthy();
    key(await box(), { key: "Enter", code: "Enter" });
    expect((await box()).value).toBe("bravo charlie");
    key(await box(), { key: "m", code: "KeyM", ctrlKey: true });
    expect((await box()).value).toBe("alpha bravo charlie");
    expect(screen.getByText("0 of 3 checked")).toBeTruthy();
  });

  it("puts the box's unsaved words in the list before Ctrl+S, and splits where the cursor is in them (Task 11 carry b)", async () => {
    const field = await start();
    // Odd spacing on purpose: the caret is found word by word, not by its count of characters.
    // Counted in characters, the caret before "zulu" here would fall before "charlie" in the list's text.
    fireEvent.change(field, { target: { value: "alpha      bravo zulu charlie" } });
    const caret = "alpha      bravo ".length;
    field.setSelectionRange(caret, caret);
    key(field, { key: "s", code: "KeyS", ctrlKey: true });
    expect((await box()).value).toBe("alpha bravo");
    await vi.waitFor(() => expect(server.edits).toHaveLength(1));
    expect(items(server.edits[0]).map((e) => e.text)).toContain(" zulu");
    key(await box(), { key: "Enter", code: "Enter" });
    expect((await box()).value).toBe("zulu charlie");
  });

  it("refuses to merge two speakers' sentences, and says why (Task 11 carry a)", async () => {
    key(await start(), { key: "Enter", code: "Enter" });
    key(await box(), { key: "m", code: "KeyM", ctrlKey: true });
    expect(screen.getByText(/Not merged: this sentence is said by Speaker 2 and the one before by Speaker 1/)).toBeTruthy();
    expect((await box()).value).toBe("delta echo");
    expect(screen.getByText("1 of 3 checked")).toBeTruthy();
  });

  it("finds the likely errors again after a split, by the new places (Task 11 carry c)", async () => {
    server.withOther = true;
    const field = await start();
    // The second opinion arrives after the review opens; it disagrees on "foxtrot" alone.
    await vi.waitFor(() => expect(screen.getByRole("button", { name: /Likely errors \(1\)/ })).toBeTruthy());
    field.setSelectionRange(6, 6);
    key(field, { key: "s", code: "KeyS", ctrlKey: true });
    expect((await box()).value).toBe("alpha");
    // "foxtrot" moved from the third place to the fourth; the next likely error is still it, not "delta echo".
    key(await box(), { key: "j", code: "KeyJ", ctrlKey: true });
    expect((await box()).value).toBe("foxtrot");
    expect(screen.getByText("hotel")).toBeTruthy();
  });

  it("puts [?] over selected words with Ctrl+U and flags the sentence", async () => {
    const field = await start();
    field.setSelectionRange(0, 5);
    key(field, { key: "u", code: "KeyU", ctrlKey: true });
    expect((await box()).value).toBe("[?] bravo charlie");
    expect(screen.getAllByText("Can't make it out").length).toBeGreaterThan(0);
  });

  it("resumes at the sentence it was left on, and plays it once the pass is picked (F25)", async () => {
    server.saved = {
      version: 1, transcript_sha: "s1", review_pass: "every", cursor_s: 2.0, started_at: "x", updated_at: "x",
      segments: [
        { start: 0.2, end: 1.3, state: "checked", flags: [], speaker: null, edited: false },
        { start: 2.0, end: 2.9, state: "unchecked", flags: [], speaker: null, edited: false },
        { start: 3.5, end: 3.9, state: "unchecked", flags: [], speaker: null, edited: false },
      ],
      corrections: [],
    };
    render(<ReviewPage recording={2} transcript={7} />);
    expect(await screen.findByText(/1 of 3 checked so far/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /^Every sentence/ }));
    expect((await box()).value).toBe("delta echo");
    expect(screen.getByText("1 of 3 checked")).toBeTruthy();
    expect(audio().currentTime).toBeCloseTo(1.7, 5);
  });

  it("saves under the transcript's sha as it is now, never the old review's (Task 11 carry d)", async () => {
    server.saved = {
      version: 1, transcript_sha: "s0", review_pass: "every", cursor_s: 0, started_at: "x", updated_at: "x",
      segments: [{ start: 0.2, end: 1.3, state: "checked", flags: [], speaker: null, edited: false }],
      corrections: [],
    };
    key(await start(), { key: "Enter", code: "Enter" });
    await vi.waitFor(() => expect(server.reviews.at(-1)?.transcript_sha).toBe("s1"), { timeout: 2000 });
  });

  it("finishes the pass and saves the answer key", async () => {
    await start();
    for (let i = 0; i < 3; i += 1) key(await box(), { key: "Enter", code: "Enter" });
    expect(await screen.findByRole("heading", { name: "This pass is done" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Save as answer key" }));
    expect(await screen.findByText(/Saved a.reference.json and a.reference.txt beside the transcript/)).toBeTruthy();
    // The key is built from the server's copy, so the last check was saved first.
    expect(server.reviews.at(-1)?.segments.map((s) => s.state)).toEqual(["checked", "checked", "checked"]);
  });

  it("leaves for the transcript with Esc once everything is saved", async () => {
    const went: string[] = [];
    const field = await start((href) => went.push(href));
    fireEvent.change(field, { target: { value: "alpha bravo charles" } });
    key(field, { key: "Escape", code: "Escape" });
    await vi.waitFor(() => expect(went).toEqual(["/?recording=2&transcript=7"]));
    // What the box held went into the list before leaving.
    expect(items(server.edits.at(-1)).map((e) => e.text)).toContain(" charles");
  });

  it("leaves the same way by the bar's back arrow (F27)", async () => {
    const went: string[] = [];
    await start((href) => went.push(href));
    fireEvent.click(screen.getByRole("link", { name: "Back to the transcript" }));
    await vi.waitFor(() => expect(went).toEqual(["/?recording=2&transcript=7"]));
  });
});

describe("Review mode, fix round 1", () => {
  it("the flag menu shows a flag taken as checked (critique 7 Oct, P2-8)", async () => {
    const field = await start();
    key(field, { key: "u", code: "KeyU", ctrlKey: true });
    key(field, { key: "f", code: "KeyF", ctrlKey: true });
    const unclear = await screen.findByRole("menuitemcheckbox", { name: /Can't make it out/ });
    // Ctrl+U adds this flag but does not toggle it, so the item names no key (fix round 1 review, M1).
    expect(unclear.textContent).not.toContain("Ctrl U");
    expect(unclear.getAttribute("aria-checked")).toBe("true");
    expect(screen.getByRole("menuitemcheckbox", { name: /Not speech/ }).getAttribute("aria-checked")).toBe("false");
  });

  it("while the flag menu is open, Esc in the box closes the menu and stays, and no other key acts (I1)", async () => {
    const went: string[] = [];
    const field = await start((href) => went.push(href));
    key(field, { key: "f", code: "KeyF", ctrlKey: true });
    expect(await screen.findByRole("menu")).toBeTruthy();
    // The menu is open but the key reaches the box first (a fast Esc, I1).
    key(field, { key: "Enter", code: "Enter" });
    expect(screen.getByText("0 of 3 checked")).toBeTruthy();
    key(field, { key: "Escape", code: "Escape" });
    await vi.waitFor(() => expect(screen.queryByRole("menu")).toBeNull());
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(went).toEqual([]);
    expect((await box()).value).toBe("alpha bravo charlie");
  });

  it("says Not saved when the edit list's save is refused, and saves no check beside it (I2; #274, final review I2)", async () => {
    server.refuseEdits = true;
    const field = await start();
    fireEvent.change(field, { target: { value: "alpha bravo charles" } });
    key(field, { key: "Enter", code: "Enter" });
    await vi.waitFor(() => expect(screen.getByText("Not saved")).toBeTruthy());
    expect(screen.queryByText("Saved")).toBeNull();
    await new Promise((resolve) => setTimeout(resolve, 600));
    // Only the review saved whole when the pass was picked: the check is not on the server.
    expect(server.reviews.flatMap((r) => r.segments.map((s) => s.state))).not.toContain("checked");
  });

  it("after a refused save, Esc says to reload, which is what works (Task 13 re-review minor)", async () => {
    server.refuseEdits = true;
    const went: string[] = [];
    const field = await start((href) => went.push(href));
    fireEvent.change(field, { target: { value: "alpha bravo charles" } });
    key(field, { key: "Escape", code: "Escape" });
    await vi.waitFor(() => expect(screen.getByText(/^Still in Review/)).toBeTruthy());
    expect(screen.getByText(/^Still in Review/).textContent).toMatch(/Reload the page/);
    expect(screen.getByText(/^Still in Review/).textContent).not.toMatch(/Esc tries again/);
    expect(went).toEqual([]);
  });

  it("switching pass after one has finished leaves the done panel for the new pass's first sentence (I3)", async () => {
    server.withOther = true;
    render(<ReviewPage recording={2} transcript={7} />);
    fireEvent.click(await screen.findByRole("button", { name: /^Likely errors\s*1/ }));
    expect((await box()).value).toBe("foxtrot");
    key(await box(), { key: "Enter", code: "Enter" });
    expect(await screen.findByRole("heading", { name: "This pass is done" })).toBeTruthy();
    const pause = vi.spyOn(HTMLMediaElement.prototype, "pause");
    fireEvent.click(screen.getByRole("button", { name: /^Every sentence$/ }));
    expect((await box()).value).toBe("alpha bravo charlie");
    expect(screen.queryByRole("heading", { name: "This pass is done" })).toBeNull();
    // And it plays the sentence it lands on, from 0.3 s before it (here, from 0).
    expect(audio().currentTime).toBeCloseTo(0, 5);
    pause.mockRestore();
  });

  it("Shift+Enter keeps the words typed in the box (I4: no data loss)", async () => {
    key(await start(), { key: "Enter", code: "Enter" });
    const field = await box();
    fireEvent.change(field, { target: { value: "delta echo golf" } });
    key(field, { key: "Enter", code: "Enter", shiftKey: true });
    expect((await box()).value).toBe("alpha bravo charlie");
    await vi.waitFor(() => expect(server.edits).toHaveLength(1));
    expect(items(server.edits[0]).map((e) => e.text)).toContain(" golf");
    key(await box(), { key: "Enter", code: "Enter" });
    expect((await box()).value).toBe("delta echo golf");
  });

  it("Tab plays again from 1.5 s before where it stopped, never before the sentence's start, and stops after its end (I4; UAT 3)", async () => {
    const pause = vi.fn();
    HTMLMediaElement.prototype.pause = pause;
    key(await start(), { key: "Enter", code: "Enter" });
    // "delta echo", 2.0 to 2.9 s, played on arrival and stopped at 3.1 s.
    audio().currentTime = 3.1;
    key(await box(), { key: "Tab", code: "Tab" });
    // 1.5 s back is 1.6 s, inside the sentence before: it starts at its own start.
    expect(audio().currentTime).toBeCloseTo(2.0, 5);
    // And stops 0.2 s after its end, as arrival does, not at the recording's end.
    pause.mockClear();
    audio().currentTime = 3.05;
    audio().dispatchEvent(new Event("seeked"));
    expect(pause).not.toHaveBeenCalled();
    audio().currentTime = 3.12;
    audio().dispatchEvent(new Event("seeked"));
    expect(pause).toHaveBeenCalled();
    // Paused far past it (a click on the waveform): Tab comes back into the sentence.
    audio().currentTime = 51;
    key(await box(), { key: "Tab", code: "Tab" });
    expect(audio().currentTime).toBeCloseTo(2.0, 5);
  });

  it("plays a sentence on arrival up to 0.2 s after its end, then stops (I4)", async () => {
    const pause = vi.fn();
    HTMLMediaElement.prototype.pause = pause;
    key(await start(), { key: "Enter", code: "Enter" });
    // "delta echo" ends at 2.9: the stop is at 3.1.
    pause.mockClear();
    audio().currentTime = 3.05;
    audio().dispatchEvent(new Event("seeked"));
    expect(pause).not.toHaveBeenCalled();
    audio().currentTime = 3.12;
    audio().dispatchEvent(new Event("seeked"));
    expect(pause).toHaveBeenCalled();
  });

  it("typing pauses playback (I4)", async () => {
    const pause = vi.fn();
    HTMLMediaElement.prototype.pause = pause;
    const field = await start();
    pause.mockClear();
    fireEvent.input(field, { target: { value: "alpha bravo charlie x" } });
    expect(pause).toHaveBeenCalled();
  });

  it("Ctrl+. and Ctrl+, step the speed through Review's four (I4)", async () => {
    const field = await start();
    key(field, { key: ".", code: "Period", ctrlKey: true });
    await vi.waitFor(() => expect(audio().playbackRate).toBe(1.25));
    expect(screen.getByText("Playing at 1.25×")).toBeTruthy();
    key(await box(), { key: ",", code: "Comma", ctrlKey: true });
    key(await box(), { key: ",", code: "Comma", ctrlKey: true });
    await vi.waitFor(() => expect(audio().playbackRate).toBe(0.75));
  });

  it("Ctrl+G takes the second opinion, and Ctrl+Shift+J goes back to the likely error before (I4)", async () => {
    server.withOther = true;
    const field = await start();
    await vi.waitFor(() => expect(screen.getByRole("button", { name: /Likely errors \(1\)/ })).toBeTruthy());
    // Flag the first sentence, so there is a likely error behind the one Ctrl+J finds.
    key(field, { key: "u", code: "KeyU", ctrlKey: true });
    key(await box(), { key: "j", code: "KeyJ", ctrlKey: true });
    expect((await box()).value).toBe("foxtrot");
    key(await box(), { key: "g", code: "KeyG", ctrlKey: true });
    expect((await box()).value).toBe("hotel");
    key(await box(), { key: "J", code: "KeyJ", ctrlKey: true, shiftKey: true });
    expect((await box()).value).toBe("alpha bravo charlie");
  });

  it("Ctrl+/ opens Review's key sheet (I4)", async () => {
    render(<KeySheet />);
    key(await start(), { key: "/", code: "Slash", ctrlKey: true });
    const sheet = await screen.findByRole("dialog", { name: "Keys in Review" });
    // A tablet focuses the box only on a tap, so its keyboard needs one first (Task 14 review, Minor 4).
    expect(sheet.textContent).toContain("On a tablet, tap the sentence once");
    // Ctrl+G's way back is on the sheet (UAT 5).
    expect(sheet.textContent).toMatch(/Ctrl\+G again/);
  });

  it("Ctrl+/ takes focus out of the box at once, and Esc closes the sheet and puts it back (UAT 4)", async () => {
    render(<KeySheet />);
    const went: string[] = [];
    const field = await start((href) => went.push(href));
    key(field, { key: "/", code: "Slash", ctrlKey: true });
    // Before the sheet has drawn: no key can reach the box behind it.
    expect(document.activeElement).not.toBe(field);
    await screen.findByRole("dialog", { name: "Keys in Review" });
    act(() => {
      fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape", code: "Escape" });
    });
    await vi.waitFor(() => expect(screen.queryByRole("dialog", { name: "Keys in Review" })).toBeNull());
    await vi.waitFor(() => expect(document.activeElement).toBe(field));
    expect(went).toEqual([]);
  });

  it("Ctrl+G again, or Cmd+Z in the box, puts back the words it replaced (UAT 5)", async () => {
    server.withOther = true;
    const field = await start();
    await vi.waitFor(() => expect(screen.getByRole("button", { name: /Likely errors \(1\)/ })).toBeTruthy());
    key(field, { key: "j", code: "KeyJ", ctrlKey: true });
    fireEvent.change(await box(), { target: { value: "foxtrot golf" } });
    key(await box(), { key: "g", code: "KeyG", ctrlKey: true });
    expect((await box()).value).toBe("hotel");
    key(await box(), { key: "g", code: "KeyG", ctrlKey: true });
    expect((await box()).value).toBe("foxtrot golf");
    expect(screen.getByText(/Your words are back/)).toBeTruthy();
    key(await box(), { key: "g", code: "KeyG", ctrlKey: true });
    expect((await box()).value).toBe("hotel");
    key(await box(), { key: "z", code: "KeyZ", metaKey: true });
    expect((await box()).value).toBe("foxtrot golf");
  });

  it("asks before the browser leaves with words in the box not yet in the list (Minor 2)", async () => {
    const field = await start();
    const leaving = () => {
      const event = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(event);
      return event.defaultPrevented;
    };
    expect(leaving()).toBe(false);
    fireEvent.change(field, { target: { value: "alpha bravo charles" } });
    expect(leaving()).toBe(true);
  });

  it("Esc on the finish panel leaves Review (Minor 7)", async () => {
    const went: string[] = [];
    await start((href) => went.push(href));
    for (let i = 0; i < 3; i += 1) key(await box(), { key: "Enter", code: "Enter" });
    await screen.findByRole("heading", { name: "This pass is done" });
    key(document.body, { key: "Escape", code: "Escape" });
    await vi.waitFor(() => expect(went).toEqual(["/?recording=2&transcript=7"]));
  });
});

describe("the end of a pass with sentences left (UAT 1)", () => {
  it("says how many are left, and Enter goes to the first unchecked; the key stays partial until all are checked", async () => {
    server.saved = {
      version: 1, transcript_sha: "s1", review_pass: "every", cursor_s: 2.0, started_at: "x", updated_at: "x",
      segments: [
        { start: 0.2, end: 1.3, state: "unchecked", flags: [], speaker: null, edited: false, words_hash: null },
        { start: 2.0, end: 2.9, state: "unchecked", flags: [], speaker: null, edited: false, words_hash: null },
        { start: 3.5, end: 3.9, state: "unchecked", flags: [], speaker: null, edited: false, words_hash: null },
      ],
      corrections: [],
    };
    render(<ReviewPage recording={2} transcript={7} />);
    fireEvent.click(await screen.findByRole("button", { name: /^Every sentence/ }));
    expect((await box()).value).toBe("delta echo");
    key(await box(), { key: "Enter", code: "Enter" });
    key(await box(), { key: "Enter", code: "Enter" });
    expect(await screen.findByRole("heading", { name: "1 sentence left in this pass" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "This pass is done" })).toBeNull();
    const go = screen.getByRole("button", { name: /Go to the first unchecked/ });
    expect(document.activeElement).toBe(go);
    // Saving now is still only a partial key: it asks first.
    fireEvent.click(screen.getByRole("button", { name: "Save as answer key" }));
    expect(await screen.findByRole("group", { name: "Partial answer key" })).toBeTruthy();
    act(() => {
      fireEvent.keyDown(go, { key: "Enter", code: "Enter" });
      fireEvent.click(go);
    });
    expect((await box()).value).toBe("alpha bravo charlie");
    // On through the pass, now with every sentence checked.
    for (let i = 0; i < 3; i += 1) key(await box(), { key: "Enter", code: "Enter" });
    expect(await screen.findByRole("heading", { name: "This pass is done" })).toBeTruthy();
  });
});

describe("Review after the final review (#274)", () => {
  it("a check keeps a hash of the words it was checked with, corrections and all (I1)", async () => {
    const field = await start();
    fireEvent.change(field, { target: { value: "alpha bravo charles" } });
    key(field, { key: "Enter", code: "Enter" });
    await vi.waitFor(() => expect(server.reviews.at(-1)?.segments[0]).toMatchObject({ state: "checked", words_hash: wordsHash("alpha bravo charles") }), { timeout: 2000 });
  });

  it("transcribed again: a checked sentence whose words changed is unchecked, and the page says how many (I1, ruling R7)", async () => {
    server.replaced = "This transcript was made again after it was last edited, so the old edits no longer fit its words. They are kept beside the library as x.json; this list starts again from the new transcript.";
    server.saved = {
      version: 1, transcript_sha: "s0", review_pass: "every", cursor_s: 0, started_at: "x", updated_at: "x",
      segments: [
        // Checked with a correction the new transcript does not have.
        { start: 0.2, end: 1.3, state: "checked", flags: [], speaker: null, edited: true, words_hash: wordsHash("alpha bravo charles") },
        { start: 2.0, end: 2.9, state: "checked", flags: [], speaker: null, edited: false, words_hash: wordsHash("delta echo") },
        { start: 3.5, end: 3.9, state: "unchecked", flags: [], speaker: null, edited: false, words_hash: null },
      ],
      corrections: [],
    };
    render(<ReviewPage recording={2} transcript={7} />);
    expect(await screen.findByText(/1 checked sentence no longer matches and is unchecked again/)).toBeTruthy();
    expect(screen.getByText(/kept beside the library as x\.json/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /^Every sentence/ }));
    expect(await screen.findByText("1 of 3 checked")).toBeTruthy();
  });

  it("the edit list changed in another tab: the review save stops too, and Review says to reload (I2)", async () => {
    const field = await start();
    await vi.waitFor(() => expect(server.reviews).toHaveLength(1));
    listChangedElsewhere();
    fireEvent.change(field, { target: { value: "alpha bravo charles" } });
    key(field, { key: "Enter", code: "Enter" });
    await vi.waitFor(() => expect(currentError()?.error).toBe("ListChanged"));
    await vi.waitFor(() => expect(screen.getByText(/changed in another tab\. Reload the page/)).toBeTruthy());
    await new Promise((resolve) => setTimeout(resolve, 600));
    expect(server.reviews).toHaveLength(1);
    expect(server.reviewPatches).toEqual([]);
    // Nothing more acts on the sentence: a check now is not taken, and the notice says why.
    act(() => dismissError());
    const now = await box();
    key(now, { key: "Enter", code: "Enter" });
    await new Promise((resolve) => setTimeout(resolve, 600));
    expect(server.reviewPatches).toEqual([]);
    expect(screen.getByText(/changed in another tab\. Reload the page/)).toBeTruthy();
    // Leaving says the edit list's own reason, not that the transcript was made again (Minor M1).
    key(now, { key: "Escape", code: "Escape" });
    await vi.waitFor(() => expect(screen.getByText(/^Still in Review/).textContent).toMatch(/changed in another tab/));
  });

  it("the answer key names the earlier key it kept beside the new one (I1)", async () => {
    server.keptKey = ["a.reference.20261008T101500Z.json", "a.reference.20261008T101500Z.txt"];
    await start();
    for (let i = 0; i < 3; i += 1) key(await box(), { key: "Enter", code: "Enter" });
    fireEvent.click(await screen.findByRole("button", { name: "Save as answer key" }));
    expect(await screen.findByText(/The earlier key is kept beside it as a\.reference\.20261008T101500Z\.json and a\.reference\.20261008T101500Z\.txt/)).toBeTruthy();
  });
});

describe("Review saves one change, not the whole review (#251)", () => {
  it("saves a new review whole once, when the pass is picked, and nothing before", async () => {
    render(<ReviewPage recording={2} transcript={7} />);
    await screen.findByRole("button", { name: /^Every sentence/ });
    await new Promise((resolve) => setTimeout(resolve, 500));
    expect(server.reviews).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: /^Every sentence/ }));
    await vi.waitFor(() => expect(server.reviews).toHaveLength(1));
    expect(server.reviews[0]?.segments.map((s) => s.state)).toEqual(["unchecked", "unchecked", "unchecked"]);
    expect(server.reviewPatches).toEqual([]);
  });

  it("sends a check as one segment against the review's sha, and the next against the sha its answer gave", async () => {
    const field = await start();
    await vi.waitFor(() => expect(server.reviews).toHaveLength(1));
    key(field, { key: "Enter", code: "Enter" });
    await vi.waitFor(() => expect(server.reviewPatches).toHaveLength(1), { timeout: 2000 });
    expect(server.reviewPatches[0]).toMatchObject({
      transcript_sha: "s1",
      review_sha: "review-1",
      start: 0,
      delete: 1,
      insert: [{ start: 0.2, end: 1.3, state: "checked" }],
      corrections: [],
      cursor_s: 2.0,
    });
    key(await box(), { key: "Enter", code: "Enter" });
    await vi.waitFor(() => expect(server.reviewPatches).toHaveLength(2), { timeout: 2000 });
    expect(server.reviewPatches[1]).toMatchObject({ review_sha: "review-2", start: 1, delete: 1 });
    expect(server.reviews.at(-1)?.segments.map((s) => s.state)).toEqual(["checked", "checked", "unchecked"]);
  });

  it("patches a resumed review against the sha it was read with, and a correction is appended, not resent", async () => {
    server.saved = {
      version: 1, transcript_sha: "s1", review_pass: "every", cursor_s: 0.2, started_at: "x", updated_at: "x",
      segments: [
        { start: 0.2, end: 1.3, state: "unchecked", flags: [], speaker: null, edited: false },
        { start: 2.0, end: 2.9, state: "unchecked", flags: [], speaker: null, edited: false },
        { start: 3.5, end: 3.9, state: "unchecked", flags: [], speaker: null, edited: false },
      ],
      corrections: [{ at: "x", start: 3.5, end: 3.9, before: "foxtrot", after: "foxtrot" }],
    };
    const field = await start();
    fireEvent.change(field, { target: { value: "alpha bravo charles" } });
    key(field, { key: "Enter", code: "Enter" });
    await vi.waitFor(() => expect(server.reviewPatches).toHaveLength(1), { timeout: 2000 });
    expect(server.reviewPatches[0]).toMatchObject({ review_sha: "review-0", corrections: [{ before: "charlie", after: "charles" }] });
    expect(server.reviews.at(-1)?.corrections).toHaveLength(2);
  });

  it("a review changed in another tab: the patch is refused, nothing more is sent, and the page says to reload", async () => {
    const went: string[] = [];
    const field = await start((href) => went.push(href));
    await vi.waitFor(() => expect(server.reviews).toHaveLength(1));
    // Another tab saved the review since: not what this page holds, before or after its change.
    savedElsewhere({ ...(server.saved as object), cursor_s: 3.5 });
    key(field, { key: "Enter", code: "Enter" });
    await vi.waitFor(() => expect(currentError()?.error).toBe("ReviewChanged"), { timeout: 2000 });
    key(await box(), { key: "Enter", code: "Enter" });
    key(await box(), { key: "Escape", code: "Escape" });
    await vi.waitFor(() => expect(screen.getByText(/^Still in Review/).textContent).toMatch(/Reload the page/));
    expect(server.reviewPatches).toHaveLength(1);
    expect(went).toEqual([]);
  });
});

describe("Review saves whose fate is in doubt, and a second tab (#251 fix round 1)", () => {
  const states = () => (server.saved as { segments: { state: string }[] } | null)?.segments.map((s) => s.state);

  for (const fault of ["lost-after", "500-after"] as const) {
    it(`a check applied but answered ${fault === "lost-after" ? "never" : "with a 500"}: the next check goes against the server's sha, nothing lost, no reload asked`, async () => {
      const field = await start();
      await vi.waitFor(() => expect(server.reviews).toHaveLength(1));
      server.reviewFault = fault;
      key(field, { key: "Enter", code: "Enter" });
      await vi.waitFor(() => expect(server.reviewReads).toBe(1), { timeout: 2000 });
      key(await box(), { key: "Enter", code: "Enter" });
      await vi.waitFor(() => expect(states()).toEqual(["checked", "checked", "unchecked"]), { timeout: 2000 });
      expect(server.reviewPatches.map((p) => p.review_sha)).toEqual(["review-1", "review-2"]);
      expect(currentError()).toBeNull();
    });
  }

  it("a check lost before it arrived is sent again against the same sha", async () => {
    const field = await start();
    await vi.waitFor(() => expect(server.reviews).toHaveLength(1));
    server.reviewFault = "lost-before";
    key(field, { key: "Enter", code: "Enter" });
    await vi.waitFor(() => expect(states()).toEqual(["checked", "unchecked", "unchecked"]), { timeout: 2000 });
    expect(server.reviewReads).toBe(1);
    expect(currentError()).toBeNull();
  });

  it("the creating save's answer lost: the review is the server's, and the first check patches it", async () => {
    server.reviewFault = "lost-after";
    const field = await start();
    await vi.waitFor(() => expect(server.reviewReads).toBe(1), { timeout: 2000 });
    key(field, { key: "Enter", code: "Enter" });
    await vi.waitFor(() => expect(states()).toEqual(["checked", "unchecked", "unchecked"]), { timeout: 2000 });
    expect(server.reviews).toHaveLength(2);
    expect(currentError()).toBeNull();
  });

  it("a second tab that saw no review cannot write over the review another device made since (I2)", async () => {
    render(<ReviewPage recording={2} transcript={7} />);
    const every = await screen.findByRole("button", { name: /^Every sentence/ });
    // The phone made the review and checked a sentence while this tab sat at the chooser.
    const phone = {
      version: 1, transcript_sha: "s1", review_pass: "every", cursor_s: 2.0, started_at: "x", updated_at: "x",
      segments: [
        { start: 0.2, end: 1.3, state: "checked", flags: [], speaker: null, edited: false },
        { start: 2.0, end: 2.9, state: "unchecked", flags: [], speaker: null, edited: false },
        { start: 3.5, end: 3.9, state: "unchecked", flags: [], speaker: null, edited: false },
      ],
      corrections: [],
    };
    savedElsewhere(phone);
    fireEvent.click(every);
    await vi.waitFor(() => expect(currentError()?.error).toBe("ReviewChanged"), { timeout: 2000 });
    expect(server.reviewPuts).toEqual(["none"]);
    expect(server.saved).toBe(phone);
  });

  it("a review really changed in another tab: refused, read once, and the page says to reload", async () => {
    const field = await start();
    await vi.waitFor(() => expect(server.reviews).toHaveLength(1));
    savedElsewhere({ ...(server.saved as object), cursor_s: 3.5 });
    key(field, { key: "Enter", code: "Enter" });
    await vi.waitFor(() => expect(currentError()?.error).toBe("ReviewChanged"), { timeout: 2000 });
    expect(server.reviewReads).toBe(1);
    expect(server.reviewPatches).toHaveLength(1);
  });
});
