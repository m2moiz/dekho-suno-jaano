// The app's own settings, kept between launches by the server (#69): one
// file beside the library, read through GET /api/settings and changed through
// PUT. A cookie would do for a choice the page needs before any request (the
// theme, the speed); these are read when a dialog opens, so they live where
// `dsj ui` keeps everything else, with a version number and migrations
// (dsj/ui/settings.py).

import { api } from "@/api/client";
import type { components } from "@/api/schema";

export type Settings = components["schemas"]["Settings"];
export type SettingsUpdate = components["schemas"]["SettingsUpdate"];

/** What a fresh install starts from, and what the page uses when the server cannot be asked. */
export const DEFAULTS: Settings = { version: 1, transcribe_answer: "mixed", transcribe_diarize: true };

/** The settings as the server keeps them; the defaults when it could not be asked. */
export async function loadSettings(): Promise<Settings> {
  const { data } = await api.GET("/api/settings").catch(() => ({ data: undefined }));
  return data ?? DEFAULTS;
}

/**
 * Keep `changes` for the next launch. A failure is logged and not shown:
 * the run the person asked for matters more than remembering its answer.
 */
export async function saveSettings(changes: SettingsUpdate): Promise<void> {
  const { error } = await api.PUT("/api/settings", { body: changes }).catch(() => ({ error: "unreachable" }));
  if (error !== undefined) console.warn("dsj ui could not keep the settings", error);
}
