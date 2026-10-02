// The token that lets this page, and only this page, use the dsj ui server
// (#112). `dsj ui` opens http://127.0.0.1:<port>/#t=<token>. The part after
// `#` never reaches a server, so it stays out of logs and out of Referer; this
// file takes it, wipes it from the address bar at once so it stays out of the
// browser's history too, and puts it on every request the API client sends.

import { api } from "@/api/client";
import type { AppError } from "@/features/errors/appError";

const KEY = "dsj-token";
const FRAGMENT = /^#t=([A-Za-z0-9_-]+)$/;

/** What the page says when it was opened without its token. */
export const NO_TOKEN: AppError = {
  error: "NoToken",
  message:
    "This page was opened without its key, so it cannot reach dsj. Open the address " +
    "`dsj ui` printed in the terminal, including the part after #.",
  request: null,
};

let token: string | null = null;

// Every request through the generated client carries the token as a header.
// Without one the server answers 401 with a sentence saying how to get it.
api.use({
  onRequest({ request }) {
    if (token !== null) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  },
});

/**
 * Take the token from the address bar, or from this tab's earlier load.
 *
 * Kept in sessionStorage so a reload of this tab still works: it is per tab
 * and per port, so it dies with the tab and never reaches another server.
 */
export function takeToken(win: Window = window): string | null {
  const found = FRAGMENT.exec(win.location.hash);
  if (found?.[1] !== undefined) {
    token = found[1];
    win.sessionStorage.setItem(KEY, token);
    win.history.replaceState(win.history.state, "", win.location.pathname + win.location.search);
    return token;
  }
  token = win.sessionStorage.getItem(KEY);
  return token;
}

/**
 * The token, for the one request that cannot carry the header: a media
 * element's, which the server lets put it in the query (#59).
 */
export function sessionToken(): string | null {
  return token;
}

// The server exits three minutes after the last beat (#112 rule 6, IDLE_S in
// dsj/ui/server.py), so a closed window does not leave it running. Every 15 s
// while the tab is in front; a hidden tab's timer is slowed by the browser to
// about once a minute (measured in Chromium, #204), which the cutoff allows for.
export const BEAT_MS = 15_000;

/**
 * Beat now, then every BEAT_MS, and the moment the tab comes back into view,
 * so a tab the browser has slowed down does not wait for its next slow tick.
 */
export function startHeartbeat(win: Window = window): () => void {
  const beat = () => {
    // A failed beat is not an error to put in front of the reader: the next
    // one may land, and a server that is gone shows itself on the next real
    // request. It is logged, not dropped.
    api.POST("/api/heartbeat").catch((error: unknown) => {
      console.warn("dsj ui heartbeat failed", error);
    });
  };
  const onVisible = () => {
    if (win.document.visibilityState === "visible") beat();
  };
  beat();
  const timer = win.setInterval(beat, BEAT_MS);
  win.document.addEventListener("visibilitychange", onVisible);
  return () => {
    win.clearInterval(timer);
    win.document.removeEventListener("visibilitychange", onVisible);
  };
}
