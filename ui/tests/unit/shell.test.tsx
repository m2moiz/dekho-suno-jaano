import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Installed before the imports below run: the generated client keeps the
// fetch it finds when it is created. The settings menu reads /api/settings.
const fetchMock = vi.hoisted(() => {
  const mock = vi.fn<(request: Request) => Promise<Response>>();
  globalThis.fetch = mock as unknown as typeof fetch;
  return mock;
});

import { AppBar } from "../../src/features/shell/AppBar";
import { takeToken } from "../../src/features/session/session";
import { stubMatchMedia } from "./media";
import { choose } from "./menus";

let settings = { version: 1, transcribe_answer: "mixed", transcribe_diarize: true, export_formats: [] as string[], export_overwrite: false };
let put: object[] = [];

beforeEach(() => {
  stubMatchMedia();
  document.cookie = "dsj-theme=; max-age=0; path=/";
  delete document.documentElement.dataset.theme;
  window.history.replaceState(null, "", "/#t=a-token");
  takeToken();
  settings = { version: 1, transcribe_answer: "mixed", transcribe_diarize: true, export_formats: [], export_overwrite: false };
  put = [];
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (request: Request) => {
    if (new URL(request.url).pathname !== "/api/settings") return Response.json({ detail: "Not Found" }, { status: 404 });
    if (request.method === "PUT") {
      const body = (await request.json()) as object;
      put.push(body);
      settings = { ...settings, ...body };
    }
    return Response.json(settings);
  });
});
afterEach(cleanup);

describe("the app bar", () => {
  it("carries the wordmark home on the library, and a way back on any other page", () => {
    const { rerender } = render(<AppBar />);
    expect(screen.getByRole("link", { name: "dsj" }).getAttribute("href")).toBe("/");
    rerender(<AppBar back />);
    expect(screen.getByRole("link", { name: "Library" }).getAttribute("href")).toBe("/");
  });

  it("is a banner on the blue field", () => {
    render(<AppBar>tools</AppBar>);
    expect(screen.getByRole("banner").className).toContain("bg-field");
  });

  it("keeps the auto-export's formats and overwrite policy on the server (#132)", async () => {
    settings.export_formats = ["txt"];
    render(<AppBar />);
    act(() => fireEvent.click(screen.getByRole("button", { name: "Settings" })));
    const menu = await screen.findByRole("menu");
    expect(within(menu).getByText("After a transcription, also write")).toBeTruthy();
    const text = await within(menu).findByRole("menuitemcheckbox", { name: "Plain text, beside the recording" });
    await vi.waitFor(() => expect(text.getAttribute("aria-checked")).toBe("true"));
    choose(within(menu).getByRole("menuitemcheckbox", { name: "SRT subtitles, beside the recording" }));
    await vi.waitFor(() => expect(put).toEqual([{ export_formats: ["srt", "txt"] }]));
    // The menu stays open for the next box.
    choose(within(menu).getByRole("menuitemcheckbox", { name: "Write over a file already there" }));
    await vi.waitFor(() => expect(put).toHaveLength(2));
    expect(put[1]).toEqual({ export_overwrite: true });
  });

  it("keeps the colours choice in its settings menu, and keeps it in the cookie", async () => {
    render(<AppBar />);
    act(() => fireEvent.click(screen.getByRole("button", { name: "Settings" })));
    choose(await screen.findByRole("menuitemradio", { name: "Dark" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.cookie).toContain("dsj-theme=dark");
  });
});
