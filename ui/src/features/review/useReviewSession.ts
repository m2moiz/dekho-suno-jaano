// One review in progress (Hashiya spec, Review mode): the sentence in hand,
// what each key does to it, and the document saved as it changes. The laptop
// desk (ReviewDesk.tsx) and the phone card (Task 14) draw the same session.
//
// Where edits go (spec): a change of words is the reader's own CorrectOp, over
// only the words that differ (F4), so it shows in the reader and every other
// word keeps its link to the audio; a change of speaker is a SpeakerOp. Both
// go through the one Editor, so the reader's Cmd+Z takes them back. The
// review document holds spans, states, flags, the pass, the cursor and each
// correction's before and after (seam C, F28), never the words themselves.

import { type RefObject, useEffect, useMemo, useRef, useState } from "react";

import { type Editable, onPageHide, Outdated, type SaveState, type Saving, useContent, useLatest } from "@/features/edit/editing";
import { speakerLabels } from "@/features/edit/readContent";
import { newSpeakerLabel, speakerAt, speakerChange } from "@/features/edit/speaker";
import type { PlayerControls } from "@/features/player/Player";
import { speedLabel, stepSpeed } from "@/features/player/speed";
import { showKeys } from "@/features/shell/KeySheet";
import { REVIEW_SHEET } from "@/features/shell/keys";
import { cutoffFor } from "@/features/transcript/confidence";
import type { Reading, TranscriptDoc } from "@/features/transcript/document";
import { displayName, speakerColour } from "@/features/transcript/speakers";
import { readCookie, writeCookie } from "@/lib/cookie";
import type { Action } from "./keymap";
import {
  AFTER_S,
  BEFORE_S,
  caretInList,
  type Counts,
  counts,
  type CurrentSha,
  documentOf,
  entryRange,
  likelyErrors,
  mergeWithPrevious,
  passOrder,
  RESUME_BACK_S,
  resume,
  type ReviewCorrection,
  type ReviewDocument,
  type ReviewPass,
  type Segment,
  segmentText,
  type Span,
  splitAt,
  step,
  timeLeft,
  toggleFlag,
  wordCorrection,
  wordIndex,
} from "./model";
import { clearDraft, readDraft, writeDraft } from "./draft";
import { useReviewSave } from "./reviewApi";
import { secondOpinion } from "./secondOpinion";

export type Caret = { start: number; end: number };

export type SentenceView = {
  index: number;
  segment: Segment;
  text: string;
  /** Who says it: the label, the name a person gave it, and its colour. */
  label: string | null;
  name: string | null;
  colour: string | undefined;
};

export type Session = {
  /** On entry, until a pass is picked (F13): the chooser shows, nothing plays. */
  choosing: boolean;
  /** Pick the pass and start: the sentence in hand plays (F25). */
  choose: (pass: ReviewPass) => void;
  /** Whether this review was picked up again, and how far it had got, for the chooser to say. */
  resumed: boolean;
  current: SentenceView | null;
  before: SentenceView[];
  after: SentenceView[];
  text: string;
  setText: (text: string) => void;
  /** Typing pauses playback (spec). */
  pause: () => void;
  second: { words: string[]; differs: boolean[] | null } | null;
  pass: ReviewPass;
  setPass: (pass: ReviewPass) => void;
  likelyCount: number;
  progress: Counts;
  timeLeft: string | null;
  notice: string | null;
  flagging: boolean;
  setFlagging: (open: boolean) => void;
  finished: boolean;
  saving: SaveState;
  speakers: { label: string; name: string; colour: string | undefined }[];
  act: (action: Action, caret?: Caret) => void;
  /** Save everything and go back to the transcript (Esc, the bar's back arrow, the finish panel). */
  leave: () => void;
  /** Resolve once the review and the edit list are both saved; throws NotSaved when either is not. */
  settle: () => Promise<void>;
};

type Args = {
  transcriptId: number;
  doc: TranscriptDoc;
  editable: Editable;
  /** The edit list's own save (editing.ts useSave), so leaving and the answer key wait for it. */
  edits: Saving;
  saved: ReviewDocument | null;
  sha: CurrentSha;
  other: Reading | null;
  controls: RefObject<PlayerControls | null>;
  /** Where leaving goes, once everything is saved. */
  onLeave: () => void;
};

// Two sentences before and after the one in hand (spec).
const CONTEXT = 2;
// Said once when the box is filled again from the browser's copy (draft.ts).
const RESTORED = "Restored words typed before the page closed";
// The pass picked last, kept between reviews so the chooser offers it first (F13).
const PASS_COOKIE = "dsj-review-pass";

