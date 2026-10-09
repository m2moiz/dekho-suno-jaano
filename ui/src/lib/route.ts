// Which page the address names. Three pages, so no router: the library at
// `/`, one transcript at `/?recording=<id>&transcript=<id>`, and that
// transcript's review at the same address with `&review=1`. Plain links
// between them, so the back button, a reload and a new tab all just work; the
// token survives each, because session.ts keeps it for the tab (#112).

export type Route =
  | { page: "library" }
  | { page: "transcript"; recording: number; transcript: number }
  | { page: "review"; recording: number; transcript: number };

function id(value: string | null): number | null {
  return value !== null && /^\d+$/.test(value) ? Number(value) : null;
}

/** The page `search` (a location's `?...` part) names. Anything malformed is the library. */
export function readRoute(search: string): Route {
  const params = new URLSearchParams(search);
  const recording = id(params.get("recording"));
  const transcript = id(params.get("transcript"));
  if (recording === null || transcript === null) return { page: "library" };
  // Review is the same transcript, checked sentence by sentence (Hashiya spec, Review mode).
  return params.get("review") === "1" ? { page: "review", recording, transcript } : { page: "transcript", recording, transcript };
}

/** The address of one transcript's page. */
export function transcriptHref(recording: number, transcript: number): string {
  return `/?recording=${recording}&transcript=${transcript}`;
}

/** The address of one transcript's review. */
export function reviewHref(recording: number, transcript: number): string {
  return `${transcriptHref(recording, transcript)}&review=1`;
}
