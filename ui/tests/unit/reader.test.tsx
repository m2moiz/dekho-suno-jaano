// The reader in the Hashiya world: turns as list items with a margin, tools on
// selection, Correct in place, and the corrected words shown struck through.
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fetchMock = vi.hoisted(() => {
  const mock = vi.fn<(request: Request) => Promise<Response>>();
  globalThis.fetch = mock as unknown as typeof fetch;
  return mock;
});

import { dismissError } from "../../src/features/errors/appError";
import { takeToken } from "../../src/features/session/session";
import { TranscriptPage } from "../../src/features/transcript/TranscriptPage";
import type { Content, Entry, Item } from "../../src/lib/editOps";
import { listReply, saves, savedList } from "./editsServer";
import { installHighlights } from "./highlights";
import { stubMatchMedia } from "./media";

function item(sourceStart: number, length: number, text: string, confidence: number | null = 0.95): Item {
  return { kind: "item", source: "0", sourceStart, length, text, muted: false, confidence };
}
const para = (speaker: string): Entry => ({ kind: "paragraph", speaker, language: null });

// Contiguous, the gaps held by items with no words, as the dev linter that
// loadEditable installs requires (lib/linter.ts).
const CONTENT: Content = [
  para("SPEAKER_00"),
  item(0, 0.2, "", null),
  item(0.2, 0.3, " alpha"),
  item(0.5, 0.1, "", null),
  item(0.6, 0.3, " bravo"),
  item(0.9, 0.1, "", null),
  item(1.0, 0.3, " charlie", 0.3),
  item(1.3, 0.7, "", null),
  para("SPEAKER_01"),
  item(2.0, 0.4, " delta"),
];
const DOC = {
  audio: "/rec/a.wav",
  model: "mlx-community/parakeet-tdt-0.6b-v3",
  speakers: ["SPEAKER_00", "SPEAKER_01"],
  sentences: [
    { start: 0.2, end: 1.3, speaker: 0, text: " alpha bravo charlie", tokens: [
      { t: 0.2, w: " alpha", e: 0.5, c: 0.95 }, { t: 0.6, w: " bravo", e: 0.9, c: 0.95 }, { t: 1.0, w: " charlie", e: 1.3, c: 0.3 },
    ] },
    { start: 2.0, end: 2.4, speaker: 1, text: " delta", tokens: [{ t: 2.0, w: " delta", e: 2.4, c: 0.95 }] },
  ],
};

let saved: Content[] = [];
// Each name table the page sent to PUT /names (#243).
let named: Record<string, string>[] = [];
let review: unknown = null;

beforeEach(() => {
  installHighlights();
  stubMatchMedia();
  window.history.replaceState(null, "", "/?recording=2&transcript=7#t=a-token");
  takeToken();
  saved = [];
  named = [];
  review = null;
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (request: Request) => {
    const path = new URL(request.url).pathname;
    if (path === "/api/recordings") {
      return Response.json([{
        id: 2, path: "/rec/a.wav", size_bytes: 1, duration_s: 3, content_id: "c", audio_codec: "pcm",
        video_codec: null, first_seen: "x", missing: false, unreadable: null, title: null,
        transcripts: [{ id: 7, finished_at: "x", engine: "parakeet", model: "parakeet", diarized: true, speaker_count: 2, mark_count: null, language: null, last_edited_at: null, language_tag: null, review_checked: null, review_total: null }],
      }]);
    }
    if (path === "/api/transcripts/7") return Response.json(DOC);
    if (path === "/api/transcripts/7/edits") {
      if (!saves(request)) return listReply(CONTENT);
      const content = await savedList(request, saved.at(-1) ?? CONTENT);
      saved.push(content);
      return listReply(content);
    }
    if (path === "/api/transcripts/7/names" && request.method === "PUT") {
      const body = (await request.json()) as { names: Record<string, string> };
      named.push(body.names);
      return Response.json({ content: CONTENT, names: body.names, pad_s: 0.1, edited_at: null, spans: [], unrenderable: null, replaced: null, transcript_sha: "sha-1" });
    }
    if (path === "/api/transcripts/7/matches") return Response.json({ matches: [], words_searched: 4, lists: ["en"], recall: "recall: x" });
    if (path === "/api/transcripts/7/review") return Response.json({ document: review, transcript_sha: "sha-1" });
    if (path === "/api/recording/2/waveform") return new Response(new Int8Array([-3, 3]));
    return Response.json({ detail: "Not Found" }, { status: 404 });
  });
});

