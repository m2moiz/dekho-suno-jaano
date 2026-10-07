import { X } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Sheet, SheetClose, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { TOUCH, useMediaQuery } from "@/lib/media";

/**
 * Bleeping, out of the reader's way (Hashiya spec, Reader: "a drawer from the
 * right, a bottom sheet on the phone"; critique: "~350 px of tools before the
 * first word").
 */
export function BleepDrawer({ open, onOpenChange, children }: { open: boolean; onOpenChange: (open: boolean) => void; children: ReactNode }) {
  const touch = useMediaQuery(TOUCH);
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side={touch ? "bottom" : "right"}
        showCloseButton={false}
        className={touch ? "max-h-[85dvh] overflow-y-auto" : "overflow-y-auto data-[side=right]:sm:max-w-xl"}
      >
        <SheetHeader className="pr-14">
          <SheetTitle>Bleep</SheetTitle>
          <SheetDescription>
            Words your lists match, muted as a render would mute them. Muting is an edit: Cmd+Z takes it back, and the recording is never changed.
          </SheetDescription>
        </SheetHeader>
        {/* The sheet's own close button is 28 px; this one is the 44 px a thumb needs (F15). */}
        <SheetClose
          render={<Button variant="ghost" size="icon" className="absolute top-2 right-2 size-11" />}
        >
          <X aria-hidden />
          <span className="sr-only">Close</span>
        </SheetClose>
        <div className="px-4 pb-6">{children}</div>
      </SheetContent>
    </Sheet>
  );
}
