// Starting a bleep render from the page, and following it (#215).
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const fetchMock = vi.hoisted(() => {
  const mock = vi.fn<(request: Request) => Promise<Response>>();
  globalThis.fetch = mock as unknown as typeof fetch;
  return mock;
});

import { alone } from "../../src/features/bleep/render";
import { RenderStatus } from "../../src/features/bleep/RenderStatus";
import { dismissError } from "../../src/features/errors/appError";
import { takeToken } from "../../src/features/session/session";
import { TranscriptPage } from "../../src/features/transcript/TranscriptPage";
import type { Content, Item } from "../../src/lib/editOps";
import { installHighlights } from "./highlights";
import { openBleepPanel } from "./menus";

function item(sourceStart: number, length: number, text: string, muted = false): Item {
  return { kind: "item", source: "0", sourceStart, length, text, muted, confidence: text ? 0.9 : null };
}

const CONTENT: Content = [
  { kind: "paragraph", speaker: null, language: null },
  item(0, 0.3, ""),
  item(0.3, 0.4, " alpha", true),
  item(0.7, 0.3, ""),
  item(1.0, 0.4, " bravo", true),
  item(1.4, 0.3, ""),
  item(1.7, 0.4, " charlie"),
];
const BRAVO = { start: 4, stop: 5, word: "bravo", entry: "en:bravo", start_s: 1.0, end_s: 1.4 };
const JOB = {
  id: 1, transcript_id: 7, recording_id: 2, started_at: "x", state: "starting" as const, fraction: 0,
  output: "/rec/a.bleeped.wav", spans: 1, error: null, notes: [],
};

afterEach(() => {
  cleanup();
  act(() => dismissError());
});

it("mutes one match alone and gives every other word its sound", () => {
  const one = alone(CONTENT, BRAVO);
  expect(one.filter((e) => e.kind === "item" && e.muted).map((e) => (e as Item).text)).toEqual([" bravo"]);
  expect(one[4]).toBe(CONTENT[4]);
});

describe("RenderStatus", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/?recording=2&transcript=7#t=a-token");
    takeToken();
  });

  it("shows how far a render has got", () => {
    render(<RenderStatus job={{ ...JOB, state: "rendering", fraction: 0.42 }} />);
    expect(screen.getByRole("status", { name: "Rendering" }).textContent).toContain("a.bleeped.wav: 42%");
  });

  it("links a finished render by its id, the token in the query, with its path and notes", () => {
    render(<RenderStatus job={{ ...JOB, state: "done", fraction: 1, notes: ["Capped 1 muted words"] }} />);
    const done = screen.getByRole("status", { name: "Rendered" });
    expect(within(done).getByRole("link", { name: "a.bleeped.wav" }).getAttribute("href")).toBe(
      "/api/renders/1/media?t=a-token",
    );
    expect(done.textContent).toContain("/rec/a.bleeped.wav");
    expect(done.textContent).toContain("Capped 1 muted words");
  });

  it("says why a render failed", () => {
    render(<RenderStatus job={{ ...JOB, state: "failed", error: "MediaError: ffmpeg said no" }} />);
    expect(screen.getByRole("status").textContent).toBe("The render failed: MediaError: ffmpeg said no");
  });
});

describe("the Render buttons", () => {
  let sent: Content[] = [];
  let polls = 0;

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
    sent = [];
    polls = 0;
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
        return Response.json({ content: CONTENT, names: {}, pad_s: 0.1, edited_at: null, spans: [[0.2, 0.8], [0.9, 1.5]], unrenderable: null, replaced: null, transcript_sha: "sha-1" });
      }
      if (path === "/api/transcripts/7/matches") {
        return Response.json({ matches: [BRAVO], words_searched: 3, lists: ["en"], recall: "recall: x" });
      }
      if (path === "/api/transcripts/7/render") {
        sent.push(((await request.json()) as { content: Content }).content);
        return Response.json(JOB, { status: 202 });
      }
      if (path === "/api/renders") {
        polls += 1;
        return Response.json([{ ...JOB, state: polls > 1 ? "done" : "rendering", fraction: polls > 1 ? 1 : 0.5 }]);
      }
      if (path === "/api/recording/2/waveform") return new Response(new Int8Array([-3, 3]));
      // The reader reads the review for its margin marks (Task 13); none here.
      if (path === "/api/transcripts/7/review") return Response.json({ document: null, transcript_sha: "sha-1" });
      return Response.json({ detail: "Not Found" }, { status: 404 });
    });
  });

  it("renders the list as it is, follows the job, and links the file when done", async () => {
    render(<TranscriptPage recording={2} transcript={7} />);
    const panel = await openBleepPanel();
    await within(panel).findByRole("list", { name: "Matches" });
    expect(panel.textContent).toContain("with 2 spans silenced");
    fireEvent.click(within(panel).getByRole("button", { name: "Render" }));
    await vi.waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0]).toEqual(CONTENT);
    expect(await within(panel).findByRole("link", { name: "a.bleeped.wav" }, { timeout: 3000 })).toBeTruthy();
  });

  it("shows the render where it is when the drawer is closed and opened again", async () => {
    render(<TranscriptPage recording={2} transcript={7} />);
    const panel = await openBleepPanel();
    await within(panel).findByRole("list", { name: "Matches" });
    fireEvent.click(within(panel).getByRole("button", { name: "Render" }));
    await vi.waitFor(() => expect(sent).toHaveLength(1));
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    await vi.waitFor(() => expect(screen.queryByRole("region", { name: "Words to bleep" })).toBeNull());
    const again = await openBleepPanel();
    expect(await within(again).findByRole("status", { name: /^Render(ing|ed)$/ })).toBeTruthy();
  });

  it("renders one match alone", async () => {
    render(<TranscriptPage recording={2} transcript={7} />);
    const panel = await openBleepPanel();
    await within(panel).findByRole("list", { name: "Matches" });
    fireEvent.click(within(panel).getByRole("button", { name: "Render alone" }));
    await vi.waitFor(() => expect(sent).toHaveLength(1));
    expect((sent[0] ?? []).filter((e) => e.kind === "item" && e.muted).map((e) => (e as Item).text)).toEqual([" bravo"]);
  });
});
