// What the export waits for: the server exports its own copy of the edit list,
// so the page must not ask for a file while that copy is behind the page's (#244).
import { cleanup, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const fetchMock = vi.hoisted(() => {
  const mock = vi.fn<(request: Request) => Promise<Response>>();
  globalThis.fetch = mock as unknown as typeof fetch;
  return mock;
});

import { type Editable, keepaliveFits, Latest, NotSaved, Outdated, useSave } from "../../src/features/edit/editing";
import { currentError, dismissError } from "../../src/features/errors/appError";
import { type Content, Editor, type Entry } from "../../src/lib/editOps";
import { type Splice, spliced } from "../../src/lib/splice";

const PARAGRAPH: Entry = { kind: "paragraph", speaker: null, language: null };
const CONTENT: Content = [
  PARAGRAPH,
  { kind: "item", source: "0", sourceStart: 0.2, length: 0.3, text: " Hello", muted: false, confidence: 0.9 },
  { kind: "item", source: "0", sourceStart: 0.5, length: 0.3, text: " there", muted: false, confidence: 0.9 },
];

/** What a patch answers (#251): the new list's sha, never the entries. */
const SAVED = (listSha = "list-2") => ({ list_sha: listSha, edited_at: "x", spans: null, unrenderable: null });

function editable(): Editable {
  const editor = new Editor(CONTENT);
  return {
    editor,
    padS: 0.05,
    renderable: new Latest({ spans: null, unrenderable: null }),
    names: new Latest({}),
    sha: "sha-1",
    replaced: null,
    saved: { content: editor.content, listSha: "list-1" },
  };
}

type Sent = { method: string; path: string; keepalive: boolean; body: Record<string, unknown> };

/** Requests the test answers by hand, and what each was: method, body, and whether it was sent with keepalive. */
function slowServer() {
  const answers: ((reply: Response) => void)[] = [];
  const sent: Sent[] = [];
  fetchMock.mockImplementation(async (request) => {
    const body = (await request.clone().json()) as Record<string, unknown>;
    sent.push({ method: request.method, path: new URL(request.url).pathname, keepalive: request.keepalive, body });
    return new Promise<Response>((resolve) => answers.push(resolve));
  });
  return { answers, sent };
}

/** `content` with each patch sent made in turn, as the server makes it. */
function applied(content: Content, sent: Sent[]): Content {
  return sent
    .filter((s) => s.method === "PATCH")
    .reduce<Content>((list, { body }) => spliced(list, body as unknown as Splice<Entry>), content);
}

const ok = (listSha?: string) => Response.json(SAVED(listSha));
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
    // Nothing more goes while the first flies: the second change is made against the list its answer names (#251).
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(server.sent).toHaveLength(1);
    server.answers[0]?.(ok("list-2"));
    // The second change goes in its own request; the export is not let through between the two.
    await vi.waitFor(() => expect(server.sent).toHaveLength(2));
    await Promise.resolve();
    expect(done).toBe(false);
    server.answers[1]?.(ok("list-3"));
    await settled;
    expect(done).toBe(true);
    expect(server.sent.map((s) => [s.method, s.body.list_sha, s.body.start, s.body.delete])).toEqual([
      ["PATCH", "list-1", 1, 1],
      ["PATCH", "list-2", 2, 1],
    ]);
    expect(applied(CONTENT, server.sent)).toEqual(e.editor.content);
    expect(e.saved).toEqual({ content: e.editor.content, listSha: "list-3" });
  });

  it("sends one entry for one change, with keepalive, never the whole list (#251)", async () => {
    const e = editable();
    const { result } = renderHook(() => useSave(7, e));
    const server = slowServer();
    muteOne(e.editor, 2);
    await vi.waitFor(() => expect(server.sent).toHaveLength(1));
    expect(server.sent[0]).toEqual({
      method: "PATCH",
      path: "/api/transcripts/7/edits",
      keepalive: true,
      body: { transcript_sha: "sha-1", list_sha: "list-1", start: 2, delete: 1, insert: [{ ...CONTENT[2], muted: true }] },
    });
    server.answers[0]?.(ok());
    await result.current.settle();
  });

  it("sends nothing for a change undone before it was sent", async () => {
    const e = editable();
    const { result } = renderHook(() => useSave(7, e));
    const server = slowServer();
    muteOne(e.editor, 1);
    await vi.waitFor(() => expect(server.sent).toHaveLength(1));
    muteOne(e.editor, 2);
    e.editor.undo();
    server.answers[0]?.(ok());
    await result.current.settle();
    expect(server.sent).toHaveLength(1);
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
    // The save, then the read that asks whether it landed after all (#251 fix round 1): both fail.
    fetchMock.mockResolvedValueOnce(Response.json({ detail: "disk full" }, { status: 500 }));
    fetchMock.mockResolvedValueOnce(Response.json({ detail: "disk full" }, { status: 500 }));
    muteOne(e.editor, 1);
    await expect(result.current.settle()).rejects.toBeInstanceOf(NotSaved);
    fetchMock.mockResolvedValueOnce(ok());
    await result.current.settle();
    expect(fetchMock.mock.calls.map(([r]) => r.method)).toEqual(["PATCH", "GET", "PATCH"]);
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
    expect(bodies[0]).toMatchObject({ transcript_sha: "sha-1", list_sha: "list-1" });
  });

  const madeAgain = { error: "TranscriptChanged", message: "This transcript was made again while it was open. Reload the page.", request: "/api/transcripts/7/edits" };
  const keptAside = { ...madeAgain, message: "They are kept beside the library as abc.json. Reload the page." };

  it("stops saving once the transcript was made again, sends the list whole to be kept aside, and says to reload", async () => {
    const e = editable();
    const { result } = renderHook(() => useSave(7, e));
    const sent: string[] = [];
    fetchMock.mockImplementation(async (request) => {
      sent.push(request.method);
      return Response.json(request.method === "PUT" ? keptAside : madeAgain, { status: 409 });
    });
    muteOne(e.editor, 1);
    await vi.waitFor(() => expect(currentError()?.message).toBe(keptAside.message));
    await vi.waitFor(() => expect(result.current.state).toBe("failed"));
    // Each refused save is kept aside by the server: the page must not send another per keystroke.
    muteOne(e.editor, 2);
    await expect(result.current.settle()).rejects.toThrow(/Reload the page/);
    expect(sent).toEqual(["PATCH", "PUT"]);
    const whole = (await (fetchMock.mock.calls[1]?.[0] as Request).json()) as { content: Content };
    expect(whole.content.map((x) => (x.kind === "item" ? x.muted : null))).toEqual([null, true, false]);
  });

  it("after the refusal, asks before leaving only for what was typed while it flew", async () => {
    const e = editable();
    renderHook(() => useSave(7, e));
    const server = slowServer();
    const leaving = () => {
      const event = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(event);
      return event.defaultPrevented;
    };
    muteOne(e.editor, 1);
    await vi.waitFor(() => expect(server.sent).toHaveLength(1));
    // Typed while the save that will be refused is in flight: the server never sees it.
    muteOne(e.editor, 2);
    server.answers[0]?.(Response.json(madeAgain, { status: 409 }));
    await vi.waitFor(() => expect(server.sent).toHaveLength(2));
    server.answers[1]?.(Response.json(keptAside, { status: 409 }));
    await vi.waitFor(() => expect(currentError()?.error).toBe("TranscriptChanged"));
    expect(leaving()).toBe(true);
    expect(server.sent.map((s) => s.method)).toEqual(["PATCH", "PUT"]);
  });

  it("after the refusal, with nothing typed since, leaves without asking", async () => {
    const e = editable();
    renderHook(() => useSave(7, e));
    const server = slowServer();
    muteOne(e.editor, 1);
    await vi.waitFor(() => expect(server.sent).toHaveLength(1));
    server.answers[0]?.(Response.json(madeAgain, { status: 409 }));
    await vi.waitFor(() => expect(server.sent).toHaveLength(2));
    server.answers[1]?.(Response.json(keptAside, { status: 409 }));
    await vi.waitFor(() => expect(currentError()?.error).toBe("TranscriptChanged"));
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
  });

  it("stops saving when the list was changed in another tab, says so, and leaving still asks (#251)", async () => {
    const e = editable();
    const { result } = renderHook(() => useSave(7, e));
    const changed = { error: "ListChanged", message: "This transcript's edits were changed in another tab. Reload the page.", request: "/api/transcripts/7/edits" };
    // The other tab's list: neither this page's list before the change nor after it.
    const theirs = CONTENT.map((x) => (x.kind === "item" ? { ...x, text: `${x.text}!` } : x));
    fetchMock.mockImplementation(async (request) =>
      request.method === "GET"
        ? Response.json({ content: theirs, names: {}, pad_s: 0.05, edited_at: null, spans: null, unrenderable: null, replaced: null, transcript_sha: "sha-1", list_sha: "list-theirs" })
        : Response.json(changed, { status: 409 }),
    );
    muteOne(e.editor, 1);
    await vi.waitFor(() => expect(currentError()?.error).toBe("ListChanged"));
    muteOne(e.editor, 2);
    await expect(result.current.settle()).rejects.toBeInstanceOf(Outdated);
    // Read once to rule out its own patch landing; never sent whole: that would write over the other tab's list.
    expect(fetchMock.mock.calls.map(([r]) => r.method)).toEqual(["PATCH", "GET"]);
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
  });

  it("a rename waits for the patch in flight, and the next patch is made against the sha the rename answered (#251)", async () => {
    const e = editable();
    const { result } = renderHook(() => useSave(7, e));
    const server = slowServer();
    muteOne(e.editor, 1);
    await vi.waitFor(() => expect(server.sent).toHaveLength(1));
    const renamed = result.current.rename({ SPEAKER_00: "Ali" });
    muteOne(e.editor, 2);
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(server.sent).toHaveLength(1);
    server.answers[0]?.(ok("list-2"));
    await vi.waitFor(() => expect(server.sent).toHaveLength(2));
    expect(server.sent[1]).toMatchObject({ method: "PUT", path: "/api/transcripts/7/names" });
    server.answers[1]?.(Response.json({ names: { SPEAKER_00: "Ali" }, list_sha: "list-named" }));
    expect(await renamed).toEqual({ SPEAKER_00: "Ali" });
    expect(e.names.value).toEqual({ SPEAKER_00: "Ali" });
    await vi.waitFor(() => expect(server.sent).toHaveLength(3));
    expect(server.sent[2]?.body).toMatchObject({ list_sha: "list-named", start: 2 });
    server.answers[2]?.(ok("list-4"));
    await result.current.settle();
  });
});

