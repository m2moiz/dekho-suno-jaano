import { describe, expect, it, vi } from "vitest";

import { api } from "@/api/client";
import type { components } from "@/api/schema";

type Recording = components["schemas"]["Recording"];

describe("the API client", () => {
  it("asks this page's own origin for the recordings and hands back the reply", async () => {
    const reply: Recording[] = [];
    // Per request, not vi.stubGlobal: openapi-fetch keeps the fetch it found
    // when the client was created, so a stub installed afterwards is never called.
    const fetchSpy = vi.fn(async (_request: Request) => Response.json(reply));

    const { data, error } = await api.GET("/api/recordings", { fetch: fetchSpy });

    expect(error).toBeUndefined();
    expect(data).toEqual([]);
    const request = fetchSpy.mock.calls[0]?.[0];
    expect(request?.method).toBe("GET");
    expect(new URL(request?.url ?? "").pathname).toBe("/api/recordings");
    expect(new URL(request?.url ?? "").origin).toBe(window.location.origin);
  });

  it("types the reply from dsj/ui/schemas.py", () => {
    // Held by tsc, not by this assertion: if `durationSeconds` ever exists on a
    // recording, or the reply decays to an untyped object, the directive
    // below is unused and `tsc --noEmit` fails.
    const read = (recording: Recording) =>
      // @ts-expect-error the field is duration_s; there is no durationSeconds
      recording.durationSeconds;
    expect(typeof read).toBe("function");
  });
});
