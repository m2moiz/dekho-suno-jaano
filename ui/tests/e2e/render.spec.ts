// Rendering the bleeped file from the app as a job (#215), in real chromium
// and Playwright's webkit, against the real `dsj ui` and the real ffmpeg: the
// file lands beside the recording with its log and source note, and the app
// links to it.
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { editableTranscript } from "./editable.ts";
import { readerUrl, scratchDir, seed, tone } from "./seed.ts";

test("a render from the app writes the bleeped copy beside the recording and links it", async ({ page }, info) => {
  const dir = scratchDir();
  // Words and a length of this browser's own: the run's word list and library are shared.
  const [one, two] = [`kilo${info.project.name}`, `lima${info.project.name}`];
  const seconds = 12 + info.project.name.length / 10;
  const recording = tone(dir, seconds, `render-${info.project.name}.wav`);
  const seeded = seed(editableTranscript(recording, [["alpha", one, "charlie", two]]), dir);
  await page.goto(readerUrl(seeded));
  const panel = page.getByRole("region", { name: "Words to bleep" });
  for (const word of [one, two]) {
    await panel.getByRole("textbox", { name: "A word to add to your list" }).fill(word);
    await panel.getByRole("button", { name: "Add" }).click();
    await expect(panel.getByRole("listitem", { name: word })).toContainText("muted");
  }
  await expect(page.getByRole("toolbar", { name: "Edit" }).getByRole("status")).toHaveText("Saved");
  await expect(panel).toContainText("with 2 spans silenced");

  await panel.getByRole("button", { name: "Render", exact: true }).click();
  const done = panel.getByRole("status", { name: "Rendered" });
  await expect(done).toContainText("Rendered 2 spans", { timeout: 20_000 });
  const stem = path.join(dir, `render-${info.project.name}`);
  expect(existsSync(`${stem}.bleeped.wav`)).toBe(true);
  expect(existsSync(`${stem}.bleeped.source.txt`)).toBe(true);
  const log = JSON.parse(readFileSync(`${stem}.bleeped.bleeps.json`, "utf8")) as { muted: { word: string }[] };
  expect(log.muted.map((m) => m.word)).toEqual([one, two]);
  // The link plays the file through the server, by the render's id.
  const href = await done.getByRole("link").getAttribute("href");
  const reply = await page.request.get(new URL(href ?? "", page.url()).toString());
  expect(reply.status()).toBe(200);
  expect((await reply.body()).equals(readFileSync(`${stem}.bleeped.wav`))).toBe(true);

  // One match alone: a second file, the first kept, one word muted in it.
  await panel.getByRole("listitem", { name: two }).getByRole("button", { name: "Render alone" }).click();
  await expect(done).toContainText("Rendered 1 span", { timeout: 20_000 });
  const second = JSON.parse(readFileSync(`${stem}.bleeped-2.bleeps.json`, "utf8")) as { muted: { word: string }[] };
  expect(second.muted.map((m) => m.word)).toEqual([two]);
  expect(existsSync(`${stem}.bleeped.wav`)).toBe(true);
});
