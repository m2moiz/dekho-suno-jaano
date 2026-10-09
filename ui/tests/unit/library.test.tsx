import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Installed before the imports below run: the generated client keeps the
// fetch it finds when it is created, so a stub put in place later is never called.
const fetchMock = vi.hoisted(() => {
  const mock = vi.fn<(request: Request) => Promise<Response>>();
  globalThis.fetch = mock as unknown as typeof fetch;
  return mock;
});

import { currentError, dismissError } from "../../src/features/errors/appError";
import {
  durationLabel,
  engineLabel,
  marksLabel,
  pictureNote,
  sizeLabel,
  speakersLabel,
} from "../../src/features/library/describe";
import { LibraryPage } from "../../src/features/library/LibraryPage";
import { displayTitle } from "../../src/features/library/title";
import type { RecordingRow, TranscriptRow } from "../../src/features/library/types";
import { takeToken } from "../../src/features/session/session";
import { stubMatchMedia } from "./media";

function transcript(overrides: Partial<TranscriptRow>): TranscriptRow {
  return {
    id: 1,
    finished_at: "2026-09-20T17:05:00+00:00",
    engine: "parakeet",
    model: "mlx-community/parakeet-tdt-0.6b-v3",
    diarized: false,
    speaker_count: null,
    mark_count: null,
    language: null,
    last_edited_at: null,
    language_tag: null,
    review_checked: null,
    review_total: null,
    ...overrides,
  };
}

const ROWS: RecordingRow[] = [
  {
    id: 2,
    path: "/Users/me/Recordings/review.mov",
    size_bytes: 1_048_576,
    content_id: "c1",
    audio_codec: "aac",
    missing: false,
    unreadable: null,
    title: null,
    duration_s: 3725,
    video_codec: "h264",
    first_seen: "2026-09-20T17:00:00+00:00",
    transcripts: [transcript({ id: 7, engine: "whisper", language: "ur", language_tag: "urdu" })],
  },
  {
    id: 1,
    path: "/Volumes/Old disk/standup.m4a",
    size_bytes: 2_048,
    content_id: "c2",
    audio_codec: "aac",
    missing: true,
    unreadable: null,
    title: null,
    duration_s: 249,
    video_codec: null,
    first_seen: "2026-09-01T08:30:00+00:00",
    transcripts: [
      transcript({ id: 3, engine: null, diarized: true, speaker_count: 1, mark_count: 0 }),
    ],
  },
];

function serve(rows: unknown, status = 200) {
  fetchMock.mockReset();
  // Each row asks once for the jobs already running (#113); none are.
  fetchMock.mockImplementation(async (request: Request) =>
    new URL(request.url).pathname === "/api/jobs"
      ? Response.json([])
      : Response.json(rows, { status }),
  );
  return fetchMock;
}

beforeEach(() => {
  stubMatchMedia();
  window.history.replaceState(null, "", "/#t=a-token");
  takeToken();
});

afterEach(() => {
  cleanup();
  act(() => dismissError());
});