describe("a rename names the list it was made against (#274, final review C1)", () => {
  /** What the server holds after another tab or the phone deleted " Hello": a list of another shape. */
  const PHONES: Content = [CONTENT[0] as Entry, CONTENT[2] as Entry];
  const listReply = (content: Content, names: Record<string, string>, listSha: string) =>
    Response.json({ content, names, pad_s: 0.05, edited_at: null, spans: null, unrenderable: null, replaced: null, transcript_sha: "sha-1", list_sha: listSha });

  it("sends the list's sha and the transcript's with the names", async () => {
    const e = editable();
    const { result } = renderHook(() => useSave(7, e));
    const server = slowServer();
    const renamed = result.current.rename({ SPEAKER_00: "Ali" });
    await vi.waitFor(() => expect(server.sent).toHaveLength(1));
    expect(server.sent[0]).toMatchObject({ method: "PUT", path: "/api/transcripts/7/names", body: { names: { SPEAKER_00: "Ali" }, list_sha: "list-1", transcript_sha: "sha-1" } });
    server.answers[0]?.(Response.json({ names: { SPEAKER_00: "Ali" }, list_sha: "list-named" }));
    await renamed;
    expect(e.saved.listSha).toBe("list-named");
  });

  it("the reviewer's probe: refused after the phone's patch, the page keeps its own sha, says to reload, and its next correction is never sent", async () => {
    const e = editable();
    const { result } = renderHook(() => useSave(7, e));
    const changed = { error: "ListChanged", message: "This transcript's edits were changed in another tab or window after this page loaded them, so these names were not saved. Reload the page to load them again.", request: "/api/transcripts/7/names" };
    fetchMock.mockImplementation(async (request) =>
      request.method === "GET" ? listReply(PHONES, {}, "list-phone") : Response.json(changed, { status: 409 }),
    );
    // The server's own refusal, for the dialog; a second rename is not even sent.
    await expect(result.current.rename({ SPEAKER_00: "Ali" })).rejects.toMatchObject({ name: "ListChanged" });
    await expect(result.current.rename({ SPEAKER_00: "Ali" })).rejects.toBeInstanceOf(Outdated);
    expect(e.saved.listSha).toBe("list-1");
    expect(e.names.value).toEqual({});
    await vi.waitFor(() => expect(result.current.outdated).toMatch(/Reload the page/));
    // The correction the laptop makes next: nothing goes, so nothing lands in the wrong place.
    e.editor.applyEdit({ kind: "correct", start: 2, stop: 3, entries: [{ ...(CONTENT[2] as Entry), text: " where" } as Entry] });
    await expect(result.current.settle()).rejects.toBeInstanceOf(Outdated);
    expect(fetchMock.mock.calls.map(([r]) => r.method)).toEqual(["PUT", "GET"]);
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
  });

  it("a rename whose answer was lost: the list read once holds the names asked for, so its sha is taken", async () => {
    const e = editable();
    const { result } = renderHook(() => useSave(7, e));
    let puts = 0;
    fetchMock.mockImplementation(async (request) => {
      if (request.method === "GET") return listReply(CONTENT, { SPEAKER_00: "Ali" }, "list-named");
      puts += 1;
      throw new TypeError("Failed to fetch");
    });
    expect(await result.current.rename({ SPEAKER_00: " Ali " })).toEqual({ SPEAKER_00: "Ali" });
    expect(puts).toBe(1);
    expect(e.saved.listSha).toBe("list-named");
    expect(result.current.outdated).toBeNull();
  });

  it("a rename lost before it arrived is sent again, once, against the sha read", async () => {
    const e = editable();
    const { result } = renderHook(() => useSave(7, e));
    const bodies: Record<string, unknown>[] = [];
    fetchMock.mockImplementation(async (request) => {
      if (request.method === "GET") return listReply(CONTENT, {}, "list-1");
      bodies.push((await request.json()) as Record<string, unknown>);
      if (bodies.length === 1) throw new TypeError("Failed to fetch");
      return Response.json({ names: { SPEAKER_00: "Ali" }, list_sha: "list-named" });
    });
    expect(await result.current.rename({ SPEAKER_00: "Ali" })).toEqual({ SPEAKER_00: "Ali" });
    expect(bodies.map((b) => b.list_sha)).toEqual(["list-1", "list-1"]);
    expect(e.saved.listSha).toBe("list-named");
  });
});

