import { describe, expect, it } from "vitest";

import { readRoute, transcriptHref } from "../../src/lib/route";

describe("readRoute", () => {
  it("names the library when there is no query", () => {
    expect(readRoute("")).toEqual({ page: "library" });
  });

  it("names a transcript by its recording and transcript ids", () => {
    expect(readRoute("?recording=2&transcript=7")).toEqual({
      page: "transcript",
      recording: 2,
      transcript: 7,
    });
  });

  it("round-trips the address it builds", () => {
    expect(readRoute(new URL(transcriptHref(12, 40), "http://x").search)).toEqual({
      page: "transcript",
      recording: 12,
      transcript: 40,
    });
  });

  it.each(["?transcript=7", "?recording=2", "?recording=..&transcript=7", "?recording=-1&transcript=7", "?recording=1.5&transcript=2"])(
    "falls back to the library for %s",
    (search) => {
      expect(readRoute(search)).toEqual({ page: "library" });
    },
  );
});
