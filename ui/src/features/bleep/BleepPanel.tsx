import { type FormEvent, type RefObject, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { Renderable } from "@/features/edit/editing";
import type { EditReading } from "@/features/edit/readContent";
import { fromThrown, showError } from "@/features/errors/appError";
import type { PlayerControls } from "@/features/player/Player";
import { type Content, type Editor, itemsIn } from "@/lib/editOps";
import { addWord, atLabel, findMatches, isMuted, type Match, type Matches } from "./matches";
import { alone, type RenderJob, startRender, useRender } from "./render";
import { RenderStatus } from "./RenderStatus";

// How much of the recording an audition plays either side of a match, in
// seconds: enough to hear the words around the cut, which is what a clipped
// neighbour sounds like (#44).
export const AROUND_S = 1;

type Props = {
  transcriptId: number;
  editor: Editor;
  content: Content;
  edit: EditReading;
  renderable: Renderable;
  /** How far a mute reaches each side of a word, in seconds (dsj.hatao.PAD_S). */
  padS: number;
  controls: RefObject<PlayerControls | null>;
};

/**
 * The words a word list matched (#84): each with where it is and what matched
 * it, to dismiss, mute again, or hear on its own, and a box that adds a word
 * to the user's own list. Muting and dismissing are edits, so Cmd+Z takes
 * each back. Nothing here renders: what plays muted is what a render mutes.
 */
export function BleepPanel({ transcriptId, editor, content, edit, renderable, padS, controls }: Props) {
  const [found, setFound] = useState<Matches | null>(null);
  const [looked, setLooked] = useState(0);
  const [note, setNote] = useState<string | null>(null);
  const [started, setStarted] = useState<RenderJob | null>(null);
  const job = useRender(started);
  const busy = job !== null && job.state !== "done" && job.state !== "failed";
  const render = (list: Content) =>
    startRender(transcriptId, list).then(setStarted, (thrown: unknown) =>
      showError(fromThrown(thrown, `/api/transcripts/${transcriptId}/render`)),
    );

  // Looked for again when the words change (a word retyped, #83) or a word
  // is added to the list; a mute changes neither, and keeps the same reading.
  useEffect(() => {
    let live = true;
    findMatches(transcriptId, editor.content).then(
      (next) => {
        if (live) setFound(next);
      },
      (thrown: unknown) => {
        if (live) showError(fromThrown(thrown, `/api/transcripts/${transcriptId}/matches`));
      },
    );
    return () => {
      live = false;
    };
  }, [transcriptId, editor, edit.reading, looked]);

  const matches = found?.matches ?? [];
  const unmuted = matches.filter((m) => !isMuted(content, m));
  const entriesOf = (list: Match[]) => list.flatMap((m) => itemsIn(content, m.start, m.stop));

  const add = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const field = event.currentTarget.elements.namedItem("word") as HTMLInputElement;
    const word = field.value.trim();
    if (word === "") return;
    addWord(word).then(
      async (added) => {
        field.value = "";
        // The next pass, with the word in the list, mutes what it newly finds.
        const next = await findMatches(transcriptId, editor.content);
        setFound(next);
        const fresh = next.matches.filter((m) => m.entry === added.entry && !isMuted(editor.content, m));
        if (fresh.length > 0) {
          editor.applyEdit({ kind: "flag", entries: fresh.flatMap((m) => itemsIn(editor.content, m.start, m.stop)) });
        }
        const where = added.added ? `Added "${word}" to your word list` : `"${word}" is already on a list (${added.entry})`;
        setNote(`${where}. ${fresh.length === 1 ? "1 match" : `${fresh.length} matches`} muted.`);
        setLooked((n) => n + 1);
      },
      (thrown: unknown) => showError(fromThrown(thrown, "/api/words")),
    );
  };

  return (
    <section aria-label="Words to bleep" className="mb-8 rounded-lg border p-4 text-sm">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h3 className="font-medium">Words to bleep</h3>
        <Button
          variant="outline"
          size="sm"
          disabled={unmuted.length === 0}
          onClick={() => editor.applyEdit({ kind: "flag", entries: entriesOf(unmuted) })}
        >
          {unmuted.length > 0 ? `Mute all ${unmuted.length}` : "Mute all"}
        </Button>
      </div>
      {found === null ? (
        <p className="text-muted-foreground">Looking through the word lists…</p>
      ) : matches.length === 0 ? (
        <p className="text-muted-foreground" role="status">
          No word matched: {found.words_searched.toLocaleString("en")} words searched against the{" "}
          {found.lists.join(", ")} lists.
        </p>
      ) : (
        <ul aria-label="Matches" className="flex max-h-72 flex-col gap-1 overflow-y-auto">
          {matches.map((m) => {
            const muted = isMuted(content, m);
            return (
              <li key={`${m.start}-${m.stop}`} className="flex items-center gap-3" aria-label={m.word}>
                <span className="w-16 shrink-0 font-mono text-muted-foreground tabular-nums">{atLabel(m.start_s)}</span>
                <span dir="auto" className={`font-medium ${muted ? "line-through" : ""}`}>
                  {m.word}
                </span>
                <span className="truncate text-muted-foreground">{m.entry}</span>
                <span className="ml-auto shrink-0 text-muted-foreground">{muted ? "muted" : "dismissed"}</span>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => controls.current?.hear(Math.max(0, m.start_s - AROUND_S), m.end_s + AROUND_S)}
                >
                  Hear
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={busy}
                  title="Render the recording with only this word muted"
                  onClick={() => void render(alone(content, m))}
                >
                  Render alone
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="w-24"
                  onClick={() =>
                    editor.applyEdit(
                      muted
                        ? { kind: "dismiss", entries: itemsIn(content, m.start, m.stop) }
                        : { kind: "flag", entries: itemsIn(content, m.start, m.stop) },
                    )
                  }
                >
                  {muted ? "Dismiss" : "Mute again"}
                </Button>
              </li>
            );
          })}
        </ul>
      )}
      <div className="mt-3 flex items-center gap-3">
        <Button
          size="sm"
          disabled={busy || renderable.spans === null || renderable.spans.length === 0}
          onClick={() => void render(content)}
        >
          Render
        </Button>
        <span className="text-muted-foreground">
          {renderable.spans === null
            ? "This list cannot be rendered."
            : renderable.spans.length === 0
              ? "Nothing is muted yet."
              : `Writes a copy beside the recording with ${renderable.spans.length === 1 ? "1 span" : `${renderable.spans.length} spans`} silenced; the recording is not changed.`}
        </span>
      </div>
      {job !== null && <RenderStatus job={job} />}
      <form onSubmit={add} className="mt-3 flex items-center gap-2">
        <Input name="word" aria-label="A word to add to your list" placeholder="Add a word to your list" className="max-w-64" />
        <Button type="submit" variant="outline" size="sm">
          Add
        </Button>
        {note !== null && (
          <span className="text-muted-foreground" role="status">
            {note}
          </span>
        )}
      </form>
      <p className="mt-3 text-xs text-muted-foreground">
        Playing mutes what a render would mute, each word from {padS} s before it to {padS} s after.
        {renderable.unrenderable !== null && ` This list cannot be rendered: ${renderable.unrenderable}.`}
        {found !== null && ` Recall: ${found.recall.replace(/^recall: /, "")}.`}
      </p>
    </section>
  );
}
