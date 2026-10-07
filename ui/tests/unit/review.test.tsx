// Review mode by keyboard, in jsdom against a mocked server (Hashiya spec, Review mode).
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fetchMock = vi.hoisted(() => {
  const mock = vi.fn<(request: Request) => Promise<Response>>();
  globalThis.fetch = mock as unknown as typeof fetch;
  return mock;
});

import { dismissError } from "../../src/features/errors/appError";
import { ReviewPage } from "../../src/features/review/ReviewPage";
import { takeToken } from "../../src/features/session/session";
import type { Content, Entry, Item } from "../../src/lib/editOps";
import { installHighlights } from "./highlights";
import { stubMatchMedia } from "./media";

function item(sourceStart: number, length: number, text: string, confidence: number | null = 0.95): Item {
  return { kind: "item", source: "0", sourceStart, length, text, muted: false, confidence };
}
const gap = (sourceStart: number, length: number): Item => item(sourceStart, length, "", null);
const para = (speaker: string): Entry => ({ kind: "paragraph", speaker, language: null });

// Contiguous, with an item of no text for every pause, as dsj/hatao.py
// `from_transcript` builds a list, so the dev linter accepts it (F2).
const CONTENT: Content = [
  para("SPEAKER_00"),
  gap(0, 0.2),
  item(0.2, 0.3, " alpha"),
  gap(0.5, 0.1),
  item(0.6, 0.3, " bravo"),
  gap(0.9, 0.1),
  item(1.0, 0.3, " charlie"),
  para("SPEAKER_01"),
  gap(1.3, 0.7),
  item(2.0, 0.4, " delta"),
  gap(2.4, 0.1),
  item(2.5, 0.4, " echo"),
  para("SPEAKER_00"),
  gap(2.9, 0.6),
  item(3.5, 0.4, " foxtrot"),
];
const DOC = {
  audio: "/rec/a.wav",
  model: "mlx-community/parakeet-tdt-0.6b-v3",
  speakers: ["SPEAKER_00", "SPEAKER_01"],
  sentences: [
    { start: 0.2, end: 1.3, speaker: 0, text: " alpha bravo charlie", tokens: [{ t: 0.2, w: " alpha", e: 0.5 }, { t: 0.6, w: " bravo", e: 0.9 }, { t: 1.0, w: " charlie", e: 1.3 }] },
    { start: 2.0, end: 2.9, speaker: 1, text: " delta echo", tokens: [{ t: 2.0, w: " delta", e: 2.4 }, { t: 2.5, w: " echo", e: 2.9 }] },
    { start: 3.5, end: 3.9, speaker: 0, text: " foxtrot", tokens: [{ t: 3.5, w: " foxtrot", e: 3.9 }] },
  ],
};
// A second transcript of the same recording, which hears "hotel" for "foxtrot".
const OTHER = {
  audio: "/rec/a.wav",
  model: "mlx-community/whisper-large-v3-turbo",
  sentences: [
    { start: 0.2, end: 2.9, text: " alpha bravo charlie delta echo", tokens: [{ t: 0.2, w: " alpha", e: 0.5 }, { t: 0.6, w: " bravo", e: 0.9 }, { t: 1.0, w: " charlie", e: 1.3 }, { t: 2.0, w: " delta", e: 2.4 }, { t: 2.5, w: " echo", e: 2.9 }] },
    { start: 3.5, end: 3.9, text: " hotel", tokens: [{ t: 3.5, w: " hotel", e: 3.9 }] },
  ],
};
const ROW = { finished_at: "x", diarized: true, speaker_count: 2, mark_count: null, language: null, last_edited_at: null, language_tag: "english", review_checked: null, review_total: null };
const recording = (others: boolean) => ({
  id: 2, path: "/rec/a.wav", title: null, size_bytes: 1, duration_s: 5, content_id: "c", audio_codec: "pcm",
  video_codec: null, first_seen: "x", missing: false, unreadable: null,
  transcripts: [
    { ...ROW, id: 7, engine: "parakeet", model: "parakeet" },
    ...(others ? [{ ...ROW, id: 8, engine: "whisper", model: "whisper" }] : []),
  ],
});

type Saved = { transcript_sha: string; segments: { state: string }[]; corrections: { before: string; after: string }[] };
let edits: Content[] = [];
let reviews: Saved[] = [];
let saved: unknown = null;
let withOther = false;

beforeEach(() => {
  installHighlights();
  stubMatchMedia();
  HTMLMediaElement.prototype.play = () => Promise.resolve();
  HTMLMediaElement.prototype.pause = () => undefined;
  window.history.replaceState(null, "", "/?recording=2&transcript=7&review=1#t=a-token");
  takeToken();
  document.cookie = "dsj-review-pass=; max-age=0; path=/";
  edits = [];
  reviews = [];
  saved = null;
  withOther = false;
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (request: Request) => {
    const path = new URL(request.url).pathname;
    const body: unknown = request.method === "GET" ? null : await request.json();
    if (path === "/api/recordings") return Response.json([recording(withOther)]);
    if (path === "/api/transcripts/7") return Response.json(DOC);
    if (path === "/api/transcripts/8") return Response.json(OTHER);
    if (path === "/api/transcripts/7/edits") {
      const content = request.method === "PUT" ? (body as { content: Content }).content : CONTENT;
      if (request.method === "PUT") edits.push(content);
      return Response.json({ content, names: {}, replaced: null, pad_s: 0.1, edited_at: null, spans: [], unrenderable: null, transcript_sha: "s1" });
    }
    if (path === "/api/transcripts/7/review") {
      if (request.method === "PUT") {
        reviews.push(body as Saved);
        return Response.json(body);
      }
      return Response.json({ document: saved, transcript_sha: "s1" });
    }
    if (path === "/api/transcripts/7/reference") return Response.json({ files: ["a.reference.json", "a.reference.txt"], segments: 3, unchecked: 0 });
    if (path === "/api/recording/2/waveform") return new Response(new Int8Array([-3, 3]));
    return Response.json({ detail: "Not Found" }, { status: 404 });
  });
});

