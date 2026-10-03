// Every change to a transcript's edit list goes through one function,
// `applyEdit`, and every kind of change says how to undo itself (#66).
//
// The edit list is #63's document, entry for entry the file `dsj hatao`
// reads (dsj/hatao.py, `dumps`): paragraphs, and items naming a stretch of a
// source's audio and the text said in it. Its wire shape is generated from
// dsj/ui/schemas.py, so this file never describes it by hand.
//
// Why the undo lives on the kind and not in a list. audapolis wraps its state
// in redux-undo with a hand-written list of which actions count as edits; add
// a kind of edit, forget the list, and Cmd+Z quietly skips it. Here `KINDS`
// must hold, for every member of the `EditOp` union, a `do` and an `undo`
// (`apply` and `invert`), and the type says so: a kind with no undo, or a
// member of the union with no entry, is a build error.
// ui/tests/unit/editOps.test.ts compiles both mistakes and asserts the error.
//
// History holds only `EditOp`s. A caret move, a scroll or a playback tick is
// not one, so there is no way to put one into it, and Cmd+Z can only ever
// step back through edits.
//
// Relative imports only, so the unit test can hand this file to the
// TypeScript compiler on its own.

import type { components } from "../api/schema";

export type Paragraph = components["schemas"]["ParagraphEntry"];
export type Item = components["schemas"]["ItemEntry"];
export type Entry = Paragraph | Item;
export type Content = readonly Entry[];

/**
 * Set each listed entry's `muted` to the value beside it: #63's
 * `mute(doc, start, stop, muted=...)`, by hand. Paragraphs are skipped, as
 * the Python side skips them.
 */
export type MuteOp = { kind: "mute"; entries: number[]; muted: boolean[] };

/** Mute every match a word list found, as one step (#84): what `dsj hatao` mutes. */
export type FlagOp = { kind: "flag"; entries: number[] };

/** Give one match its audio back (#84). Its word stays in the list, matched and dismissed. */
export type DismissOp = { kind: "dismiss"; entries: number[] };

/**
 * Put `entries` in place of entries [start, stop): a stretch of words retyped
 * (#83). The entries carry their own times, so nothing around them moves.
 */
export type CorrectOp = { kind: "correct"; start: number; stop: number; entries: Entry[] };

/**
 * Put `entries` in place of entries [start, stop): a word's edge dragged
 * (#85), its neighbours and the pauses between them re-timed to match.
 */
export type RetimeOp = { kind: "retime"; start: number; stop: number; entries: Entry[] };

// Every kind of edit there is. A new kind joins this union and `KINDS` below.
export type EditOp = MuteOp | FlagOp | DismissOp | CorrectOp | RetimeOp;

/** What every kind of edit must say: how to do it, how to undo it, and what to call it. */
export type EditKind<O extends EditOp> = {
  /** `content` with `op` done. Never changes `content` itself. */
  apply(content: Content, op: O): Content;
  /** The edit that turns the result of `apply(before, op)` back into `before`. */
  invert(before: Content, op: O): EditOp;
  /** A few words for the Undo and Redo buttons: "mute 2 words". */
  describe(op: O): string;
};

type Kinds = { [K in EditOp["kind"]]: EditKind<Extract<EditOp, { kind: K }>> };

/** `content` with each of `entries` an item muted as `muted` says. */
function setMuted(content: Content, entries: number[], muted: boolean[]): Content {
  const out = content.slice();
  entries.forEach((index, k) => {
    const entry = out[index];
    if (entry === undefined) throw new RangeError(`no entry ${index} in a list of ${out.length}`);
    if (entry.kind === "item") out[index] = { ...entry, muted: muted[k] ?? true };
  });
  return out;
}

const KINDS: Kinds = {
  mute: {
    apply: (content, op) => setMuted(content, op.entries, op.muted),
    invert: (before, op) => mutedAsBefore(before, op.entries),
    describe: (op) => {
      const on = op.muted.filter(Boolean).length;
      return on === op.muted.length ? "mute" : on === 0 ? "unmute" : "mute and unmute";
    },
  },
  flag: {
    apply: (content, op) => setMuted(content, op.entries, op.entries.map(() => true)),
    invert: (before, op) => mutedAsBefore(before, op.entries),
    describe: () => "mute the matches",
  },
  dismiss: {
    apply: (content, op) => setMuted(content, op.entries, op.entries.map(() => false)),
    invert: (before, op) => mutedAsBefore(before, op.entries),
    describe: () => "dismiss",
  },
  correct: {
    apply: (content, op) => splice(content, op.start, op.stop, op.entries),
    invert: (before, op) => ({
      kind: "correct",
      start: op.start,
      stop: op.start + op.entries.length,
      entries: before.slice(op.start, op.stop),
    }),
    describe: () => "correction",
  },
  retime: {
    apply: (content, op) => splice(content, op.start, op.stop, op.entries),
    invert: (before, op) => ({
      kind: "retime",
      start: op.start,
      stop: op.start + op.entries.length,
      entries: before.slice(op.start, op.stop),
    }),
    describe: () => "timing",
  },
};

/** `content` with entries [start, stop) replaced by `entries`. */
function splice(content: Content, start: number, stop: number, entries: Entry[]): Content {
  if (!(0 <= start && start <= stop && stop <= content.length)) {
    throw new RangeError(`entries [${start}, ${stop}) are not inside a list of ${content.length}`);
  }
  return [...content.slice(0, start), ...entries, ...content.slice(stop)];
}

