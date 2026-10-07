import { afterEach, describe, expect, it, vi } from "vitest";

const fetchMock = vi.hoisted(() => {
  const mock = vi.fn<(request: Request) => Promise<Response>>();
  globalThis.fetch = mock as unknown as typeof fetch;
  return mock;
});

import { ApiError } from "../../src/features/errors/appError";
import { exportTranscript } from "../../src/features/transcript/exportFile";

afterEach(() => vi.restoreAllMocks());

describe("exportTranscript", () => {
  it("downloads the server's text under the recording's title", async () => {
    fetchMock.mockResolvedValue(new Response("1\n00:00:00,200 --> 00:00:00,900\nHello.\n", { headers: { "content-type": "text/plain" } }));
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();
    const clicked: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(this.download);
    });
    await exportTranscript(7, "srt", "Sat 20 Sep, 9:42 am");
    expect(new URL(fetchMock.mock.calls[0]?.[0].url ?? "").pathname).toBe("/api/transcripts/7/export/srt");
    expect(clicked).toEqual(["Sat 20 Sep, 9.42 am.srt"]);
  });

  it("says what the server said when there is no such format", async () => {
    fetchMock.mockResolvedValue(Response.json({ detail: "There is no export format 'docx'." }, { status: 404 }));
    URL.createObjectURL = vi.fn(() => "blob:x");
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    await expect(exportTranscript(7, "srt", "talk")).rejects.toBeInstanceOf(ApiError);
    expect(click).not.toHaveBeenCalled();
  });
});
