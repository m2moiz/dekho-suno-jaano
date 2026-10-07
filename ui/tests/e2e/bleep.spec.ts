// Reviewing the words to bleep in the app (#84), in real chromium and
// Playwright's webkit, against the real `dsj ui`: a word added from the app
// lands in the user's list (a temp file, global-setup.ts), the next pass
// matches it, and playing over it is silent exactly where a render would be,
// fading in and out as a render does (#225).
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";

import { expect, type Locator, type Page, test } from "@playwright/test";

import { editableTranscript, openBleep, painted } from "./editable.ts";
import { readerUrl, scratchDir, seed, tone } from "./seed.ts";

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
  const panel = await openBleep(page);
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

const PHONE = 767;

for (const { width, height } of [
  { width: 1440, height: 900 },
  { width: 390, height: 844 },
]) {
  const phone = width <= PHONE;
  test(`at ${width}x${height} the drawer is a ${phone ? "modal bottom sheet" : "non-modal right drawer"}, with focus, size and badge as specified`, async ({ page }, info) => {
    const word = `sierra${width}${info.project.name}`;
    const dir = scratchDir();
    const seeded = seed(
      editableTranscript(tone(dir, 9 + width / 10000 + info.project.name.length / 10, `drawer-${width}-${info.project.name}.wav`), [
        ["alpha", "bravo", word, "delta"],
      ]),
      dir,
    );
    await page.setViewportSize({ width, height });
    await page.goto(readerUrl(seeded));
    await expect(page.locator("article")).toContainText(word);
    const more = page.getByRole("button", { name: "More" });
    const dialog = page.getByRole("dialog", { name: "Bleep" });
    const menuBleep = page.getByRole("menuitem", { name: /^Bleep/ });
    // Nothing of the panel is on the page before the menu opens it.
    await expect(page.getByRole("region", { name: "Words to bleep" })).toHaveCount(0);
    const panel = await openBleep(page);
    await panel.getByRole("textbox", { name: "A word to add to your list" }).fill(word);
    await panel.getByRole("button", { name: "Add" }).click();
    const row = panel.getByRole("listitem", { name: word });
    await expect(row).toContainText("muted");

    // Settled against the edge it slides in from, so measured after its transition.
    await expect
      .poll(async () => {
        const box = await dialog.boundingBox();
        return box === null ? null : Math.round(phone ? box.y + box.height : box.x + box.width);
      })
      .toBe(phone ? height : width);

    // No blur anywhere: a flat dim behind the phone's modal sheet, none behind the laptop's drawer.
    const overlays = page.locator('[data-slot="sheet-overlay"]');
    if (phone) {
      await expect(overlays).toHaveCount(1);
      expect(await overlays.evaluate((el) => getComputedStyle(el).backdropFilter)).toBe("none");
      // The sheet leaves the text being acted on in sight: at most 60 dvh.
      const box = await dialog.boundingBox();
      expect(box?.height ?? height).toBeLessThanOrEqual(height * 0.6 + 1);
    } else {
      await expect(overlays).toHaveCount(0);
    }

    // Every target in the drawer is 44 px tall on the phone (F15).
    if (phone) {
      const buttons = [
        page.getByRole("button", { name: "Close" }),
        panel.getByRole("button", { name: "Mute all" }),
        panel.getByRole("textbox", { name: "A word to add to your list" }),
        panel.getByRole("button", { name: "Add" }),
        panel.getByRole("button", { name: "Render", exact: true }),
        ...["Hear", "Render alone", "Dismiss"].map((name) => row.getByRole("button", { name })),
      ];
      for (const button of buttons) {
        const box = await button.boundingBox();
        if (box === null) throw new Error("a control is not on screen");
        expect(box.height).toBeGreaterThanOrEqual(44);
      }
    }

    // Render is the drawer's main action: filled with the text colour, which is neither the
    // outlined buttons' fill nor gold (the rail's Play keeps that).
    const fill = (button: Locator) => button.evaluate((el) => getComputedStyle(el).backgroundColor);
    const ink = await page.evaluate(() => getComputedStyle(document.body).color);
    await expect.poll(() => fill(panel.getByRole("button", { name: "Render", exact: true }))).toBe(ink);
    expect(await fill(row.getByRole("button", { name: "Hear" }))).not.toBe(ink);
    expect(ink).not.toBe("rgb(200, 162, 74)");

    if (phone) {
      // Modal: Tab and Shift+Tab circle inside the sheet, however many times. Focus
      // passes a guard on the way round, so it is read once it has settled.
      for (const key of [...Array(14).fill("Tab"), ...Array(4).fill("Shift+Tab")]) {
        await page.keyboard.press(key);
        await expect.poll(() => dialog.evaluate((el) => el.contains(document.activeElement))).toBe(true);
      }
    } else {
      // Non-modal: the bar stays in the accessibility tree and in reach, and a click on the transcript does not close the drawer.
      await expect(page.getByRole("button", { name: "Undo" })).toBeEnabled();
      await expect(page.getByRole("toolbar", { name: "Edit" }).getByRole("status")).toHaveText("Saved");
      await page.locator("article p").first().click({ position: { x: 5, y: 5 } });
      await expect(dialog).toBeVisible();
    }

    // Esc and Close both hand focus back to the More button.
    await panel.getByRole("textbox", { name: "A word to add to your list" }).focus();
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(more).toBeFocused();
    await openBleep(page);
    await page.getByRole("button", { name: "Close" }).click();
    await expect(dialog).toHaveCount(0);
    await expect(more).toBeFocused();

    // The menu's Bleep item counts what Mute all would still mute: nothing once the match is muted, one once it is dismissed.
    await more.click();
    await expect(menuBleep).toHaveText("Bleep");
    // Esc once focus is in the menu: before that there is nothing yet to dismiss it.
    await expect.poll(() => page.evaluate(() => document.activeElement?.closest("[role=menu]") !== null)).toBe(true);
    await page.keyboard.press("Escape");
    await expect(menuBleep).toHaveCount(0);
    const again = await openBleep(page);
    await again.getByRole("listitem", { name: word }).getByRole("button", { name: "Dismiss" }).click();
    await page.getByRole("button", { name: "Close" }).click();
    await more.click();
    await expect(menuBleep).toHaveText("Bleep1");
  });
}

