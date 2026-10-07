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

  it("names the file for the recording without its extension", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(new Response("x", { headers: { "content-type": "text/plain" } })));
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();
    const clicked: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(this.download);
    });
    await exportTranscript(7, "vtt", "talk.wav");
    await exportTranscript(7, "txt", "board.review.final.mp4");
    await exportTranscript(7, "srt", "Notes v1.2");
    // Only a recording's own extension goes: a typed title keeps its ".com",
    // and a leading dot or a control character would hide or break the file
    // (Task 6 review, deferred to Task 16).
    await exportTranscript(7, "srt", "call with acme.com");
    await exportTranscript(7, "txt", "..hidden\u0007 notes");
    expect(clicked).toEqual(["talk.vtt", "board.review.final.txt", "Notes v1.2.srt", "call with acme.com.srt", "hidden notes.txt"]);
  });

  it("downloads an empty file for a transcript with no words", async () => {
    // The client reads a zero-length body as no data at all.
    fetchMock.mockResolvedValue(new Response("", { headers: { "content-type": "text/plain", "content-length": "0" } }));
    const made: Blob[] = [];
    URL.createObjectURL = vi.fn((blob: Blob | MediaSource) => {
      made.push(blob as Blob);
      return "blob:x";
    });
    URL.revokeObjectURL = vi.fn();
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    await exportTranscript(7, "srt", "talk.wav");
    expect(click).toHaveBeenCalledOnce();
    expect(made.map((blob) => blob.size)).toEqual([0]);
  });
});
