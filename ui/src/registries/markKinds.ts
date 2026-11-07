// The kinds a mark can be (#67), in one list, so the picker on the selection
// toolbar, the colours in the transcript, the marks panel and the export all
// read the same four. The server holds the same four (dsj/ui/schemas.py
// MarkKind); a fifth goes in both places. The colours live in
// transcript.css as ::highlight(dsj-mark-<id>) rules, flat bands: the
// Highlight API paints colour and decoration only, never a rounded corner.

export type MarkKind = "key" | "question" | "todo" | "quote";

export type MarkKindInfo = {
  id: MarkKind;
  label: string;
  /** The ::highlight() name the transcript paints this kind with. */
  highlight: string;
  /** The legend's swatch, the same colour as the band in light mode. */
  swatch: string;
};

export const MARK_KINDS: readonly MarkKindInfo[] = [
  { id: "key", label: "Key point", highlight: "dsj-mark-key", swatch: "light-dark(#f6e3a1, #6b5a16)" },
  { id: "question", label: "Question", highlight: "dsj-mark-question", swatch: "light-dark(#cfe3f7, #1f4062)" },
  { id: "todo", label: "To do", highlight: "dsj-mark-todo", swatch: "light-dark(#d8f0cf, #2a5a28)" },
  { id: "quote", label: "Quote", highlight: "dsj-mark-quote", swatch: "light-dark(#ecd9f2, #4d2a5c)" },
];

export function markKind(id: string): MarkKindInfo {
  return MARK_KINDS.find((k) => k.id === id) ?? (MARK_KINDS[0] as MarkKindInfo);
}
