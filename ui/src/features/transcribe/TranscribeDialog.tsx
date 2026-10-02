import { useEffect, useId, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { fromThrown, showError } from "@/features/errors/appError";
import { fileName } from "@/features/library/describe";
import type { RecordingRow } from "@/features/library/types";
import { type Engine, loadEngines, startJob } from "./jobs";

type EngineName = Engine["name"];

/**
 * The picker (#113): engine, model, whisper's three options, speaker labels,
 * start over. Every control is one `dsj suno` flag, and nothing else is offered.
 */
export function TranscribeDialog({
  recording,
  onClose,
}: {
  recording: RecordingRow;
  onClose: () => void;
}) {
  const [engines, setEngines] = useState<Engine[] | null>(null);
  const [engine, setEngine] = useState<EngineName>("parakeet");
  // One model per engine, so switching engines and back keeps what was typed.
  const [models, setModels] = useState<Partial<Record<EngineName, string>>>({});
  const [language, setLanguage] = useState("");
  const [prompt, setPrompt] = useState("");
  const [romanUrdu, setRomanUrdu] = useState(false);
  const [diarize, setDiarize] = useState(true);
  const [requireDiarize, setRequireDiarize] = useState(false);
  const [startOver, setStartOver] = useState(false);
  const [sending, setSending] = useState(false);
  const ids = useId();

  useEffect(() => {
    let live = true;
    loadEngines().then(
      (listed) => {
        if (!live) return;
        setEngines(listed);
        // The first engine that can run, so Start is never pressed on one that cannot.
        const runnable = listed.find((e) => e.reason === null);
        if (runnable !== undefined) setEngine(runnable.name);
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
  const chosen = engines.find((e) => e.name === engine);
  const model = models[engine] ?? chosen?.default_model ?? "";
  const whisper = engine === "whisper";
  const unavailable = engines.filter((e) => e.reason !== null);

  const start = () => {
    setSending(true);
    startJob(recording.id, {
      engine,
      model: model.trim() || null,
      language: whisper ? language.trim() || null : null,
      prompt: whisper ? prompt.trim() || null : null,
      roman_urdu: whisper && romanUrdu,
      diarize,
      require_diarize: diarize && requireDiarize,
      start_over: startOver,
    }).then(
      () => onClose(),
      (thrown: unknown) => {
        // Refused (another run holds the machine, the file is in a synced
        // folder): the server's sentence says why, in the error dialog.
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
      <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Transcribe {fileName(recording.path)}</DialogTitle>
          <DialogDescription>Runs on this Mac. Nothing leaves it.</DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-2">
          <span className="text-sm font-medium" id={`${ids}-engine`}>
            Engine
          </span>
          <ToggleGroup
            aria-labelledby={`${ids}-engine`}
            variant="outline"
            size="sm"
            spacing={0}
            value={[engine]}
            onValueChange={(picked: string[]) => {
              const next = engines.find((e) => e.name === picked[0] && e.reason === null);
              if (next !== undefined) setEngine(next.name);
            }}
          >
            {engines.map((e) => (
              <ToggleGroupItem key={e.name} value={e.name} disabled={e.reason !== null}>
                {e.name}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
          {unavailable.map((e) => (
            <p key={e.name} className="text-xs text-muted-foreground" data-unavailable={e.name}>
              {e.name} cannot run here: {e.reason}
            </p>
          ))}
        </div>

        <div className="flex flex-col gap-2">
          <Label htmlFor={`${ids}-model`}>Model</Label>
          <Input
            id={`${ids}-model`}
            value={model}
            onChange={(event) => setModels({ ...models, [engine]: event.target.value })}
            spellCheck={false}
          />
        </div>

        {whisper && (
          <>
            <div className="flex flex-col gap-2">
              <Label htmlFor={`${ids}-language`}>Language</Label>
              <Input
                id={`${ids}-language`}
                value={language}
                placeholder="detected"
                onChange={(event) => setLanguage(event.target.value)}
                spellCheck={false}
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor={`${ids}-prompt`}>Prompt</Label>
              <Textarea
                id={`${ids}-prompt`}
                value={prompt}
                onChange={(event) => setPrompt(event.target.value)}
              />
            </div>
            <Toggle id={`${ids}-roman`} label="Roman Urdu" checked={romanUrdu} onChange={setRomanUrdu} />
            {!romanUrdu && (
              <p className="text-xs text-muted-foreground">
                whisper reports no progress until it is done. With Roman Urdu it reports every
                two minutes of audio.
              </p>
            )}
          </>
        )}

        <Toggle id={`${ids}-diarize`} label="Label speakers" checked={diarize} onChange={setDiarize} />
        {diarize && (
          <Toggle
            id={`${ids}-require`}
            label="Fail if speakers cannot be labelled"
            checked={requireDiarize}
            onChange={setRequireDiarize}
          />
        )}
        <Toggle
          id={`${ids}-over`}
          label="Start over, not from where an earlier run stopped"
          checked={startOver}
          onChange={setStartOver}
        />

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={start} disabled={sending || chosen?.reason !== null}>
            Start
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Toggle({
  id,
  label,
  checked,
  onChange,
}: {
  id: string;
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <Switch id={id} checked={checked} onCheckedChange={(next: boolean) => onChange(next)} />
      <Label htmlFor={id}>{label}</Label>
    </div>
  );
}
