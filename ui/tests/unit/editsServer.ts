// The edit list's routes as the unit tests' mocked servers answer them. The
// page saves one change at a time (#251), a PATCH of a splice made against the
// list the server holds, so a mock that records what was saved must apply it
// to its own copy, as the real server does. Shared by every test file whose
// mock keeps the list (F21).
import type { Content, Entry } from "../../src/lib/editOps";
import { type Splice, spliced } from "../../src/lib/splice";

/** Whether `request` saves the edit list: a patch (#251), or the whole list (kept aside after a 409). */
export const saves = (request: Request): boolean => request.method === "PATCH" || request.method === "PUT";

/** The edit list once `request` has saved over `held`: its patch spliced in, or the list it sent whole. */
export async function savedList(request: Request, held: Content): Promise<Content> {
  const body: unknown = await request.json();
  return request.method === "PATCH" ? spliced(held, body as Splice<Entry>) : (body as { content: Content }).content;
}

/** The server's answer for an edit list: the list and what goes beside it, a patch's fields included. */
export function listReply(content: Content, more: Record<string, unknown> = {}): Response {
  return Response.json({
    content,
    names: {},
    pad_s: 0.1,
    edited_at: null,
    spans: [],
    unrenderable: null,
    replaced: null,
    transcript_sha: "sha-1",
    list_sha: "list-1",
    ...more,
  });
}
