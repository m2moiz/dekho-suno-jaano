// Who a speaker is on the page: their name and their colour (Hashiya spec,
// "a fixed nameplate and colour per speaker"). The colour follows the
// speaker's place in the transcript's list, so speaker 1 is the same blue in
// every turn and every page; sub-project D later ties it to a person.

import { speakerName } from "./document";

/** Names a person gave the speakers, by label (Task 5 saves them in the edit list). */
export type Names = Readonly<Record<string, string>>;

export const NO_NAMES: Names = Object.freeze({});

/** `var(--speaker-n)` for the speaker at `index`, cycling through the six. */
export function speakerColour(index: number | null): string | undefined {
  return index === null || index < 0 ? undefined : `var(--speaker-${(index % 6) + 1})`;
}

/** The name a person gave the speaker, else "Speaker n" for a diarizer's label, else the label. */
export function displayName(speakers: readonly string[], names: Names, index: number | null): string | null {
  if (index === null) return null;
  const label = speakers[index];
  if (label === undefined) return null;
  return names[label] ?? speakerName([...speakers], index);
}
