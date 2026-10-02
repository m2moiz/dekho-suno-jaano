// A choice kept between launches of `dsj ui`. A cookie, not localStorage:
// every launch binds a new port and localStorage is kept per port, while a
// cookie on 127.0.0.1 is shared by them all (observed in Chromium on
// 2026-09-23, #116). The theme keeps its own copy of these two lines in
// ui/src/features/theme/theme.ts, because ui/index.html reads that cookie
// before any script loads.

// A year, renewed on every change, so a choice never quietly expires.
const MAX_AGE_S = 60 * 60 * 24 * 365;

/** The cookie's value, or undefined when it is not set. */
export function readCookie(name: string, doc: Document = document): string | undefined {
  return new RegExp(`(?:^|; )${name}=([^;]*)`).exec(doc.cookie)?.[1];
}

export function writeCookie(name: string, value: string, doc: Document = document): void {
  doc.cookie = `${name}=${value}; path=/; max-age=${MAX_AGE_S}; SameSite=Strict`;
}
