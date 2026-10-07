import { type FormEvent, type RefObject, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { Renderable } from "@/features/edit/editing";
import { fromThrown, showError } from "@/features/errors/appError";
import type { PlayerControls } from "@/features/player/Player";
import { type Content, type Editor, itemsIn } from "@/lib/editOps";
import { TOUCH, useMediaQuery } from "@/lib/media";
import { addWord, atLabel, findMatches, isMuted, type Match } from "./matches";
import { alone, type RenderJob, startRender, useRender } from "./render";
import { RenderStatus } from "./RenderStatus";
import type { MatchesState } from "./useMatches";

// How much of the recording an audition plays either side of a match, in
// seconds: enough to hear the words around the cut, which is what a clipped
// neighbour sounds like (#44).
export const AROUND_S = 1;

type Props = {
  transcriptId: number;
  editor: Editor;
  content: Content;
  renderable: Renderable;
  /** How far a mute reaches each side of a word, in seconds (dsj.hatao.PAD_S). */
  padS: number;
  controls: RefObject<PlayerControls | null>;
  /** The words the lists matched, looked for while the reader is open (it badges the menu's Bleep item). */
  matches: MatchesState;
  /** The render in progress or last finished, kept by the page so closing the drawer does not lose it. */
  started: RenderJob | null;
  onStarted: (job: RenderJob) => void;
};

/**
 * The words a word list matched (#84): each with where it is and what matched
 * it, to dismiss, mute again, or hear on its own, and a box that adds a word
 * to the user's own list. Muting and dismissing are edits, so Cmd+Z takes
 * each back. Nothing here renders: what plays muted is what a render mutes.
 */
export function BleepPanel({ transcriptId, editor, content, renderable, padS, controls, matches: state, started, onStarted }: Props) {
  const { found, setFound, again } = state;
  const [note, setNote] = useState<string | null>(null);
  const job = useRender(started);
  const busy = job !== null && job.state !== "done" && job.state !== "failed";
  // 44 px targets where the reader has a touch layout (F15).
  const touch = useMediaQuery(TOUCH);
  const tall = touch ? "h-11 px-3" : "";
  const render = (list: Content) =>
    startRender(transcriptId, list).then(onStarted, (thrown: unknown) =>
      showError(fromThrown(thrown, `/api/transcripts/${transcriptId}/render`)),
    );

  const matched = found?.matches ?? [];
  const unmuted = matched.filter((m) => !isMuted(content, m));
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
        again();
      },
      (thrown: unknown) => showError(fromThrown(thrown, "/api/words")),
    );
  };

  return (
    <section aria-label="Words to bleep" className="flex flex-col gap-4 text-sm">
      <div className="flex justify-end">
        <Button
          variant="outline"
          size="sm"
          className={tall}
          disabled={unmuted.length === 0}
          onClick={() => editor.applyEdit({ kind: "flag", entries: entriesOf(unmuted) })}
        >
          {unmuted.length > 0 ? `Mute all ${unmuted.length}` : "Mute all"}
        </Button>
      </div>
      {found === null ? (
        <p className="text-muted-foreground">Looking through the word lists…</p>
      ) : matched.length === 0 ? (
        <p className="text-muted-foreground" role="status">
          No word matched: {found.words_searched.toLocaleString("en")} words searched against the{" "}
          {found.lists.join(", ")} lists.
        </p>
      ) : (
        <ul aria-label="Matches" className="flex flex-col divide-y">
          {matched.map((m) => {
            const muted = isMuted(content, m);
            return (
              <li key={`${m.start}-${m.stop}`} className="flex flex-col gap-2 py-3 first:pt-0" aria-label={m.word}>
                <div className="flex items-baseline gap-3">
                  <span className="w-16 shrink-0 font-mono text-muted-foreground tabular-nums">{atLabel(m.start_s)}</span>
                  <span dir="auto" className={`font-medium ${muted ? "line-through" : ""}`}>
                    {m.word}
                  </span>
                  <span className="min-w-0 truncate text-muted-foreground">{m.entry}</span>
                  <span className="ml-auto shrink-0 text-muted-foreground">{muted ? "muted" : "dismissed"}</span>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    className={tall}
                    onClick={() => controls.current?.hear(Math.max(0, m.start_s - AROUND_S), m.end_s + AROUND_S)}
                  >
                    Hear
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className={tall}
                    disabled={busy}
                    title="Render the recording with only this word muted"
                    onClick={() => void render(alone(content, m))}
                  >
                    Render alone
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className={`min-w-24 ${tall}`}
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
                </div>
              </li>
            );
          })}
        </ul>
      )}
      <div className="flex flex-wrap items-center gap-3">
        {/* The drawer's main action, filled with the text colour (navy on the light card,
            pale on the dark one): the strongest fill here short of gold, which the
            rail's Play keeps (F23). */}
        <Button
          size="sm"
          className={`bg-foreground text-background hover:bg-foreground/85 ${touch ? "h-11 px-4" : "h-8 px-4"}`}
          disabled={busy || renderable.spans === null || renderable.spans.length === 0}
          onClick={() => void render(content)}
        >
          Render
        </Button>
        <span className="min-w-0 flex-1 basis-48 text-muted-foreground">
          {renderable.spans === null
            ? "This list cannot be rendered."
            : renderable.spans.length === 0
              ? "Nothing is muted yet."
              : `Writes a copy beside the recording with ${renderable.spans.length === 1 ? "1 span" : `${renderable.spans.length} spans`} silenced; the recording is not changed.`}
        </span>
      </div>
      {job !== null && <RenderStatus job={job} />}
      <form onSubmit={add} className="flex flex-wrap items-center gap-2">
        <Input
          name="word"
          aria-label="A word to add to your list"
          placeholder="Add a word to your list"
          className={`min-w-0 flex-1 ${touch ? "h-11" : ""}`}
        />
        <Button type="submit" variant="outline" size="sm" className={tall}>
          Add
        </Button>
        {note !== null && (
          <span className="basis-full text-muted-foreground" role="status">
            {note}
          </span>
        )}
      </form>
      <p className="text-xs text-muted-foreground">
        Playing mutes what a render would mute, each word from {padS} s before it to {padS} s after.
        {renderable.unrenderable !== null && ` This list cannot be rendered: ${renderable.unrenderable}.`}
        {found !== null && ` Recall: ${found.recall.replace(/^recall: /, "")}.`}
      </p>
    </section>
  );
}