describe("the library page", () => {
  it("lists every recording in the order the server sent, newest first", async () => {
    const seen = serve(ROWS);
    render(<LibraryPage />);
    const items = await screen.findAllByRole("listitem", { name: /^(review|standup)$/ });
    expect(items.map((li) => li.getAttribute("aria-label"))).toEqual(["review", "standup"]);
    const request = seen.mock.calls[0]?.[0];
    expect(new URL(request?.url ?? "").pathname).toBe("/api/recordings");
    expect(request?.headers.get("Authorization")).toBe("Bearer a-token");
  });

  it("keeps date, engine and model under Details, and tags the row's language", async () => {
    serve(ROWS);
    render(<LibraryPage />);
    const review = await screen.findByRole("listitem", { name: "review" });
    expect(within(review).getByText("Urdu")).toBeTruthy();
    // No model id on the row itself (critique: "model repo ID as subtitle").
    expect(within(review).queryByText(/mlx-community/)).toBeNull();
    fireEvent.click(within(review).getByRole("button", { name: "Details" }));
    const made = within(review).getByText("Made").nextElementSibling?.textContent ?? "";
    expect(made).toContain("2026");
    expect(made).toContain("whisper");
    expect(within(review).getByText("Model").nextElementSibling?.textContent).toBe("mlx-community/parakeet-tdt-0.6b-v3");
    expect(within(review).getByText("Speakers").nextElementSibling?.textContent).toBe("speakers not labelled");
  });

  it("shows an adopted transcript's engine as unknown, and one speaker as 1 speaker", async () => {
    serve(ROWS);
    render(<LibraryPage />);
    const standup = await screen.findByRole("listitem", { name: "standup" });
    expect(within(standup).getByRole("img", { name: "1 speaker" })).toBeTruthy();
    fireEvent.click(within(standup).getByRole("button", { name: "Details" }));
    expect(within(standup).getByText("Made").nextElementSibling?.textContent).toMatch(/unknown engine$/);
    expect(within(standup).getByText("Speakers").nextElementSibling?.textContent).toBe("1 speaker");
    expect(within(standup).getByText("Marks").nextElementSibling?.textContent).toBe("0 marks");
  });

  it("keeps a missing recording, greyed out, with its last known path", async () => {
    serve(ROWS);
    render(<LibraryPage />);
    const standup = await screen.findByRole("listitem", { name: "standup" });
    expect(standup.getAttribute("data-missing")).toBe("true");
    expect(within(standup).getByRole("link", { name: "standup" }).className).toContain("text-muted-foreground");
    expect(within(standup).getByText("Not where it was last seen.")).toBeTruthy();
    fireEvent.click(within(standup).getByRole("button", { name: "Details" }));
    expect(within(standup).getByText("/Volumes/Old disk/standup.m4a")).toBeTruthy();
    const review = screen.getByRole("listitem", { name: "review" });
    expect(review.getAttribute("data-missing")).toBeNull();
  });

  it("opens each recording's latest transcript from its title", async () => {
    serve(ROWS);
    render(<LibraryPage />);
    const review = await screen.findByRole("listitem", { name: "review" });
    expect(within(review).getByRole("link", { name: "review" }).getAttribute("href")).toBe("/?recording=2&transcript=7");
    const standup = screen.getByRole("listitem", { name: "standup" });
    expect(within(standup).getByRole("link", { name: "standup" }).getAttribute("href")).toBe("/?recording=1&transcript=3");
  });

  it("offers Transcribe only on a recording with no transcript, and Transcribe again under Details", async () => {
    serve([...ROWS, { ...ROWS[0], id: 5, path: "/r/fresh.wav", transcripts: [] }]);
    render(<LibraryPage />);
    const fresh = await screen.findByRole("listitem", { name: "fresh" });
    expect(within(fresh).getByRole("button", { name: "Transcribe" })).toBeTruthy();
    expect(within(fresh).queryByRole("link")).toBeNull();
    const review = screen.getByRole("listitem", { name: "review" });
    expect(within(review).queryByRole("button", { name: /^Transcribe/ })).toBeNull();
    fireEvent.click(within(review).getByRole("button", { name: "Details" }));
    expect(within(review).getByRole("button", { name: "Transcribe again" })).toBeTruthy();
  });

  it("says the library is empty when it is, and offers Add recording there too", async () => {
    serve([]);
    render(<LibraryPage />);
    expect(await screen.findByRole("heading", { name: "No recordings yet" })).toBeTruthy();
    const adds = screen.getAllByRole("button", { name: "Add recording" });
    expect(adds).toHaveLength(2);
    // One gold action on the screen (rulings F23): the bar's.
    expect(adds.filter((b) => b.className.includes("bg-gold"))).toHaveLength(1);
    expect(screen.queryByRole("searchbox")).toBeNull();
  });

  it("titles a recording from its file's timestamp, and renames it inline", async () => {
    const seen = serve([{ ...ROWS[0], path: "/r/20250920_094234.m4a" }]);
    seen.mockImplementation(async (request: Request) => {
      const path = new URL(request.url).pathname;
      if (path === "/api/jobs") return Response.json([]);
      if (request.method === "PATCH") return Response.json({ ...ROWS[0], title: "Sunday call" });
      return Response.json([{ ...ROWS[0], path: "/r/20250920_094234.m4a" }]);
    });
    render(<LibraryPage />);
    const row = await screen.findByRole("listitem", { name: /^Sat 20 Sep/ });
    fireEvent.click(within(row).getByRole("button", { name: /^Rename/ }));
    const field = screen.getByRole("textbox", { name: "Title" });
    fireEvent.change(field, { target: { value: "Sunday call" } });
    fireEvent.keyDown(field, { key: "Enter" });
    await vi.waitFor(() => expect(seen.mock.calls.some(([r]) => r.method === "PATCH")).toBe(true));
    const patch = seen.mock.calls.map(([r]) => r).find((r) => r.method === "PATCH");
    expect(new URL(patch?.url ?? "").pathname).toBe("/api/recordings/2");
    expect(await patch?.json()).toEqual({ title: "Sunday call" });
  });

  it("sends an empty title when the default is typed back, and nothing when Escape leaves", async () => {
    const seen = serve([{ ...ROWS[0], path: "/r/20250920_094234.m4a", title: "Sunday call" }]);
    render(<LibraryPage />);
    const row = await screen.findByRole("listitem", { name: "Sunday call" });
    const rename = within(row).getByRole("button", { name: /^Rename/ });
    fireEvent.click(rename);
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Title" }), { key: "Escape" });
    expect(screen.queryByRole("textbox", { name: "Title" })).toBeNull();
    // Focus goes back to the pencil, not to the page's start.
    expect(document.activeElement).toBe(within(row).getByRole("button", { name: /^Rename/ }));
    fireEvent.click(within(row).getByRole("button", { name: /^Rename/ }));
    const field = screen.getByRole("textbox", { name: "Title" });
    fireEvent.change(field, { target: { value: displayTitle({ title: null, path: "/r/20250920_094234.m4a" }) } });
    fireEvent.blur(field);
    await vi.waitFor(() => expect(seen.mock.calls.filter(([r]) => r.method === "PATCH")).toHaveLength(1));
    const patch = seen.mock.calls.map(([r]) => r).find((r) => r.method === "PATCH");
    expect(await patch?.json()).toEqual({ title: "" });
  });

  it("sets an Urdu-script title in Nastaliq with lang ur, and a Latin one in Literata", async () => {
    serve([{ ...ROWS[0], title: "امی کی کال" }, ROWS[1]]);
    render(<LibraryPage />);
    const urdu = await screen.findByRole("link", { name: "امی کی کال" });
    expect(urdu.getAttribute("lang")).toBe("ur");
    expect(urdu.getAttribute("dir")).toBe("auto");
    expect(urdu.className).toContain("font-urdu");
    const latin = screen.getByRole("link", { name: "standup" });
    expect(latin.getAttribute("lang")).toBeNull();
    expect(latin.className).toContain("font-reading");
    fireEvent.click(screen.getByRole("button", { name: "Rename امی کی کال" }));
    const field = screen.getByRole("textbox", { name: "Title" });
    expect(field.getAttribute("lang")).toBe("ur");
    expect(field.className).toContain("font-urdu");
  });

  it("keeps focus where it went when the rename field is left, and saves what was typed", async () => {
    const seen = serve(ROWS);
    render(<LibraryPage />);
    const row = await screen.findByRole("listitem", { name: "review" });
    fireEvent.click(within(row).getByRole("button", { name: "Rename review" }));
    const field = screen.getByRole("textbox", { name: "Title" });
    fireEvent.change(field, { target: { value: "Weekly review" } });
    const search = screen.getByRole("searchbox", { name: "Search titles" });
    // A real move of focus, as a Tab or a click on the search would make.
    act(() => search.focus());
    await vi.waitFor(() => expect(seen.mock.calls.some(([r]) => r.method === "PATCH")).toBe(true));
    await vi.waitFor(() => expect(screen.queryByRole("textbox", { name: "Title" })).toBeNull());
    expect(document.activeElement).toBe(search);
  });

  it("keeps the typed title in the field when the server refuses it, and shows why", async () => {
    const refusal = { error: "HTTP 422", message: "title too long", request: "x" };
    const seen = serve(ROWS);
    seen.mockImplementation(async (request: Request) => {
      const path = new URL(request.url).pathname;
      if (path === "/api/jobs") return Response.json([]);
      if (request.method === "PATCH") return Response.json(refusal, { status: 422 });
      return Response.json(ROWS);
    });
    render(<LibraryPage />);
    const row = await screen.findByRole("listitem", { name: "review" });
    fireEvent.click(within(row).getByRole("button", { name: "Rename review" }));
    const field = screen.getByRole("textbox", { name: "Title" });
    fireEvent.change(field, { target: { value: "Weekly review" } });
    fireEvent.keyDown(field, { key: "Enter" });
    await vi.waitFor(() => expect(currentError()).toEqual({ ...refusal, request: "/api/recordings/2" }));
    expect((screen.getByRole("textbox", { name: "Title" }) as HTMLInputElement).value).toBe("Weekly review");
    // The error dialog taking focus is a blur, not a second try.
    fireEvent.blur(screen.getByRole("textbox", { name: "Title" }));
    expect(seen.mock.calls.filter(([r]) => r.method === "PATCH")).toHaveLength(1);
  });

  it("finds an Urdu title typed with Arabic letters, and a title in any case", async () => {
    serve([{ ...ROWS[0], title: "امی کی کال" }, ROWS[1]]);
    render(<LibraryPage />);
    await screen.findByRole("listitem", { name: "امی کی کال" });
    const search = screen.getByRole("searchbox", { name: "Search titles" });
    expect(search.getAttribute("dir")).toBe("auto");
    // Arabic yeh and kaf (U+064A, U+0643) for the Urdu ی and ک the title holds.
    fireEvent.change(search, { target: { value: "\u0643\u064A" } });
    expect(screen.getByRole("listitem", { name: "امی کی کال" })).toBeTruthy();
    expect(screen.queryByRole("listitem", { name: "standup" })).toBeNull();
    fireEvent.change(search, { target: { value: "STAND" } });
    expect(screen.getByRole("listitem", { name: "standup" })).toBeTruthy();
  });

  it("filters by title as you type, and says when nothing matches", async () => {
    serve(ROWS);
    render(<LibraryPage />);
    await screen.findByRole("listitem", { name: "review" });
    fireEvent.change(screen.getByRole("searchbox", { name: "Search titles" }), { target: { value: "stand" } });
    expect(screen.queryByRole("listitem", { name: "review" })).toBeNull();
    expect(screen.getByRole("listitem", { name: "standup" })).toBeTruthy();
    fireEvent.change(screen.getByRole("searchbox", { name: "Search titles" }), { target: { value: "zzz" } });
    expect(screen.getByRole("status").textContent).toBe("No title or file name has “zzz” in it.");
    fireEvent.click(screen.getByRole("button", { name: "Clear search" }));
    expect(screen.getAllByRole("listitem", { name: /^(review|standup)$/ })).toHaveLength(2);
    expect(document.activeElement).toBe(screen.getByRole("searchbox", { name: "Search titles" }));
    expect(screen.getByRole("status").textContent).toBe("");
  });

  it("shows review progress, and older versions folded", async () => {
    serve([
      {
        ...ROWS[0],
        transcripts: [
          { ...transcript({ id: 9 }), review_checked: 212, review_total: 252 },
          transcript({ id: 8 }),
          transcript({ id: 7 }),
        ],
      },
    ]);
    render(<LibraryPage />);
    const row = await screen.findByRole("listitem", { name: "review" });
    expect(within(row).getByText("212 of 252 checked")).toBeTruthy();
    const versions = within(row).getByRole("button", { name: "2 earlier versions" });
    expect(within(row).getByRole("link", { name: "review" }).getAttribute("href")).toBe("/?recording=2&transcript=9");
    expect(within(row).getAllByRole("link")).toHaveLength(1);
    fireEvent.click(versions);
    expect(
      within(row)
        .getAllByRole("link")
        .map((a) => a.getAttribute("href")),
    ).toEqual(["/?recording=2&transcript=9", "/?recording=2&transcript=8", "/?recording=2&transcript=7"]);
  });

  it("sends a failed read to the error dialog with the server's own words", async () => {
    serve({ error: "LibraryError", message: "a version 2 library", request: "/api/recordings" }, 500);
    render(<LibraryPage />);
    expect(await screen.findByText("The library could not be read.")).toBeTruthy();
    expect(currentError()).toEqual({
      error: "LibraryError",
      message: "a version 2 library",
      request: "/api/recordings",
    });
  });
});

