// Reviewing the words to bleep in the app (#84), in real chromium and
// Playwright's webkit, against the real `dsj ui`: a word added from the app
// lands in the user's list (a temp file, global-setup.ts), the next pass
// matches it, and playing over it is silent exactly where a render would be,
// fading in and out as a render does (#225).
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, type Page, test } from "@playwright/test";

import { editableTranscript, painted } from "./editable.ts";
import { readerUrl, scratchDir, seed } from "./seed.ts";

// Where "foxtrot" is in the transcript below (editable.ts spaces the words),
// and the span dsj.hatao.spans_to_mute makes of it: 0.1 s either side.
const FOXTROT = { start: 3.2, end: 3.55 };
const SPAN = { start: 3.1, end: 3.65 };
// One frame at 60 Hz, the most WebKit's frame-by-frame mute may run late or early by.
const FRAME_S = 1 / 60;
// dsj/media.py MUTE_FADE_S: the half-way point of each fade is this far outside the span.
const HALF_FADE_S = 0.0025;
// Where the tone below steps from half height to a quarter, and back.
const STEPS = { down: 2.5, up: 4.5 };

/**
 * 8 s of a 440 Hz sine at half height, a quarter from STEPS.down to STEPS.up,
 * so where the sound steps tells where in the recording it is.
 */
function steppedTone(dir: string): string {
  const file = path.join(dir, "stepped.wav");
  const level = `if(between(t\\,${STEPS.down}\\,${STEPS.up})\\,0.25\\,0.5)`;
  const run = spawnSync(
    "ffmpeg",
    ["-y", "-loglevel", "error", "-f", "lavfi", "-i", `aevalsrc=exprs=sin(2*PI*440*t)*${level}:s=48000:d=8`, file],
    { encoding: "utf8" },
  );
  if (run.status !== 0) throw new Error(`ffmpeg could not write ${file}: ${run.stderr}`);
  return file;
}

// Before the page loads: every sample the page sends to the speakers, with the
// audio clock's time it plays at, read off between the last node and them.
function tapTheSpeakers(): void {
  const w = window as unknown as { heard: [number, Float32Array][]; rate: number };
  w.heard = [];
  const connect = AudioNode.prototype.connect;
  let tapped = false;
  AudioNode.prototype.connect = function (this: AudioNode, target: AudioNode | AudioParam, ...rest: number[]) {
    if (target instanceof AudioDestinationNode && !tapped) {
      tapped = true;
      w.rate = this.context.sampleRate;
      const tap = (this.context as AudioContext).createScriptProcessor(2048, 1, 1);
      tap.onaudioprocess = (e) => w.heard.push([e.playbackTime, Float32Array.from(e.inputBuffer.getChannelData(0))]);
      (connect as (t: AudioNode) => AudioNode).call(this, tap);
      (connect as (t: AudioNode) => AudioNode).call(tap, target);
    }
    return (connect as (t: AudioNode | AudioParam, ...r: number[]) => AudioNode).call(this, target, ...rest);
  } as typeof AudioNode.prototype.connect;
}

/**
 * In what the page sent to the speakers (tapTheSpeakers), each fade's middle
 * lands within 2 ms of a render's, measured from the tone's step nearer it,
 * and the sound between the fades is exact silence.
 */
async function expectFadesWhereARenderPutsThem(page: Page, project: string): Promise<void> {
  // On the audio clock: where the tone steps down and up, where each fade is
  // half way, and the loudest sample between the fades.
  const heard = await page.evaluate(() => {
    const { heard, rate } = window as unknown as { heard: [number, Float32Array][]; rate: number };
    const first = heard[0]?.[0] ?? 0;
    const all = new Float32Array(heard.reduce((n, [, d]) => n + d.length, 0));
    let at = 0;
    for (const [, d] of heard) {
      all.set(d, at);
      at += d.length;
    }
    // The height of the sine: the loudest sample in 1.5 ms (more than one crest), every 0.25 ms.
    const width = Math.round(0.0015 * rate);
    const step = Math.round(0.00025 * rate);
    const level: [number, number][] = [];
    for (let i = 0; i + width <= all.length; i += step) {
      let top = 0;
      for (let j = i; j < i + width; j++) top = Math.max(top, Math.abs(all[j] ?? 0));
      level.push([first + (i + width / 2) / rate, top]);
    }
    const crossing = (after: number, height: number, down: boolean): number => {
      for (let i = 1; i < level.length; i++) {
        const [ta, a] = level[i - 1] as [number, number];
        const [tb, b] = level[i] as [number, number];
        if (ta < after) continue;
        if (down ? a >= height && b < height : a < height && b >= height) return ta + ((tb - ta) * (a - height)) / (a - b);
      }
      return Number.NaN;
    };
    const playing = level.find(([, top]) => top > 0.4)?.[0] ?? Number.NaN;
    const down = crossing(playing, 0.375, true);
    const out = crossing(down + 0.05, 0.125, true);
    const back = crossing(out + 0.05, 0.125, false);
    const up = crossing(back + 0.05, 0.375, false);
    let loudest = 0;
    for (const [t, top] of level) if (t > out + 0.003 && t < back - 0.003) loudest = Math.max(loudest, top);
    return { down, out, back, up, loudest };
  });
  // Each fade's middle against the step nearer it, in ms: 0 is where a render puts it.
  const outLate = (heard.out - heard.down - (SPAN.start - HALF_FADE_S - STEPS.down)) * 1000;
  const backLate = (heard.back - heard.up - (SPAN.end + HALF_FADE_S - STEPS.up)) * 1000;
  console.log(
    `${project}: fade out ${outLate.toFixed(2)} ms and fade in ${backLate.toFixed(2)} ms from a render's; ` +
      `loudest between ${heard.loudest}`,
  );
  expect(Math.abs(outLate)).toBeLessThan(2);
  expect(Math.abs(backLate)).toBeLessThan(2);
  expect(heard.loudest).toBe(0);
}

