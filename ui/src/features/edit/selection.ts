// Which words the reader has selected in the transcript, as word indexes.
//
// The transcript is plain text, one text node a paragraph (#58), so a native
// selection is the selection: drag across words, or double-click one, and
// these are the words an edit applies to. Nothing here is React state per
// frame: it is read on `selectionchange`, which fires when a person selects.

import { type Reading, wordAtOffset } from "@/features/transcript/document";

/** The first and last word selected, both included. */
export type Selected = { first: number; last: number };

function turnOf(node: Node): number | null {
  if (node.nodeType !== Node.TEXT_NODE) return null;
  const turn = node.parentElement?.dataset["turn"];
  return turn === undefined ? null : Number(turn);
}

type Ends = { startTurn: number; startOffset: number; endTurn: number; endOffset: number; endText: Text };

/**
 * Where `range` starts and ends in `root`'s paragraphs. Usually both ends sit
 * in a paragraph's text. A triple-click ends on the next turn's element, and
 * a drag can start in the margin: then the ends are the first and last
 * characters of paragraph text the range takes in.
 */
function endsOf(root: Element, range: Range): Ends | null {
  const startTurn = turnOf(range.startContainer);
  const endTurn = turnOf(range.endContainer);
  if (startTurn !== null && endTurn !== null && root.contains(range.startContainer) && root.contains(range.endContainer)) {
    return { startTurn, startOffset: range.startOffset, endTurn, endOffset: range.endOffset, endText: range.endContainer as Text };
  }
  let ends: Ends | null = null;
  for (const p of root.querySelectorAll<HTMLElement>("p[data-turn]")) {
    const text = p.firstChild;
    if (!(text instanceof Text) || !range.intersectsNode(text)) continue;
    const from = text === range.startContainer ? range.startOffset : range.comparePoint(text, 0) < 0 ? text.length : 0;
    const to = text === range.endContainer ? range.endOffset : range.comparePoint(text, text.length) > 0 ? 0 : text.length;
    if (from >= to) continue;
    const turn = Number(p.dataset["turn"]);
    const at: Ends = ends ?? { startTurn: turn, startOffset: from, endTurn: turn, endOffset: to, endText: text };
    at.endTurn = turn;
    at.endOffset = to;
    at.endText = text;
    ends = at;
  }
  return ends;
}

/** The words `range` covers inside `root`'s paragraphs, or null when it covers none. */
export function wordsIn(reading: Reading, root: Element, range: Range): Selected | null {
  if (range.collapsed || !range.intersectsNode(root)) return null;
  const ends = endsOf(root, range);
  if (ends === null || ends.endOffset === 0) return null;
  const first = wordAtOffset(reading, ends.startTurn, ends.startOffset);
  // The end is the gap after the last character selected.
  let last = wordAtOffset(reading, ends.endTurn, ends.endOffset - 1);
  // A selection that ends on a space ends before the word that space opens:
  // a word's text starts with the space in front of it.
  const lastSelected = ends.endText.data[ends.endOffset - 1] ?? "";
  if (/\s/.test(lastSelected) && ends.endOffset - 1 < (reading.words.offset[last] ?? 0) + leadOf(reading, last, ends.endText)) {
    last -= 1;
  }
  if (first < 0 || last < first) return null;
  return { first, last };
}

/** How many whitespace characters open word `word` in `node`'s text. */
function leadOf(reading: Reading, word: number, node: Node): number {
  const from = reading.words.offset[word] ?? 0;
  const text = (node.textContent ?? "").slice(from, from + (reading.words.length[word] ?? 0));
  return /^\s*/.exec(text)?.[0].length ?? 0;
}

/** The words the page's selection covers inside `root`, or null. */
export function selectedWords(reading: Reading, root: Element): Selected | null {
  const selection = window.getSelection();
  if (selection === null || selection.rangeCount === 0) return null;
  return wordsIn(reading, root, selection.getRangeAt(0));
}

/** The paragraphs' text nodes, by turn: the article's `p[data-turn]` children. */
export function turnTexts(root: Element): Text[] {
  const texts: Text[] = [];
  for (const p of root.querySelectorAll<HTMLElement>("p[data-turn]")) {
    if (p.firstChild instanceof Text) texts[Number(p.dataset["turn"])] = p.firstChild;
  }
  return texts;
}

/**
 * Select words [first, last] in their paragraph's text, without the space in
 * front of the first, and return the range, or null when the paragraph is
 * not drawn. The reader's own selection, so the Selection toolbar follows it.
 */
export function selectWords(reading: Reading, texts: readonly (Text | undefined)[], first: number, last = first): Range | null {
  const { turn, offset, length } = reading.words;
  const text = texts[turn[first] ?? -1];
  if (text === undefined) return null;
  const from = offset[first] ?? 0;
  const to = (offset[last] ?? 0) + (length[last] ?? 0);
  const lead = /^\s*/.exec(text.data.slice(from, to))?.[0].length ?? 0;
  const range = document.createRange();
  range.setStart(text, Math.min(from + lead, to));
  range.setEnd(text, to);
  const selection = window.getSelection();
  selection?.removeAllRanges();
  selection?.addRange(range);
  return range;
}

/**
 * Give `paragraph` the keyboard focus, as the place the reader is in the
 * text: after Esc in the Selection toolbar and after Correct closes, focus
 * goes back to the words, never to the page's body.
 */
export function focusText(paragraph: HTMLElement | null | undefined): void {
  if (paragraph == null) return;
  // Focusable by script only, so Tab does not stop on 238 paragraphs.
  paragraph.tabIndex = -1;
  focusKeepingSelection(paragraph);
}

/**
 * Focus `element` and leave the page's selection as it was. Moving focus may
 * move the selection on some platforms (jsdom collapses it into the focused
 * element, as its focusing steps allow), and the Selection toolbar lives on
 * the selection: put it back if it moved.
 */
export function focusKeepingSelection(element: HTMLElement): void {
  const selection = window.getSelection();
  const was = selection !== null && selection.rangeCount > 0 ? selection.getRangeAt(0).cloneRange() : null;
  element.focus({ preventScroll: true });
  if (selection === null || was === null) return;
  const now = selection.rangeCount > 0 ? selection.getRangeAt(0) : null;
  const same =
    now !== null &&
    now.startContainer === was.startContainer &&
    now.startOffset === was.startOffset &&
    now.endContainer === was.endContainer &&
    now.endOffset === was.endOffset;
  if (same) return;
  selection.removeAllRanges();
  selection.addRange(was);
}
