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
import type { RecordingRow } from "../../src/features/library/types";
import { takeToken } from "../../src/features/session/session";
import { hasFraction, progressLine } from "../../src/features/transcribe/describe";
import { type Engine, forgetJobs, type Job } from "../../src/features/transcribe/jobs";
import { TranscribeControl } from "../../src/features/transcribe/TranscribeControl";

const RECORDING: RecordingRow = {
  id: 4,
  path: "/Users/me/Recordings/standup.m4a",
  size_bytes: 2_048,
  content_id: "c4",
  audio_codec: "aac",
  missing: false,
  duration_s: 315,
  video_codec: null,
  first_seen: "2026-10-02T08:30:00+00:00",
  transcripts: [],
};

const ENGINES: Engine[] = [
  { name: "parakeet", reason: null, default_model: "mlx-community/parakeet-tdt-0.6b-v3" },
  { name: "whisper", reason: null, default_model: "mlx-community/whisper-large-v3-turbo" },
  {
    name: "sherpa",
    reason: "the sherpa engine cannot run here: sherpa-onnx will not import here",
    default_model: "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8",
  },
];

function job(overrides: Partial<Job>): Job {
  return {
    id: 1,
    recording_id: 4,
    engine: "parakeet",
    model: "mlx-community/parakeet-tdt-0.6b-v3",
    language: null,
    reports_progress: true,
    started_at: "2026-10-02T09:00:00+00:00",
    state: "running",
    fraction: 1 / 3,
    audio_done_s: 105,
    audio_total_s: 315,
    elapsed_s: 5,
    speed: 21,
    eta_s: 10,
    stalled_s: null,
    error: null,
    transcript_id: null,
    notes: [],
    ...overrides,
  };
}

type Route = (request: Request) => Response | Promise<Response>;

/** Answer each request by its method and path; anything else fails the test loudly. */
function serve(routes: Record<string, Route>) {
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (request: Request) => {
    const key = `${request.method} ${new URL(request.url).pathname}`;
    const route = routes[key];
    if (route === undefined) throw new Error(`no route for ${key}`);
    return route(request);
  });
  return fetchMock;
}

const sent = (method: string, path: string) =>
  fetchMock.mock.calls
    .map(([request]) => request)
    .filter((r) => r.method === method && new URL(r.url).pathname === path);

beforeEach(() => {
  window.history.replaceState(null, "", "/#t=a-token");
  takeToken();
  forgetJobs();
});

afterEach(() => {
  cleanup();
  act(() => {
    dismissError();
    forgetJobs();
  });
});

async function openPicker() {
  render(<TranscribeControl recording={RECORDING} />);
  fireEvent.click(await screen.findByRole("button", { name: "Transcribe" }));
  return screen.findByRole("dialog");
}

