// The one hit-test the reader has (#57 section 7): which paragraph and which
// character sit under a point. Click-to-seek uses it (#60), and so will
// click-a-mark (#67) and inline correction (#83), so it knows nothing about
// words or time, only `data-turn` paragraphs of plain text.
//
// caretPositionFromPoint is the standard and caretRangeFromPoint the older
// spelling. Safari only shipped the first in 26.2 (MDN browser-compat-data
// 8.1.2), so the fallback is what an older Safari runs.

export type Point = { clientX: number; clientY: number };
export type TextHit = { turn: number; offset: number };

type CaretDocument = Pick<Document, "createRange"> & {
  caretPositionFromPoint?: (x: number, y: number) => { offsetNode: Node; offset: number } | null;
  caretRangeFromPoint?: (x: number, y: number) => Range | null;
};

function caretAt(doc: CaretDocument, x: number, y: number): { node: Node; offset: number } | null {
  if (typeof doc.caretPositionFromPoint === "function") {
    const found = doc.caretPositionFromPoint(x, y);
    return found === null ? null : { node: found.offsetNode, offset: found.offset };
  }
  if (typeof doc.caretRangeFromPoint === "function") {
    const found = doc.caretRangeFromPoint(x, y);
    return found === null ? null : { node: found.startContainer, offset: found.startOffset };
  }
  return null;
}

function contains(rect: DOMRect, x: number, y: number): boolean {
  return x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom;
}

/**
 * The paragraph and the character under `point`, or null off the text.
 *
 * A caret position is the gap nearest the point, not the character under it:
 * a click on the right half of a word's last letter returns the gap after it,
 * which is the next word's leading space. So the character on each side of the
 * gap is measured and the one the point is inside wins. Measuring, rather than
 * comparing x, keeps right-to-left paragraphs right too.
 */
export function offsetAtPoint(point: Point, doc: CaretDocument = document): TextHit | null {
  const caret = caretAt(doc, point.clientX, point.clientY);
  if (caret === null || caret.node.nodeType !== Node.TEXT_NODE) return null;
  const paragraph = caret.node.parentElement;
  const turn = paragraph?.dataset["turn"];
  if (turn === undefined) return null;
  const length = caret.node.textContent?.length ?? 0;
  let offset = caret.offset;
  if (offset > 0) {
    const before = doc.createRange();
    before.setStart(caret.node, offset - 1);
    before.setEnd(caret.node, offset);
    const inBefore = Array.from(before.getClientRects()).some((r) =>
      contains(r, point.clientX, point.clientY),
    );
    if (inBefore || offset >= length) offset -= 1;
  }
  return { turn: Number(turn), offset };
}
