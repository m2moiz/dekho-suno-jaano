// A screen recording's picture on the same playhead as its words (#80), in
// real chromium and Playwright's webkit. The recording is made here by ffmpeg,
// picture and sound, never one of the owner's (#127 trap 9).
import { expect, type Page, test } from "@playwright/test";
import { spawnSync } from "node:child_process";
import path from "node:path";

import { readerUrl, scratchDir, seed } from "./seed.ts";

const REPO = path.resolve(import.meta.dirname, "../../..");
// The frame grid the page's picture and `dsj dikhao`'s are compared on.
const W = 64;
const H = 48;

function run(command: string, args: string[], options: { cwd?: string } = {}) {
  const result = spawnSync(command, args, { encoding: "buffer", ...options });
  if (result.status !== 0) throw new Error(`${command} failed: ${result.stderr.toString()}`);
  return result.stdout;
}

/** 12 s of ffmpeg's moving test card with a tone: h264 and AAC in a .mov. */
function screenRecording(dir: string): string {
  const file = path.join(dir, "screen.mov");
  run("ffmpeg", [
    "-y", "-loglevel", "error",
    "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=25:duration=12",
    "-f", "lavfi", "-i", "sine=frequency=440:duration=12",
    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", file,
  ]);
  return file;
}

/** `dsj dikhao`'s frame at `seconds`, as W x H RGB. */
function dikhao(video: string, seconds: number, dir: string): Uint8Array {
  const jpg = path.join(dir, `frame-${seconds}.jpg`);
  run("uv", ["run", "dsj", "dikhao", video, String(seconds), "-o", jpg, "--width", "0"], { cwd: REPO });
  return run("ffmpeg", ["-loglevel", "error", "-i", jpg, "-vf", `scale=${W}:${H}`, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]);
}

/**
 * The frame the page's <video> is showing, as W x H RGB: a screenshot of the
 * element, controls off, decoded by ffmpeg. Not drawImage onto a canvas, which
 * reads back blank in headless Playwright WebKit (measured 2026-10-02).
 */
