import { type CSSProperties, useEffect, useRef } from "react";

import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Kbd } from "@/components/ui/kbd";
import { Textarea } from "@/components/ui/textarea";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { atLabel } from "@/features/bleep/matches";
import type { SaveState } from "@/features/edit/editing";
import { titleFace } from "@/features/library/title";
import { AppBar } from "@/features/shell/AppBar";
import { FIELD_BUTTON, FIELD_EDGE } from "@/features/shell/field";
import { KeysItem } from "@/features/shell/KeySheet";
import { FOOTER_KEYS, REVIEW_SHEET } from "@/features/shell/keys";
import { langOf } from "@/lib/script";
import { FinishPanel } from "./FinishPanel";
import { actionFor } from "./keymap";
import type { Flag, ReviewPass } from "./model";
import type { SentenceView, Session } from "./useReviewSession";
import "./review.css";

const SAVE_TEXT: Record<SaveState, string> = { saved: "Saved", saving: "Saving…", failed: "Not saved" };

export const FLAGS: [Flag, string][] = [
  ["unclear", "Can't make it out"],
  ["not_speech", "Not speech"],
  ["overlap", "Overlapping talk"],
  ["cut_off", "Cut off"],
];

// A sentence of 15 s fills the margin's tick: a choice, about the longest
// sentence an engine writes before it cuts one.
const TICK_FULL_S = 15;

function style(view: SentenceView): CSSProperties {
  const seconds = view.segment.end - view.segment.start;
  return { "--speaker": view.colour, "--tick": `${Math.min(100, (seconds / TICK_FULL_S) * 100)}%` } as CSSProperties;
}

/** A sentence around the one in hand: dim, its margin quiet. */
function Context({ view }: { view: SentenceView }) {
  return (
    <div className="review-row" style={style(view)}>
      <div className="review-margin">
        {view.name !== null && <span className="nameplate">{view.name}</span>}
        <span>{atLabel(view.segment.start)}</span>
      </div>
      <p className="review-context" dir="auto" lang={langOf(view.text)}>
        {view.text || <span className="text-sm italic">No words</span>}
      </p>
    </div>
  );
}

/** The second opinion: the other transcript's words for this span, the differing ones underlined. */
export function SecondOpinion({ second }: { second: NonNullable<Session["second"]> }) {
  if (second.words.length === 0) return <p className="text-sm text-dim">The other transcript has nothing here.</p>;
  return (
    <p className="review-context" dir="auto" lang={langOf(second.words.join(" "))}>
      <span className="sr-only">Second opinion: </span>
      {second.words.map((word, k) => (
        <span key={k}>
          {k > 0 && " "}
          {second.differs?.[k] ? <span className="underline decoration-dotted decoration-2 underline-offset-4">{word}</span> : word}
        </span>
      ))}
    </p>
  );
}

const PASSES: [ReviewPass, string, string][] = [
  ["every", "Every sentence", "In order, for an answer key."],
  ["likely", "Likely errors", "Unsure words, flags, and where the second opinion disagrees."],
];

/**
 * The pass, picked on entry (spec: "The pass is chosen on entry", F13): two
 * buttons, the one picked last focused, so Enter starts it; nothing plays
 * until one is picked, and then the sentence in hand does (F25).
 */
function PassChooser({ session }: { session: Session }) {
  const { checked, total } = session.progress;
  return (
    <main className="mx-auto flex w-full max-w-xl flex-1 flex-col justify-center gap-6 px-3 py-12 sm:px-6">
      <div className="flex flex-col gap-2">
        <h2 className="font-reading text-3xl font-semibold text-balance">Which sentences?</h2>
        <p className="text-muted-foreground">
          {session.resumed
            ? `${checked.toLocaleString("en")} of ${total.toLocaleString("en")} checked so far. You pick up where you left off.`
            : `${total.toLocaleString("en")} sentences. Each plays as you reach it; Enter marks it checked.`}
        </p>
      </div>
      <div role="group" aria-label="Pass" className="flex flex-col gap-3">
        {PASSES.map(([pass, label, says]) => (
          <Button
            key={pass}
            variant="outline"
            autoFocus={pass === session.pass}
            className="h-auto min-h-11 flex-col items-start gap-0.5 px-4 py-3 text-left whitespace-normal"
            onClick={() => session.choose(pass)}
            onKeyDown={(event) => {
              if (event.key === "Escape") session.leave();
            }}
          >
            <span className="text-base font-semibold">
              {label}
              <span className="ml-2 font-normal text-muted-foreground tabular-nums">
                {(pass === "every" ? total : session.likelyCount).toLocaleString("en")}
              </span>
            </span>
            <span className="text-sm font-normal text-muted-foreground">{says}</span>
          </Button>
        ))}
      </div>
      <p role="status" aria-live="polite" className="min-h-6 text-sm text-muted-foreground">
        {session.notice}
      </p>
    </main>
  );
}

type Props = { session: Session; title: string; back: string; transcriptId: number };

/**
 * Review mode on a Mac (Hashiya spec, "Laptop, keyboard-first"): the
 * sentence in hand in the middle, large, in an edit box that keeps the focus
 * the whole time; two sentences either side, dimmed; the margin beside it;
 * the second opinion beneath; progress, the pass and time left in the bar;
 * the five most used keys in the footer.
 */
