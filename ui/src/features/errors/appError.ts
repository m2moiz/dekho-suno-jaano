// One shape for every failure the page can show (#82), matching what
// dsj/ui/errors.py sends: the error's name, its message exactly as dsj wrote
// it, and the request that failed. The dialog shows the message; the copy
// button takes all three, because the name is what makes a pasted error
// searchable.

import { useSyncExternalStore } from "react";

export type AppError = {
  error: string;
  message: string;
  request: string | null;
};

function isAppError(value: unknown): value is AppError {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return typeof v.error === "string" && typeof v.message === "string";
}

/** The error a failed reply's parsed body carries, or one made from its status when it carries none. */
export function fromBody(body: unknown, response: Response, request: string): AppError {
  if (isAppError(body)) {
    return { error: body.error, message: body.message, request };
  }
  // FastAPI's own replies (a 404, a 422) carry `detail`: a sentence, or a list.
  const raw: unknown =
    typeof body === "object" && body !== null && "detail" in body
      ? (body as { detail: unknown }).detail
      : body;
  const detail = typeof raw === "string" ? raw : raw == null ? "" : JSON.stringify(raw);
  return {
    error: `HTTP ${response.status}`,
    message: detail || response.statusText || "The server answered with no explanation.",
    request,
  };
}

/** Anything thrown, as an AppError, keeping its own name and text. */
export function fromThrown(thrown: unknown, request: string | null = null): AppError {
  if (thrown instanceof ApiError) return thrown.detail;
  if (thrown instanceof Error) {
    return { error: thrown.name, message: thrown.message, request };
  }
  return { error: "Error", message: String(thrown), request };
}

/** What the copy button puts on the clipboard. */
export function copyText(e: AppError): string {
  const lines = [`${e.error}: ${e.message}`];
  if (e.request !== null) lines.push(`request: ${e.request}`);
  return lines.join("\n");
}

/** A failed API reply, thrown, so a caller's catch hands the dialog the server's words. */
export class ApiError extends Error {
  readonly detail: AppError;
  /** The reply's HTTP status, where the caller passed it: a save tells a 500 from a refusal by it. */
  readonly status: number | null;

  constructor(detail: AppError, status: number | null = null) {
    super(detail.message);
    this.name = detail.error;
    this.detail = detail;
    this.status = status;
  }
}

/**
 * Whether a save that threw may have been applied all the same (#251 fix
 * round 1, I1): its answer never came (the network dropped it), or the server
 * failed after writing (a 5xx), or it was refused as made against a document
 * changed since, which is what a save applied with its answer lost looks like
 * to the next one. `changed` is that refusal's name.
 */
export function inDoubt(thrown: unknown, changed: string): boolean {
  if (!(thrown instanceof ApiError)) return true;
  return thrown.detail.error === changed || (thrown.status ?? 0) >= 500;
}

// The error the dialog is showing, if any: module state, not React state, so
// code outside any component (a fetch, a startup check) can raise it.
let shown: AppError | null = null;
const listeners = new Set<() => void>();

function emit() {
  for (const listener of listeners) listener();
}

export function showError(e: AppError): void {
  shown = e;
  emit();
}

export function dismissError(): void {
  shown = null;
  emit();
}

export function currentError(): AppError | null {
  return shown;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useShownError(): AppError | null {
  return useSyncExternalStore(subscribe, currentError);
}