async function shown(page: Page): Promise<Uint8Array> {
  const video = page.locator("video");
  await video.evaluate((v: HTMLVideoElement) => {
    v.controls = false;
  });
  // The picture inside the element: letterboxed, since the element is the
  // bar's width and the picture keeps its own shape.
  const clip = await video.evaluate((v: HTMLVideoElement) => {
    const box = v.getBoundingClientRect();
    const scale = Math.min(box.width / v.videoWidth, box.height / v.videoHeight);
    const width = v.videoWidth * scale;
    const height = v.videoHeight * scale;
    // Inset a pixel each side, clear of any edge the scaler blends.
    return {
      x: box.left + (box.width - width) / 2 + 1,
      y: box.top + (box.height - height) / 2 + 1,
      width: width - 2,
      height: height - 2,
    };
  });
  const png = await page.screenshot({ clip });
  await video.evaluate((v: HTMLVideoElement) => {
    v.controls = true;
  });
  const decoded = spawnSync(
    "ffmpeg",
    ["-loglevel", "error", "-i", "pipe:0", "-vf", `scale=${W}:${H}`, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
    { input: png },
  );
  if (decoded.status !== 0) throw new Error(`ffmpeg could not read the screenshot: ${decoded.stderr}`);
  return decoded.stdout;
}

function difference(a: Uint8Array, b: Uint8Array): number {
  let sum = 0;
  for (let i = 0; i < a.length; i += 1) sum += Math.abs((a[i] ?? 0) - (b[i] ?? 0));
  return sum / a.length;
}

function words(start: number, speaker: number, count: number) {
  const tokens = Array.from({ length: count }, (_, i) => ({ t: start + i * 0.5, w: ` f${start + i * 0.5}` }));
  return { start, end: start + count * 0.5, speaker, text: tokens.map((t) => t.w).join(""), tokens };
}

function transcript(audio: string) {
  return {
    audio,
    model: "mlx-community/parakeet-tdt-0.6b-v3",
    speakers: ["SPEAKER_00", "SPEAKER_01"],
    diarization: "senko 0.1.0",
    text: "",
    unclear: [],
    sentences: [words(0, 0, 8), words(4, 1, 8), words(8, 0, 8)],
  };
}

async function clickWord(page: Page, word: string) {
  const box = await page.evaluate((word) => {
    for (const p of document.querySelectorAll("article p")) {
      const text = p.firstChild as Text;
      const i = text.data.indexOf(word);
      if (i < 0) continue;
      // Into the middle of the window first, as a person would: a word under
      // the sticky player is not there to click, and the click would land on
      // the picture instead, which Chromium takes as play.
      p.scrollIntoView({ block: "center" });
      const range = document.createRange();
      range.setStart(text, i);
      range.setEnd(text, i + word.length);
      const rect = range.getBoundingClientRect();
      return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
    }
    throw new Error(`no paragraph holds ${word}`);
  }, word);
  await page.mouse.click(box.x, box.y);
}

test("a screen recording shows its picture on the words' playhead, folds away and stays folded", async ({ page }) => {
  // Twelve `uv run dsj dikhao` calls, about a second and a half each.
  test.slow();
  const dir = scratchDir();
  const video = screenRecording(dir);
  const seeded = seed(transcript(video), dir);
  await page.goto(readerUrl(seeded));
  await expect(page.locator("article p")).toHaveCount(3);
  await expect(page.locator("audio")).toHaveCount(0);
  await expect.poll(() => page.evaluate(() => (document.querySelector("video") as HTMLVideoElement).videoWidth)).toBe(320);

  // A click on the word at 6 s moves the picture with it.
  await clickWord(page, "f6");
  await page.evaluate(() => (document.querySelector("video") as HTMLVideoElement).pause());
  await page.evaluate(
    () =>
      new Promise<void>((resolve) => {
        const v = document.querySelector("video") as HTMLVideoElement;
        v.currentTime = 6;
        v.addEventListener("seeked", () => resolve(), { once: true });
      }),
  );
  // Let the frame at 6 s reach the screen before it is photographed.
  await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
  await page.waitForTimeout(300);
  const painted = await page.evaluate(() => [...(CSS.highlights.get("dsj-playhead") ?? [])].map((r) => (r as Range).toString()));
  expect(painted).toEqual(["f6"]);
  // The page's picture is closer to `dsj dikhao`'s frame at 6 s than to its
  // frame at any other whole second of the recording.
  const atSix = await shown(page);
  const distances = Array.from({ length: 12 }, (_, second) => difference(atSix, dikhao(video, second, dir)));
  console.log(`difference from dikhao's frame at each second: ${distances.map((d) => d.toFixed(1)).join(" ")}`);
  const closest = distances.indexOf(Math.min(...distances));
  expect(closest).toBe(6);

  // Folded away, it keeps playing.
  await page.getByRole("button", { name: "Hide picture" }).click();
  await expect(page.locator("video")).toBeHidden();
  await page.getByRole("button", { name: "Play" }).click();
  const before = await page.evaluate(() => (document.querySelector("video") as HTMLVideoElement).currentTime);
  await page.waitForTimeout(800);
  const after = await page.evaluate(() => {
    const v = document.querySelector("video") as HTMLVideoElement;
    return { time: v.currentTime, paused: v.paused };
  });
  expect(after.paused).toBe(false);
  expect(after.time).toBeGreaterThan(before + 0.3);
  await expect(page.getByRole("button", { name: "Pause" })).toBeVisible();

  // And folded it stays, when the page is opened again.
  await page.goto(readerUrl(seeded));
  await expect(page.getByRole("button", { name: "Show picture" })).toBeVisible();
  await expect(page.locator("video")).toBeHidden();
});

test("an audio recording has no picture box and no error", async ({ page }) => {
  const dir = scratchDir();
  const audio = path.join(dir, "call.mp3");
  run("ffmpeg", ["-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=330:duration=12", audio]);
  const seeded = seed(transcript(audio), dir);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(readerUrl(seeded));
  await expect(page.locator("article p")).toHaveCount(3);
  await expect(page.locator("video")).toHaveCount(0);
  await expect.poll(() => page.evaluate(() => document.querySelector("audio")?.readyState ?? 0)).toBeGreaterThan(0);
  await expect(page.getByRole("button", { name: /picture/ })).toHaveCount(0);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(errors).toEqual([]);
});

/** A tiny video of `seconds`, 16x16 at 1 fps with near-silent sound, so 2.5 h stays small. */
function tinyVideo(dir: string, seconds: number, name: string): string {
  const file = path.join(dir, name);
  run("ffmpeg", [
    "-y", "-loglevel", "error",
    "-f", "lavfi", "-i", `color=c=gray:size=16x16:rate=1:duration=${seconds}`,
    "-f", "lavfi", "-i", `anullsrc=r=8000:cl=mono:d=${seconds}`,
    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "8k", "-shortest", file,
  ]);
  return file;
}

// The waveform is the rail's only scrubber. On a phone, a video's rail also
// holds the picture button, and the time joined it in fix round 1: worked out
// from font metrics it left the waveform about 26 px, and none at an hour
// (fix round 1 review, I3). Measured here at 390 px, short and 2.5 h.
for (const [label, seconds] of [["a 12 s", 12], ["a 2.5 h", 9000]] as const) {
  test(`on a 390 px phone, ${label} video leaves the waveform 120 px or more`, async ({ page }, info) => {
    test.slow();
    await page.setViewportSize({ width: 390, height: 844 });
    const dir = scratchDir();
    const video = tinyVideo(dir, seconds + info.project.name.length / 100, `tiny-${seconds}-${info.project.name}.mov`);
    const seeded = seed(transcript(video), dir);
    await page.goto(readerUrl(seeded));
    const position = page.getByRole("slider", { name: "Position" });
    await expect(position).toBeVisible();
    const box = await position.boundingBox();
    console.log(`waveform at 390 px, ${label} video: ${box?.width.toFixed(1)} px`);
    expect(box?.width ?? 0).toBeGreaterThanOrEqual(120);
  });
}
