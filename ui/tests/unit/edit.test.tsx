import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fetchMock = vi.hoisted(() => {
  const mock = vi.fn<(request: Request) => Promise<Response>>();
  globalThis.fetch = mock as unknown as typeof fetch;
  return mock;
});

import { mutedWords } from "../../src/features/edit/EditBar";
import { keepReading, readContent } from "../../src/features/edit/readContent";
import { wordsIn } from "../../src/features/edit/selection";
import { currentError, dismissError } from "../../src/features/errors/appError";
import { takeToken } from "../../src/features/session/session";
import { TranscriptPage } from "../../src/features/transcript/TranscriptPage";
import { type Content, Editor, type Entry, type Item, muteRange } from "../../src/lib/editOps";
import { listReply, saves, savedList } from "./editsServer";
import { installHighlights, painted } from "./highlights";
import { stubMatchMedia } from "./media";
import { choose } from "./menus";

function item(sourceStart: number, length: number, text: string, extra: Partial<Item> = {}): Item {
  return { kind: "item", source: "0", sourceStart, length, text, muted: false, confidence: 0.9, ...extra };
}

function paragraph(speaker: string | null = null): Entry {
  return { kind: "paragraph", speaker, language: null };
}

// " Hello" " there" "." then a second paragraph " Fi" "ne" with a pause between the pieces.
const CONTENT: Content = [
  paragraph("SPEAKER_00"),
  item(0, 0.2, ""),
  item(0.2, 0.36, " Hello"),
  item(0.56, 0.24, " there", { confidence: 0.4 }),
  item(0.8, 0.08, "."),
  item(0.88, 0.32, ""),
  paragraph("SPEAKER_01"),
  item(1.2, 0.1, " Fi"),
  item(1.3, 0.05, ""),
  item(1.35, 0.15, "ne"),
];
const SPEAKERS = ["SPEAKER_00", "SPEAKER_01"];

afterEach(() => {
  cleanup();
  act(() => dismissError());
  // wordsIn's articles are put in the page by hand, so taken out by hand.
  document.body.replaceChildren();
});

describe("readContent", () => {
  const edit = readContent(CONTENT, SPEAKERS);

  it("reads the list as the reader draws a transcript: a paragraph a speaker turn", () => {
    expect(edit.reading.turns.map((t) => [t.speaker, t.text])).toEqual([
      [0, " Hello there."],
      [1, " Fine"],
    ]);
  });

  it("gives each word the entries it spans, the pause inside a word included", () => {
    const words = Array.from(edit.first, (first, w) => [first, edit.stop[w]]);
    // " Hello", " there." (word and full stop), " Fine" across the pause inside it.
    expect(words).toEqual([[2, 3], [3, 5], [7, 10]]);
  });

  it("times each word from its own entries and carries their confidence", () => {
    expect(Array.from(edit.reading.words.start)).toEqual([0.2, 0.56, 1.2]);
    expect(edit.reading.words.confidence[1]).toBeCloseTo(0.4);
  });

  it("keeps the same Reading through a mute, and makes a new one when a word changes", () => {
    const muted = new Editor(CONTENT);
    muted.applyEdit(muteRange(CONTENT, 2, 3, true));
    expect(keepReading(edit, readContent(muted.content, SPEAKERS)).reading).toBe(edit.reading);
    const retyped = CONTENT.map((e, i) => (i === 3 ? { ...e, text: " their" } : e));
    expect(keepReading(edit, readContent(retyped, SPEAKERS)).reading).not.toBe(edit.reading);
  });

  it("lists a word as muted when any entry of it is", () => {
    const content = CONTENT.map((e, i) => (i === 9 && e.kind === "item" ? { ...e, muted: true } : e));
    expect(mutedWords(edit, content)).toEqual([2]);
  });
});

