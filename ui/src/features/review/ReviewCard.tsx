import { Flag as FlagIcon, Plus, RotateCcw } from "lucide-react";
import { type CSSProperties, useEffect, useRef } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { atLabel } from "@/features/bleep/matches";
import { titleFace } from "@/features/library/title";
import { AppBar } from "@/features/shell/AppBar";
import { FIELD_BUTTON, FIELD_EDGE } from "@/features/shell/field";
import { KeysItem } from "@/features/shell/KeySheet";
import { REVIEW_CARD_SHEET } from "@/features/shell/keys";
import { FINE, useMediaQuery } from "@/lib/media";
import { langOf } from "@/lib/script";
import { FinishPanel } from "./FinishPanel";
import { BOX_HINT_ID, FLAGS, FlagMenu, onBoxKey, PassChooser, SAVE_TEXT, SecondOpinion } from "./ReviewDesk";
import { useSwipe } from "./swipe";
import type { Session } from "./useReviewSession";
import "./review.css";

const CARD_HINT = "Tab plays. Option+Tab moves to the other controls.";

type Props = { session: Session; title: string; back: string; transcriptId: number };


/**
 * Review mode on a phone or tablet (Hashiya spec, "Phone and tablet,
 * touch-first"): one sentence a screen as a card, the margin as one line on
 * top, the words below (tap to edit; the keyboard opens), the second opinion
 * beneath, a large replay, a flag button, a row of speaker chips, progress in
 * the bar. Swipe left for checked and next, right for back; the same two are
 * buttons in thumb reach above the player rail. Every target is 44 px or
 * more (F15). It draws the desk's own Session, so leaving, back, split, merge,
 * the pass switch and the answer key put the box's words in the list first,
 * exactly as there; and with a keyboard the box takes the desk's keys (F14).
 */