describe("useSave when the page goes away (Task 14 re-review, R1-I1; #251)", () => {
  afterEach(() => {
    Reflect.deleteProperty(document, "visibilityState");
  });

  const hide = () => {
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "hidden" });
    document.dispatchEvent(new Event("visibilitychange"));
  };

  it("hidden while a patch flies: nothing goes beside it; the change behind it follows its answer, against its sha, with keepalive", async () => {
    const e = editable();
    renderHook(() => useSave(7, e));
    const server = slowServer();
    muteOne(e.editor, 1);
    await vi.waitFor(() => expect(server.sent).toHaveLength(1));
    // Made while the first save flies, then the page is hidden: a patch sent now
    // would be made against the same list as the one in flight.
    muteOne(e.editor, 2);
    hide();
    window.dispatchEvent(new Event("pagehide"));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(server.sent).toHaveLength(1);
    expect(server.sent[0]?.keepalive).toBe(true);
    server.answers[0]?.(ok("list-2"));
    await vi.waitFor(() => expect(server.sent).toHaveLength(2));
    expect(server.sent[1]).toMatchObject({ keepalive: true, body: { list_sha: "list-2" } });
    expect(applied(CONTENT, server.sent)).toEqual(e.editor.content);
  });

  it("hidden after a save failed: what the server lacks goes at once; nothing when it has it all", async () => {
    const e = editable();
    renderHook(() => useSave(7, e));
    const server = slowServer();
    window.dispatchEvent(new Event("pagehide"));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(server.sent).toEqual([]);
    muteOne(e.editor, 1);
    await vi.waitFor(() => expect(server.sent).toHaveLength(1));
    server.answers[0]?.(Response.json({ error: "Boom", message: "The disk is full.", request: "/api/transcripts/7/edits" }, { status: 500 }));
    await vi.waitFor(() => expect(currentError()?.error).toBe("Boom"));
    hide();
    await vi.waitFor(() => expect(server.sent).toHaveLength(2));
    expect(server.sent[1]).toMatchObject({ keepalive: true, body: { list_sha: "list-1", start: 1 } });
  });

  it("a change too big for its share of the keepalive limit goes as an ordinary request", async () => {
    const e = editable();
    const { result } = renderHook(() => useSave(7, e));
    const server = slowServer();
    e.editor.applyEdit({ kind: "correct", start: 1, stop: 2, entries: [{ ...(CONTENT[1] as Entry), text: "x".repeat(40_000) } as Entry] });
    await vi.waitFor(() => expect(server.sent).toHaveLength(1));
    expect(server.sent[0]?.keepalive).toBe(false);
    server.answers[0]?.(ok());
    await result.current.settle();
  });
});