export function ReviewDesk({ session, title, back, transcriptId }: Props) {
  const box = useRef<HTMLTextAreaElement>(null);
  const current = session.current;
  // Back in the box after each move, and after the flag menu closes; never
  // while it is open, so the menu keeps the keyboard (F12).
  useEffect(() => {
    if (!session.flagging && !session.choosing) box.current?.focus();
  }, [current?.index, session.flagging, session.choosing, session.pass, session.finished]);

  const face = titleFace(title);
  const bar = (
    <AppBar
      back={{
        href: back,
        label: "Back to the transcript",
        // As Esc: save first, then go (F27).
        onClick: (event) => {
          // Cmd+click and the like keep the link's own new tab (Minor 6).
          if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
          event.preventDefault();
          session.leave();
        },
      }}
      settings={<KeysItem sheet={REVIEW_SHEET} shortcut="Ctrl /" />}
    >
      <h1 dir="auto" lang={face.lang} className={`min-w-0 flex-1 truncate font-semibold ${face.className}`}>
        <span className="font-reading">Review · </span>
        {title}
      </h1>
      {!session.choosing && (
        <>
          <span role="status" aria-live="polite" className="text-sm text-field-foreground tabular-nums">
            {session.progress.checked.toLocaleString("en")} of {session.progress.total.toLocaleString("en")} checked
          </span>
          {session.timeLeft !== null && <span className="text-sm text-field-muted">{session.timeLeft}</span>}
          <ToggleGroup
            aria-label="Pass"
            variant="outline"
            spacing={0}
            value={[session.pass]}
            onValueChange={(picked: string[]) => {
              if (picked[0] === "every" || picked[0] === "likely") session.setPass(picked[0]);
            }}
          >
            <ToggleGroupItem value="every" className={`h-11 ${FIELD_BUTTON} ${FIELD_EDGE}`}>
              Every sentence
            </ToggleGroupItem>
            <ToggleGroupItem value="likely" className={`h-11 ${FIELD_BUTTON} ${FIELD_EDGE}`}>
              Likely errors <span className="tabular-nums">({session.likelyCount.toLocaleString("en")})</span>
            </ToggleGroupItem>
          </ToggleGroup>
          <span className="min-w-16 text-sm text-field-muted">{SAVE_TEXT[session.saving]}</span>
        </>
      )}
    </AppBar>
  );

  if (session.choosing) {
    return (
      <>
        {bar}
        <PassChooser session={session} />
      </>
    );
  }
  if (session.finished) {
    return (
      <>
        {bar}
        <FinishPanel transcriptId={transcriptId} progress={session.progress} back={back} leave={session.leave} settle={session.settle} />
      </>
    );
  }
  return (
    <>
      {bar}
      <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col justify-center gap-5 px-3 py-8 sm:px-6">
        {session.before.map((view) => (
          <Context key={view.index} view={view} />
        ))}
        {current !== null && (
          <section aria-label="Sentence being checked" className="review-row my-3" style={style(current)}>
            <div className="review-margin text-sm">
              {current.name !== null && <span className="nameplate text-sm">{current.name}</span>}
              <span>
                {atLabel(current.segment.start)} · {(current.segment.end - current.segment.start).toFixed(1)} s
              </span>
              <span className="review-tick" aria-hidden />
              <span className={current.segment.state === "checked" ? "text-checked" : undefined}>
                {current.segment.state === "checked" ? "Checked" : "Not checked yet"}
              </span>
              {current.segment.flags.map((flag) => (
                <span key={flag} className="rounded-full border border-border px-2 text-xs">
                  {FLAGS.find(([f]) => f === flag)?.[1]}
                </span>
              ))}
              <DropdownMenu open={session.flagging} onOpenChange={session.setFlagging}>
                <DropdownMenuTrigger render={<Button variant="ghost" size="sm" className="-ml-2.5 h-8 text-muted-foreground max-md:h-11" />}>
                  Flag
                </DropdownMenuTrigger>
                {/* Focus goes back to the box when the menu closes, not to its trigger (F12). */}
                <DropdownMenuContent align="start" className="w-auto" finalFocus={box}>
                  {FLAGS.map(([flag, label]) => (
                    <DropdownMenuCheckboxItem
                      key={flag}
                      checked={current.segment.flags.includes(flag)}
                      closeOnClick
                      onCheckedChange={() => session.act({ kind: "flag", flag })}
                    >
                      {label}
                    </DropdownMenuCheckboxItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
            <div className="flex min-w-0 flex-col gap-3">
              <Textarea
                ref={box}
                aria-label="What was said"
                className="review-box"
                dir="auto"
                lang={langOf(session.text)}
                spellCheck={false}
                value={session.text}
                onChange={(event) => session.setText(event.target.value)}
                onInput={() => session.pause()}
                onKeyDown={(event) => {
                  // The flag menu open: the box takes no key; Esc closes the menu (I1).
                  if (session.flagging) {
                    event.preventDefault();
                    if (event.key === "Escape") session.setFlagging(false);
                    return;
                  }
                  const action = actionFor(event.nativeEvent);
                  if (action === null) return;
                  event.preventDefault();
                  session.act(action, { start: event.currentTarget.selectionStart, end: event.currentTarget.selectionEnd });
                }}
              />
              {session.second !== null && <SecondOpinion second={session.second} />}
            </div>
          </section>
        )}
        {session.after.map((view) => (
          <Context key={view.index} view={view} />
        ))}
        <p role="status" aria-live="polite" className="min-h-6 text-sm text-muted-foreground">
          {session.notice}
        </p>
      </main>
      <footer className="mx-auto flex w-full max-w-4xl flex-wrap gap-x-5 gap-y-1 px-3 pb-3 text-xs text-muted-foreground sm:px-6">
        {FOOTER_KEYS.map((key) => (
          <span key={key.does} className="flex items-center gap-1">
            {key.keys.map((k) => (
              <Kbd key={k}>{k}</Kbd>
            ))}
            {key.does}
          </span>
        ))}
      </footer>
    </>
  );
}