describe("bringing a recording in (#110)", () => {
  const ADDED: RecordingRow = {
    id: 9,
    path: "/Users/me/Movies/demo.mov",
    size_bytes: 373_293_056,
    content_id: "c9",
    audio_codec: "aac",
    missing: false,
    unreadable: null,
    title: null,
    duration_s: 61,
    video_codec: "prores",
    first_seen: "2026-10-02T20:00:00+00:00",
    transcripts: [],
  };

  /** A server whose library is `rows`, and whose dialog answers `picked` to each ask. */
  function library(rows: RecordingRow[], picked: (path: string) => Response) {
    fetchMock.mockReset();
    fetchMock.mockImplementation(async (request: Request) => {
      const path = new URL(request.url).pathname;
      if (path === "/api/jobs") return Response.json([]);
      if (path === "/api/recordings") return Response.json(rows);
      return picked(path);
    });
    return fetchMock;
  }

  /** The empty library's own Add recording, in the page rather than the bar. */
  function emptyAdd(): HTMLButtonElement {
    return within(screen.getByRole("main")).getByRole("button", { name: "Add recording" }) as HTMLButtonElement;
  }

  function asked(path: string): Request[] {
    return fetchMock.mock.calls.map((c) => c[0]).filter((r) => new URL(r.url).pathname === path);
  }

  it("offers Add recording on an empty library, and lists what was picked without a reload", async () => {
    const rows: RecordingRow[] = [];
    library(rows, () => {
      rows.push(ADDED);
      return Response.json(ADDED);
    });
    render(<LibraryPage />);
    expect(await screen.findByRole("heading", { name: "No recordings yet" })).toBeTruthy();
    act(() => emptyAdd().click());
    const row = await screen.findByRole("listitem", { name: "demo" });
    expect(asked("/api/recordings/import").map((r) => r.method)).toEqual(["POST"]);
    // Nothing about where the file is goes up: the server asks the Mac.
    expect(await asked("/api/recordings/import")[0]?.text()).toBe("");
    expect(within(row).getByText("1:01")).toBeTruthy();
    expect(within(row).getByText("Not transcribed yet")).toBeTruthy();
    fireEvent.click(within(row).getByRole("button", { name: "Details" }));
    expect(within(row).getByText("373 MB")).toBeTruthy();
    expect(within(row).getByText(/Its picture \(prores\) does not show in every browser/)).toBeTruthy();
    expect(currentError()).toBeNull();
  });

  it("does nothing at all when the dialog is cancelled", async () => {
    library([], () => Response.json(null));
    render(<LibraryPage />);
    await screen.findByRole("heading", { name: "No recordings yet" });
    act(() => emptyAdd().click());
    await vi.waitFor(() => expect(asked("/api/recordings/import")).toHaveLength(1));
    await vi.waitFor(() =>
      expect(emptyAdd().disabled).toBe(false),
    );
    expect(asked("/api/recordings")).toHaveLength(1);
    expect(currentError()).toBeNull();
  });

  it("puts a refusal in the error dialog in the server's own words", async () => {
    const busy = { error: "PickerBusy", message: "a file dialog from dsj is already open.", request: "x" };
    library([], () => Response.json(busy, { status: 409 }));
    render(<LibraryPage />);
    await screen.findByRole("heading", { name: "No recordings yet" });
    act(() => emptyAdd().click());
    await vi.waitFor(() =>
      expect(currentError()).toEqual({ ...busy, request: "/api/recordings/import" }),
    );
  });

  it("shows what ffmpeg said about a file it could not read, and will not transcribe it", async () => {
    const said = "ffprobe could not read /r/cut.mov: moov atom not found";
    library([{ ...ADDED, path: "/r/cut.mov", unreadable: said, duration_s: null, video_codec: null }], () =>
      Response.json(null),
    );
    render(<LibraryPage />);
    const row = await screen.findByRole("listitem", { name: "cut" });
    expect(within(row).getByRole("note").textContent).toBe(`ffmpeg could not read this file: ${said}`);
    expect((within(row).getByRole("button", { name: "Transcribe" }) as HTMLButtonElement).disabled).toBe(true);
    // One quiet line with Relink (Hashiya spec), above the row's stretched link so it can be selected.
    expect(within(row).getByRole("button", { name: "Relink" })).toBeTruthy();
    expect(within(row).getByRole("note").parentElement?.className).toContain("z-10");
    // No transcript, nothing to open: no hover tint saying otherwise.
    expect(row.className).not.toContain("hover:");
  });

  it("re-points a missing recording from its row", async () => {
    const rows: RecordingRow[] = [{ ...ADDED, missing: true }];
    library(rows, (path) => {
      expect(path).toBe("/api/recordings/9/relink");
      rows[0] = { ...ADDED, path: "/Users/me/Movies/demo-renamed.mov" };
      return Response.json(rows[0]);
    });
    render(<LibraryPage />);
    const row = await screen.findByRole("listitem", { name: "demo" });
    expect(screen.getAllByRole("button", { name: "Relink" })).toHaveLength(1);
    act(() => within(row).getByRole("button", { name: "Relink" }).click());
    const found = await screen.findByRole("listitem", { name: "demo-renamed" });
    expect(found.getAttribute("data-missing")).toBeNull();
    expect(screen.queryByRole("button", { name: "Relink" })).toBeNull();
  });
});

