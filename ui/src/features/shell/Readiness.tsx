// The first-run screen (#70): what a run needs that this Mac does not have
// yet, said before any work starts, with the fix. Read from GET /api/readiness,
// which asks the machine now (ffmpeg on PATH, each engine's own availability,
// each runnable engine's default model on disk), so installing ffmpeg and
// reloading clears the line. Nothing is shown when everything is ready.

import { useEffect, useState } from "react";

import { api } from "@/api/client";
import type { components } from "@/api/schema";

export type Readiness = components["schemas"]["Readiness"];

/**
 * Read the machine's readiness; null when the server could not be asked or
 * answered with something else (the page still works, with no notice).
 */
export async function loadReadiness(): Promise<Readiness | null> {
  const { data } = await api.GET("/api/readiness").catch(() => ({ data: undefined }));
  if (data === undefined || !Array.isArray(data.tools) || !Array.isArray(data.models)) return null;
  return data;
}

/** The lines the screen shows for `readiness`, each a thing to fix; none when ready. */
export function shortfalls(readiness: Readiness): string[] {
  const lines: string[] = [];
  for (const tool of readiness.tools) {
    if (!tool.ok && tool.reason !== null) lines.push(tool.reason);
  }
  const runnable = readiness.engines.filter((e) => e.reason === null);
  if (runnable.length === 0) {
    for (const engine of readiness.engines) {
      if (engine.reason !== null) lines.push(`${engine.name}: ${engine.reason}`);
    }
  }
  for (const model of readiness.models) {
    if (model.state === "missing" || model.state === "partial") lines.push(model.reason);
  }
  return lines;
}

export function ReadinessNotice() {
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  useEffect(() => {
    let live = true;
    void loadReadiness().then((found) => {
      if (live) setReadiness(found);
    });
    return () => {
      live = false;
    };
  }, []);
  if (readiness === null || readiness.ready) return null;
  const lines = shortfalls(readiness);
  if (lines.length === 0) return null;
  return (
    <section
      role="status"
      aria-label="Before the first run"
      className="flex flex-col gap-2 rounded-xl border border-border bg-card px-4 py-3 text-sm"
    >
      <h2 className="font-semibold">Before the first run</h2>
      <ul className="flex list-disc flex-col gap-1 pl-5">
        {lines.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
    </section>
  );
}
