// A `dsj ui` of a spec's own, on a library of its own: for a journey that has
// to quit the app and start it again (#158), which the one server
// global-setup.ts starts for the whole run cannot do.
import { type ChildProcess, spawn } from "node:child_process";
import path from "node:path";
import { createInterface } from "node:readline";

const REPO = path.resolve(import.meta.dirname, "../../..");

// `exited` settles when the process ends, however it ends: stopped, or stopping itself.
export type Server = { url: string; stop: () => Promise<void>; exited: Promise<void> };

function firstLine(child: ChildProcess): Promise<string> {
  return new Promise((resolve, reject) => {
    if (child.stdout === null) {
      reject(new Error("dsj ui was started without a stdout pipe"));
      return;
    }
    createInterface({ input: child.stdout }).once("line", resolve);
    child.once("exit", (code) => reject(new Error(`dsj ui exited (${code}) before printing its URL`)));
  });
}

/** Start `dsj ui --print-url` on `library` and wait for the address it prints. */
export async function startUi(library: string): Promise<Server> {
  const child = spawn("uv", ["run", "dsj", "ui", "--print-url"], {
    cwd: REPO,
    env: { ...process.env, DSJ_LIBRARY: library },
    stdio: ["ignore", "pipe", "inherit"],
  });
  const url = await firstLine(child);
  const exited = new Promise<void>((resolve) => child.once("exit", () => resolve()));
  return {
    url,
    exited,
    // Quit it, as Ctrl-C does, and wait until it has let go of its port and lock.
    stop: async () => {
      if (child.exitCode === null && child.signalCode === null) child.kill("SIGTERM");
      await exited;
    },
  };
}