function lostNotice(lost: number): string {
  return `The transcript was made again since this review was saved. ${lost} checked ${
    lost === 1 ? "sentence no longer matches and is" : "sentences no longer match and are"
  } unchecked again.`;
}

function lastPass(): ReviewPass {
  return readCookie(PASS_COOKIE) === "likely" ? "likely" : "every";
}

/**
 * The segments' spans, the same array for as long as no span changes, so the
 * second opinion (about 30 ms over 1,500 sentences, Task 12 review M11) is
 * worked out again only after a split, a merge or an edit, and never for a
 * check or a flag. Its `disagree` set is keyed by index, so it must follow
 * every split and merge (Task 11 review).
 */
function useSpans(segments: readonly Segment[]): readonly Span[] {
  const last = useRef<readonly Span[]>([]);
  return useMemo(() => {
    const before = last.current;
    const same = before.length === segments.length && before.every((s, i) => s.start === segments[i]?.start && s.end === segments[i]?.end);
    if (!same) last.current = segments.map(({ start, end }) => ({ start, end }));
    return last.current;
  }, [segments]);
}

export function useReviewSession({ transcriptId, doc, editable, edits, saved, sha, other, controls, onLeave }: Args): Session {
  const { editor } = editable;
  const content = useContent(editor);
  const names = useLatest(editable.names);
  const words = useMemo(() => wordIndex(content), [content]);
  const [opening] = useState(() => resume(saved, editor.content, sha));
  // Words typed before the page closed, kept in the browser (draft.ts): put
  // back in their sentence's box when the transcript is the same one and the
  // list does not already say them. Pure, so StrictMode's second call agrees;
  // a draft not used is cleared by the effect below, as the box is saved.
  const [restored] = useState(() => {
    const draft = readDraft(transcriptId);
    if (draft === null || draft.sha !== sha) return null;
    const at = opening.segments.findIndex((s) => s.start <= draft.start && draft.start < s.end);
    const segment = opening.segments[at];
    if (segment === undefined) return null;
    const listed = segmentText(editor.content, wordIndex(editor.content), segment);
    return listed === draft.text ? null : { index: at, shown: listed, text: draft.text };
  });
  const [segments, setSegments] = useState<Segment[]>(opening.segments);
  const [index, setIndex] = useState(restored?.index ?? opening.cursor);
  const [pass, setPassState] = useState<ReviewPass>(saved?.review_pass ?? lastPass());
  const [choosing, setChoosing] = useState(true);
  const [fixes, setFixes] = useState<ReviewCorrection[]>(saved?.corrections ?? []);
  // The same list, as of this instant: a page going away saves a correction
  // made in that same moment, before any render has put it in `fixes`.
  const fixesNow = useRef<ReviewCorrection[]>(fixes);
  const [startedAt] = useState(() => saved?.started_at ?? new Date().toISOString());
  const [notice, setNotice] = useState<string | null>(restored !== null ? RESTORED : opening.lost > 0 ? lostNotice(opening.lost) : null);
  const [flagging, setFlagging] = useState(false);
  const [finished, setFinished] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const checkedAt = useRef<number[]>([]);

  const labels = useMemo(() => speakerLabels(content, doc.speakers) ?? [], [content, doc.speakers]);
  const spans = useSpans(segments);
  const texts = useMemo(() => spans.map((s) => segmentText(content, words, s)), [spans, content, words]);
  const opinions = useMemo(() => secondOpinion(other, spans, texts), [other, spans, texts]);
  const likely = useMemo(
    () => likelyErrors(content, words, segments, cutoffFor(doc.model), opinions.disagree),
    [content, words, segments, doc.model, opinions.disagree],
  );
  const order = useMemo(() => passOrder(segments.length, pass, likely), [segments.length, pass, likely]);

  const segment = segments[index];
  const shown = texts[index] ?? "";
  // The box holds what is typed; a new sentence, or new words in this one,
  // start it again from what the list says.
  const [typed, setTyped] = useState(restored ?? { shown, index, text: shown });
  const text = typed.shown === shown && typed.index === index ? typed.text : shown;
  const setText = (next: string) => {
    setTyped({ shown, index, text: next });
    // At once, not in an effect: the page may be torn down before the next render.
    if (segment !== undefined && next !== shown) writeDraft(transcriptId, sha, segment, next);
  };
  // The browser's copy follows the box: kept while it differs from its
  // sentence, cleared once its words are in the list and the list is saved.
  // A draft from another sha, or one the list already says, goes here too.
  useEffect(() => {
    if (text !== shown) {
      if (segment !== undefined) writeDraft(transcriptId, sha, segment, text);
    } else if (edits.state === "saved") {
      clearDraft(transcriptId);
    }
  }, [text, shown, segment, edits.state, transcriptId, sha]);

  const document = useMemo(
    () => documentOf({ sha, pass, cursorS: segments[index]?.start ?? 0, startedAt, segments, corrections: fixes }),
    [sha, pass, segments, index, startedAt, fixes],
  );
  const { state: reviewSaving, flush, keep } = useReviewSave(transcriptId, document);
  // The bar's one word covers both saves: Review's words go to the edit list,
  // its checks to the review, and either can fail alone (Task 13 review, I2).
  const saving: SaveState =
    reviewSaving === "failed" || edits.state === "failed" ? "failed" : reviewSaving === "saving" || edits.state === "saving" ? "saving" : "saved";
  const settle = async () => {
    await Promise.all([flush(), edits.settle()]);
  };

  const view = (i: number): SentenceView | null => {
    const s = segments[i];
    if (s === undefined) return null;
    const range = entryRange(words, s);
    const label = range === null ? s.speaker : speakerAt(content, range.start);
    const at = label === null ? -1 : labels.indexOf(label);
    return {
      index: i,
      segment: s,
      text: texts[i] ?? "",
      label,
      name: at < 0 ? null : displayName(labels, names, at),
      colour: speakerColour(at < 0 ? null : at),
    };
  };

  const hear = (s: Segment | undefined) => {
    if (s !== undefined) controls.current?.hear(Math.max(0, s.start - BEFORE_S), s.end + AFTER_S);
  };

  const go = (to: number, list: readonly Segment[], play = true) => {
    setIndex(to);
    setFlagging(false);
    if (play) hear(list[to]);
  };

  /**
   * Put what the box says into the edit list, only the words that differ
   * (F4), and give back the segments with this one marked edited when it
   * changed. Unchanged words give back `list` itself.
   */
  const commit = (list: Segment[]): Segment[] => {
    if (segment === undefined) return list;
    const range = entryRange(wordIndex(editor.content), segment);
    if (range === null) {
      if (text.trim() !== "") setNotice("This sentence has no words left to correct here. Undo in the reader brings them back.");
      return list;
    }
    const fix = wordCorrection(editor.content, range, text);
    if (fix === null) return list;
    editor.applyEdit(fix.op);
    // Every change of words, before and after: sub-project C's learning data (spec, "Seam for C"; F28).
    fixesNow.current = [...fixesNow.current, { at: new Date().toISOString(), ...fix.correction }];
    setFixes(fixesNow.current);
    return list.map((s, i) => (i === index ? { ...s, edited: true } : s));
  };

  /** Where `pass` starts from here: this sentence when it is in the pass, else the next one in it, else its first. */
  const entryOf = (to: ReviewPass): number | null => {
    const list = passOrder(segments.length, to, likely);
    if (list.includes(index)) return index;
    return list.find((i) => i > index) ?? list[0] ?? null;
  };

  const setPass = (next: ReviewPass) => {
    setPassState(next);
    writeCookie(PASS_COOKIE, next);
    // After a pass has finished, the next one starts at its first sentence not
    // yet checked, and the done panel gives way to it (Task 13 review, I3).
    const fresh = passOrder(segments.length, next, likely);
    const to = finished ? (fresh.find((i) => segments[i]?.state !== "checked") ?? fresh[0] ?? null) : entryOf(next);
    if (to === null) {
      setNotice("There are no likely errors in this transcript. Every sentence is the pass to take.");
      return;
    }
    if (finished) {
      setFinished(false);
      go(to, segments);
      return;
    }
    if (to === index) return;
    const list = commit(segments);
    setSegments(list);
    go(to, list, !choosing);
  };

  const choose = (next: ReviewPass) => {
    // A box filled again from the browser's copy keeps its sentence, whatever the pass.
    const to = text !== shown ? index : entryOf(next);
    if (to === null) {
      setNotice("There are no likely errors in this transcript. Every sentence is the pass to take.");
      return;
    }
    setPassState(next);
    writeCookie(PASS_COOKIE, next);
    setChoosing(false);
    setIndex(to);
    // Arriving plays the sentence (spec, F25); the pick is the gesture the browser needs to play.
    hear(segments[to]);
  };

  // Leaving waits a render, so the document saved is the one the last key made.
  const onLeaveNow = useRef(onLeave);
  onLeaveNow.current = onLeave;
  const settleNow = useRef(settle);
  settleNow.current = settle;
  useEffect(() => {
    if (!leaving) return;
    let live = true;
    settleNow.current().then(
      () => {
        if (live) onLeaveNow.current();
      },
      (thrown: unknown) => {
        if (!live) return;
        setLeaving(false);
        // The save's own failure is already on screen; this says why the page stayed.
        // Review's own words: the edit list's NotSaved messages speak of exporting.
        // Once the transcript was made again no save can succeed: only a reload helps.
        setNotice(
          thrown instanceof Outdated
            ? "Still in Review: the transcript was made again since this page opened, so nothing more saves here. Reload the page."
            : "Still in Review: the last changes are not saved yet, for the reason shown. Esc tries again.",
        );
      },
    );
    return () => {
      live = false;
    };
  }, [leaving]);

  // Words in the box not yet in the list are not saved anywhere: leaving the
  // page by the browser asks first (Task 13 review, Minor 2). Esc commits them.
  const unsaved = useRef(false);
  unsaved.current = text !== shown;
  useEffect(() => {
    const leaving = (event: BeforeUnloadEvent) => {
      if (unsaved.current) event.preventDefault();
    };
    window.addEventListener("beforeunload", leaving);
    return () => window.removeEventListener("beforeunload", leaving);
  }, []);

  // The page hidden or left. A phone gives no beforeunload (iOS Safari never
  // fires it) and may never run this page again: a swipe back, an app switch
  // that ends in the tab evicted, a reload. So the box's words go into the
  // list, and both saves go at once with keepalive (Task 14 re-review,
  // R1-I1). On a desktop this happens on every switch away too, which costs a
  // save of what was typed, as Enter would make it, without checking it.
  const hideNow = useRef<() => void>(() => undefined);
  hideNow.current = () => {
    if (choosing) return;
    const list = commit(segments);
    edits.keep();
    if (list === segments) {
      keep();
      return;
    }
    setSegments(list);
    keep(documentOf({ sha, pass, cursorS: segments[index]?.start ?? 0, startedAt, segments: list, corrections: fixesNow.current }));
  };
  useEffect(() => onPageHide(() => hideNow.current()), []);

  const leave = () => {
    controls.current?.pause();
    setSegments(commit(segments));
    setLeaving(true);
  };

  const act = (action: Action, caret?: Caret) => {
    if (segment === undefined || choosing) return;
    // While the flag menu is open its keys are its own: a key that reaches the
    // box first (a fast Esc after Ctrl+F) only closes it (Task 13 review, I1).
    if (flagging && action.kind !== "flag") {
      if (action.kind === "leave") setFlagging(false);
      return;
    }
    switch (action.kind) {
      case "check": {
        const next = commit(segments).map((s, i) => (i === index ? { ...s, state: "checked" as const } : s));
        setSegments(next);
        checkedAt.current.push(Date.now());
        const to = step(order, index, 1);
        if (to === null) {
          setFinished(true);
          controls.current?.pause();
        } else {
          go(to, next);
        }
        return;
      }
      case "previous": {
        const next = commit(segments);
        setSegments(next);
        const to = step(order, index, -1);
        if (to === null) setNotice("This is the first sentence of the pass.");
        else go(to, next);
        return;
      }
      case "toggle":
        controls.current?.toggle(RESUME_BACK_S);
        return;
      case "replay":
        hear(segment);
        return;
      case "slower":
      case "faster": {
        const player = controls.current;
        if (player === null) return;
        const next = stepSpeed(player.speed(), action.kind === "faster" ? 1 : -1);
        player.setSpeed(next);
        setNotice(`Playing at ${speedLabel(next)}`);
        return;
      }
      case "speaker": {
        const label =
          action.n - 1 < labels.length ? labels[action.n - 1] : action.n - 1 === labels.length ? newSpeakerLabel(labels) : undefined;
        if (label === undefined) {
          setNotice(`There are ${labels.length} speakers. Ctrl+${labels.length + 1} adds a new one.`);
          return;
        }
        const next = commit(segments);
        const all = labels.includes(label) ? labels : [...labels, label];
        const name = displayName(all, names, all.indexOf(label)) ?? label;
        const range = entryRange(wordIndex(editor.content), segment);
        const op = range === null ? null : speakerChange(editor.content, range.start, range.stop, label);
        if (op === null) {
          setSegments(next);
          setNotice(range === null ? "This sentence has no words to give a speaker." : `Already said by ${name}`);
          return;
        }
        editor.applyEdit(op);
        setSegments(next.map((s, i) => (i === index ? { ...s, speaker: label } : s)));
        setNotice(`Said by ${name}`);
        return;
      }
      case "second": {
        const theirs = opinions.words[index] ?? [];
        if (other === null || theirs.length === 0) setNotice("There is no second opinion for this sentence.");
        else {
          setText(theirs.join(" "));
          setNotice("The second opinion's reading is in the box. Enter checks it.");
        }
        return;
      }
      case "unclear": {
        setSegments(segments.map((s, i) => (i === index && !s.flags.includes("unclear") ? { ...s, flags: [...s.flags, "unclear" as const] } : s)));
        if (caret !== undefined && caret.end > caret.start) setText(`${text.slice(0, caret.start)}[?]${text.slice(caret.end)}`);
        else if (text.trim() === "") setText("[?]");
        setNotice("Flagged: can't make it out");
        return;
      }
      case "flags":
        setFlagging(true);
        return;
      case "flag":
        setSegments(segments.map((s, i) => (i === index ? toggleFlag(s, action.flag) : s)));
        setFlagging(false);
        return;
      case "split": {
        // The box's unsaved words go into the list first, so the split is made
        // in the words the box shows; the caret is then found in the list's
        // text word by word, whatever the box's spacing (Task 11 review).
        const next = commit(segments);
        const range = entryRange(wordIndex(editor.content), segment);
        const listText = range === null ? "" : segmentText(editor.content, wordIndex(editor.content), segment);
        const at = caretInList(text, caret?.start ?? 0, listText);
        if (at === null) {
          setSegments(next);
          setNotice("The cursor's place could not be found in the sentence's words, so nothing was split.");
          return;
        }
        const result = splitAt(editor.content, next, index, at);
        if ("refused" in result) {
          setSegments(next);
          setNotice(result.refused);
          return;
        }
        setSegments(result.segments);
        setNotice("Split in two. Both halves are to be checked.");
        return;
      }
      case "merge": {
        if (index === 0) {
          setNotice("This is the first sentence; there is none before it to merge with.");
          return;
        }
        // One sentence has one speaker: two speakers' sentences are not merged (Task 11 review).
        const mine = view(index);
        const theirs = view(index - 1);
        if (mine !== null && theirs !== null && mine.label !== theirs.label) {
          setNotice(
            `Not merged: this sentence is said by ${mine.name ?? "no one named"} and the one before by ${theirs.name ?? "no one named"}. ` +
              "Give them one speaker with Ctrl+1 to Ctrl+9 first.",
          );
          return;
        }
        const merged = mergeWithPrevious(commit(segments), index);
        if (merged === null) return;
        setSegments(merged);
        go(index - 1, merged, false);
        setNotice("Merged with the sentence before.");
        return;
      }
      case "nextLikely":
      case "previousLikely": {
        const to = step(likely, index, action.kind === "nextLikely" ? 1 : -1);
        if (to === null) {
          setNotice(action.kind === "nextLikely" ? "No likely error after this one." : "No likely error before this one.");
          return;
        }
        const next = commit(segments);
        setSegments(next);
        go(to, next);
        return;
      }
      case "keys":
        showKeys(REVIEW_SHEET);
        return;
      case "leave":
        leave();
        return;
    }
  };

  const remaining = order.filter((i) => segments[i]?.state !== "checked").length;
  const views = (from: number, to: number) =>
    Array.from({ length: Math.max(0, to - from) }, (_, k) => view(from + k)).filter((v): v is SentenceView => v !== null);
  return {
    choosing,
    choose,
    resumed: saved !== null,
    current: view(index),
    before: views(Math.max(0, index - CONTEXT), index),
    after: views(index + 1, Math.min(segments.length, index + 1 + CONTEXT)),
    text,
    setText,
    pause: () => controls.current?.pause(),
    second: other === null ? null : { words: opinions.words[index] ?? [], differs: opinions.differs[index] ?? null },
    pass,
    setPass,
    likelyCount: likely.length,
    progress: counts(segments),
    timeLeft: timeLeft(checkedAt.current, remaining),
    notice,
    flagging,
    setFlagging,
    finished,
    saving,
    speakers: labels.map((label, i) => ({ label, name: displayName(labels, names, i) ?? label, colour: speakerColour(i) })),
    act,
    leave,
    settle,
  };
}