/** The mute that puts each of `entries` back as it is in `before`. */
function mutedAsBefore(before: Content, entries: number[]): MuteOp {
  return {
    kind: "mute",
    entries,
    muted: entries.map((index) => {
      const entry = before[index];
      return entry?.kind === "item" && entry.muted;
    }),
  };
}

function run(content: Content, op: EditOp): Content {
  // One kind's functions, for that kind's op: TypeScript cannot follow the
  // pairing through the index, so it is stated here, once.
  const kind = KINDS[op.kind] as EditKind<EditOp>;
  return kind.apply(content, op);
}

function inverse(before: Content, op: EditOp): EditOp {
  return (KINDS[op.kind] as EditKind<EditOp>).invert(before, op);
}

/** What the Undo and Redo buttons call an edit. */
export function describe(op: EditOp): string {
  return (KINDS[op.kind] as EditKind<EditOp>).describe(op);
}

/** The items among entries [start, stop). */
export function itemsIn(content: Content, start: number, stop: number): number[] {
  const entries: number[] = [];
  for (let i = start; i < stop; i += 1) if (content[i]?.kind === "item") entries.push(i);
  return entries;
}

/** A mute or unmute of every item in entries [start, stop), as one edit. */
export function muteRange(content: Content, start: number, stop: number, muted: boolean): MuteOp {
  const entries = itemsIn(content, start, stop);
  return { kind: "mute", entries, muted: entries.map(() => muted) };
}

// How many steps Undo goes back. #66 asks for at least 100. An edit's step
// holds only the entries it touched, so a thousand of them is small.
export const HISTORY_LIMIT = 1000;

/** One undo step: the edits made, and the edits that take them back, in the order made. */
type Step = { label: string; ops: EditOp[]; inverses: EditOp[] };

export type EditorOptions = {
  /**
   * Run on the list after every edit, undo and redo, before it is kept:
   * throwing refuses the edit, and the list stays as it was (#86).
   */
  check?: (content: Content) => void;
  limit?: number;
};

/**
 * One transcript's edit list and its history. The list changes only through
 * `applyEdit`, `undo` and `redo`, and every listener hears each change.
 */
export class Editor {
  private current: Content;
  private done: Step[] = [];
  private undone: Step[] = [];
  private gesture: Step | null = null;
  private readonly listeners = new Set<() => void>();
  private readonly check: (content: Content) => void;
  private readonly limit: number;

  constructor(content: Content, { check, limit = HISTORY_LIMIT }: EditorOptions = {}) {
    this.check = check ?? (() => undefined);
    this.limit = limit;
    this.check(content);
    this.current = content;
  }

  get content(): Content {
    return this.current;
  }

  /** Do `op`, and keep how to undo it. The one way the list changes. */
  applyEdit(op: EditOp): void {
    const before = this.current;
    const back = inverse(before, op);
    this.set(run(before, op));
    if (this.gesture !== null) {
      this.gesture.ops.push(op);
      this.gesture.inverses.push(back);
    } else {
      this.remember({ label: describe(op), ops: [op], inverses: [back] });
    }
    this.emit();
  }

  /**
   * Every edit until `endGesture` is one undo step: a whole drag, not one
   * step for each move of the pointer (#66 step 4, #85).
   */
  beginGesture(): void {
    if (this.gesture === null) this.gesture = { label: "", ops: [], inverses: [] };
  }

  endGesture(): void {
    const gesture = this.gesture;
    this.gesture = null;
    if (gesture === null || gesture.ops.length === 0) return;
    const first = gesture.ops[0];
    if (first !== undefined) gesture.label = describe(first);
    this.remember(gesture);
    this.emit();
  }

  get inGesture(): boolean {
    return this.gesture !== null;
  }

  canUndo(): boolean {
    return this.done.length > 0;
  }

  canRedo(): boolean {
    return this.undone.length > 0;
  }

  /** What Undo would take back, or null. */
  undoLabel(): string | null {
    return this.done.at(-1)?.label ?? null;
  }

  redoLabel(): string | null {
    return this.undone.at(-1)?.label ?? null;
  }

  /** Take back the last step. False when there is none. */
  undo(): boolean {
    this.endGesture();
    const step = this.done.pop();
    if (step === undefined) return false;
    let content = this.current;
    for (const op of step.inverses.toReversed()) content = run(content, op);
    this.set(content, () => this.done.push(step));
    this.undone.push(step);
    this.emit();
    return true;
  }

  /** Do again the last step undone. False when there is none. */
  redo(): boolean {
    this.endGesture();
    const step = this.undone.pop();
    if (step === undefined) return false;
    let content = this.current;
    for (const op of step.ops) content = run(content, op);
    this.set(content, () => this.undone.push(step));
    this.done.push(step);
    this.emit();
    return true;
  }

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  /** Keep `content` once `check` passes it; when it throws, put the history back first. */
  private set(content: Content, restore?: () => void): void {
    try {
      this.check(content);
    } catch (thrown) {
      restore?.();
      throw thrown;
    }
    this.current = content;
  }

  private remember(step: Step): void {
    this.done.push(step);
    if (this.done.length > this.limit) this.done.shift();
    this.undone = [];
  }

  private emit(): void {
    for (const listener of this.listeners) listener();
  }
}
