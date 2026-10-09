// jsdom has neither matchMedia nor ResizeObserver; the bar, the rail and the
// phone layouts use both. Each test file that needs them installs them in
// beforeEach; nothing here restores them.

/** A ResizeObserver that never fires: jsdom lays nothing out, so there is nothing to observe. */
export function stubResizeObserver(): void {
  globalThis.ResizeObserver ??= class {
    observe() {}
    disconnect() {}
    unobserve() {}
  };
}

/** matchMedia answering each query with `matches(query)`: a phone is `(q) => q.includes("coarse")`. */
export function stubMatchMedia(matches: (query: string) => boolean = () => false): void {
  stubResizeObserver();
  window.matchMedia = ((query: string) => ({
    matches: matches(query),
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}