afterEach(() => {
  cleanup();
  act(() => dismissError());
});

const box = () => screen.findByRole("textbox", { name: "What was said" }) as Promise<HTMLTextAreaElement>;
const key = (target: HTMLElement, init: KeyboardEventInit) =>
  act(() => {
    fireEvent.keyDown(target, init);
  });
const items = (content: Content | undefined) => (content ?? []).filter((e): e is Item => e.kind === "item" && e.text !== "");

/** Open Review and take the pass the chooser offers first (F13). */
async function start(navigate?: (href: string) => void, pass = "Every sentence"): Promise<HTMLTextAreaElement> {
  render(<ReviewPage recording={2} transcript={7} {...(navigate === undefined ? {} : { navigate })} />);
  fireEvent.click(await screen.findByRole("button", { name: new RegExp(`^${pass}`) }));
  return box();
}
const audio = () => document.querySelector("audio") as HTMLAudioElement;

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
    await vi.waitFor(() => expect(reviews.at(-1)?.segments[0]?.state).toBe("checked"), { timeout: 2000 });
  });

  it("puts only the changed words into the edit list, once, records them for C, and Shift+Enter goes back (F4, F28)", async () => {
    key(await start(), { key: "Enter", code: "Enter" });
    const field = await box();
    fireEvent.change(field, { target: { value: "delta echo golf" } });
    key(field, { key: "Enter", code: "Enter" });
    await vi.waitFor(() => expect(edits).toHaveLength(1));
    const words = items(edits[0]);
    expect(words.map((e) => e.text)).toContain(" golf");
    // delta was not retyped: it keeps its own time and its engine confidence.
    expect(words.find((e) => e.text === " delta")).toEqual(item(2.0, 0.4, " delta"));
    await vi.waitFor(() => expect(reviews.at(-1)?.corrections).toMatchObject([{ before: "echo", after: "echo golf" }]), { timeout: 2000 });
    key(await box(), { key: "Enter", code: "Enter", shiftKey: true });
    expect((await box()).value).toBe("delta echo golf");
    // Checking it again changes nothing: the box already says what the list says (Review Focus 2).
    key(await box(), { key: "Enter", code: "Enter" });
    await new Promise((resolve) => setTimeout(resolve, 600));
    expect(edits).toHaveLength(1);
  });

  it("sets who said a sentence with Ctrl+2", async () => {
    key(await start(), { key: "2", code: "Digit2", ctrlKey: true });
    await vi.waitFor(() => expect(edits).toHaveLength(1));
    expect(edits[0]?.[0]).toEqual({ kind: "paragraph", speaker: "SPEAKER_01", language: null });
    expect(screen.getByText("Said by Speaker 2")).toBeTruthy();
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
    await vi.waitFor(() => expect(edits).toHaveLength(1));
    expect(items(edits[0]).map((e) => e.text)).toContain(" zulu");
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
    withOther = true;
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
    saved = {
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
    saved = {
      version: 1, transcript_sha: "s0", review_pass: "every", cursor_s: 0, started_at: "x", updated_at: "x",
      segments: [{ start: 0.2, end: 1.3, state: "checked", flags: [], speaker: null, edited: false }],
      corrections: [],
    };
    key(await start(), { key: "Enter", code: "Enter" });
    await vi.waitFor(() => expect(reviews.at(-1)?.transcript_sha).toBe("s1"), { timeout: 2000 });
  });

  it("finishes the pass and saves the answer key", async () => {
    await start();
    for (let i = 0; i < 3; i += 1) key(await box(), { key: "Enter", code: "Enter" });
    expect(await screen.findByRole("heading", { name: "This pass is done" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Save as answer key" }));
    expect(await screen.findByText(/Saved a.reference.json and a.reference.txt beside the transcript/)).toBeTruthy();
    // The key is built from the server's copy, so the last check was saved first.
    expect(reviews.at(-1)?.segments.map((s) => s.state)).toEqual(["checked", "checked", "checked"]);
  });

  it("leaves for the transcript with Esc once everything is saved", async () => {
    const went: string[] = [];
    const field = await start((href) => went.push(href));
    fireEvent.change(field, { target: { value: "alpha bravo charles" } });
    key(field, { key: "Escape", code: "Escape" });
    await vi.waitFor(() => expect(went).toEqual(["/?recording=2&transcript=7"]));
    // What the box held went into the list before leaving.
    expect(items(edits.at(-1)).map((e) => e.text)).toContain(" charles");
  });

  it("leaves the same way by the bar's back arrow (F27)", async () => {
    const went: string[] = [];
    await start((href) => went.push(href));
    fireEvent.click(screen.getByRole("link", { name: "Back to the transcript" }));
    await vi.waitFor(() => expect(went).toEqual(["/?recording=2&transcript=7"]));
  });
});
