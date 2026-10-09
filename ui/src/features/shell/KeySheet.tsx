import { XIcon } from "lucide-react";
import { useSyncExternalStore } from "react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DropdownMenuItem, DropdownMenuSeparator } from "@/components/ui/dropdown-menu";
import { Kbd } from "@/components/ui/kbd";
import { TOUCH, useMediaQuery } from "@/lib/media";
import type { Sheet } from "./keys";

// The sheet on show, if any: module state, as the error dialog's is, so the
// `?` key, Ctrl+/ in Review and the settings menu all open the one sheet.
let shown: Sheet | null = null;
// Where the focus was when the sheet opened, to go back to when it closes.
let returnTo: HTMLElement | null = null;
const listeners = new Set<() => void>();

function emit(): void {
  for (const listener of listeners) listener();
}

/**
 * Open `sheet`. The focus leaves where it was at once, before the sheet has
 * drawn and taken it: in Chromium a key pressed in that moment (Esc, say)
 * still reached Review's box behind the sheet, and left Review (UAT 8 Oct,
 * finding 4, about 1 in 3). Closing the sheet puts the focus back.
 */
export function showKeys(sheet: Sheet): void {
  const active = document.activeElement;
  if (active instanceof HTMLElement && active !== document.body && active.closest("[role=dialog]") === null) {
    returnTo = active;
    active.blur();
  }
  shown = sheet;
  emit();
}

export function hideKeys(): void {
  shown = null;
  emit();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The key sheet, mounted once by App. */
export function KeySheet() {
  const sheet = useSyncExternalStore(subscribe, () => shown);
  if (sheet === null) return null;
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) hideKeys();
      }}
    >
      <DialogContent
        className="sm:max-w-lg"
        aria-label="Keys"
        showCloseButton={false}
        finalFocus={() => {
          const back = returnTo;
          returnTo = null;
          return back?.isConnected ? back : true;
        }}
      >
        {/* The primitive's own close is 28 px; this one is 44 on a phone (F15). */}
        <DialogClose render={<Button variant="ghost" size="icon" className="absolute top-2 right-2 size-11 sm:size-7" />}>
          <XIcon aria-hidden />
          <span className="sr-only">Close</span>
        </DialogClose>
        <DialogHeader>
          <DialogTitle>{sheet.title}</DialogTitle>
          <DialogDescription className="sr-only">Every key this page answers.</DialogDescription>
        </DialogHeader>
        <table className="w-full text-sm">
          <tbody>
            {sheet.keys.map((key) => (
              <tr key={key.does} className="border-b border-border/60 last:border-0">
                <td className="py-1.5 pr-4 whitespace-nowrap">
                  {key.keys.map((k) => (
                    <Kbd key={k} className="mr-1">
                      {k}
                    </Kbd>
                  ))}
                </td>
                <td className="py-1.5">{key.does}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {sheet.notes.map((note) => (
          <p key={note} className="text-sm text-muted-foreground">
            {note}
          </p>
        ))}
      </DialogContent>
    </Dialog>
  );
}

/** "Keys" in the settings menu, for the page's own sheet. */
export function KeysItem({ sheet, shortcut = "?" }: { sheet: Sheet; shortcut?: string }) {
  // 44 px where the page has its touch layout, as the menu's other items (F15).
  const tall = useMediaQuery(TOUCH);
  return (
    <>
      <DropdownMenuSeparator />
      <DropdownMenuItem className={tall ? "min-h-11" : undefined} onClick={() => showKeys(sheet)}>
        Keys
        <Kbd className="ml-auto">{shortcut}</Kbd>
      </DropdownMenuItem>
    </>
  );
}