test("on the phone the sheet's header and Close stay in sight while a long list scrolls", async ({ page }, info) => {
  const word = `tango${info.project.name}`;
  const dir = scratchDir();
  const sentences = Array.from({ length: 6 }, () => ["alpha", word, "bravo", word, "charlie", word, "delta", word]);
  const seeded = seed(editableTranscript(tone(dir, 40 + info.project.name.length / 10, `long-${info.project.name}.wav`), sentences), dir);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(readerUrl(seeded));
  await expect(page.locator("article")).toContainText(word);
  const panel = await openBleep(page);
  await panel.getByRole("textbox", { name: "A word to add to your list" }).fill(word);
  await panel.getByRole("button", { name: "Add" }).click();
  await expect(panel.getByRole("listitem", { name: word })).toHaveCount(24);
  const list = panel.locator("xpath=..");
  const scrolled = await list.evaluate((el) => {
    el.scrollTop = el.scrollHeight;
    return [el.scrollTop, el.scrollHeight, el.clientHeight];
  });
  expect(scrolled[0]).toBeGreaterThan(0);
  expect(scrolled[1]).toBeGreaterThan(scrolled[2] ?? 0);
  const close = await page.getByRole("button", { name: "Close" }).boundingBox();
  const title = await page.getByRole("heading", { name: "Bleep" }).boundingBox();
  for (const box of [close, title]) {
    expect(box?.y ?? -1).toBeGreaterThanOrEqual(0);
    expect((box?.y ?? 0) + (box?.height ?? 0)).toBeLessThanOrEqual(844);
  }
  // The sheet's top sits below 40 % of the window: the text being acted on is still on screen above it.
  const sheet = await page.getByRole("dialog", { name: "Bleep" }).boundingBox();
  expect(sheet?.y ?? 0).toBeGreaterThanOrEqual(844 * 0.4 - 1);
});

for (const width of [390, 700]) {
  test(`at ${width} px wide the reader's menu items are 44 px tall`, async ({ page }, info) => {
    const dir = scratchDir();
    const seeded = seed(
      editableTranscript(tone(dir, 11 + width / 10000 + info.project.name.length / 10, `items-${width}-${info.project.name}.wav`), [
        ["alpha", "bravo", "charlie", "delta"],
      ]),
      dir,
    );
    await page.setViewportSize({ width, height: 900 });
    await page.goto(readerUrl(seeded));
    await expect(page.locator("article")).toContainText("charlie");
    await page.getByRole("button", { name: "More" }).click();
    for (const name of [/^Timing/, /^Bleep/]) {
      // Polled: the menu zooms in, so its first frames are a little under full size.
      await expect
        .poll(async () => (await page.getByRole("menuitem", { name }).boundingBox())?.height ?? 0)
        .toBeGreaterThanOrEqual(44);
    }
  });
}