describe("wordsIn", () => {
  const edit = readContent(CONTENT, SPEAKERS);

  function article(): { root: HTMLElement; texts: Text[] } {
    const root = document.createElement("article");
    const texts = edit.reading.turns.map((turn, i) => {
      const p = document.createElement("p");
      p.dataset["turn"] = String(i);
      p.textContent = turn.text;
      root.append(p);
      return p.firstChild as Text;
    });
    document.body.append(root);
    return { root, texts };
  }

  function select(start: Text, from: number, end: Text, to: number): Range {
    const range = document.createRange();
    range.setStart(start, from);
    range.setEnd(end, to);
    return range;
  }

  it("finds the words a selection covers, across paragraphs too", () => {
    const { root, texts } = article();
    const [first, second] = texts as [Text, Text];
    expect(wordsIn(edit.reading, root, select(first, 1, first, 6))).toEqual({ first: 0, last: 0 });
    expect(wordsIn(edit.reading, root, select(first, 3, second, 3))).toEqual({ first: 0, last: 2 });
  });

  it("does not take in the next word for the space a selection ends on", () => {
    const { root, texts } = article();
    const first = texts[0] as Text;
    // " Hello " : the space after Hello opens " there".
    expect(wordsIn(edit.reading, root, select(first, 1, first, 7))).toEqual({ first: 0, last: 0 });
  });

  it("reads a selection whose ends sit on elements, as a triple-click's do, by the text it takes in", () => {
    const { root, texts } = article();
    const [first, second] = texts as [Text, Text];
    const range = document.createRange();
    // From before the first paragraph to the start of the second: all of the first.
    range.setStart(root, 0);
    range.setEnd(second.parentElement as HTMLElement, 0);
    expect(wordsIn(edit.reading, root, range)).toEqual({ first: 0, last: 1 });
    range.setStart(first, 3);
    range.setEnd(root, root.childNodes.length);
    expect(wordsIn(edit.reading, root, range)).toEqual({ first: 0, last: 2 });
  });

  it("is null for a collapsed selection or one outside the transcript", () => {
    const { root, texts } = article();
    const first = texts[0] as Text;
    expect(wordsIn(edit.reading, root, select(first, 2, first, 2))).toBeNull();
    const elsewhere = document.createTextNode("elsewhere");
    document.body.append(elsewhere);
    expect(wordsIn(edit.reading, root, select(elsewhere, 0, elsewhere, 4))).toBeNull();
  });
});

