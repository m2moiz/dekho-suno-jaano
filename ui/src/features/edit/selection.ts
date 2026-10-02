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

/** The words `range` covers inside `root`'s paragraphs, or null when it covers none. */
export function wordsIn(reading: Reading, root: Element, range: Range): Selected | null {
  if (range.collapsed || !root.contains(range.commonAncestorContainer)) return null;
  const startTurn = turnOf(range.startContainer);
  const endTurn = turnOf(range.endContainer);
  if (startTurn === null || endTurn === null || range.endOffset === 0) return null;
  const first = wordAtOffset(reading, startTurn, range.startOffset);
  // The end is the gap after the last character selected.
  let last = wordAtOffset(reading, endTurn, range.endOffset - 1);
  // A selection that ends on a space ends before the word that space opens:
  // a word's text starts with the space in front of it.
  const lastSelected = range.endContainer.textContent?.[range.endOffset - 1] ?? "";
  if (/\s/.test(lastSelected) && range.endOffset - 1 < (reading.words.offset[last] ?? 0) + leadOf(reading, last, range.endContainer)) {
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
