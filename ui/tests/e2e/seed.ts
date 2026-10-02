// Puts a transcript into the library the run's `dsj ui` serves, the way the
// app's own adoption does it (dsj/ui/store.py, Library.adopt), and says how to
// open it. global-setup.ts points DSJ_LIBRARY at a temporary file, so nothing
// here touches the owner's library.
import { spawnSync } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

const REPO = path.resolve(import.meta.dirname, "../../..");

const ADOPT = `
import json, sys
from pathlib import Path
from dsj.ui.store import Library
with Library.open() as library:
    adoption = library.adopt([Path(sys.argv[1])])
    if adoption.refused:
        sys.exit(f"refused: {adoption.refused}")
    found = library.transcript(adoption.transcripts[0])
    print(json.dumps({"recording": found.recording_id, "transcript": found.id}))
`;

export type Seeded = { recording: number; transcript: number; dir: string };

function env(name: string): string {
  const value = process.env[name];
  if (value === undefined) {
    throw new Error(`${name} is unset: run through \`just ui-e2e\` or \`just ui-perf\`, whose global setup sets it`);
  }
  return value;
}

/** A fresh directory for one test's files, under the system's temp folder. */
export function scratchDir(): string {
  return mkdtempSync(path.join(tmpdir(), "dsj-e2e-seed-"));
}

/** Write `transcript` as JSON in `dir`, adopt it, and return its ids. */
export function seed(transcript: object, dir: string = scratchDir()): Seeded {
  const file = path.join(dir, "transcript.json");
  writeFileSync(file, JSON.stringify(transcript));
  const run = spawnSync("uv", ["run", "python", "-c", ADOPT, file], {
    cwd: REPO,
    env: { ...process.env, DSJ_LIBRARY: env("DSJ_LIBRARY") },
    encoding: "utf8",
  });
  if (run.status !== 0) throw new Error(`adopting ${file} failed: ${run.stderr}`);
  return { ...(JSON.parse(run.stdout) as { recording: number; transcript: number }), dir };
}

/** The address of a seeded transcript's page, token included. */
export function readerUrl(seeded: Seeded): string {
  const url = new URL(env("DSJ_UI_URL"));
  url.search = `?recording=${seeded.recording}&transcript=${seeded.transcript}`;
  return url.toString();
}

/** A tone of `seconds`, made by ffmpeg in `dir`, for a transcript to point at. */
export function tone(dir: string, seconds: number, name = "tone.wav"): string {
  const file = path.join(dir, name);
  const run = spawnSync(
    "ffmpeg",
    ["-y", "-loglevel", "error", "-f", "lavfi", "-i", `sine=frequency=440:duration=${seconds}`, file],
    { encoding: "utf8" },
  );
  if (run.status !== 0) throw new Error(`ffmpeg could not write ${file}: ${run.stderr}`);
  return file;
}
