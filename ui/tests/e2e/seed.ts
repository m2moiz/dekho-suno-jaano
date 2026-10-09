// Puts a transcript into the library the run's `dsj ui` serves, the way the
// app's own adoption does it (dsj/ui/store.py, Library.adopt), and says how to
// open it. global-setup.ts points DSJ_LIBRARY at a temporary file, so nothing
// here touches the owner's library, and removes the folders made here at the end.
import { spawnSync } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
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

// The same, for a transcript a run from the app wrote: the run says its engine.
const RECORD_RUN = `
import json, sys
from pathlib import Path
from dsj.ui.store import Library
with Library.open() as library:
    found = library.record_run(Path(sys.argv[1]), engine=sys.argv[2])
    print(json.dumps({"recording": found.recording_id, "transcript": found.id}))
`;

export type Seeded = { recording: number; transcript: number; dir: string; transcriptPath: string };

function env(name: string): string {
  const value = process.env[name];
  if (value === undefined) {
    throw new Error(`${name} is unset: run through \`just ui-e2e\` or \`just ui-perf\`, whose global setup sets it`);
  }
  return value;
}

/**
 * A fresh directory for one test's files, inside the run's scratch folder,
 * which global-setup.ts removes at the end (#242).
 */
export function scratchDir(): string {
  return mkdtempSync(path.join(env("DSJ_E2E_SCRATCH"), "seed-"));
}

function put(library: string, transcript: object, dir: string, script: string, ...args: string[]): Seeded {
  // Its own name, so two transcripts can share a folder.
  const file = path.join(dir, `transcript-${(seeded += 1)}.json`);
  writeFileSync(file, JSON.stringify(transcript));
  const run = spawnSync("uv", ["run", "python", "-c", script, file, ...args], {
    cwd: REPO,
    env: { ...process.env, DSJ_LIBRARY: library },
    encoding: "utf8",
  });
  if (run.status !== 0) throw new Error(`putting ${file} in ${library} failed: ${run.stderr}`);
  return { ...(JSON.parse(run.stdout) as { recording: number; transcript: number }), dir, transcriptPath: file };
}

let seeded = 0;

/** Write `transcript` as JSON in `dir`, adopt it into the run's library, and return its ids. */
export function seed(transcript: object, dir: string = scratchDir()): Seeded {
  return put(env("DSJ_LIBRARY"), transcript, dir, ADOPT);
}

/** The same, into the library at `library`. */
export function adoptInto(library: string, transcript: object, dir: string): Seeded {
  return put(library, transcript, dir, ADOPT);
}

/** Put `transcript` into the library at `library` as a run from the app with `engine` would. */
export function recordRunInto(library: string, transcript: object, dir: string, engine: string): Seeded {
  return put(library, transcript, dir, RECORD_RUN, engine);
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

/**
 * `seconds` of ffmpeg's test card at 640x360, the shape #230 measured with,
 * and a tone: h264 and AAC in a .mov, made in `dir`.
 */
export function screenRecording(dir: string, seconds: number): string {
  const file = path.join(dir, "screen.mov");
  const run = spawnSync(
    "ffmpeg",
    [
      "-y", "-loglevel", "error",
      "-f", "lavfi", "-i", `testsrc2=size=640x360:rate=25:duration=${seconds}`,
      "-f", "lavfi", "-i", `sine=frequency=440:duration=${seconds}`,
      "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", file,
    ],
    { encoding: "utf8" },
  );
  if (run.status !== 0) throw new Error(`ffmpeg could not write ${file}: ${run.stderr}`);
  return file;
}
