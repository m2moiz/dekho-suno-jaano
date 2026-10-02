// jsdom has no CSS Custom Highlight API. This stands in for the two pieces the
// playhead touches, Highlight (a set of ranges) and CSS.highlights (a map by
// name), so a test can read back what would be painted. Real browsers are
// tested in ui/tests/e2e/.

export class FakeHighlight extends Set<Range> {}

export function installHighlights(): Map<string, FakeHighlight> {
  const registry = new Map<string, FakeHighlight>();
  Object.assign(globalThis, { Highlight: FakeHighlight });
  const css = (globalThis as { CSS?: object }).CSS ?? {};
  Object.assign(css, { highlights: registry });
  Object.assign(globalThis, { CSS: css });
  return registry;
}

/** The text a named highlight would paint, one string per range. */
export function painted(registry: Map<string, FakeHighlight>, name: string): string[] {
  return Array.from(registry.get(name) ?? [], (range) => range.toString());
}
