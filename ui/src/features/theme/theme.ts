// Light, dark, or follow the Mac (#116).
//
// The choice is kept in a cookie, not localStorage. Every `dsj ui` binds a new
// port (#112), and localStorage is keyed on the port, so a choice saved there
// is gone on the next launch (observed in Chromium on 2026-09-23). A cookie is
// keyed on the host alone, so 127.0.0.1 keeps it across ports. Not the server
// and not the library either: the colours must be known before the first
// paint, which no request can be.
//
// The inline script at the top of ui/index.html reads the same cookie before
// any stylesheet, which is what stops a white flash; this file is everything
// after that.

export const THEMES = ["light", "dark", "system"] as const;
export type Theme = (typeof THEMES)[number];

export const COOKIE = "dsj-theme";
// A year, renewed on every change. Long enough that it never quietly expires.
const MAX_AGE_S = 60 * 60 * 24 * 365;

function isTheme(value: string | undefined): value is Theme {
  return (THEMES as readonly string[]).includes(value ?? "");
}

/** The saved choice, or "system" when nothing (or nothing sensible) is saved. */
export function readTheme(doc: Document = document): Theme {
  const found = new RegExp(`(?:^|; )${COOKIE}=([^;]*)`).exec(doc.cookie)?.[1];
  return isTheme(found) ? found : "system";
}

/** Paint `theme` now. "system" hands the choice back to the Mac, live. */
export function applyTheme(theme: Theme, doc: Document = document): void {
  const root = doc.documentElement;
  root.dataset.theme = theme;
  root.style.colorScheme = theme === "system" ? "light dark" : theme;
}

/** Keep `theme` for every later launch, and paint it. */
export function saveTheme(theme: Theme, doc: Document = document): void {
  doc.cookie = `${COOKIE}=${theme}; path=/; max-age=${MAX_AGE_S}; SameSite=Strict`;
  applyTheme(theme, doc);
}
