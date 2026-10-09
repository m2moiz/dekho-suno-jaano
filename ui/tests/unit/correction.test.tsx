// Retyping a stretch of words, bound to the same audio (#83).
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fetchMock = vi.hoisted(() => {
  const mock = vi.fn<(request: Request) => Promise<Response>>();
  globalThis.fetch = mock as unknown as typeof fetch;
  return mock;
});

import { correction } from "../../src/features/edit/correct";
import { readContent } from "../../src/features/edit/readContent";
import { dismissError } from "../../src/features/errors/appError";
import { takeToken } from "../../src/features/session/session";
import { unsureWords } from "../../src/features/transcript/confidence";
import { TranscriptPage } from "../../src/features/transcript/TranscriptPage";
import { type Content, Editor, type Entry, type Item } from "../../src/lib/editOps";
import { lint } from "../../src/lib/linter";
import { listReply, saves, savedList } from "./editsServer";
import { installHighlights } from "./highlights";

function item(sourceStart: number, length: number, text: string, extra: Partial<Item> = {}): Item {
  return { kind: "item", source: "0", sourceStart, length, text, muted: false, confidence: 0.95, ...extra };
}
const PARAGRAPH: Entry = { kind: "paragraph", speaker: null, language: null };

// " I have assigned the the role" with the doubled "the" heard at 1.2 s, then " done".
const CONTENT: Content = [
  PARAGRAPH,
  item(0, 0.2, ""),
  item(0.2, 0.2, " I"),
  item(0.4, 0.3, " have"),
  item(0.7, 0.5, " assigned"),
  item(1.2, 0.2, " the", { confidence: 0.3 }),
  item(1.4, 0.1, ""),
  item(1.5, 0.2, " the", { confidence: 0.3 }),
  item(1.7, 0.4, " role"),
  item(2.1, 0.3, ""),
  PARAGRAPH,
  item(2.4, 0.4, " done"),
];

const texts = (content: Content) => content.filter((e) => e.kind === "item" && e.text).map((e) => (e as Item).text);

describe("correction", () => {
  // " the the" (entries 5 to 7, the pause between them included) retyped as " the".
  const op = correction(CONTENT, 5, 8, "the");

  it("keeps the stretch's start and end, and gives the words inside plausible boundaries", () => {
    const retyped = correction(CONTENT, 5, 9, "to the role");
    const items = retyped.entries as Item[];
    expect(items.map((e) => e.text)).toEqual([" to", " the", " role"]);
    expect(items[0]?.sourceStart).toBe(1.2);
    const last = items.at(-1) as Item;
    expect(last.sourceStart + last.length).toBeCloseTo(2.1, 6);
    // In proportion to their letters, 2 + 3 + 4 of 9 across 0.9 s.
    expect(items.map((e) => e.sourceStart)).toEqual([1.2, 1.4, 1.7]);
    expect(items.map((e) => e.length)).toEqual([0.2, 0.3, 0.4]);
  });

  it("moves no neighbouring word", () => {
    const after = new Editor(CONTENT).content;
    const editor = new Editor(CONTENT);
    editor.applyEdit(op);
    expect(editor.content.slice(0, 5)).toEqual(after.slice(0, 5));
    expect(editor.content.slice(6)).toEqual(after.slice(8));
    expect(texts(editor.content)).toEqual([" I", " have", " assigned", " the", " role", " done"]);
  });

  it("keeps the list one that plays the recording in order", () => {
    const editor = new Editor(CONTENT, { check: (c) => lint(c, new Set(["0"])) });
    editor.applyEdit(op);
    editor.applyEdit(correction(editor.content, 2, 4, "I've"));
    expect(texts(editor.content)).toEqual([" I've", " assigned", " the", " role", " done"]);
  });

  it("is one undo step", () => {
    const editor = new Editor(CONTENT);
    editor.applyEdit(op);
    expect(editor.undoLabel()).toBe("correction");
    editor.undo();
    expect(editor.content).toEqual(CONTENT);
    expect(editor.canUndo()).toBe(false);
  });

  it("takes away the low-confidence tint from the words it writes", () => {
    const before = readContent(CONTENT, undefined).reading;
    expect(unsureWords(before, 0.5)).toEqual([3, 4]);
    const editor = new Editor(CONTENT);
    editor.applyEdit(op);
    const after = readContent(editor.content, undefined).reading;
    expect(unsureWords(after, 0.5)).toEqual([]);
  });

  it("keeps a muted stretch muted", () => {
    const muted = CONTENT.map((e, i) => (i === 5 && e.kind === "item" ? { ...e, muted: true } : e));
    expect((correction(muted, 5, 8, "the").entries as Item[]).every((e) => e.muted)).toBe(true);
  });

  it("leaves an emptied stretch as audio with no words, from start to end", () => {
    const emptied = correction(CONTENT, 5, 8, "  ");
    expect(emptied.entries).toEqual([item(1.2, 0.5, "", { confidence: null })]);
  });
});