describe("TranscriptPage, editing", () => {
  const RECORDING = {
    id: 2,
    path: "/rec/review.m4a",
    size_bytes: 10,
    duration_s: 2,
    content_id: "c",
    audio_codec: "aac",
    video_codec: null,
    first_seen: "2026-09-20T17:00:00+00:00",
    missing: false,
    unreadable: null,
    playhead_s: null,
    title: null,
    transcripts: [
      {
        id: 7,
        finished_at: "2026-09-20T17:05:00+00:00",
        engine: "parakeet",
        model: "mlx-community/parakeet-tdt-0.6b-v3",
        diarized: true,
        speaker_count: 2,
        mark_count: null,
        language: null,
        last_edited_at: null,
        language_tag: null,
        review_checked: null,
        review_total: null,
      },
    ],
  };
  const TRANSCRIPT = {
    audio: "/rec/review.m4a",
    model: "mlx-community/parakeet-tdt-0.6b-v3",
    speakers: SPEAKERS,
    sentences: [{ start: 0.2, end: 0.88, speaker: 0, text: " Hello there.", tokens: [{ t: 0.2, w: " Hello", e: 0.5 }] }],
  };
  let saved: unknown[] = [];
  let registry: ReturnType<typeof installHighlights>;
  let marks: Record<string, unknown>[] = [];
  let removed: number[] = [];

  beforeEach(() => {
    registry = installHighlights();
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
    marks = [];
    removed = [];
    fetchMock.mockReset();
    fetchMock.mockImplementation(async (request: Request) => {
      const path = new URL(request.url).pathname;
      if (path === "/api/recordings") return Response.json([RECORDING]);
      if (path === "/api/transcripts/7") return Response.json(TRANSCRIPT);
      if (path === "/api/transcripts/7/edits" && request.method === "GET") {
        return Response.json({ content: CONTENT, names: {}, pad_s: 0.1, edited_at: null, spans: [], unrenderable: null, replaced: null, transcript_sha: "sha-1" });
      }
      if (path === "/api/transcripts/7/edits" && saves(request)) {
        const content = await savedList(request, (saved.at(-1) as Content | undefined) ?? CONTENT);
        saved.push(content);
        return listReply(content, { edited_at: "2026-10-03T00:00:00+00:00" });
      }
      if (path === "/api/transcripts/7/matches") {
        return Response.json({ matches: [], words_searched: 3, lists: ["en", "ur", "hi", "pa"], recall: "recall: unmeasured" });
      }
      if (path === "/api/recording/2/waveform") return new Response(new Int8Array([-3, 3]));
      // The recording's marks (#67): what the test put there, plus what the page makes.
      if (path === "/api/recordings/2/highlights" && request.method === "GET") return Response.json(marks);
      if (path === "/api/recordings/2/highlights" && request.method === "POST") {
        const body = (await request.json()) as Record<string, unknown>;
        const made = { id: marks.length + 1, recording_id: 2, note: "", made_at: "2026-11-07T00:00:00+00:00", ...body };
        marks.push(made);
        return Response.json(made, { status: 201 });
      }
      const mark = /^\/api\/highlights\/(\d+)$/.exec(path);
      if (mark !== null && request.method === "DELETE") {
        removed.push(Number(mark[1]));
        marks = marks.filter((m) => m.id !== Number(mark[1]));
        return new Response(null, { status: 204 });
      }
      if (mark !== null && request.method === "PATCH") {
        const body = (await request.json()) as Record<string, unknown>;
        marks = marks.map((m) => (m.id === Number(mark[1]) ? { ...m, ...body } : m));
        return Response.json(marks.find((m) => m.id === Number(mark[1])));
      }
      // The reader reads the review for its margin marks (Task 13); none here.
      if (path === "/api/transcripts/7/review") return Response.json({ document: null, transcript_sha: "sha-1" });
      return Response.json({ detail: "Not Found" }, { status: 404 });
    });
  });

  /**
   * Select `word` and wait for the Selection toolbar's `button`, as a person
   * waits for the tools to appear beside the words. The toolbar appears only
   * once React has run the effects that read the selection, so finding it is
   * the wait (a click made in the commit itself, before those effects, did
   * nothing on 2026-10-03).
   */
  async function selectReady(word: string, button = "Mute"): Promise<HTMLButtonElement> {
    act(() => selectWord(word));
    const tools = await screen.findByRole("toolbar", { name: "Selection" });
    const found = within(tools).getByRole("button", { name: button }) as HTMLButtonElement;
    await vi.waitFor(() => expect(found.disabled).toBe(false));
    return found;
  }

  function selectWord(word: string): void {
    for (const p of document.querySelectorAll("article p")) {
      const text = p.firstChild as Text;
      const at = text.data.indexOf(word);
      if (at < 0) continue;
      const range = document.createRange();
      range.setStart(text, at);
      range.setEnd(text, at + word.length);
      const selection = window.getSelection();
      selection?.removeAllRanges();
      selection?.addRange(range);
      document.dispatchEvent(new Event("selectionchange"));
      return;
    }
    throw new Error(`no paragraph holds ${word}`);
  }

  it("marks the selected words, paints them, and keeps them on the recording (#67)", async () => {
    render(<TranscriptPage recording={2} transcript={7} />);
    await screen.findByRole("toolbar", { name: "Edit" });
    fireEvent.click(await selectReady("there", "Mark"));
    choose(await screen.findByRole("menuitem", { name: "Question" }));
    await vi.waitFor(() => expect(marks).toHaveLength(1));
    // "there." is one word: the full stop's token has no space before it (document.ts), and
    // a word ends where the next begins (#60 step 6), so the mark runs to 0.88.
    expect(marks[0]).toMatchObject({ start_s: 0.56, end_s: 0.88, kind: "question", text: "there." });
    await vi.waitFor(() => expect(painted(registry, "dsj-mark-question")).toEqual(["there."]));
    expect(painted(registry, "dsj-mark-key")).toEqual([]);
  });

  it("paints the marks the recording already has when the page opens, by their time (#67)", async () => {
    marks = [{ id: 4, recording_id: 2, start_s: 0.2, end_s: 0.56, kind: "key", note: "", text: "Hello", made_at: "x" }];
    render(<TranscriptPage recording={2} transcript={7} />);
    await screen.findByRole("toolbar", { name: "Edit" });
    await vi.waitFor(() => expect(painted(registry, "dsj-mark-key")).toEqual(["Hello"]));
  });

  it("lists the marks in a drawer from the menu, plays one, and takes one away (#67)", async () => {
    marks = [
      { id: 4, recording_id: 2, start_s: 0.2, end_s: 0.56, kind: "key", note: "the number", text: "Hello", made_at: "x" },
      { id: 5, recording_id: 2, start_s: 1.2, end_s: 1.5, kind: "todo", note: "", text: "Fine", made_at: "x" },
    ];
    render(<TranscriptPage recording={2} transcript={7} />);
    await screen.findByRole("toolbar", { name: "Edit" });
    act(() => fireEvent.click(screen.getByRole("button", { name: "More" })));
    const item = await screen.findByRole("menuitem", { name: /^Marks\d*$/ });
    expect(item.textContent).toContain("2");
    choose(item);
    const list = await screen.findByRole("list", { name: "Marks" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]?.textContent).toContain("Hello");
    expect((within(rows[0] as HTMLElement).getByRole("textbox", { name: "Note" }) as HTMLInputElement).value).toBe("the number");
    expect((within(rows[1] as HTMLElement).getByRole("combobox", { name: "Kind" }) as HTMLSelectElement).value).toBe("todo");
    fireEvent.click(within(rows[1] as HTMLElement).getByRole("button", { name: "Remove mark" }));
    await vi.waitFor(() => expect(removed).toEqual([5]));
    await vi.waitFor(() => expect(within(list).getAllByRole("listitem")).toHaveLength(1));
  });

  it("mutes the selected word, saves it, and Cmd+Z and Cmd+Shift+Z take it back and forth", async () => {
    render(<TranscriptPage recording={2} transcript={7} />);
    await screen.findByRole("toolbar", { name: "Edit" });
    fireEvent.click(await selectReady("there"));
    expect(painted(registry, "dsj-muted")).toEqual(["there."]);
    await vi.waitFor(() => expect(saved).toHaveLength(1));
    const first = saved[0] as Content;
    expect(first.filter((e) => e.kind === "item" && e.muted).map((e) => (e as Item).text)).toEqual([" there", "."]);

    act(() => {
      fireEvent.keyDown(document.body, { key: "z", metaKey: true });
    });
    expect(painted(registry, "dsj-muted")).toEqual([]);
    await vi.waitFor(() => expect(saved).toHaveLength(2));
    act(() => {
      fireEvent.keyDown(document.body, { key: "z", metaKey: true, shiftKey: true });
    });
    expect(painted(registry, "dsj-muted")).toEqual(["there."]);
    await vi.waitFor(() => expect(saved).toHaveLength(3));
    expect(currentError()).toBeNull();
  });

  /** The edit list's saves held until `release` is called, and what happened in what order. */
  function holdSaves(answer: "ok" | "fail" = "ok") {
    const log: string[] = [];
    let release = () => undefined as void;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    const before = fetchMock.getMockImplementation();
    fetchMock.mockImplementation(async (request: Request) => {
      const path = new URL(request.url).pathname;
      if (path === "/api/transcripts/7/edits" && saves(request)) {
        await held;
        log.push("saved");
        if (answer === "fail") return Response.json({ error: "Boom", message: "The disk is full.", request: path }, { status: 500 });
      }
      return (before as (r: Request) => Promise<Response>)(request);
    });
    return { log, release: () => release() };
  }

  it("R opens Review only once the edit in flight is saved, so Review starts from it (Task 13 re-review)", async () => {
    const save = holdSaves();
    render(<TranscriptPage recording={2} transcript={7} navigate={(href) => save.log.push(`went ${href}`)} />);
    await screen.findByRole("toolbar", { name: "Edit" });
    fireEvent.click(await selectReady("there"));
    act(() => {
      fireEvent.keyDown(document.body, { key: "r", code: "KeyR" });
    });
    await new Promise((resolve) => setTimeout(resolve, 50));
    // Nothing has left yet: no navigation, so no browser "Leave site?" either.
    expect(save.log).toEqual([]);
    save.release();
    await vi.waitFor(() => expect(save.log).toEqual(["saved", "went /?recording=2&transcript=7&review=1"]));
    expect(currentError()).toBeNull();
  });

  it("the gold Review link waits the same way", async () => {
    const save = holdSaves();
    render(<TranscriptPage recording={2} transcript={7} navigate={(href) => save.log.push(`went ${href}`)} />);
    await screen.findByRole("toolbar", { name: "Edit" });
    fireEvent.click(await selectReady("there"));
    fireEvent.click(screen.getByRole("link", { name: "Review" }));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(save.log).toEqual([]);
    save.release();
    await vi.waitFor(() => expect(save.log).toEqual(["saved", "went /?recording=2&transcript=7&review=1"]));
  });

  it("stays in the reader and says so when the edit cannot be saved", async () => {
    const save = holdSaves("fail");
    render(<TranscriptPage recording={2} transcript={7} navigate={(href) => save.log.push(`went ${href}`)} />);
    await screen.findByRole("toolbar", { name: "Edit" });
    fireEvent.click(await selectReady("there"));
    act(() => {
      fireEvent.keyDown(document.body, { key: "r", code: "KeyR" });
    });
    save.release();
    await vi.waitFor(() => expect(currentError()?.message).toMatch(/^Review did not open/));
    // The one error dialog shows this message in place of the save's own, so
    // it carries the server's reason too (Task 13 re-review round 2).
    expect(currentError()?.message).toContain("The disk is full.");
    // A 500 may have been written all the same: the list is read, found without
    // the change, and the change sent once more, which fails too (#251 fix round 1).
    expect(save.log).toEqual(["saved", "saved"]);
  });

  it("offers Unmute in place of Mute once every selected word is muted, and it takes the mute away", async () => {
    render(<TranscriptPage recording={2} transcript={7} />);
    await screen.findByRole("toolbar", { name: "Edit" });
    fireEvent.click(await selectReady("there"));
    expect(painted(registry, "dsj-muted")).toEqual(["there."]);
    const tools = screen.getByRole("toolbar", { name: "Selection" });
    expect(within(tools).queryByRole("button", { name: "Mute" })).toBeNull();
    fireEvent.click(within(tools).getByRole("button", { name: "Unmute" }));
    expect(painted(registry, "dsj-muted")).toEqual([]);
    await vi.waitFor(() => expect(saved).toHaveLength(2));
  });

  it("on a phone the word toolbar goes once playback starts, so it never sits over the line being read (UAT 8)", async () => {
    const before = window.matchMedia;
    const play = HTMLMediaElement.prototype.play;
    const rect = Range.prototype.getBoundingClientRect;
    stubMatchMedia((query) => query.includes("coarse"));
    // Playback runs the playhead, which measures the word it paints.
    HTMLMediaElement.prototype.play = () => Promise.resolve();
    Range.prototype.getBoundingClientRect = () => new DOMRect();
    try {
      render(<TranscriptPage recording={2} transcript={7} />);
      await screen.findByRole("toolbar", { name: "Edit" });
      await selectReady("there");
      // Play, from the rail: the selection and its toolbar go.
      act(() => {
        document.querySelector("audio")?.dispatchEvent(new Event("play"));
      });
      await vi.waitFor(() => expect(screen.queryByRole("toolbar", { name: "Selection" })).toBeNull());
      // Hear, from the toolbar itself, keeps it: the words are being listened to before a fix.
      fireEvent.click(await selectReady("there", "Hear"));
      act(() => {
        document.querySelector("audio")?.dispatchEvent(new Event("play"));
      });
      await new Promise((resolve) => setTimeout(resolve, 50));
      expect(screen.queryByRole("toolbar", { name: "Selection" })).not.toBeNull();
    } finally {
      window.matchMedia = before;
      HTMLMediaElement.prototype.play = play;
      Range.prototype.getBoundingClientRect = rect;
    }
  });

  it("keeps Undo, Redo and whether it is saved in the Edit toolbar, and nothing for the selection there", async () => {
    render(<TranscriptPage recording={2} transcript={7} />);
    const bar = await screen.findByRole("toolbar", { name: "Edit" });
    expect(within(bar).getAllByRole("button").map((b) => b.getAttribute("aria-label"))).toEqual(["Undo", "Redo"]);
    // "Saved" says nothing before there is an edit for it to be about.
    expect(within(bar).getByRole("status").textContent).toBe("");
    fireEvent.click(await selectReady("there"));
    await vi.waitFor(() => expect(within(bar).getByRole("status").textContent).toBe("Saved"));
  });

  it("leaves Cmd+Z to a text field being typed in", async () => {
    render(<TranscriptPage recording={2} transcript={7} />);
    await screen.findByRole("toolbar", { name: "Edit" });
    fireEvent.click(await selectReady("Hello"));
    const field = document.createElement("input");
    document.body.append(field);
    act(() => {
      fireEvent.keyDown(field, { key: "z", metaKey: true });
    });
    expect(painted(registry, "dsj-muted")).toEqual(["Hello"]);
    field.remove();
  });

  it("offers no editing at all until the edit list has arrived", async () => {
    // A mute made before the list arrived would be lost when it landed. The
    // page never offers one: it draws nothing editable until the list is in.
    let release: () => void = () => undefined;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    const answer = fetchMock.getMockImplementation() as (request: Request) => Promise<Response>;
    fetchMock.mockImplementation(async (request: Request) => {
      const path = new URL(request.url).pathname;
      if (path === "/api/transcripts/7/edits" && request.method === "GET") await held;
      return answer(request);
    });
    render(<TranscriptPage recording={2} transcript={7} />);
    await vi.waitFor(() =>
      expect(fetchMock.mock.calls.some(([r]) => new URL(r.url).pathname === "/api/transcripts/7")).toBe(true),
    );
    await new Promise((resolve) => setTimeout(resolve, 200));
    expect(screen.queryByRole("toolbar", { name: "Edit" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Mute" })).toBeNull();
    expect(document.querySelectorAll("article p")).toHaveLength(0);
    release();
    await screen.findByRole("toolbar", { name: "Edit" });
    fireEvent.click(await selectReady("there"));
    expect(painted(registry, "dsj-muted")).toEqual(["there."]);
  });

  it("says, in the key sheet, that edits are kept and their undo history is not", async () => {
    render(<TranscriptPage recording={2} transcript={7} />);
    await screen.findByRole("toolbar", { name: "Edit" });
    act(() => fireEvent.keyDown(document.body, { key: "?", code: "Slash", shiftKey: true }));
    // KeySheet is App's; this page only asks for it, so the request is read back here.
    const { KeySheet, hideKeys } = await import("../../src/features/shell/KeySheet");
    render(<KeySheet />);
    expect((await screen.findByRole("dialog")).textContent).toContain("closing or reloading it keeps the edits and forgets their undo");
    act(() => hideKeys());
  });
});
