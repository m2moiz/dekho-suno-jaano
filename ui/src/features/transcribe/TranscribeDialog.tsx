import { useEffect, useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { fromThrown, showError } from "@/features/errors/appError";
import { displayTitle, titleFace } from "@/features/library/title";
import type { RecordingRow } from "@/features/library/types";
import { TOUCH, useMediaQuery } from "@/lib/media";
import { cn } from "@/lib/utils";
import { type Advanced, CHOICES, type ChoiceId, costLabel, expectedLabel, requestFor, speedFor } from "./choices";
import { type Engine, loadEngines, startJob } from "./jobs";

type EngineName = Engine["name"];

const PLAIN: Advanced = { engine: null, model: "", prompt: "", diarize: true, requireDiarize: false, startOver: false };

// A chosen radio in ink, not the primitive's gold: gold is this dialog's one
// primary action, Start (rulings F23).
const INK_RADIO =
  "data-checked:border-foreground data-checked:bg-foreground dark:data-checked:bg-foreground [&_[data-slot=radio-group-indicator]>span]:bg-background";

// A row of a radio list: the whole row is the target, 44 px tall.
const ROW = "flex min-h-11 cursor-pointer items-center gap-3 rounded-lg px-2 hover:bg-muted";

/**
 * Transcribe, asking the owner's question first (Hashiya spec, Transcribe):
 * what is spoken. The answer picks the engine and its settings, and the
 * dialog says how long that should take and what it uses. Every engine the
 * server lists is a choice beside it (the seam for a cloud engine, #247:
 * one that says so is marked "cloud" and priced, with no change here); the
 * rest folds under Advanced.
 */
export function TranscribeDialog({ recording, onClose }: { recording: RecordingRow; onClose: () => void }) {
  const [engines, setEngines] = useState<Engine[] | null>(null);
  const [answer, setAnswer] = useState<ChoiceId>("mixed");
  const [advanced, setAdvanced] = useState<Advanced>(PLAIN);
  const [sending, setSending] = useState(false);
  const touch = useMediaQuery(TOUCH);
  const ids = useId();

  useEffect(() => {
    let live = true;
    loadEngines().then(
      (listed) => {
        if (live) setEngines(listed);
      },
      (thrown: unknown) => {
        if (!live) return;
        onClose();
        showError(fromThrown(thrown, "/api/engines"));
      },
    );
    return () => {
      live = false;
    };
  }, [onClose]);

  if (engines === null) return null;
  const choice = CHOICES.find((c) => c.id === answer) ?? (CHOICES[0] as (typeof CHOICES)[number]);
  const request = requestFor(choice, advanced);
  const engine = engines.find((e) => e.name === request.engine);
  const runnable = engines.filter((e) => e.reason === null);
  const unavailable = engines.filter((e) => e.reason !== null);
  const speed = speedFor(choice, advanced);
  const expected = speed === null ? null : expectedLabel(recording.duration_s, speed);
  const title = displayTitle(recording);
  const face = titleFace(title);
  const tall = touch ? "h-11" : "";
  const set = <K extends keyof Advanced>(key: K, value: Advanced[K]) => setAdvanced({ ...advanced, [key]: value });

  // A typed model belongs to the engine it was typed for, so it goes with it.
  const pickEngine = (name: EngineName) =>
    setAdvanced({ ...advanced, engine: name === choice.engine ? null : name, model: name === request.engine ? advanced.model : "" });
  // A new answer picks its own engine again, over one picked by hand.
  const pickAnswer = (id: ChoiceId) => {
    const next = CHOICES.find((c) => c.id === id);
    if (next === undefined) return;
    setAnswer(id);
    setAdvanced({ ...advanced, engine: null, model: next.engine === request.engine ? advanced.model : "" });
  };

  const start = () => {
    setSending(true);
    startJob(recording.id, request).then(
      () => onClose(),
      (thrown: unknown) => {
        // Refused (another run holds the machine, the file is gone): the
        // server's sentence says why, in the error dialog.
        onClose();
        showError(fromThrown(thrown));
      },
    );
  };

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className="max-h-[calc(100dvh-2rem)] gap-5 overflow-y-auto sm:max-w-lg">
        {/* Clear of the close button in the corner. */}
        <DialogHeader className="pr-8">
          <DialogTitle className="text-balance">
            Transcribe{" "}
            <bdi lang={face.lang} className={face.className}>
              {title}
            </bdi>
          </DialogTitle>
          <DialogDescription>
            {engine?.cloud === true
              ? `Sends the recording's sound to ${engine.name}, off this Mac.`
              : "Runs on this Mac. Nothing leaves it."}
          </DialogDescription>
        </DialogHeader>

        <fieldset className="flex flex-col">
          <legend id={`${ids}-what`} className="mb-1 font-medium">
            What's spoken?
          </legend>
          <RadioGroup
            aria-labelledby={`${ids}-what`}
            className="gap-0"
            value={answer}
            onValueChange={(picked: ChoiceId) => pickAnswer(picked)}
          >
            {CHOICES.map((c) => (
              <label key={c.id} className={ROW}>
                <RadioGroupItem value={c.id} className={INK_RADIO} />
                {c.label}
              </label>
            ))}
          </RadioGroup>
        </fieldset>

        {/* The expected time first and large: speed is what the owner weighs. */}
        <div role="status" className="flex flex-col gap-0.5">
          {expected !== null && <p className="text-lg font-semibold tabular-nums">{expected}. </p>}
          <p className="text-sm text-muted-foreground">
            Uses {advanced.engine === null ? choice.says : advanced.engine}.
          </p>
        </div>

        <fieldset className="flex flex-col">
          <legend id={`${ids}-engine`} className="mb-1 text-sm font-medium">
            Engine
          </legend>
          {/* Every engine the server lists, so a new one (a cloud engine, #247) appears here with no change to this dialog. */}
          <RadioGroup
            aria-labelledby={`${ids}-engine`}
            className="gap-0"
            value={request.engine}
            onValueChange={(picked: EngineName) => pickEngine(picked)}
          >
            {runnable.map((e) => {
              const cost = costLabel(recording.duration_s, e.usd_per_hour);
              return (
                <label key={e.name} className={cn(ROW, "flex-wrap gap-y-0 py-1")}>
                  <RadioGroupItem value={e.name} className={INK_RADIO} />
                  <span>{e.name}</span>
                  {e.cloud && (
                    <span className="rounded-full border border-border px-2 text-xs text-muted-foreground">cloud</span>
                  )}
                  {e.name === choice.engine && <span className="text-sm text-muted-foreground">for this answer</span>}
                  {cost !== null && <span className="basis-full pl-7 text-sm text-muted-foreground tabular-nums">{cost}</span>}
                </label>
              );
            })}
          </RadioGroup>
          {unavailable.map((e) => (
            // One grey line an engine, its reason on request (spec, Transcribe).
            <Collapsible key={e.name} className="px-2 text-sm text-muted-foreground" data-unavailable={e.name}>
              <span>{e.name} can't run on this Mac. </span>
              <CollapsibleTrigger
                aria-label={`Why ${e.name} can't run`}
                className={cn("underline underline-offset-4", touch && "min-h-11")}
              >
                Why
              </CollapsibleTrigger>
              <CollapsibleContent className="mt-1 whitespace-pre-wrap select-text">{e.reason}</CollapsibleContent>
            </Collapsible>
          ))}
        </fieldset>

        <Collapsible>
          <CollapsibleTrigger className="min-h-11 text-sm font-medium underline-offset-4 hover:underline">Advanced</CollapsibleTrigger>
          <CollapsibleContent className="mt-2 flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor={`${ids}-model`}>Model</Label>
              <Input
                id={`${ids}-model`}
                className={tall}
                value={advanced.model}
                placeholder={engine?.default_model ?? ""}
                onChange={(event) => set("model", event.target.value)}
                spellCheck={false}
              />
            </div>
            {request.engine === "whisper" && (
              <div className="flex flex-col gap-2">
                <Label htmlFor={`${ids}-prompt`}>Prompt</Label>
                <Textarea id={`${ids}-prompt`} value={advanced.prompt} onChange={(event) => set("prompt", event.target.value)} />
              </div>
            )}
            <Toggle id={`${ids}-diarize`} label="Skip speaker labels" checked={!advanced.diarize} onChange={(skip) => set("diarize", !skip)} />
            {advanced.diarize && (
              <Toggle
                id={`${ids}-require`}
                label="Fail if speakers cannot be labelled"
                checked={advanced.requireDiarize}
                onChange={(v) => set("requireDiarize", v)}
              />
            )}
            <Toggle
              id={`${ids}-over`}
              label="Start over, not from where an earlier run stopped"
              checked={advanced.startOver}
              onChange={(v) => set("startOver", v)}
            />
          </CollapsibleContent>
        </Collapsible>

        <DialogFooter>
          <Button variant="outline" className={tall} onClick={onClose}>
            Cancel
          </Button>
          {/* The one gold action: the default variant is gold. Off for an engine the server does not list or cannot run. */}
          <Button onClick={start} disabled={sending || engine?.reason !== null} className={cn("font-semibold", tall)}>
            Start
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Toggle({ id, label, checked, onChange }: { id: string; label: string; checked: boolean; onChange: (checked: boolean) => void }) {
  return (
    <div className="flex min-h-11 items-center gap-2">
      <Switch id={id} checked={checked} onCheckedChange={(next: boolean) => onChange(next)} />
      <Label htmlFor={id}>{label}</Label>
    </div>
  );
}