describe("the words for each value", () => {
  it("says a picture some browsers cannot draw may not show, and says nothing of h264", () => {
    expect(pictureNote("h264")).toBeNull();
    expect(pictureNote("vp9")).toBeNull();
    expect(pictureNote(null)).toBeNull();
    expect(pictureNote("hevc")).toBe("Its picture (hevc) does not show in every browser. Its sound always plays.");
  });

  it("never reads labelling that did not run as one speaker", () => {
    expect(speakersLabel(transcript({ diarized: false }))).toBe("speakers not labelled");
    expect(speakersLabel(transcript({ diarized: true, speaker_count: 1 }))).toBe("1 speaker");
    expect(speakersLabel(transcript({ diarized: true, speaker_count: 3 }))).toBe("3 speakers");
    expect(speakersLabel(transcript({ diarized: null }))).toBe("speaker labels unknown");
  });

  it("never guesses an engine", () => {
    expect(engineLabel(transcript({ engine: null }))).toBe("unknown");
    expect(engineLabel(transcript({ engine: "sherpa" }))).toBe("sherpa");
  });

  it("keeps a scan that never ran apart from one that found nothing", () => {
    expect(marksLabel(transcript({ mark_count: null }))).toBe("not scanned for marks");
    expect(marksLabel(transcript({ mark_count: 0 }))).toBe("0 marks");
    expect(marksLabel(transcript({ mark_count: 1 }))).toBe("1 mark");
  });

  it("writes a size the way Finder does", () => {
    expect(sizeLabel(355_976_290)).toBe("356 MB");
    expect(sizeLabel(2_048)).toBe("2.0 KB");
    expect(sizeLabel(512)).toBe("512 bytes");
    expect(sizeLabel(4_200_000_000)).toBe("4.2 GB");
    expect(sizeLabel(null)).toBeNull();
  });

  it("writes a length the way a player does", () => {
    expect(durationLabel(249)).toBe("4:09");
    expect(durationLabel(3725)).toBe("1:02:05");
    expect(durationLabel(null)).toBeNull();
  });
});