describe("the Correct button", () => {
  let saved: Content[] = [];

  beforeEach(() => {
    installHighlights();
    globalThis.ResizeObserver ??= class {
      observe() {}
      disconnect() {}
      unobserve() {}
    };
    window.matchMedia ??= () =>
      ({ matches: false, addEventListener() {}, removeEventListener() {} }) as unknown as MediaQueryList;
    window.history.replaceState(null, "", "/?recording=2&transcript=7#t=a-token");
    takeToken();
    saved = [];
    fetchMock.mockReset();
    fetchMock.mockImplementation(async (request: Request) => {
      const path = new URL(request.url).pathname;
      if (path === "/api/recordings") {
        return Response.json([
          {
            id: 2, path: "/rec/a.wav", size_bytes: 1, duration_s: 3, content_id: "c", audio_codec: "pcm",
            video_codec: null, first_seen: "x", missing: false, unreadable: null, title: null,
            transcripts: [{ id: 7, finished_at: "x", engine: "parakeet", model: "parakeet", diarized: null, speaker_count: null, mark_count: null, language: null, last_edited_at: null, language_tag: null, review_checked: null, review_total: null }],
          },
        ]);
      }
      if (path === "/api/transcripts/7") return Response.json({ audio: "/rec/a.wav", model: "parakeet", sentences: [] });
      if (path === "/api/transcripts/7/edits") {
        if (!saves(request)) return listReply(CONTENT);
        const content = await savedList(request, saved.at(-1) ?? CONTENT);
        saved.push(content);
        return listReply(content);
      }
      if (path === "/api/transcripts/7/matches") {
        return Response.json({ matches: [], words_searched: 6, lists: ["en"], recall: "recall: x" });
      }
      if (path === "/api/recording/2/waveform") return new Response(new Int8Array([-3, 3]));
      // The reader reads the review for its margin marks (Task 13); none here.
      if (path === "/api/transcripts/7/review") return Response.json({ document: null, transcript_sha: "sha-1" });
      return Response.json({ detail: "Not Found" }, { status: 404 });
    });
  });

  afterEach(() => {
    cleanup();
    act(() => dismissError());
  });

  function select(from: string, to: string): void {
    const text = document.querySelector("article p")?.firstChild as Text;
    const range = document.createRange();
    range.setStart(text, text.data.indexOf(from));
    range.setEnd(text, text.data.lastIndexOf(to) + to.length);
    window.getSelection()?.removeAllRanges();
    window.getSelection()?.addRange(range);
    document.dispatchEvent(new Event("selectionchange"));
  }

  it("retypes the selected words in place, and the reader and the saved list show it", async () => {
    render(<TranscriptPage recording={2} transcript={7} />);
    await screen.findByRole("toolbar", { name: "Edit" });
    act(() => select("the the", "the the"));
    // The Selection toolbar appears once the page's effects have read the selection.
    const tools = await screen.findByRole("toolbar", { name: "Selection" });
    const correct = within(tools).getByRole("button", { name: "Correct" }) as HTMLButtonElement;
    await vi.waitFor(() => expect(correct.disabled).toBe(false));
    fireEvent.click(correct);
    const field = await screen.findByRole("textbox", { name: "What was said" });
    expect((field as HTMLInputElement).value).toBe("the the");
    // In place, over the words: no dialog.
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.change(field, { target: { value: "the" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await vi.waitFor(() => expect(document.querySelector("article p")?.textContent).toBe(" I have assigned the role"));
    await vi.waitFor(() => expect(saved).toHaveLength(1));
    expect(texts(saved[0] ?? [])).toEqual([" I", " have", " assigned", " the", " role", " done"]);
  });
});