describe("useSave when a patch's fate is in doubt (#251 fix round 1, I1)", () => {
  // A server that holds a list and its sha, and applies patches as the real one does.
  // `fault` says what happens to the next patch: its answer lost after it was applied
  // (a phone's Wi-Fi handing over mid-request), a 500 after it was written, or the
  // request lost before it arrived.
  type Fault = "none" | "lost-after" | "500-after" | "lost-before";
  function listServer() {
    const state = { content: CONTENT as Content, saves: 0, fault: "none" as Fault, patches: [] as string[], reads: 0 };
    const sha = () => `list-${state.saves + 1}`;
    fetchMock.mockImplementation(async (request) => {
      if (request.method === "GET") {
        state.reads += 1;
        return Response.json({
          content: state.content, names: {}, pad_s: 0.05, edited_at: null, spans: null, unrenderable: null,
          replaced: null, transcript_sha: "sha-1", list_sha: sha(),
        });
      }
      const body = (await request.json()) as Splice<Entry> & { list_sha: string };
      state.patches.push(body.list_sha);
      const fault = state.fault;
      state.fault = "none";
      if (fault === "lost-before") throw new TypeError("Failed to fetch");
      if (body.list_sha !== sha()) {
        return Response.json({ error: "ListChanged", message: "This transcript's edits were changed in another tab. Reload the page.", request: "/api/transcripts/7/edits" }, { status: 409 });
      }
      state.content = spliced(state.content, body);
      state.saves += 1;
      if (fault === "lost-after") throw new TypeError("Failed to fetch");
      if (fault === "500-after") return Response.json({ error: "OSError", message: "The library could not be written.", request: "/api/transcripts/7/edits" }, { status: 500 });
      return Response.json(SAVED(sha()));
    });
    return state;
  }

  const mutedOf = (content: Content) => content.map((x) => (x.kind === "item" ? x.muted : null));

  for (const fault of ["lost-after", "500-after"] as const) {
    it(`a patch applied but answered ${fault === "lost-after" ? "never" : "with a 500"}: the next change is made against the server's sha, and nothing is lost`, async () => {
      const e = editable();
      const { result } = renderHook(() => useSave(7, e));
      const server = listServer();
      server.fault = fault;
      muteOne(e.editor, 1);
      await vi.waitFor(() => expect(server.patches.length).toBeGreaterThanOrEqual(1));
      muteOne(e.editor, 2);
      await result.current.settle();
      expect(server.reads).toBe(1);
      expect(mutedOf(server.content)).toEqual([null, true, true]);
      expect(e.saved.listSha).toBe("list-3");
      expect(currentError()?.error).not.toBe("ListChanged");
      expect(result.current.state).toBe("saved");
    });
  }

  it("the reviewer's probe: answer lost after the mute was applied, then a second change is not refused as another tab's", async () => {
    const e = editable();
    const { result } = renderHook(() => useSave(7, e));
    const server = listServer();
    server.fault = "lost-after";
    muteOne(e.editor, 1);
    await vi.waitFor(() => expect(server.reads).toBe(1));
    await vi.waitFor(() => expect(result.current.state).toBe("saved"));
    expect(e.saved.listSha).toBe("list-2");
    muteOne(e.editor, 2);
    await result.current.settle();
    expect(server.patches).toEqual(["list-1", "list-2"]);
    expect(mutedOf(server.content)).toEqual([null, true, true]);
  });

  it("a patch lost before it arrived is sent again, once, against the same sha", async () => {
    const e = editable();
    const { result } = renderHook(() => useSave(7, e));
    const server = listServer();
    server.fault = "lost-before";
    muteOne(e.editor, 1);
    await result.current.settle();
    expect(server.patches).toEqual(["list-1", "list-1"]);
    expect(server.reads).toBe(1);
    expect(mutedOf(server.content)).toEqual([null, true, false]);
    expect(currentError()).toBeNull();
  });

  it("a list really changed in another tab: the page stops saving and says to reload, as before", async () => {
    const e = editable();
    const { result } = renderHook(() => useSave(7, e));
    const server = listServer();
    // Another tab muted " there" and saved it.
    server.content = spliced(CONTENT, { start: 2, delete: 1, insert: [{ ...(CONTENT[2] as Entry), muted: true } as Entry] });
    server.saves = 1;
    muteOne(e.editor, 1);
    await expect(result.current.settle()).rejects.toBeInstanceOf(Outdated);
    expect(currentError()?.error).toBe("ListChanged");
    expect(server.reads).toBe(1);
    expect(server.patches).toEqual(["list-1"]);
    expect(mutedOf(server.content)).toEqual([null, false, true]);
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
