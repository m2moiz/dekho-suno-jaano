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
import { choose } from "./menus";

const RECORDING: RecordingRow = {
  id: 4,
  path: "/Users/me/Recordings/standup.m4a",
  size_bytes: 2_048,
  content_id: "c4",
  audio_codec: "aac",
  missing: false,
  unreadable: null,
  title: null,
  duration_s: 315,
  video_codec: null,
  first_seen: "2026-10-02T08:30:00+00:00",
  transcripts: [],
};

const ENGINES: Engine[] = [
  { name: "parakeet", reason: null, default_model: "mlx-community/parakeet-tdt-0.6b-v3", cloud: false, usd_per_hour: null },
  { name: "whisper", reason: null, default_model: "mlx-community/whisper-large-v3-turbo", cloud: false, usd_per_hour: null },
  {
    name: "sherpa",
    reason: "the sherpa engine cannot run here: sherpa-onnx will not import here",
    default_model: "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8",
    cloud: false,
    usd_per_hour: null,
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

describe("the Transcribe dialog", () => {
  async function open(engines: Engine[] = ENGINES): Promise<Request[]> {
    const posted: Request[] = [];
    serve({
      "GET /api/jobs": () => Response.json([]),
      "GET /api/engines": () => Response.json(engines),
      "POST /api/recordings/4/transcribe": (request) => {
        posted.push(request.clone());
        return Response.json(job({ engine: "whisper" }), { status: 202 });
      },
    });
    render(<TranscribeControl recording={{ ...RECORDING, duration_s: 2520 }} />);
    fireEvent.click(await screen.findByRole("button", { name: "Transcribe" }));
    await screen.findByRole("radiogroup", { name: "What's spoken?" });
    return posted;
  }

  it("asks what is spoken first, says how long and what it will use, and runs it", async () => {
    const posted = await open();
    // 2,520 s at --roman-urdu's measured 3.76x (choices.ts).
    expect(screen.getByRole("status").textContent).toBe(
      "About 11 minutes for this 42-minute recording. Uses whisper, writing Urdu in Roman letters.",
    );
    fireEvent.click(screen.getByRole("button", { name: "Start" }));
    await vi.waitFor(() => expect(posted).toHaveLength(1));
    expect(await posted[0]?.json()).toEqual({
      engine: "whisper",
      model: null,
      language: null,
      prompt: null,
      roman_urdu: true,
      diarize: true,
      require_diarize: false,
      start_over: false,
    });
    expect(posted[0]?.headers.get("Authorization")).toBe("Bearer a-token");
  });

  it("runs English on parakeet, and mostly Urdu on whisper in Urdu", async () => {
    const posted = await open();
    choose(screen.getByRole("radio", { name: "English or European languages" }));
    expect(screen.getByRole("status").textContent).toBe("About 2 minutes for this 42-minute recording. Uses parakeet.");
    choose(screen.getByRole("radio", { name: "Mostly Urdu" }));
    fireEvent.click(screen.getByRole("button", { name: "Start" }));
    await vi.waitFor(() => expect(posted).toHaveLength(1));
    expect(await posted[0]?.json()).toMatchObject({ engine: "whisper", roman_urdu: false, language: "ur" });
  });

  it("offers every engine that can run as a choice, and one that cannot as one grey line", async () => {
    const posted = await open();
    const group = screen.getByRole("radiogroup", { name: "Engine" });
    expect(within(group).getAllByRole("radio").map((r) => r.closest("label")?.textContent)).toEqual([
      "parakeet",
      "whisperfor this answer",
    ]);
    expect(screen.getByText("sherpa can't run on this Mac.")).toBeTruthy();
    expect(screen.queryByText(/sherpa-onnx will not import here/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Why sherpa can't run" }));
    expect(screen.getByText(/sherpa-onnx will not import here/)).toBeTruthy();

    // Picked by hand, an engine runs as itself, without the answer's Roman Urdu.
    choose(within(group).getByRole("radio", { name: "parakeet" }));
    expect(screen.getByRole("status").textContent).toBe("About 2 minutes for this 42-minute recording. Uses parakeet.");
    fireEvent.click(screen.getByRole("button", { name: "Start" }));
    await vi.waitFor(() => expect(posted).toHaveLength(1));
    expect(await posted[0]?.json()).toMatchObject({ engine: "parakeet", roman_urdu: false, language: null });
  });

  it("marks an engine the server calls cloud, prices the recording on it, and stops saying nothing leaves", async () => {
    // A stand-in for sub-project B's cloud engine (#247): the dialog reads only the fields.
    await open([{ ...ENGINES[0], cloud: true, usd_per_hour: 1.2 } as Engine, ...ENGINES.slice(1)]);
    const group = screen.getByRole("radiogroup", { name: "Engine" });
    const parakeet = within(group).getByRole("radio", { name: /^parakeet/ }).closest("label");
    expect(parakeet?.textContent).toBe("parakeetcloudAbout $0.84 for this recording");
    expect(screen.getByText("Runs on this Mac. Nothing leaves it.")).toBeTruthy();
    choose(within(group).getByRole("radio", { name: /^parakeet/ }));
    expect(screen.getByText("Sends the recording's sound to parakeet, off this Mac.")).toBeTruthy();
  });

  it("folds the rest under Advanced", async () => {
    await open();
    expect(screen.queryByLabelText("Model")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Advanced" }));
    expect((screen.getByLabelText("Model") as HTMLInputElement).placeholder).toBe("mlx-community/whisper-large-v3-turbo");
    expect(screen.getByLabelText("Prompt")).toBeTruthy();
    choose(screen.getByRole("radio", { name: "English or European languages" }));
    // parakeet takes no prompt, as `dsj suno` refuses one.
    expect(screen.queryByLabelText("Prompt")).toBeNull();
  });

  it("carries Skip speaker labels into the request", async () => {
    const posted = await open();
    fireEvent.click(screen.getByRole("button", { name: "Advanced" }));
    fireEvent.click(screen.getByRole("switch", { name: "Skip speaker labels" }));
    fireEvent.click(screen.getByRole("button", { name: "Start" }));
    await vi.waitFor(() => expect(posted).toHaveLength(1));
    expect(await posted[0]?.json()).toMatchObject({ diarize: false, require_diarize: false });
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
    render(<TranscribeControl recording={RECORDING} />);
    fireEvent.click(await screen.findByRole("button", { name: "Transcribe" }));
    fireEvent.click(await screen.findByRole("button", { name: "Start" }));
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
