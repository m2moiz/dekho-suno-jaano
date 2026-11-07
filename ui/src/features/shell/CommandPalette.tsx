// The command palette behind ⌘K / Ctrl+K (#88): the same list of keys the `?`
// sheet shows, as a searchable list a person can run from. Both read one
// registry (features/shell/keys.ts), so a key added there appears in both
// without touching either. A key whose command the page has not handed over
// (one another component binds, like the unsure-word arrows) is listed and
// says to press it, so the list is still complete.
//
// Module state, as the key sheet's: one palette for the page, opened from a
// key handler that is not inside React's tree.

import { useEffect, useId, useState, useSyncExternalStore } from "react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Kbd } from "@/components/ui/kbd";

import type { Key, Sheet } from "./keys";

/** What the palette can run: the commands of a sheet's keys, by the key's id. */
export type Runners = Readonly<Record<string, () => void>>;

type Shown = { sheet: Sheet; runners: Runners };

let shown: Shown | null = null;
const listeners = new Set<() => void>();

function emit(): void {
  for (const listener of listeners) listener();
}

/** Open the palette on `sheet`, running a chosen key through `runners`. */
export function showCommands(sheet: Sheet, runners: Runners): void {
  shown = { sheet, runners };
  emit();
}

export function hideCommands(): void {
  shown = null;
  emit();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The keys of `sheet` whose label mentions every word of `query`. */
export function matching(sheet: Sheet, query: string): readonly Key[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  return sheet.keys.filter((key) => {
    const text = `${key.does} ${key.keys.join(" ")}`.toLowerCase();
    return words.every((word) => text.includes(word));
  });
}

export function CommandPalette() {
  const current = useSyncExternalStore(subscribe, () => shown);
  const [query, setQuery] = useState("");
  const ids = useId();
  useEffect(() => {
    if (current !== null) setQuery("");
  }, [current]);
  if (current === null) return null;
  const { sheet, runners } = current;
  const listed = matching(sheet, query);
  const run = (key: Key) => {
    const runner = key.id === undefined ? undefined : runners[key.id];
    if (runner === undefined) return;
    hideCommands();
    runner();
  };
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) hideCommands();
      }}
    >
      <DialogContent className="sm:max-w-lg" aria-label="Commands">
        <DialogHeader>
          <DialogTitle>Commands</DialogTitle>
          <DialogDescription className="sr-only">Every key this page answers; pick one to run it.</DialogDescription>
        </DialogHeader>
        <Input
          id={`${ids}-query`}
          aria-label="Find a command"
          placeholder="Type to find a command"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && listed[0] !== undefined) {
              event.preventDefault();
              run(listed[0]);
            }
          }}
          autoFocus
        />
        <ul className="flex max-h-80 flex-col gap-1 overflow-y-auto" aria-label="Commands">
          {listed.map((key) => {
            const runnable = key.id !== undefined && runners[key.id] !== undefined;
            return (
              <li key={`${key.keys.join("+")} ${key.does}`}>
                <Button
                  variant="ghost"
                  className="h-auto w-full justify-between gap-3 py-2 text-left whitespace-normal"
                  disabled={!runnable}
                  title={runnable ? undefined : "Press the key itself"}
                  onClick={() => run(key)}
                >
                  <span>{key.does}</span>
                  <span className="flex shrink-0 gap-1">
                    {key.keys.map((k) => (
                      <Kbd key={k}>{k}</Kbd>
                    ))}
                  </span>
                </Button>
              </li>
            );
          })}
          {listed.length === 0 && <li className="text-sm text-muted-foreground">Nothing matches.</li>}
        </ul>
      </DialogContent>
    </Dialog>
  );
}
