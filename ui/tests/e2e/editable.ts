// A transcript the app can edit (#66): every token has its end `e` and a
// confidence `c`, as `dsj suno` writes them since v0.2.0, over a tone ffmpeg
// makes, so no test ever opens one of the owner's recordings.
import type { Page } from "@playwright/test";

type Token = { t: number; e: number; w: string; c: number };

/**
 * Two speakers' sentences of `words`, each word 0.35 s long and 0.5 s after
 * the one before, with 0.4 s more between the sentences.
 */
export function editableTranscript(audio: string, sentences: string[][], unsure: string[] = []) {
  let t = 0.3;
  const out = sentences.map((words, i) => {
    const tokens: Token[] = words.map((w) => {
      const token = { t: +t.toFixed(3), e: +(t + 0.35).toFixed(3), w: ` ${w}`, c: unsure.includes(w) ? 0.3 : 0.95 };
      t += 0.5;
      return token;
    });
    t += 0.4;
    const first = tokens[0] as Token;
    const last = tokens.at(-1) as Token;
    return { start: first.t, end: last.e, speaker: i % 2, text: tokens.map((x) => x.w).join(""), tokens };
  });
  return {
    audio,
    engine: "parakeet",
    model: "mlx-community/parakeet-tdt-0.6b-v3",
    speakers: ["SPEAKER_00", "SPEAKER_01"],
    diarization: "senko 0.1.0",
    text: "",
    unclear: [],
    sentences: out,
  };
}

/** Select `word`, the first time any paragraph holds it, as a drag across it would. */
export async function selectWord(page: Page, word: string, last: string = word): Promise<void> {
  await page.evaluate(
    ({ word, last }) => {
      const paragraphs = Array.from(document.querySelectorAll("article p"));
      const find = (w: string) => {
        for (const p of paragraphs) {
          const text = p.firstChild as Text;
          const at = text.data.indexOf(w);
          if (at >= 0) return { text, at };
        }
        throw new Error(`no paragraph holds ${JSON.stringify(w)}`);
      };
      const from = find(word);
      const to = find(last);
      const range = document.createRange();
      range.setStart(from.text, from.at);
      range.setEnd(to.text, to.at + last.length);
      const selection = window.getSelection();
      selection?.removeAllRanges();
      selection?.addRange(range);
    },
    { word, last },
  );
}

/** The text each range of the named highlight paints. */
export function painted(page: Page, name: string): Promise<string[]> {
  return page.evaluate((name) => Array.from(CSS.highlights.get(name) ?? [], (r) => r.toString()), name);
}

/** Open the bleep drawer from the reader's menu, and return its panel. */
export async function openBleep(page: Page) {
  await page.getByRole("button", { name: "More" }).click();
  await page.getByRole("menuitem", { name: /^Bleep/ }).click();
  const panel = page.getByRole("region", { name: "Words to bleep" });
  await panel.waitFor();
  return panel;
}