export function ReviewCard({ session, title, back, transcriptId }: Props) {
  const box = useRef<HTMLTextAreaElement>(null);
  // A mouse is there: the box takes the focus after each move, as on the desk,
  // so the keys work in a narrow window (F14). On a touch screen it does not,
  // because focus in a text box opens the phone's keyboard over the card.
  const fine = useMediaQuery(FINE);
  const swipe = useSwipe((way) => session.act({ kind: way === "left" ? "check" : "previous" }));
  const current = session.current;
  useEffect(() => {
    if (fine && !session.flagging && !session.choosing) box.current?.focus();
  }, [fine, current?.index, session.flagging, session.choosing, session.pass, session.finished]);

  const face = titleFace(title);
  const bar = (
    <AppBar
      back={{
        href: back,
        label: "Back to the transcript",
        // As Esc: save first, then go (F27).
        onClick: (event) => {
          if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
          event.preventDefault();
          session.leave();
        },
      }}
      settings={<KeysItem sheet={REVIEW_CARD_SHEET} shortcut="Ctrl /" />}
    >
      <h1 dir="auto" lang={face.lang} className={session.choosing ? `min-w-0 flex-1 truncate font-semibold ${face.className}` : "sr-only"}>
        <span className="font-reading">Review · </span>
        {title}
      </h1>
      {!session.choosing && (
        <>
          <div className="flex min-w-0 flex-1 flex-col leading-tight">
            <span role="status" aria-live="polite" className="truncate text-sm font-medium text-field-foreground tabular-nums">
              {session.progress.checked.toLocaleString("en")} of {session.progress.total.toLocaleString("en")} checked
            </span>
            <span className="truncate text-xs text-field-muted">{SAVE_TEXT[session.saving]}</span>
          </div>
          <ToggleGroup
            aria-label="Pass"
            variant="outline"
            spacing={0}
            value={[session.pass]}
            onValueChange={(picked: string[]) => {
              if (picked[0] === "every" || picked[0] === "likely") session.setPass(picked[0]);
            }}
          >
            <ToggleGroupItem value="every" className={`h-11 min-w-11 ${FIELD_BUTTON} ${FIELD_EDGE}`}>
              All
            </ToggleGroupItem>
            <ToggleGroupItem value="likely" className={`h-11 min-w-11 ${FIELD_BUTTON} ${FIELD_EDGE}`}>
              Likely <span className="tabular-nums">({session.likelyCount.toLocaleString("en")})</span>
            </ToggleGroupItem>
          </ToggleGroup>
        </>
      )}
    </AppBar>
  );

  if (session.choosing) {
    return (
      <>
        {bar}
        <PassChooser session={session} checks={fine ? "Enter marks it checked" : "a swipe left, or Checked, next, marks it checked"} />
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
      <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-5 px-3 pt-4 pb-6 sm:justify-center sm:px-6">
        {current !== null && (
          <article
            {...swipe}
            aria-label="Sentence being checked"
            className="flex touch-pan-y touch-pinch-zoom flex-col gap-3 rounded-2xl border border-border bg-card p-4 shadow-md shadow-black/5"
            style={{ "--speaker": current.colour } as CSSProperties}
          >
            <p className="flex min-h-6 flex-wrap items-center gap-x-3 gap-y-1 text-sm tabular-nums text-muted-foreground">
              {current.name !== null && (
                <span dir="auto" lang={langOf(current.name)} className="font-semibold" style={{ color: current.colour }}>
                  {current.name}
                </span>
              )}
              <span>
                {atLabel(current.segment.start)} · {(current.segment.end - current.segment.start).toFixed(1)} s
              </span>
              <span className={current.segment.state === "checked" ? "font-medium text-checked" : undefined}>
                {current.segment.state === "checked" ? "Checked" : "Not checked yet"}
              </span>
              {current.segment.flags.map((flag) => (
                <span key={flag} className="rounded-full border border-border px-2 text-xs">
                  {FLAGS.find(([f]) => f === flag)?.[1]}
                </span>
              ))}
            </p>
            {/* Only where a keyboard is likely: read to VoiceOver on a phone with
                none, it names keys nobody has (fix round 1 review, M2). F6 is the
                desk's; the card has no regions to step through. */}
            {fine && (
              <span id={BOX_HINT_ID} className="sr-only">
                {CARD_HINT}
              </span>
            )}
            <Textarea
              ref={box}
              aria-label="What was said"
              {...(fine ? { "aria-describedby": BOX_HINT_ID } : {})}
              className="review-box"
              dir="auto"
              lang={langOf(session.text)}
              spellCheck={false}
              value={session.text}
              onChange={(event) => session.setText(event.target.value)}
              onInput={() => session.pause()}
              onKeyDown={(event) => onBoxKey(session, event)}
            />
            {session.second !== null && <SecondOpinion second={session.second} />}
          </article>
        )}
        <div className="flex items-center justify-center gap-3">
          <Button variant="outline" className="h-12 rounded-full px-5 text-base" onClick={() => session.act({ kind: "replay" })}>
            <RotateCcw aria-hidden className="size-5" />
            Play again
          </Button>
          <FlagMenu
            session={session}
            roomy
            {...(fine ? { finalFocus: box } : {})}
            trigger={<Button variant="outline" className="h-12 rounded-full px-5 text-base" />}
          >
            <FlagIcon aria-hidden className="size-5" />
            Flag
          </FlagMenu>
        </div>
        <div role="group" aria-label="Who said it" className="-mx-3 flex gap-2 overflow-x-auto px-3 pb-1 sm:mx-0 sm:flex-wrap sm:px-0">
          {session.speakers.map((speaker, i) => {
            const pressed = current?.label === speaker.label;
            return (
              <Button
                key={speaker.label}
                variant="outline"
                aria-pressed={pressed}
                className="review-chip h-11 shrink-0 rounded-full px-4 text-sm"
                style={{ "--speaker": speaker.colour } as CSSProperties}
                onClick={() => session.act({ kind: "speaker", n: i + 1 })}
              >
                <span dir="auto" lang={langOf(speaker.name)}>
                  {speaker.name}
                </span>
              </Button>
            );
          })}
          <Button
            variant="outline"
            className="h-11 shrink-0 rounded-full px-4 text-sm"
            onClick={() => session.act({ kind: "speaker", n: session.speakers.length + 1 })}
          >
            <Plus aria-hidden />
            New speaker
          </Button>
        </div>
        <p role="status" aria-live="polite" className="min-h-5 text-sm text-muted-foreground">
          {session.notice}
        </p>
      </main>
      {/* In thumb reach, just above the player rail, whose height it reads (playhead.ts PLAYER_HEIGHT). */}
      <div className="sticky z-10 border-t border-border bg-background" style={{ bottom: "var(--dsj-player-height, 0px)" }}>
        {/* 12 px clear of the rail below, so a thumb aimed at play does not mark a sentence checked (critique 7 Oct, P1-2). */}
        <div className="mx-auto grid w-full max-w-2xl grid-cols-[1fr_2fr] gap-2 px-3 pt-2 pb-3 sm:px-6">
          <Button variant="outline" className="h-12 text-base" onClick={() => session.act({ kind: "previous" })}>
            Back
          </Button>
          {/* The screen's one gold primary (F23): the default variant is gold. */}
          <Button className="h-12 text-base font-semibold" onClick={() => session.act({ kind: "check" })}>
            Checked, next
          </Button>
        </div>
      </div>
    </>
  );
}