afterEach(() => {
  cleanup();
  act(() => dismissError());
});

function select(word: string): void {
  const p = Array.from(document.querySelectorAll("article p")).find((x) => x.textContent?.includes(word)) as HTMLElement;
  const text = p.firstChild as Text;
  const range = document.createRange();
  range.setStart(text, text.data.indexOf(word));
  range.setEnd(text, text.data.indexOf(word) + word.length);
  window.getSelection()?.removeAllRanges();
  window.getSelection()?.addRange(range);
  document.dispatchEvent(new Event("selectionchange"));
}

describe("the reader", () => {
  it("draws each turn as a list item with its speaker, time and duration in the margin, under one heading", async () => {
    render(<TranscriptPage recording={2} transcript={7} />);
    const article = await screen.findByRole("article", { name: "Transcript" });
    const turns = within(article).getAllByRole("listitem");
    expect(turns).toHaveLength(2);
    expect(within(turns[0] as HTMLElement).getByText("Speaker 1")).toBeTruthy();
    expect(within(turns[1] as HTMLElement).getByText("0:02")).toBeTruthy();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(article.querySelectorAll("h2")).toHaveLength(0);
    // The words are still one text node a paragraph (#58).
    expect(article.querySelectorAll("p *")).toHaveLength(0);
    // The tick is the turn's length to scale: 1.1 s (0.2 to 1.3) against 0.4 s (2.0 to 2.4).
    const tick = (li: HTMLElement) => Number.parseFloat(li.style.getPropertyValue("--tick"));
    expect(tick(turns[0] as HTMLElement) / tick(turns[1] as HTMLElement)).toBeCloseTo(1.1 / 0.4, 5);
    expect(tick(turns[0] as HTMLElement)).toBeCloseTo((1.1 / 60) * 100, 5);
  });

  it("shows the tools for a selection only while there is one", async () => {
    render(<TranscriptPage recording={2} transcript={7} />);
    await screen.findByRole("toolbar", { name: "Edit" });
    expect(screen.queryByRole("toolbar", { name: "Selection" })).toBeNull();
    act(() => select("bravo"));
    const tools = await screen.findByRole("toolbar", { name: "Selection" });
    for (const name of ["Correct", "Hear", "Timing", "Mute"]) expect(within(tools).getByRole("button", { name })).toBeTruthy();
  });

  it("corrects in place, saves it, and strikes the original through in the margin", async () => {
    render(<TranscriptPage recording={2} transcript={7} />);
    await screen.findByRole("toolbar", { name: "Edit" });
    act(() => select("charlie"));
    const correct = within(await screen.findByRole("toolbar", { name: "Selection" })).getByRole("button", { name: "Correct" });
    fireEvent.click(correct);
    const field = (await screen.findByRole("textbox", { name: "What was said" })) as HTMLInputElement;
    expect(field.value).toBe("charlie");
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.change(field, { target: { value: "Charles Darwin" } });
    fireEvent.submit(field.form as HTMLFormElement);
    await vi.waitFor(() => expect(document.querySelector("article p")?.textContent).toBe(" alpha bravo Charles Darwin"));
    await vi.waitFor(() => expect(saved).toHaveLength(1));
    const margin = document.querySelector("article li [data-margin]") as HTMLElement;
    expect(margin.querySelector("del")?.textContent).toBe("charlie");
  });

  it("strikes a deleted word through in the margin: a stretch emptied leaves the original, marked as deleted", async () => {
    render(<TranscriptPage recording={2} transcript={7} />);
    await screen.findByRole("toolbar", { name: "Edit" });
    act(() => select("charlie"));
    fireEvent.click(within(await screen.findByRole("toolbar", { name: "Selection" })).getByRole("button", { name: "Correct" }));
    const field = (await screen.findByRole("textbox", { name: "What was said" })) as HTMLInputElement;
    fireEvent.change(field, { target: { value: "" } });
    fireEvent.submit(field.form as HTMLFormElement);
    await vi.waitFor(() => expect(document.querySelector("article p")?.textContent).toBe(" alpha bravo"));
    const margin = document.querySelector("article li [data-margin]") as HTMLElement;
    expect(margin.querySelector(".correction")?.textContent).toBe("Deleted: charlie");
  });

  it("corrects a selection made of whole paragraphs, as a triple-click makes, whose ends are elements", async () => {
    render(<TranscriptPage recording={2} transcript={7} />);
    await screen.findByRole("toolbar", { name: "Edit" });
    const p = document.querySelector("article p") as HTMLElement;
    act(() => {
      const range = document.createRange();
      range.setStart(p, 0);
      range.setEnd(p.closest("li")?.nextElementSibling as Element, 0);
      window.getSelection()?.removeAllRanges();
      window.getSelection()?.addRange(range);
      document.dispatchEvent(new Event("selectionchange"));
    });
    fireEvent.click(within(await screen.findByRole("toolbar", { name: "Selection" })).getByRole("button", { name: "Correct" }));
    expect(((await screen.findByRole("textbox", { name: "What was said" })) as HTMLInputElement).value).toBe("alpha bravo charlie");
  });

  it("moves focus to the tools for a selection made by key, Esc puts it back in the text, and so do Save and Cancel", async () => {
    render(<TranscriptPage recording={2} transcript={7} />);
    await screen.findByRole("toolbar", { name: "Edit" });
    const paragraph = document.querySelector('article p[data-turn="0"]') as HTMLElement;
    const byKey = async () => {
      // `]` selects the next unsure word ("charlie", 0.3 under parakeet's 0.9).
      act(() => {
        fireEvent.keyDown(document.body, { key: "]", code: "BracketRight" });
        document.dispatchEvent(new Event("selectionchange"));
      });
      const tools = await screen.findByRole("toolbar", { name: "Selection" });
      const correct = within(tools).getByRole("button", { name: "Correct" });
      await vi.waitFor(() => expect(document.activeElement).toBe(correct));
      return correct;
    };
    const correct = await byKey();
    expect(window.getSelection()?.toString()).toBe("charlie");
    act(() => {
      fireEvent.keyDown(correct, { key: "Escape" });
      document.dispatchEvent(new Event("selectionchange"));
    });
    expect(document.activeElement).toBe(paragraph);
    expect(window.getSelection()?.toString()).toBe("");
    await vi.waitFor(() => expect(screen.queryByRole("toolbar", { name: "Selection" })).toBeNull());

    // Cancel: focus back on the words, and they are selected again.
    fireEvent.click(await byKey());
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    await vi.waitFor(() => expect(document.activeElement).toBe(paragraph));
    expect(window.getSelection()?.toString()).toBe("charlie");

    // Save: focus on the corrected words, selected as they now read.
    act(() => {
      window.getSelection()?.removeAllRanges();
      document.dispatchEvent(new Event("selectionchange"));
    });
    fireEvent.click(await byKey());
    const field = (await screen.findByRole("textbox", { name: "What was said" })) as HTMLInputElement;
    fireEvent.change(field, { target: { value: "Charles Darwin" } });
    fireEvent.submit(field.form as HTMLFormElement);
    await vi.waitFor(() => expect(window.getSelection()?.toString()).toBe("Charles Darwin"));
    expect(document.activeElement).toBe(document.querySelector('article p[data-turn="0"]'));
    expect(document.activeElement).not.toBe(document.body);
  });

  it("moves focus to the tools once Shift comes up after Shift and an arrow grew the selection, not while it grows", async () => {
    render(<TranscriptPage recording={2} transcript={7} />);
    await screen.findByRole("toolbar", { name: "Edit" });
    act(() => {
      fireEvent.keyDown(document.body, { key: "ArrowRight", code: "ArrowRight", shiftKey: true });
      select("bravo");
    });
    const tools = await screen.findByRole("toolbar", { name: "Selection" });
    expect(document.activeElement).toBe(document.body);
    act(() => fireEvent.keyUp(document.body, { key: "Shift", code: "ShiftLeft" }));
    expect(document.activeElement).toBe(within(tools).getByRole("button", { name: "Correct" }));
    expect(window.getSelection()?.toString()).toBe("bravo");
  });

  it("forgets a ] that found no unsure word, so a selection the page makes later leaves focus alone", async () => {
    const sure = CONTENT.map((e) => (e.kind === "item" && e.confidence !== null ? { ...e, confidence: 0.95 } : e));
    const answer = fetchMock.getMockImplementation() as (request: Request) => Promise<Response>;
    fetchMock.mockImplementation(async (request: Request) =>
      new URL(request.url).pathname === "/api/transcripts/7/edits" && request.method === "GET"
        ? Response.json({ content: sure, names: {}, pad_s: 0.1, edited_at: null, spans: [], unrenderable: null, replaced: null, transcript_sha: "sha-1" })
        : answer(request),
    );
    render(<TranscriptPage recording={2} transcript={7} />);
    await screen.findByRole("toolbar", { name: "Edit" });
    act(() => fireEvent.keyDown(document.body, { key: "]", code: "BracketRight" }));
    await act(() => new Promise((resolve) => setTimeout(resolve, 10)));
    expect(window.getSelection()?.toString()).toBe("");
    // The page selects words itself, as it does after Timing's Done.
    act(() => select("bravo"));
    await screen.findByRole("toolbar", { name: "Selection" });
    await act(() => new Promise((resolve) => setTimeout(resolve, 10)));
    expect(document.activeElement).toBe(document.body);
  });

  it("leaves focus alone for a selection made with the pointer", async () => {
    render(<TranscriptPage recording={2} transcript={7} />);
    await screen.findByRole("toolbar", { name: "Edit" });
    act(() => {
      fireEvent.pointerDown(document.body);
      select("bravo");
    });
    await screen.findByRole("toolbar", { name: "Selection" });
    expect(document.activeElement).toBe(document.body);
  });

  it("answers ], [, ? and Esc with a button focused, and leaves Space and Enter to the button", async () => {
    const { isOurs } = await import("../../src/features/transcript/readerKeys");
    const button = document.createElement("button");
    document.body.append(button);
    const ours = (init: KeyboardEventInit) => {
      let answer = false;
      const listen = (event: KeyboardEvent) => {
        answer = isOurs(event);
      };
      window.addEventListener("keydown", listen);
      button.dispatchEvent(new KeyboardEvent("keydown", { ...init, bubbles: true }));
      window.removeEventListener("keydown", listen);
      return answer;
    };
    expect(ours({ key: "]", code: "BracketRight" })).toBe(true);
    expect(ours({ key: "[", code: "BracketLeft" })).toBe(true);
    expect(ours({ key: "?", code: "Slash", shiftKey: true })).toBe(true);
    expect(ours({ key: "Escape", code: "Escape" })).toBe(true);
    expect(ours({ key: " ", code: "Space" })).toBe(false);
    expect(ours({ key: "Enter", code: "Enter" })).toBe(false);
    button.remove();
  });

  it("draws Review's mark in the margin only when it is given one, per turn and per sentence", async () => {
    const { read } = await import("../../src/features/transcript/document");
    const { TranscriptView } = await import("../../src/features/transcript/TranscriptView");
    const reading = read(DOC);
    const { container, rerender } = render(<TranscriptView reading={reading} />);
    expect(container.querySelectorAll(".review")).toHaveLength(0);
    rerender(
      <TranscriptView
        reading={reading}
        review={{
          turns: new Map([[1, "checked"]]),
          sentences: [
            { start: 0.2, end: 1.3, state: "flagged" },
            { start: 2.0, end: 2.4, state: "checked" },
          ],
        }}
      />,
    );
    const marks = Array.from(container.querySelectorAll("[data-margin]"), (m) => m.querySelector(".review")?.textContent?.trim());
    // Turn 0: one sentence, flagged; turn 1 is checked as a whole.
    expect(marks).toEqual(["1 flagged", "Checked"]);
    // Said in words, not by an aria-label on a span with no role (Task 3 review).
    expect(container.querySelector("[data-margin] .review [aria-label]")).toBeNull();
  });

  it("marks the margin from the transcript's review, and not from one made against an earlier transcript", async () => {
    const segments = [
      { start: 0.2, end: 1.3, state: "checked", flags: [], speaker: null, edited: false },
      { start: 2.0, end: 2.4, state: "unchecked", flags: ["overlap"], speaker: null, edited: false },
    ];
    review = { version: 1, transcript_sha: "sha-1", review_pass: "every", cursor_s: 0, started_at: "x", updated_at: "x", segments, corrections: [] };
    const { unmount } = render(<TranscriptPage recording={2} transcript={7} />);
    await vi.waitFor(() => expect(document.querySelectorAll("[data-margin] .review")).toHaveLength(2));
    const marks = Array.from(document.querySelectorAll("[data-margin] .review"), (m) => m.textContent?.trim());
    expect(marks[0]).toMatch(/^1 of the turn's 1 reviewed sentences checked$/);
    expect(marks[1]).toBe("1 flagged");
    unmount();
    review = { ...(review as object), transcript_sha: "sha-0" };
    render(<TranscriptPage recording={2} transcript={7} />);
    await screen.findAllByRole("listitem");
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(document.querySelectorAll("[data-margin] .review")).toHaveLength(0);
  });

  it("offers the recording's other transcripts in a version picker only when it has more than one", async () => {
    const { unmount } = render(<TranscriptPage recording={2} transcript={7} />);
    await screen.findByRole("toolbar", { name: "Edit" });
    expect(screen.queryByRole("combobox", { name: "Version" })).toBeNull();
    unmount();
    const answer = fetchMock.getMockImplementation() as (request: Request) => Promise<Response>;
    fetchMock.mockImplementation(async (request: Request) => {
      if (new URL(request.url).pathname !== "/api/recordings") return answer(request);
      const [row] = (await (await answer(request)).json()) as [{ transcripts: object[] }];
      const second = { ...row.transcripts[0], id: 8, engine: "whisper", finished_at: "2026-10-02T18:05:00+00:00" };
      return Response.json([{ ...row, transcripts: [...row.transcripts, second] }]);
    });
    render(<TranscriptPage recording={2} transcript={7} />);
    expect(await screen.findByRole("combobox", { name: "Version" })).toBeTruthy();
  });

  it("renames a speaker from the margin, everywhere they speak", async () => {
    render(<TranscriptPage recording={2} transcript={7} />);
    fireEvent.click(await screen.findByRole("button", { name: "Speaker 1, rename" }));
    const field = screen.getByRole("textbox", { name: "Name for Speaker 1" });
    fireEvent.change(field, { target: { value: "  Ali " } });
    fireEvent.keyDown(field, { key: "Enter" });
    expect(await screen.findByRole("button", { name: "Ali, rename" })).toBeTruthy();
    expect(named).toEqual([{ SPEAKER_00: "Ali" }]);
    // Enter hands focus back to the nameplate, for the next key.
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Ali, rename" }));
    expect(screen.getByRole("button", { name: "Speaker 2, rename" })).toBeTruthy();
  });

  it("keeps a first rename when a second is made before the first is saved", async () => {
    // A rename built from the names last saved would send only the second,
    // and the first would be lost (Task 5 review, deferred to Task 16).
    const answer = fetchMock.getMockImplementation() as (request: Request) => Promise<Response>;
    let release: () => void = () => undefined;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    fetchMock.mockImplementation(async (request: Request) => {
      if (new URL(request.url).pathname === "/api/transcripts/7/names" && named.length === 0) {
        const reply = answer(request);
        await held;
        return reply;
      }
      return answer(request);
    });
    render(<TranscriptPage recording={2} transcript={7} />);
    fireEvent.click(await screen.findByRole("button", { name: "Speaker 1, rename" }));
    let field = screen.getByRole("textbox", { name: "Name for Speaker 1" });
    fireEvent.change(field, { target: { value: "Ali" } });
    fireEvent.keyDown(field, { key: "Enter" });
    fireEvent.click(screen.getByRole("button", { name: "Speaker 2, rename" }));
    field = screen.getByRole("textbox", { name: "Name for Speaker 2" });
    fireEvent.change(field, { target: { value: "Sara" } });
    fireEvent.keyDown(field, { key: "Enter" });
    release();
    expect(await screen.findByRole("button", { name: "Sara, rename" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Ali, rename" })).toBeTruthy();
    expect(named).toEqual([{ SPEAKER_00: "Ali" }, { SPEAKER_00: "Ali", SPEAKER_01: "Sara" }]);
  });

  it("keeps a typed name when the field is left without Enter, as a phone's keyboard closing does (#261)", async () => {
    render(<TranscriptPage recording={2} transcript={7} />);
    fireEvent.click(await screen.findByRole("button", { name: "Speaker 2, rename" }));
    const field = screen.getByRole("textbox", { name: "Name for Speaker 2" });
    fireEvent.change(field, { target: { value: "Sara" } });
    fireEvent.blur(field);
    expect(await screen.findByRole("button", { name: "Sara, rename" })).toBeTruthy();
    expect(named).toEqual([{ SPEAKER_01: "Sara" }]);
    // Left unchanged, nothing is sent.
    fireEvent.click(screen.getByRole("button", { name: "Sara, rename" }));
    fireEvent.blur(screen.getByRole("textbox", { name: "Name for Sara" }));
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(named).toEqual([{ SPEAKER_01: "Sara" }]);
  });

  it("keeps the old name on Esc, and an emptied name gives the speaker its own label back", async () => {
    render(<TranscriptPage recording={2} transcript={7} />);
    fireEvent.click(await screen.findByRole("button", { name: "Speaker 2, rename" }));
    let field = screen.getByRole("textbox", { name: "Name for Speaker 2" });
    fireEvent.change(field, { target: { value: "Sara" } });
    fireEvent.keyDown(field, { key: "Escape" });
    // A browser that fires blur as the field goes must not save what Esc dropped.
    fireEvent.blur(field);
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Speaker 2, rename" }));
    expect(named).toEqual([]);

    fireEvent.click(screen.getByRole("button", { name: "Speaker 2, rename" }));
    field = screen.getByRole("textbox", { name: "Name for Speaker 2" });
    fireEvent.change(field, { target: { value: "Sara" } });
    fireEvent.keyDown(field, { key: "Enter" });
    fireEvent.click(await screen.findByRole("button", { name: "Sara, rename" }));
    field = screen.getByRole("textbox", { name: "Name for Sara" });
    fireEvent.change(field, { target: { value: "   " } });
    fireEvent.keyDown(field, { key: "Enter" });
    expect(await screen.findByRole("button", { name: "Speaker 2, rename" })).toBeTruthy();
    expect(named).toEqual([{ SPEAKER_01: "Sara" }, {}]);
  });

  it("opens the key sheet with ?, and it says the undo history does not outlive the page", async () => {
    render(<TranscriptPage recording={2} transcript={7} />);
    await screen.findByRole("toolbar", { name: "Edit" });
    // On the page's body, where a key lands with nothing focused; it bubbles to the window.
    act(() => fireEvent.keyDown(document.body, { key: "?", code: "Slash", shiftKey: true }));
    // KeySheet is App's; this page only asks for it, so the request is read back here.
    const { KeySheet, hideKeys } = await import("../../src/features/shell/KeySheet");
    render(<KeySheet />);
    expect((await screen.findByRole("dialog")).textContent).toContain("forgets their undo");
    act(() => hideKeys());
  });
});
