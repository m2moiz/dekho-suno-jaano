// Starts the real `dsj ui --print-url` once for the whole run, so the browsers
// load exactly what a person gets: the committed build, from the Python server,
// on the port the kernel picked. Not Vite's dev server, which is a different
// thing to test.
import { type ChildProcess, spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { createInterface } from "node:readline";

const REPO = path.resolve(import.meta.dirname, "../../..");

function firstLine(child: ChildProcess): Promise<string> {
  return new Promise((resolve, reject) => {
    if (child.stdout === null) {
      reject(new Error("dsj ui was started without a stdout pipe"));
      return;
    }
    const lines = createInterface({ input: child.stdout });
    lines.once("line", resolve);
    child.once("exit", (code) => reject(new Error(`dsj ui exited (${code}) before printing its URL`)));
  });
}

export default async function globalSetup(): Promise<() => Promise<void>> {
  // A library of its own: the default one, and the ui.lock beside it, are the
  // owner's, and a test run must neither read nor lock them.
  const scratch = mkdtempSync(path.join(tmpdir(), "dsj-e2e-"));
  const library = path.join(scratch, "library.db");
  // Read by the specs that put a transcript in it (seed.ts), as DSJ_UI_URL is.
  process.env["DSJ_LIBRARY"] = library;
  // The user's own bleep list (#64), which the app writes to when a word is
  // added (#84): the owner's is in dsj's data folder, and a test never writes it.
  const words = path.join(scratch, "words.toml");
  process.env["DSJ_WORDS"] = words;
  const server = spawn("uv", ["run", "dsj", "ui", "--print-url"], {
    cwd: REPO,
    env: { ...process.env, DSJ_LIBRARY: library, DSJ_WORDS: words },
    stdio: ["ignore", "pipe", "inherit"],
  });
  const url = await firstLine(server);
  // Read by the specs. Set here, before Playwright starts its workers, which
  // inherit this process's environment.
  process.env["DSJ_UI_URL"] = url;
  return async () => {
    const exited = new Promise((resolve) => server.once("exit", resolve));
    server.kill("SIGTERM");
    await exited;
    rmSync(scratch, { recursive: true, force: true });
  };
}
