import { type FormEvent, useState } from "react";
import { createPortal } from "react-dom";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { langOf } from "@/lib/script";
import type { Box } from "./SelectionToolbar";

// Wide enough for Hear, the hint, Cancel and Save on one line; at 260 px the
// hint wrapped to four lines (`uv run python scratch/ui_shots.py --label t3
// reader-correct`, 1440x900). Its edge is the card's: the field inside carries
// the gold focus ring, and a gold box round it drew two gold lines.
const MIN_WIDTH_PX = 360;

type Props = {
  /** The words as they read now. */
  heard: string;
  /** The words' box when Correct was pressed, and the paragraph whose face the field takes. */
  box: Box;
  paragraph: HTMLElement;
  onSave: (text: string) => void;
  onCancel: () => void;
  onHear: () => void;
};

/**
 * Correct in place (Hashiya spec, Reader: "Correct (edits in place, no
 * modal)"; critique: "Correct is a modal, Timing inline"). A field laid over
 * the selected words in the paragraph's own face and size, with the words in
 * it, so retyping reads like typing on the page. The words keep the same
 * stretch of the recording (#83); an emptied field leaves it as audio with no
 * words. Enter saves, Esc cancels; Hear plays the stretch with 0.3 s either side.
 */
export function InlineCorrect({ heard, box, paragraph, onSave, onCancel, onHear }: Props) {
  const [text, setText] = useState(heard);
  const face = getComputedStyle(paragraph);
  // Room for the buttons and the one-line hint beside them, or the window less its edges.
  const width = Math.min(Math.max(box.width + 64, MIN_WIDTH_PX), window.innerWidth - 16);
  const left = Math.min(Math.max(window.scrollX + 8, box.left + window.scrollX - 8), window.scrollX + window.innerWidth - width - 8);
  const top = box.top + window.scrollY - 6;
  const unchanged = text.trim() === heard.trim();
  const save = (event: FormEvent) => {
    event.preventDefault();
    if (unchanged) onCancel();
    else onSave(text);
  };
  return createPortal(
    <form
      aria-label="Correct"
      className="absolute z-40 flex flex-col gap-1.5 rounded-lg border bg-card p-1.5 text-card-foreground shadow-lg shadow-black/15"
      style={{ top, left, width }}
      onSubmit={save}
    >
      <Input
        aria-label="What was said"
        autoFocus
        dir="auto"
        lang={langOf(text)}
        value={text}
        spellCheck={false}
        onFocus={(event) => event.currentTarget.select()}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            onCancel();
          }
        }}
        className="h-auto rounded-md bg-background px-2 py-1 text-foreground dark:bg-background"
        style={{ fontFamily: face.fontFamily, fontSize: face.fontSize, lineHeight: face.lineHeight }}
      />
      {/* 44 px targets on a phone (Hashiya spec, "Laptop and phone"), 36 on a laptop. */}
      <div className="flex items-center gap-1">
        <Button type="button" variant="ghost" size="sm" className="h-11 sm:h-9" onClick={onHear}>
          Hear
        </Button>
        <span className="ml-1 hidden text-xs whitespace-nowrap text-muted-foreground sm:inline">Enter saves · Esc cancels</span>
        <Button type="button" variant="ghost" size="sm" className="ml-auto h-11 sm:h-9" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" size="sm" className="h-11 sm:h-9" disabled={unchanged}>
          Save
        </Button>
      </div>
    </form>,
    document.body,
  );
}