test("a word added from the app is matched, muted live where a render mutes, and undone", async ({ page }, info) => {
  // The run's one word list is shared by every browser's run of this test, so
  // each adds a word of its own, which no other transcript holds.
  const word = `foxtrot${info.project.name}`;
  const dir = scratchDir();
  await page.addInitScript(tapTheSpeakers);
  const seeded = seed(
    editableTranscript(steppedTone(dir), [
      ["alpha", "bravo", "charlie", "delta"],
      ["echo", word, "golf", "hotel"],
    ]),
    dir,
  );
  await page.goto(readerUrl(seeded));
  const panel = page.getByRole("region", { name: "Words to bleep" });
  await expect(panel.getByRole("status")).toContainText("No word matched: 8 words searched");

  await panel.getByRole("textbox", { name: "A word to add to your list" }).fill(word);
  await panel.getByRole("button", { name: "Add" }).click();
  const row = panel.getByRole("listitem", { name: word });
  await expect(row).toContainText("0:03.2");
  await expect(row).toContainText(`user:${word}`);
  await expect(row).toContainText("muted");
  await expect.poll(() => painted(page, "dsj-muted")).toEqual([word]);
  expect(readFileSync(process.env["DSJ_WORDS"] ?? "", "utf8")).toContain(`roman = ["${word}"]`);
  await expect(page.getByRole("toolbar", { name: "Edit" }).getByRole("status")).toHaveText("Saved");

  // Every frame, the time and whether the sound is off, while the match is auditioned.
  await page.evaluate(() => {
    const audio = document.querySelector("audio") as HTMLAudioElement;
    const samples: [number, boolean][] = [];
    (window as unknown as { samples: typeof samples }).samples = samples;
    const look = () => {
      if (!audio.paused) samples.push([audio.currentTime, audio.muted]);
      requestAnimationFrame(look);
    };
    requestAnimationFrame(look);
  });
  await row.getByRole("button", { name: "Hear" }).click();
  // Played from a second before the word, and stopped a second after it.
  await expect
    .poll(() => page.evaluate(() => (document.querySelector("audio") as HTMLAudioElement).paused), { timeout: 8000 })
    .toBe(true);
  const stoppedAt = await page.evaluate(() => (document.querySelector("audio") as HTMLAudioElement).currentTime);
  expect(stoppedAt).toBeGreaterThanOrEqual(FOXTROT.end + 1);
  expect(stoppedAt).toBeLessThan(FOXTROT.end + 1.2);
  const samples = await page.evaluate(() => (window as unknown as { samples: [number, boolean][] }).samples);
  expect(samples[0]?.[0] ?? 0).toBeLessThan(FOXTROT.start - 0.9);

  if (info.project.name === "webkit") {
    // WebKit's sound runs ahead of its clock in Web Audio (liveMute.ts,
    // fadesInWebAudio), so there the element is muted a frame at a time, as
    // before #225: muted all through the span, and only there.
    const silent = samples.filter(([, muted]) => muted).map(([t]) => t);
    console.log(
      `webkit: ${samples.length} frames, muted from ${Math.min(...silent).toFixed(3)} to ` +
        `${Math.max(...silent).toFixed(3)} s against the span ${SPAN.start} to ${SPAN.end} s`,
    );
    const inside = samples.filter(([t]) => t > SPAN.start + FRAME_S && t < SPAN.end - FRAME_S);
    const outside = samples.filter(([t]) => t < SPAN.start - 2 * FRAME_S || t > SPAN.end + 2 * FRAME_S);
    expect(inside.length).toBeGreaterThan(10);
    expect(inside.every(([, muted]) => muted)).toBe(true);
    expect(outside.length).toBeGreaterThan(60);
    expect(outside.every(([, muted]) => !muted)).toBe(true);
  } else {
    await expectFadesWhereARenderPutsThem(page, info.project.name);
    // The gain does the muting; the element's own mute is the person's alone.
    expect(samples.every(([, muted]) => !muted)).toBe(true);
  }

  // Dismissed, it plays; one undo mutes it again.
  await row.getByRole("button", { name: "Dismiss" }).click();
  await expect(row).toContainText("dismissed");
  await expect.poll(() => painted(page, "dsj-muted")).toEqual([]);
  await page.keyboard.press("ControlOrMeta+z");
  await expect(row).toContainText("muted");
  await expect.poll(() => painted(page, "dsj-muted")).toEqual([word]);
});
