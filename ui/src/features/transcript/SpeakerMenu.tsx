import { ChevronDown } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

/** A speaker as the menu lists them: the label the list uses, the name the page shows. */
export type SpeakerChoice = { label: string; name: string };

type Props = {
  /** The speaker of the turn this menu sits beside. */
  label: string;
  name: string;
  /** Every speaker with a turn, in the transcript's order. */
  speakers: readonly SpeakerChoice[];
  /** Give this one turn to `label`, or to a speaker nobody is yet when "new". */
  onSay: (label: string | "new") => void;
  /** Give every turn of this speaker to `into` (#71). */
  onMerge: (into: string) => void;
};

/**
 * The menu beside a nameplate (#71): who said this one turn, with a new
 * speaker on offer, and merging this speaker into another when the diarizer
 * split one person in two. Renaming stays on the nameplate itself. Each
 * choice is one edit of the list, so one Undo takes it back, and it is saved
 * the way every edit is, so it is there when the recording is opened again.
 */
export function SpeakerMenu({ label, name, speakers, onSay, onMerge }: Props) {
  const others = speakers.filter((s) => s.label !== label);
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={<Button variant="ghost" size="icon" aria-label={`${name}, speaker options`} className="size-6 shrink-0 text-muted-foreground" />}
      >
        <ChevronDown aria-hidden className="size-3.5" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="min-w-56">
        <DropdownMenuGroup>
          <DropdownMenuLabel>This turn was said by</DropdownMenuLabel>
          <DropdownMenuRadioGroup
            value={label}
            onValueChange={(picked: string) => {
              if (picked !== label) onSay(picked);
            }}
          >
            {speakers.map((s) => (
              <DropdownMenuRadioItem key={s.label} value={s.label} className="min-h-11 sm:min-h-8">
                {s.name}
              </DropdownMenuRadioItem>
            ))}
          </DropdownMenuRadioGroup>
          <DropdownMenuItem className="min-h-11 sm:min-h-8" onClick={() => onSay("new")}>
            Someone new
          </DropdownMenuItem>
        </DropdownMenuGroup>
        {others.length > 0 && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuGroup>
              <DropdownMenuLabel>Merge {name} into</DropdownMenuLabel>
              {others.map((s) => (
                <DropdownMenuItem key={s.label} className="min-h-11 sm:min-h-8" onClick={() => onMerge(s.label)}>
                  {s.name}
                </DropdownMenuItem>
              ))}
            </DropdownMenuGroup>
          </>
        )}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
