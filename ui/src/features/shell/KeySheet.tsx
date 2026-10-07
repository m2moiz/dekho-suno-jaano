import { useSyncExternalStore } from "react";

import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { DropdownMenuItem, DropdownMenuSeparator } from "@/components/ui/dropdown-menu";
import { Kbd } from "@/components/ui/kbd";
import type { Sheet } from "./keys";

// The sheet on show, if any: module state, as the error dialog's is, so the
// `?` key, Ctrl+/ in Review and the settings menu all open the one sheet.
let shown: Sheet | null = null;
const listeners = new Set<() => void>();

function emit(): void {
  for (const listener of listeners) listener();
}

export function showKeys(sheet: Sheet): void {
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
      <DialogContent className="sm:max-w-lg" aria-label="Keys">
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
export function KeysItem({ sheet }: { sheet: Sheet }) {
  return (
    <>
      <DropdownMenuSeparator />
      <DropdownMenuItem onClick={() => showKeys(sheet)}>
        Keys
        <Kbd className="ml-auto">?</Kbd>
      </DropdownMenuItem>
    </>
  );
}
