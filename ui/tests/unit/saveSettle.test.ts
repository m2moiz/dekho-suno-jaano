// What the export waits for: the server exports its own copy of the edit list,
// so the page must not ask for a file while that copy is behind the page's (#244).
import { cleanup, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const fetchMock = vi.hoisted(() => {
  const mock = vi.fn<(request: Request) => Promise<Response>>();
  globalThis.fetch = mock as unknown as typeof fetch;
  return mock;
});

import { type Editable, keepaliveFits, Latest, NotSaved, useSave } from "../../src/features/edit/editing";
import { currentError, dismissError } from "../../src/features/errors/appError";
import { type Content, Editor, type Entry } from "../../src/lib/editOps";

const PARAGRAPH: Entry = { kind: "paragraph", speaker: null, language: null };
const CONTENT: Content = [
  PARAGRAPH,
  { kind: "item", source: "0", sourceStart: 0.2, length: 0.3, text: " Hello", muted: false, confidence: 0.9 },
  { kind: "item", source: "0", sourceStart: 0.5, length: 0.3, text: " there", muted: false, confidence: 0.9 },
];

const SAVED = { content: [], names: {}, pad_s: 0.05, edited_at: null, spans: null, unrenderable: null, replaced: null, transcript_sha: "sha-1" };

function editable(): Editable {
  return {
    editor: new Editor(CONTENT),
    padS: 0.05,
    renderable: new Latest({ spans: null, unrenderable: null }),
    names: new Latest({}),
    sha: "sha-1",
    replaced: null,
  };
}

/** A PUT the test answers by hand, and the bodies the server was sent. */
function slowServer() {
  const answers: ((reply: Response) => void)[] = [];
  const sent: Content[] = [];
  fetchMock.mockImplementation(async (request) => {
    sent.push(((await request.clone().json()) as { content: Content }).content);
    return new Promise<Response>((resolve) => answers.push(resolve));
  });
  return { answers, sent };
}

const ok = () => Response.json(SAVED);
const muteOne = (editor: Editor, entry: number) => editor.applyEdit({ kind: "mute", entries: [entry], muted: [true] });

afterEach(() => {
  // Unmounts each test's hook, so its "leave?" listener does not outlive it.
  cleanup();
  fetchMock.mockReset();
  dismissError();
});

describe("useSave settle", () => {
  it("resolves at once when nothing is waiting to be saved", async () => {
    const idle = editable();
    const { result } = renderHook(() => useSave(7, idle));
    await result.current.settle();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("waits for a save in flight, and for the change made while it flew", async () => {
    const e = editable();
    const { result } = renderHook(() => useSave(7, e));
    const server = slowServer();
    muteOne(e.editor, 1);
    await vi.waitFor(() => expect(server.sent).toHaveLength(1));
    muteOne(e.editor, 2);
    let done = false;
    const settled = result.current.settle().then(() => {
      done = true;
    });
    server.answers[0]?.(ok());
    // The second change goes in its own request; the export is not let through between the two.
    await vi.waitFor(() => expect(server.sent).toHaveLength(2));
    await Promise.resolve();
    expect(done).toBe(false);
    server.answers[1]?.(ok());
    await settled;
    expect(done).toBe(true);
    const lastSent = server.sent[1] as Content;
    expect(lastSent.map((x) => (x.kind === "item" ? x.muted : null))).toEqual([null, true, true]);
  });

  it("refuses, rather than export stale text, when the save fails", async () => {
    const e = editable();
    const { result } = renderHook(() => useSave(7, e));
    fetchMock.mockResolvedValue(Response.json({ detail: "disk full" }, { status: 500 }));
    muteOne(e.editor, 1);
    await expect(result.current.settle()).rejects.toBeInstanceOf(NotSaved);
  });

  it("tries again for a change an earlier failure left behind", async () => {
    const e = editable();
    const { result } = renderHook(() => useSave(7, e));
    fetchMock.mockResolvedValueOnce(Response.json({ detail: "disk full" }, { status: 500 }));
    muteOne(e.editor, 1);
    await expect(result.current.settle()).rejects.toBeInstanceOf(NotSaved);
    fetchMock.mockResolvedValueOnce(ok());
    await result.current.settle();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("refuses while a drag is under way", async () => {
    const e = editable();
    const { result } = renderHook(() => useSave(7, e));
    e.editor.beginGesture();
    muteOne(e.editor, 1);
    await expect(result.current.settle()).rejects.toBeInstanceOf(NotSaved);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("sends the sha of the transcript the list was loaded against (#249)", async () => {
    const e = editable();
    const { result } = renderHook(() => useSave(7, e));
    const bodies: unknown[] = [];
    fetchMock.mockImplementation(async (request) => {
      bodies.push(await request.clone().json());
      return ok();
    });
    muteOne(e.editor, 1);
    await result.current.settle();
    expect(bodies).toHaveLength(1);
    expect(bodies[0]).toMatchObject({ transcript_sha: "sha-1" });
  });

  it("stops saving once the transcript was made again, and says to reload", async () => {
    const e = editable();
    const { result } = renderHook(() => useSave(7, e));
    const refusal = {
      error: "TranscriptChanged",
      message: "This transcript was made again while it was open. Reload the page.",
      request: "/api/transcripts/7/edits",
    };
    fetchMock.mockImplementation(async () => Response.json(refusal, { status: 409 }));
    muteOne(e.editor, 1);
    await vi.waitFor(() => expect(currentError()?.error).toBe("TranscriptChanged"));
    await vi.waitFor(() => expect(result.current.state).toBe("failed"));
    // Each refused save is kept aside by the server: the page must not send another per keystroke.
    muteOne(e.editor, 2);
    await expect(result.current.settle()).rejects.toThrow(/Reload the page/);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("after the refusal, asks before leaving only for what was typed while it flew", async () => {
    const e = editable();
    renderHook(() => useSave(7, e));
    const server = slowServer();
    const refusal = { error: "TranscriptChanged", message: "Reload the page.", request: "/api/transcripts/7/edits" };
    const leaving = () => {
      const event = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(event);
      return event.defaultPrevented;
    };
    muteOne(e.editor, 1);
    await vi.waitFor(() => expect(server.sent).toHaveLength(1));
    // Typed while the save that will be refused is in flight: the server never sees it.
    muteOne(e.editor, 2);
    server.answers[0]?.(Response.json(refusal, { status: 409 }));
    await vi.waitFor(() => expect(currentError()?.error).toBe("TranscriptChanged"));
    expect(leaving()).toBe(true);
    expect(server.sent).toHaveLength(1);
  });

  it("after the refusal, with nothing typed since, leaves without asking", async () => {
    const e = editable();
    renderHook(() => useSave(7, e));
    const server = slowServer();
    const refusal = { error: "TranscriptChanged", message: "Reload the page.", request: "/api/transcripts/7/edits" };
    muteOne(e.editor, 1);
    await vi.waitFor(() => expect(server.sent).toHaveLength(1));
    server.answers[0]?.(Response.json(refusal, { status: 409 }));
    await vi.waitFor(() => expect(currentError()?.error).toBe("TranscriptChanged"));
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
  });
});

describe("useSave when the page goes away (Task 14 re-review, R1-I1)", () => {
  afterEach(() => {
    Reflect.deleteProperty(document, "visibilityState");
  });

  /** A server that holds every ordinary PUT and answers a keepalive one at once, keeping each body. */
  function holdingServer() {
    const kept: Content[] = [];
    const held: Content[] = [];
    fetchMock.mockImplementation(async (request) => {
      const content = ((await request.clone().json()) as { content: Content }).content;
      if (request.keepalive) {
        kept.push(content);
        return ok();
      }
      held.push(content);
      return new Promise<Response>(() => undefined);
    });
    return { kept, held };
  }

  it("sends the change behind a save in flight with keepalive when the page is hidden", async () => {
    const e = editable();
    renderHook(() => useSave(7, e));
    const server = holdingServer();
    muteOne(e.editor, 1);
    await vi.waitFor(() => expect(server.held).toHaveLength(1));
    // Made while the first save flies: an ordinary save would wait for it, and a phone may never come back.
    muteOne(e.editor, 2);
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "hidden" });
    document.dispatchEvent(new Event("visibilitychange"));
    await vi.waitFor(() => expect(server.kept).toHaveLength(1));
    expect(server.kept[0]).toEqual(e.editor.content);
  });

  it("on pagehide too, and sends nothing when the server has it all", async () => {
    const e = editable();
    renderHook(() => useSave(7, e));
    const server = holdingServer();
    window.dispatchEvent(new Event("pagehide"));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(server.kept).toEqual([]);
    muteOne(e.editor, 1);
    await vi.waitFor(() => expect(server.held).toHaveLength(1));
    window.dispatchEvent(new Event("pagehide"));
    await vi.waitFor(() => expect(server.kept).toHaveLength(1));
  });
});

describe("keepaliveFits", () => {
  it("holds a body to the browser's 64 KiB keepalive limit, counted in UTF-8 bytes", () => {
    expect(keepaliveFits({ content: "x".repeat(60_000) })).toBe(true);
    expect(keepaliveFits({ content: "x".repeat(66_000) })).toBe(false);
    // Urdu letters are two bytes each in UTF-8: 34,000 of them are over.
    expect(keepaliveFits({ content: "\u0628".repeat(34_000) })).toBe(false);
  });
});
