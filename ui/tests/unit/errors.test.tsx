import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  copyText,
  dismissError,
  fromBody,
  fromThrown,
  showError,
} from "../../src/features/errors/appError";
import { ErrorBoundary } from "../../src/features/errors/ErrorBoundary";
import { ShownErrorDialog } from "../../src/features/errors/ErrorDialog";

const FFMPEG = {
  error: "FFmpegNotFound",
  message: "ffprobe is not on PATH. dsj reads video through ffmpeg; install it with `brew install ffmpeg`.",
  request: "/api/probe",
};

afterEach(() => {
  cleanup();
  act(() => dismissError());
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function Crashes(): never {
  throw new TypeError("cannot read the transcript's sentences");
}

describe("a view that crashes", () => {
  it("shows the dialog with a reload button, and the frame stays up", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    render(
      <div>
        <header>the frame</header>
        <ErrorBoundary>
          <Crashes />
        </ErrorBoundary>
      </div>,
    );
    expect(screen.getByText("the frame")).toBeTruthy();
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(screen.getByText("cannot read the transcript's sentences")).toBeTruthy();
    expect(screen.getByText("TypeError")).toBeTruthy();
    const reload = vi.fn();
    vi.stubGlobal("location", { ...window.location, reload });
    fireEvent.click(screen.getByRole("button", { name: "Reload" }));
    expect(reload).toHaveBeenCalledOnce();
  });
});

describe("a failed request", () => {
  it("shows dsj's own sentence, unchanged", () => {
    const reply = new Response(null, { status: 503 });
    const error = fromBody(FFMPEG, reply, "/api/probe");
    expect(error).toEqual(FFMPEG);
    render(<ShownErrorDialog />);
    act(() => showError(error));
    expect(screen.getByText(FFMPEG.message)).toBeTruthy();
  });

  it("copies the name, the message and the request in one click", async () => {
    const writeText = vi.fn<(text: string) => Promise<void>>().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    render(<ShownErrorDialog />);
    act(() => showError(FFMPEG));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Copy error" }));
    });
    expect(writeText).toHaveBeenCalledWith(
      `FFmpegNotFound: ${FFMPEG.message}\nrequest: /api/probe`,
    );
    expect(screen.getByRole("button", { name: "Copied" })).toBeTruthy();
  });

  it("says so when the clipboard refuses, rather than claiming it copied", async () => {
    const writeText = vi.fn<(text: string) => Promise<void>>().mockRejectedValue(new Error("no"));
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    render(<ShownErrorDialog />);
    act(() => showError(FFMPEG));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Copy error" }));
    });
    expect(screen.getByText(/clipboard refused/)).toBeTruthy();
  });

  it("still reaches the dialog when the reply is not dsj's shape", () => {
    const reply = new Response(null, { status: 502, statusText: "Bad Gateway" });
    expect(fromBody("upstream timed out", reply, "/api/x")).toEqual({
      error: "HTTP 502",
      message: "upstream timed out",
      request: "/api/x",
    });
  });

  it("reads FastAPI's own detail sentence as the message", () => {
    const reply = new Response(null, { status: 404 });
    expect(fromBody({ detail: "There is no transcript 9 in the library." }, reply, "/api/t/9")).toEqual({
      error: "HTTP 404",
      message: "There is no transcript 9 in the library.",
      request: "/api/t/9",
    });
  });

  it("closes, and nothing is left behind", () => {
    render(<ShownErrorDialog />);
    act(() => showError(FFMPEG));
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("fromThrown", () => {
  it("keeps an API error's server-side name", () => {
    expect(fromThrown(new ApiError(FFMPEG))).toEqual(FFMPEG);
  });

  it("keeps an unlisted error's own name and text", () => {
    expect(fromThrown(new RangeError("offset past the end"), "/api/t/1")).toEqual({
      error: "RangeError",
      message: "offset past the end",
      request: "/api/t/1",
    });
    expect(fromThrown("a bare string")).toEqual({
      error: "Error",
      message: "a bare string",
      request: null,
    });
  });

  it("leaves the request line out of the copy when there was no request", () => {
    expect(copyText({ error: "NoToken", message: "open the address", request: null })).toBe(
      "NoToken: open the address",
    );
  });
});
