import { X } from "lucide-react";
import type { ReactNode, RefObject } from "react";

import { Button } from "@/components/ui/button";
import { Sheet, SheetClose, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { TOUCH, useMediaQuery } from "@/lib/media";

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Where focus goes when the drawer closes: the menu button that opened it. */
  returnFocus: RefObject<HTMLElement | null>;
  children: ReactNode;
};

/**
 * Bleeping, out of the reader's way (Hashiya spec, Reader: "a drawer from the
 * right, a bottom sheet on the phone"; critique: "~350 px of tools before the
 * first word").
 *
 * On the laptop it is non-modal: the transcript stays legible and in reach
 * beside it, so Hear plays against visible text and the bar's Saved and Undo
 * stay available to assistive tech, and a click on the transcript does not
 * close it. On the phone it is a modal bottom sheet over a flat dim, with
 * focus held inside it; its header stays put and its list scrolls.
 */
export function BleepDrawer({ open, onOpenChange, returnFocus, children }: Props) {
  const touch = useMediaQuery(TOUCH);
  return (
    <Sheet open={open} onOpenChange={onOpenChange} modal={touch} disablePointerDismissal={!touch}>
      <SheetContent
        side={touch ? "bottom" : "right"}
        showCloseButton={false}
        overlay={touch}
        overlayClassName="bg-black/40 supports-backdrop-filter:backdrop-blur-none"
        finalFocus={returnFocus}
        className={touch ? "max-h-[60dvh] overflow-hidden" : "overflow-hidden data-[side=right]:sm:max-w-xl"}
      >
        <SheetHeader className="shrink-0 pr-14">
          <SheetTitle>Bleep</SheetTitle>
          <SheetDescription>
            Words your lists match, muted as a render would mute them. Muting is an edit: Cmd+Z takes it back, and the recording is never changed.
          </SheetDescription>
        </SheetHeader>
        {/* The sheet's own close button is 28 px; this one is the 44 px a thumb needs (F15). */}
        <SheetClose render={<Button variant="ghost" size="icon" className="absolute top-2 right-2 size-11" />}>
          <X aria-hidden />
          <span className="sr-only">Close</span>
        </SheetClose>
        {/* The list scrolls here, so the header and Close stay in sight. */}
        <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-6">{children}</div>
      </SheetContent>
    </Sheet>
  );
}
