// Review mode's mocked server and fixtures, shared by the desk's tests
// (review.test.tsx) and the phone card's (review-phone.test.tsx) (F21).
//
// The fetch mock itself stays in each test file, made in `vi.hoisted`: the
// API client takes `globalThis.fetch` when it is created, on import, so the
// mock must be in place before any app module loads.
import { act, fireEvent, render, screen } from "@testing-library/react";
import type { Mock } from "vitest";

import { ReviewPage } from "../../src/features/review/ReviewPage";
import { takeToken } from "../../src/features/session/session";
import type { Content, Entry, Item } from "../../src/lib/editOps";
import { installHighlights } from "./highlights";
import { stubMatchMedia } from "./media";

export function item(sourceStart: number, length: number, text: string, confidence: number | null = 0.95): Item {
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

/** What the mocked server was sent, and how a test sets it up; reset before each test. */
export const server = {
  /** Every edit list PUT, in order. */
  edits: [] as Content[],
  /** Every review document PUT, in order. */
  reviews: [] as Saved[],
  /** The review document the server holds on opening. */
  saved: null as unknown,
  /** Whether a second transcript of the recording exists (the second opinion). */
  withOther: false,
  /** Whether the edit list's PUT is refused as made against an older transcript (409). */
  refuseEdits: false,
  /** Every request sent with `keepalive`, the kind that outlives the page: its path and body. */
  kept: [] as { path: string; body: unknown }[],
  /** The edit list the server holds, when a test needs another than CONTENT. */
  content: null as Content | null,
  /** The page torn down: from now on no ordinary PUT reaches the server (the browser cancels it); a keepalive one still does. */
  down: false,
};

/** CONTENT with one word retyped, as a correction made elsewhere (the reader, another device) leaves it. */
export function contentWith(word: string, retyped: string): Content {
  return CONTENT.map((entry) => (entry.kind === "item" && entry.text === ` ${word}` ? { ...entry, text: ` ${retyped}` } : entry));
}

/** CONTENT followed by a third speaker's `words` filler words, a list far over the 64 KiB a keepalive request may carry. */
export function longContent(words: number): Content {
  const long: Entry[] = [...CONTENT, para("SPEAKER_02")];
  let t = 3.9;
  for (let w = 0; w < words; w += 1) {
    long.push(gap(t, 0.1), item(t + 0.1, 0.3, ` w${w}${w % 12 === 11 ? "." : ""}`));
    t += 0.4;
  }
  return long;
}

/** The page going away as a phone does it: hidden (an app switch, a tab evicted), or `pagehide` (a swipe back, a reload). */
export function hidePage(how: "visibilitychange" | "pagehide"): void {
  if (how === "pagehide") {
    window.dispatchEvent(new Event("pagehide"));
    return;
  }
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "hidden" });
  document.dispatchEvent(new Event("visibilitychange"));
}

/** Undo hidePage's stub, so the next test's page is in view. */
export function showPage(): void {
  Reflect.deleteProperty(document, "visibilityState");
}

/**
 * Before each test: the server mocked through `fetchMock`, the media and the
 * cookies cleared, and `matchMedia` answering with `matches` (a laptop by
 * default; a phone is `(q) => q.includes("coarse")`).
 */
export function serveReview(fetchMock: Mock<(request: Request) => Promise<Response>>, matches?: (query: string) => boolean): void {
  installHighlights();
  stubMatchMedia(matches);
  HTMLMediaElement.prototype.play = () => Promise.resolve();
  HTMLMediaElement.prototype.pause = () => undefined;
  window.history.replaceState(null, "", "/?recording=2&transcript=7&review=1#t=a-token");
  takeToken();
  document.cookie = "dsj-review-pass=; max-age=0; path=/";
  server.edits = [];
  server.reviews = [];
  server.saved = null;
  server.withOther = false;
  server.refuseEdits = false;
  server.kept = [];
  server.content = null;
  server.down = false;
  window.localStorage.clear();
  document.cookie = "dsj-speed=; max-age=0; path=/";
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (request: Request) => {
    const path = new URL(request.url).pathname;
    const body: unknown = request.method === "GET" ? null : await request.json();
    if (request.keepalive) server.kept.push({ path, body });
    else if (server.down && request.method === "PUT") return new Promise<Response>(() => undefined);
    if (path === "/api/recordings") return Response.json([recording(server.withOther)]);
    if (path === "/api/transcripts/7") return Response.json(DOC);
    if (path === "/api/transcripts/8") return Response.json(OTHER);
    if (path === "/api/transcripts/7/edits") {
      if (request.method === "PUT" && server.refuseEdits) {
        return Response.json(
          { error: "TranscriptChanged", message: "This transcript was made again while it was open. Reload the page.", request: path },
          { status: 409 },
        );
      }
      const content = request.method === "PUT" ? (body as { content: Content }).content : (server.content ?? CONTENT);
      if (request.method === "PUT") {
        server.edits.push(content);
        server.content = content;
      }
      return Response.json({ content, names: {}, replaced: null, pad_s: 0.1, edited_at: null, spans: [], unrenderable: null, transcript_sha: "s1" });
    }
    if (path === "/api/transcripts/7/review") {
      if (request.method === "PUT") {
        server.reviews.push(body as Saved);
        return Response.json(body);
      }
      return Response.json({ document: server.saved, transcript_sha: "s1" });
    }
    if (path === "/api/transcripts/7/reference") return Response.json({ files: ["a.reference.json", "a.reference.txt"], segments: 3, unchecked: 0 });
    if (path === "/api/recording/2/waveform") return new Response(new Int8Array([-3, 3]));
    return Response.json({ detail: "Not Found" }, { status: 404 });
  });
}

export const box = () => screen.findByRole("textbox", { name: "What was said" }) as Promise<HTMLTextAreaElement>;
export const key = (target: HTMLElement, init: KeyboardEventInit) =>
  act(() => {
    fireEvent.keyDown(target, init);
  });
export const items = (content: Content | undefined) => (content ?? []).filter((e): e is Item => e.kind === "item" && e.text !== "");
export const audio = () => document.querySelector("audio") as HTMLAudioElement;

/** Open Review and take the pass the chooser offers first (F13). */
export async function start(navigate?: (href: string) => void, pass = "Every sentence"): Promise<HTMLTextAreaElement> {
  render(<ReviewPage recording={2} transcript={7} {...(navigate === undefined ? {} : { navigate })} />);
  fireEvent.click(await screen.findByRole("button", { name: new RegExp(`^${pass}`) }));
  return box();
}
