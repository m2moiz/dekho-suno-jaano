// Starts the real `dsj ui --print-url` once for the whole run, so the browsers
// load exactly what a person gets: the committed build, from the Python server,
// on the port the kernel picked. Not Vite's dev server, which is a different
// thing to test.
import { type ChildProcess, spawn } from "node:child_process";
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
  const server = spawn("uv", ["run", "dsj", "ui", "--print-url"], {
    cwd: REPO,
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
  };
}
