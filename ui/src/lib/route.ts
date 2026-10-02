// Which page the address names. Two pages, so no router: the library at `/`,
// and one transcript at `/?recording=<id>&transcript=<id>`. Plain links
// between them, so the back button, a reload and a new tab all just work; the
// token survives each, because session.ts keeps it for the tab (#112).

export type Route =
  | { page: "library" }
  | { page: "transcript"; recording: number; transcript: number };

function id(value: string | null): number | null {
  return value !== null && /^\d+$/.test(value) ? Number(value) : null;
}

/** The page `search` (a location's `?...` part) names. Anything malformed is the library. */
export function readRoute(search: string): Route {
  const params = new URLSearchParams(search);
  const recording = id(params.get("recording"));
  const transcript = id(params.get("transcript"));
  if (recording === null || transcript === null) return { page: "library" };
  return { page: "transcript", recording, transcript };
}

/** The address of one transcript's page. */
export function transcriptHref(recording: number, transcript: number): string {
  return `/?recording=${recording}&transcript=${transcript}`;
}
