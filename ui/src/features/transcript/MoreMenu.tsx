import { Ellipsis } from "lucide-react";
import { type ReactNode, type RefObject, useState } from "react";

import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { FIELD_ICON_BUTTON } from "@/features/shell/field";
import { TOUCH, useMediaQuery } from "@/lib/media";

type Props = {
  /** How many words the lists matched; the Bleep item is badged when this is more than 0. */
  matchCount: number;
  onBleep: () => void;
  /** The one selected word Timing would open, or null when none or several are selected. */
  timingWord: number | null;
  onTiming: (word: number) => void;
  /** More items: Export (Task 6). */
  extra?: ReactNode;
  /** The More button, for the drawer to hand focus back to. */
  triggerRef?: RefObject<HTMLButtonElement | null>;
};

/** The reader's menu (Hashiya spec, Reader: "a menu with Timing, Bleep, Export"). */
export function MoreMenu({ matchCount, onBleep, timingWord, onTiming, extra, triggerRef }: Props) {
  // 44 px items where the reader has its touch layout, the same rule as the rest (F15).
  const tall = useMediaQuery(TOUCH) ? "min-h-11" : "";
  // The word Timing is for, as it was when the menu opened: WebKit clears the
  // selection on a press inside the menu, which would grey Timing out between
  // the press and the release and leave the click on nothing (measured with
  // the "reader's menu opens Timing" test in bounds.spec.ts, webkit project).
  const [offered, setOffered] = useState<number | null>(null);
  return (
    <DropdownMenu onOpenChange={(open) => open && setOffered(timingWord)}>
      <DropdownMenuTrigger
        {...(triggerRef === undefined ? {} : { ref: triggerRef })}
        render={<Button variant="ghost" size="icon" aria-label="More" className={FIELD_ICON_BUTTON} />}
      >
        <Ellipsis aria-hidden />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-60">
        <DropdownMenuItem
          className={`data-disabled:opacity-100 ${tall}`}
          disabled={offered === null}
          onClick={() => offered !== null && onTiming(offered)}
        >
          <span className={offered === null ? "text-muted-foreground" : ""}>Timing</span>
          {offered === null && <span className="ml-auto text-xs text-muted-foreground">select one word</span>}
        </DropdownMenuItem>
        <DropdownMenuItem className={tall} onClick={onBleep}>
          Bleep
          {matchCount > 0 && (
            <span className="ml-auto rounded-full bg-gold px-2 text-xs font-semibold text-primary-foreground tabular-nums">
              {matchCount}
            </span>
          )}
        </DropdownMenuItem>
        {extra}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
