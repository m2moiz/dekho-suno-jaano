import { Trash2 } from "lucide-react";
import type { RefObject } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { durationLabel } from "@/features/library/describe";
import type { PlayerControls } from "@/features/player/Player";
import { MARK_KINDS, type MarkKind, markKind } from "@/registries/markKinds";
import type { Marks } from "./marks";

type Props = {
  marks: Marks;
  controls: RefObject<PlayerControls | null>;
  onError: (thrown: unknown, route: string) => void;
};

/**
 * Every mark on the recording (#67), in its order: when, which kind, the
 * words under it, and a note to type. A mark's time plays it; a mark can
 * change kind or go. Marks are the recording's, so they are here on every
 * transcript of it, and tomorrow.
 */
export function MarksPanel({ marks, controls, onError }: Props) {
  if (marks.list.length === 0) {
    return <p className="text-sm text-muted-foreground">No marks yet. Select words in the transcript and choose Mark.</p>;
  }
  return (
    <ul aria-label="Marks" className="flex flex-col divide-y divide-border">
      {marks.list.map((mark) => {
        const kind = markKind(mark.kind);
        return (
          <li key={mark.id} className="flex flex-col gap-2 py-3">
            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                className="h-9 px-2 font-mono text-sm tabular-nums"
                aria-label={`Play from ${durationLabel(mark.start_s) ?? "0:00"}`}
                onClick={() => controls.current?.hear(Math.max(0, mark.start_s - 0.3), mark.end_s + 0.3)}
              >
                {durationLabel(mark.start_s) ?? "0:00"}
              </Button>
              <span aria-hidden className="inline-block size-3 rounded-sm" style={{ background: kind.swatch }} />
              <select
                aria-label="Kind"
                className="h-9 rounded-md border border-input bg-background px-2 text-sm"
                value={mark.kind}
                onChange={(event) => {
                  marks.change(mark.id, { kind: event.target.value as MarkKind }).catch((thrown: unknown) => onError(thrown, `/api/highlights/${mark.id}`));
                }}
              >
                {MARK_KINDS.map((k) => (
                  <option key={k.id} value={k.id}>
                    {k.label}
                  </option>
                ))}
              </select>
              <Button
                variant="ghost"
                size="icon"
                className="ml-auto size-9"
                aria-label="Remove mark"
                onClick={() => {
                  marks.remove(mark.id).catch((thrown: unknown) => onError(thrown, `/api/highlights/${mark.id}`));
                }}
              >
                <Trash2 aria-hidden className="size-4" />
              </Button>
            </div>
            {mark.text !== "" && (
              <p dir="auto" className="text-sm select-text">
                {mark.text}
              </p>
            )}
            <Input
              aria-label="Note"
              placeholder="Note"
              defaultValue={mark.note}
              dir="auto"
              className="h-9"
              onBlur={(event) => {
                const note = event.currentTarget.value;
                if (note !== mark.note) marks.change(mark.id, { note }).catch((thrown: unknown) => onError(thrown, `/api/highlights/${mark.id}`));
              }}
            />
          </li>
        );
      })}
    </ul>
  );
}