describe("the picker", () => {
  it("lists parakeet, whisper and sherpa, and nothing else", async () => {
    serve({ "GET /api/jobs": () => Response.json([]), "GET /api/engines": () => Response.json(ENGINES) });
    const dialog = await openPicker();
    const group = within(dialog).getByRole("group", { name: "Engine" });
    expect(within(group).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "parakeet",
      "whisper",
      "sherpa",
    ]);
  });

  it("disables an engine that cannot run, and shows its reason", async () => {
    serve({ "GET /api/jobs": () => Response.json([]), "GET /api/engines": () => Response.json(ENGINES) });
    const dialog = await openPicker();
    const sherpa = within(dialog).getByRole("button", { name: "sherpa" });
    expect(sherpa.hasAttribute("disabled") || sherpa.getAttribute("aria-disabled") === "true").toBe(true);
    expect(within(dialog).getByText(/sherpa-onnx will not import here/)).toBeTruthy();
    const parakeet = within(dialog).getByRole("button", { name: "parakeet" });
    expect(parakeet.hasAttribute("disabled")).toBe(false);
  });

  it("shows language, prompt and Roman Urdu for whisper only", async () => {
    serve({ "GET /api/jobs": () => Response.json([]), "GET /api/engines": () => Response.json(ENGINES) });
    const dialog = await openPicker();
    expect(within(dialog).queryByLabelText("Language")).toBeNull();
    expect(within(dialog).queryByLabelText("Prompt")).toBeNull();
    expect(within(dialog).queryByRole("switch", { name: "Roman Urdu" })).toBeNull();

    fireEvent.click(within(dialog).getByRole("button", { name: "whisper" }));
    expect(within(dialog).getByLabelText("Language")).toBeTruthy();
    expect(within(dialog).getByLabelText("Prompt")).toBeTruthy();
    expect(within(dialog).getByRole("switch", { name: "Roman Urdu" })).toBeTruthy();
    expect(within(dialog).getByText(/reports no progress until it is done/)).toBeTruthy();
    // The model box follows the engine, to that engine's own default.
    expect((within(dialog).getByLabelText("Model") as HTMLInputElement).value).toBe(
      "mlx-community/whisper-large-v3-turbo",
    );

    fireEvent.click(within(dialog).getByRole("button", { name: "parakeet" }));
    expect(within(dialog).queryByLabelText("Language")).toBeNull();
  });

  it("sends whisper with Roman Urdu, speakers on, as dsj suno's flags", async () => {
    const bodies: unknown[] = [];
    serve({
      "GET /api/jobs": () => Response.json([]),
      "GET /api/engines": () => Response.json(ENGINES),
      "POST /api/recordings/4/transcribe": async (request) => {
        bodies.push(await request.json());
        return Response.json(job({ engine: "whisper", reports_progress: true, state: "starting" }), {
          status: 202,
        });
      },
    });
    const dialog = await openPicker();
    fireEvent.click(within(dialog).getByRole("button", { name: "whisper" }));
    fireEvent.click(within(dialog).getByRole("switch", { name: "Roman Urdu" }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Start" }));
    expect(await screen.findByRole("status", { name: "Transcription" })).toBeTruthy();
    expect(bodies).toEqual([
      {
        engine: "whisper",
        model: "mlx-community/whisper-large-v3-turbo",
        language: null,
        prompt: null,
        roman_urdu: true,
        diarize: true,
        require_diarize: false,
        start_over: false,
      },
    ]);
    expect(sent("POST", "/api/recordings/4/transcribe")[0]?.headers.get("Authorization")).toBe(
      "Bearer a-token",
    );
  });

  it("puts a refusal in the error dialog in the server's own words", async () => {
    const refusal = {
      error: "AlreadyRunning",
      message: "another dsj suno is already running on this machine: pid 4242, writing /tmp/x.json.",
      request: "/api/recordings/4/transcribe",
    };
    serve({
      "GET /api/jobs": () => Response.json([]),
      "GET /api/engines": () => Response.json(ENGINES),
      "POST /api/recordings/4/transcribe": () => Response.json(refusal, { status: 409 }),
    });
    const dialog = await openPicker();
    fireEvent.click(within(dialog).getByRole("button", { name: "Start" }));
    await vi.waitFor(() => expect(currentError()).toEqual(refusal));
  });
});

describe("a job on its recording's row", () => {
  it("finds a job already running when the page loads, and shows its bar", async () => {
    serve({ "GET /api/jobs": () => Response.json([job({})]) });
    render(<TranscribeControl recording={RECORDING} />);
    const status = await screen.findByRole("status", { name: "Transcription" });
    expect(status.textContent).toContain("Transcribing with parakeet");
    expect(status.textContent).toContain("1:45 of 5:15");
    expect(within(status).getByRole("progressbar").getAttribute("aria-valuenow")).toBe("33");
  });

  it("says so in words when whisper will report nothing until it is done", async () => {
    serve({
      "GET /api/jobs": () => Response.json([job({ engine: "whisper", reports_progress: false, fraction: 0 })]),
    });
    render(<TranscribeControl recording={RECORDING} />);
    const status = await screen.findByRole("status", { name: "Transcription" });
    expect(status.textContent).toContain("whisper reports no progress until it is done.");
    expect(within(status).getByRole("progressbar").getAttribute("aria-valuenow")).toBeNull();
  });

  it("shows a run that crashed as failed, with its error", async () => {
    serve({
      "GET /api/jobs": () =>
        Response.json([job({ state: "failed", error: "RuntimeError: model exploded" })]),
    });
    render(<TranscribeControl recording={RECORDING} />);
    expect((await screen.findByRole("alert")).textContent).toContain("RuntimeError: model exploded");
    expect(screen.queryByRole("status", { name: "Transcription" })).toBeNull();
  });

  it("polls while a job runs, and stops once it is done", async () => {
    vi.useFakeTimers();
    try {
      const replies = [
        [job({ fraction: 1 / 3 })],
        [job({ fraction: 2 / 3, audio_done_s: 210 })],
        [job({ state: "done", fraction: 1, transcript_id: 9, notes: ["diarization skipped: x"] })],
      ];
      serve({ "GET /api/jobs": () => Response.json(replies.shift() ?? []) });
      render(<TranscribeControl recording={RECORDING} />);
      await act(() => vi.advanceTimersByTimeAsync(0));
      expect(screen.getByRole("status").textContent).toContain("1:45 of 5:15");
      await act(() => vi.advanceTimersByTimeAsync(1000));
      expect(screen.getByRole("status").textContent).toContain("3:30 of 5:15");
      await act(() => vi.advanceTimersByTimeAsync(1000));
      expect(screen.queryByRole("status")).toBeNull();
      expect(screen.getByText("diarization skipped: x")).toBeTruthy();
      await act(() => vi.advanceTimersByTimeAsync(5000));
      expect(sent("GET", "/api/jobs")).toHaveLength(3);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("the words for a running job", () => {
  it("shows audio, speed and time left for an engine that reports", () => {
    expect(progressLine(job({}))).toBe("1:45 of 5:15 · 21.0x · about 0:10 left");
  });

  it("draws no number for phases that report none", () => {
    expect(hasFraction(job({ state: "starting" }))).toBe(false);
    expect(hasFraction(job({ state: "diarizing" }))).toBe(false);
    expect(hasFraction(job({ state: "extracting" }))).toBe(true);
    expect(hasFraction(job({ state: "running", reports_progress: false }))).toBe(false);
  });
});
