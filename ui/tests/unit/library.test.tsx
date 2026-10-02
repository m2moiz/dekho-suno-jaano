import { act, cleanup, render, screen, within } from "@testing-library/react";
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
  speakersLabel,
} from "../../src/features/library/describe";
import { LibraryPage } from "../../src/features/library/LibraryPage";
import type { RecordingRow, TranscriptRow } from "../../src/features/library/types";
import { takeToken } from "../../src/features/session/session";

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
    duration_s: 3725,
    video_codec: "h264",
    first_seen: "2026-09-20T17:00:00+00:00",
    transcripts: [transcript({ id: 7, engine: "whisper", language: "ur" })],
  },
  {
    id: 1,
    path: "/Volumes/Old disk/standup.m4a",
    size_bytes: 2_048,
    content_id: "c2",
    audio_codec: "aac",
    missing: true,
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
    const items = await screen.findAllByRole("listitem", { name: /\.(mov|m4a)$/ });
    expect(items.map((li) => li.getAttribute("aria-label"))).toEqual(["review.mov", "standup.m4a"]);
    const request = seen.mock.calls[0]?.[0];
    expect(new URL(request?.url ?? "").pathname).toBe("/api/recordings");
    expect(request?.headers.get("Authorization")).toBe("Bearer a-token");
  });

  it("shows date, engine and model for each transcript", async () => {
    serve(ROWS);
    render(<LibraryPage />);
    const review = await screen.findByRole("listitem", { name: "review.mov" });
    const line = within(review).getByText(/whisper/).textContent ?? "";
    expect(line).toContain("2026");
    expect(line).toContain("mlx-community/parakeet-tdt-0.6b-v3");
    expect(line).toContain("ur");
    expect(line).toContain("speakers not labelled");
  });

  it("shows an adopted transcript's engine as unknown, and one speaker as 1 speaker", async () => {
    serve(ROWS);
    render(<LibraryPage />);
    const standup = await screen.findByRole("listitem", { name: "standup.m4a" });
    const line = within(standup).getByText(/speaker/).textContent ?? "";
    expect(line).toContain("unknown");
    expect(line).toContain("1 speaker");
    expect(line).not.toContain("1 speakers");
    expect(line).toContain("0 marks");
  });

  it("keeps a missing recording, greyed out, with its last known path", async () => {
    serve(ROWS);
    render(<LibraryPage />);
    const standup = await screen.findByRole("listitem", { name: "standup.m4a" });
    expect(standup.getAttribute("data-missing")).toBe("true");
    expect(standup.className).toContain("opacity-50");
    expect(within(standup).getByText("/Volumes/Old disk/standup.m4a")).toBeTruthy();
    const review = screen.getByRole("listitem", { name: "review.mov" });
    expect(review.getAttribute("data-missing")).toBeNull();
  });

  it("says the library is empty when it is", async () => {
    serve([]);
    render(<LibraryPage />);
    expect(await screen.findByText("The library is empty.")).toBeTruthy();
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

describe("the words for each value", () => {
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

  it("writes a length the way a player does", () => {
    expect(durationLabel(249)).toBe("4:09");
    expect(durationLabel(3725)).toBe("1:02:05");
    expect(durationLabel(null)).toBeNull();
  });
});
