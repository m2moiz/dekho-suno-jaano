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

/** The error a failed reply carries, or one made from its status when it carries none. */
export async function fromResponse(response: Response, request: string): Promise<AppError> {
  const text = await response.text();
  let body: unknown = null;
  try {
    body = JSON.parse(text);
  } catch {
    // Not JSON: a proxy's page or an empty body. The status and the text say what there is.
    body = null;
  }
  if (isAppError(body)) {
    return { error: body.error, message: body.message, request };
  }
  // FastAPI's own replies (a 404, a 422) carry `detail`: a sentence, or a list.
  const raw: unknown =
    typeof body === "object" && body !== null && "detail" in body
      ? (body as { detail: unknown }).detail
      : text;
  const detail = typeof raw === "string" ? raw : JSON.stringify(raw);
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

  constructor(detail: AppError) {
    super(detail.message);
    this.name = detail.error;
    this.detail = detail;
  }
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
