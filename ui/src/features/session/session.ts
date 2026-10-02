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

// This page load's own id, on every request, so the server can tell a goodbye
// from this page apart from another tab that is still open (#206). A new one
// for each load: the library and a transcript are two pages, even in one tab.
export const PAGE_HEADER = "X-Dsj-Page";
const PAGE = crypto.randomUUID();

// Every request through the generated client carries the token as a header.
// Without one the server answers 401 with a sentence saying how to get it.
api.use({
  onRequest({ request }) {
    if (token !== null) request.headers.set("Authorization", `Bearer ${token}`);
    request.headers.set(PAGE_HEADER, PAGE);
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
// dsj/ui/server.py), so a page that vanished without a word does not leave it
// running. Every 15 s while the tab is in front; a hidden tab's timer is slowed
// by the browser to about once a minute (measured in Chromium, #204), which the
// cutoff allows for. A page that closes says so (sayBye), and the server stops
// seconds later instead.
export const BEAT_MS = 15_000;

/**
 * Tell the server this page is going away: closed, reloaded, or left for the
 * next page (#206). The server stops shortly after unless a page beats.
 *
 * A plain fetch, started inside the `pagehide` handler: the generated client
 * awaits its middleware before it fetches, and a page being torn down should
 * not have to outlive a promise. `keepalive` lets the request finish after the
 * page is gone, and unlike `navigator.sendBeacon` it can carry the token header.
 */
function sayBye(win: Window): void {
  if (token === null) return;
  const request = new Request(new URL("/api/bye", win.location.origin), {
    method: "POST",
    keepalive: true,
    headers: { Authorization: `Bearer ${token}`, [PAGE_HEADER]: PAGE },
  });
  fetch(request).catch((error: unknown) => {
    console.warn("dsj ui goodbye failed", error);
  });
}

/**
 * Beat now, then every BEAT_MS, and the moment the tab comes back into view,
 * so a tab the browser has slowed down does not wait for its next slow tick.
 *
 * Say goodbye on `pagehide`, and beat again on a `pageshow` that brings the
 * page back from the back-forward cache: its goodbye was already sent.
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
  const onHide = () => sayBye(win);
  const onShow = (event: PageTransitionEvent) => {
    if (event.persisted) beat();
  };
  beat();
  const timer = win.setInterval(beat, BEAT_MS);
  win.document.addEventListener("visibilitychange", onVisible);
  win.addEventListener("pagehide", onHide);
  win.addEventListener("pageshow", onShow);
  return () => {
    win.clearInterval(timer);
    win.document.removeEventListener("visibilitychange", onVisible);
    win.removeEventListener("pagehide", onHide);
    win.removeEventListener("pageshow", onShow);
  };
}
