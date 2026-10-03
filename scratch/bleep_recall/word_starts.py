#!/usr/bin/env python3
"""Where whisper puts a word's start, against where the word was said (#222).

Under `--roman-urdu`, word starts on the English sets of make_audio.py ran a
median 1.57 s early, into the pause before each word (#152). This finds which
setting does it, by decoding the same audio under each one and comparing every
token with the known position of the word it covers (audio/manifest.json):

    uv run python scratch/bleep_recall/word_starts.py decode   # whisper, one variant at a time
    uv run python scratch/bleep_recall/word_starts.py table    # the offsets, as markdown
    uv run python scratch/bleep_recall/word_starts.py align    # alignment only, no decoding
    uv run python scratch/bleep_recall/word_starts.py fixture PARAKEET.json WHISPER.json...

`decode` calls dsj.whisper.transcribe_whisper with each VARIANTS entry and
writes the payload sentences to timing/<variant>/<set>.json, skipping what is
on disk; it waits while another `dsj suno` runs or less than MIN_FREE_PCT of
memory is free. `table` reads those, and every whisper folder of transcripts
score.py made (`roman-urdu.before-222` and `whisper.before-222` are #152's,
from before the fix, kept aside when score.py ran again).

`align` tests the mechanism without decoding: it takes the words whisper
wrote under `--roman-urdu` and times them with mlx-whisper's own aligner
(`find_alignment`, the step `word_timestamps=True` runs) over the same audio,
once as written and once with a full stop after every word, under the Urdu
and the English language token. If the full stops alone move the starts back
onto the words, it is the missing punctuation, not the language or the prompt.

`fixture` asks what the fix does to real speech, where no word position is
known: on #148's public fixture it pairs each English word whisper wrote with
the same word in a parakeet transcript of the same audio within MATCH_S, and
compares whisper's start with parakeet's, which parakeet's decoder measures on
an 80 ms grid. Once as the whisper transcript stands, once with dsj.whisper's
`_pause_free_starts` replayed over each sentence. "Late" is whisper's start
after parakeet's by more than LATE_S, where the fix could cut a word's head.

"Early" is the spoken word's start minus the token's `t`. A token is the one
that overlaps the spoken word most, or failing any overlap the nearest within
MATCH_S. Prints numbers only; the transcripts stay in scratch/.
"""

from __future__ import annotations

import json
import re
import statistics
import subprocess
import sys
import time
from itertools import pairwise
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
AUDIO = HERE / "audio"
TIMING = HERE / "timing"
TRANSCRIPTS = HERE / "transcripts"
SETS = ("en_samantha", "en_daniel", "en_rishi")
MIN_FREE_PCT = 30
MATCH_S = 1.0
LATE_S = 0.1

# name: (language, prompt is the Roman Urdu one, anchor_s)
VARIANTS: dict[str, tuple[str | None, bool, float | None]] = {
    "plain": (None, False, None),
    "ur": ("ur", False, None),
    "prompt": (None, True, None),
    "ur+prompt": ("ur", True, None),
    "ur+prompt+a120": ("ur", True, 120.0),
    "ur+prompt+a60": ("ur", True, 60.0),
    "ur+prompt+a30": ("ur", True, 30.0),
}


def manifest() -> dict[str, Any]:
    return json.loads((AUDIO / "manifest.json").read_text(encoding="utf-8"))


def free_pct() -> int:
    out = subprocess.run(["memory_pressure"], capture_output=True, text=True).stdout
    found = re.search(r"free percentage:\s*(\d+)%", out)
    return int(found.group(1)) if found else 0


def busy() -> bool:
    pattern = "dsj suno|dsj.cli import main"
    return subprocess.run(["pgrep", "-f", pattern], capture_output=True).returncode == 0


def decode() -> None:
    from dsj import whisper

    for variant, (language, prompted, anchor_s) in VARIANTS.items():
        for name in SETS:
            out = TIMING / variant / f"{name}.json"
            if out.exists():
                continue
            while busy() or free_pct() < MIN_FREE_PCT:
                print(f"  waiting: busy={busy()} free={free_pct()}%", flush=True)
                time.sleep(30)
            started = time.monotonic()
            got = whisper.transcribe_whisper(
                AUDIO / f"{name}.wav",
                language=language,
                prompt=whisper.ROMAN_URDU_PROMPT if prompted else None,
                anchor_s=anchor_s,
            )
            wall = round(time.monotonic() - started, 1)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(
                json.dumps(
                    {
                        "variant": variant,
                        "language": language,
                        "prompted": prompted,
                        "anchor_s": anchor_s,
                        "model": whisper.DEFAULT_WHISPER_MODEL,
                        "wall_s": wall,
                        "sentences": got.sentences,
                    }
                ),
                encoding="utf-8",
            )
            print(f"{variant} {name}: {wall} s", flush=True)


def tokens_of(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [t for s in payload["sentences"] for t in s["tokens"]]


def nearest(target: tuple[float, float], tokens: list[dict[str, Any]]) -> dict[str, Any] | None:
    a, b = target

    def overlap(t: dict[str, Any]) -> float:
        return min(b, float(t["e"])) - max(a, float(t["t"]))

    best = max(tokens, key=overlap, default=None)
    if best is not None and overlap(best) > 0:
        return best
    mid = (a + b) / 2
    close = [t for t in tokens if abs((float(t["t"]) + float(t["e"])) / 2 - mid) <= MATCH_S]
    return min(close, key=lambda t: abs(float(t["t"]) - a), default=None)


def pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def describe(label: str, paths: list[Path]) -> str:
    units = {s["set"]: s["units"] for s in manifest()["sets"]}
    early: list[float] = []
    late_end: list[float] = []
    chained = punct = total = 0
    for path in paths:
        tokens = tokens_of(path)
        total += len(tokens)
        chained += sum(1 for p, q in pairwise(tokens) if q["t"] == p["e"])
        punct += sum(1 for t in tokens if str(t["w"]).strip()[-1:] in ".,!?;:")
        for unit in units[path.stem]:
            tok = nearest((unit["target"][0], unit["target"][1]), tokens)
            if tok is not None:
                early.append(unit["target"][0] - float(tok["t"]))
                late_end.append(float(tok["e"]) - unit["target"][1])
    return (
        f"| {label} | {total} | {chained} | {punct} | {len(early)} | "
        f"{statistics.median(early):.2f} | {pct(early, 0.1):.2f} to {pct(early, 0.9):.2f} | "
        f"{statistics.median(late_end):.2f} |"
    )


def table() -> None:
    print(
        "| setting | tokens | `t` equals the previous `e` | ending in punctuation "
        "| words matched | start, s early (median) | 10th to 90th percentile "
        "| end, s late (median) |"
    )
    print("|---|---|---|---|---|---|---|---|")
    for folder in sorted(p for p in TRANSCRIPTS.iterdir() if p.is_dir()):
        paths = [folder / f"{name}.json" for name in SETS]
        if folder.name != "parakeet" and all(p.exists() for p in paths):
            print(describe(f"score.py `{folder.name}`", paths))
    for variant in VARIANTS:
        paths = [TIMING / variant / f"{name}.json" for name in SETS]
        if all(p.exists() for p in paths):
            print(describe(variant, paths))


def align() -> None:
    import mlx.core as mx
    from mlx_whisper import audio as wa
    from mlx_whisper.timing import find_alignment
    from mlx_whisper.tokenizer import get_tokenizer
    from mlx_whisper.transcribe import ModelHolder

    from dsj.whisper import DEFAULT_WHISPER_MODEL

    model = ModelHolder.get_model(DEFAULT_WHISPER_MODEL, mx.float16)
    units = {s["set"]: s["units"] for s in manifest()["sets"]}
    rows: dict[tuple[str, str], list[float]] = {}
    for name in SETS:
        samples = wa.load_audio(str(AUDIO / f"{name}.wav"))
        written = tokens_of(TRANSCRIPTS / "roman-urdu" / f"{name}.json")
        # One 30 s window at a time, as whisper decodes, with the words whisper
        # wrote wholly inside it.
        for lo in range(0, int(len(samples) / wa.SAMPLE_RATE) - 1, 30):
            hi = lo + 30
            words = [
                str(t["w"]).strip() for t in written if lo <= float(t["t"]) and float(t["e"]) <= hi
            ]
            words = [w for w in words if w]
            if not words:
                continue
            chunk = samples[lo * wa.SAMPLE_RATE : hi * wa.SAMPLE_RATE]
            mel = wa.log_mel_spectrogram(chunk, n_mels=model.dims.n_mels, padding=wa.N_SAMPLES)
            mel = wa.pad_or_trim(mel, wa.N_FRAMES, axis=-2)
            frames = len(chunk) // wa.HOP_LENGTH
            for lang in ("ur", "en"):
                tok = get_tokenizer(
                    model.is_multilingual,
                    num_languages=model.num_languages,
                    language=lang,
                    task="transcribe",
                )
                for style, text in (
                    ("as written", " " + " ".join(words)),
                    ("a full stop after each", " " + ". ".join(words) + "."),
                ):
                    timing = find_alignment(model, tok, tok.encode(text), mel, frames)
                    spoken = [w for w in timing if w.word.strip() not in {".", ""}]
                    for unit in units[name]:
                        a, b = unit["target"]
                        if not lo <= a < hi:
                            continue

                        def overlap(w: Any, a: float = a, b: float = b, lo: int = lo) -> float:
                            return min(b, lo + float(w.end)) - max(a, lo + float(w.start))

                        near = [w for w in spoken if overlap(w) > 0]
                        if near:
                            best = max(near, key=overlap)
                            rows.setdefault((style, lang), []).append(a - (lo + float(best.start)))
    print(
        "| words timed | language token | words matched | start, s early (median) "
        "| 10th to 90th percentile |"
    )
    print("|---|---|---|---|---|")
    for (style, lang), early in rows.items():
        print(
            f"| {style} | {lang} | {len(early)} | {statistics.median(early):.2f} | "
            f"{pct(early, 0.1):.2f} to {pct(early, 0.9):.2f} |"
        )


def spoken_words(path: Path) -> list[tuple[str, float, int, int]]:
    """(word, start, sentence index, index of its first token) per written word.

    A token with a leading space starts a word, as both engines write them, so
    parakeet's sub-word pieces join into the word they spell.
    """
    out: list[tuple[str, float, int, int]] = []
    sentences = json.loads(path.read_text(encoding="utf-8"))["sentences"]
    for n, sentence in enumerate(sentences):
        for i, t in enumerate(sentence["tokens"]):
            text = str(t["w"])
            if text.startswith(" ") or i == 0:
                out.append(("", float(t["t"]), n, i))
            word, start, sn, first = out[-1]
            out[-1] = (word + re.sub(r"[^a-z']", "", text.lower()), start, sn, first)
    return [w for w in out if len(w[0]) >= 3]


def fixture(parakeet: Path, transcripts: list[Path]) -> None:
    from dsj.whisper import _pause_free_starts  # pyright: ignore[reportPrivateUsage]

    reference: dict[str, list[float]] = {}
    for word, start, _, _ in spoken_words(parakeet):
        reference.setdefault(word, []).append(start)
    print(
        "| whisper transcript | words paired | starts the fix moves | median gap to parakeet, "
        "s, as written / fixed | late by over LATE_S, as written / fixed | moved closer / farther |"
    )
    print("|---|---|---|---|---|---|")
    for path in transcripts:
        sentences = json.loads(path.read_text(encoding="utf-8"))["sentences"]
        # Each sentence of a whisper transcript is one of whisper's segments.
        fixed = _pause_free_starts(
            [
                [{"start": float(t["t"]), "end": float(t["e"])} for t in s["tokens"]]
                for s in sentences
            ]
        )
        before: list[float] = []
        after: list[float] = []
        closer = farther = 0
        for word, start, n, first in spoken_words(path):
            new = fixed[n][first]
            near = [r for r in reference.get(word, []) if abs(r - start) <= MATCH_S]
            if not near:
                continue
            ref = min(near, key=lambda r: abs(r - start))
            before.append(start - ref)
            after.append(new - ref)
            closer += abs(new - ref) < abs(start - ref)
            farther += abs(new - ref) > abs(start - ref)
        late = (sum(d > LATE_S for d in before), sum(d > LATE_S for d in after))
        gap = (statistics.median(map(abs, before)), statistics.median(map(abs, after)))
        print(
            f"| {path.parent.name}/{path.name} | {len(before)} | {closer + farther} | "
            f"{gap[0]:.3f} / {gap[1]:.3f} | {late[0]} / {late[1]} | {closer} / {farther} |"
        )


def main(argv: list[str]) -> None:
    steps = {"decode": decode, "table": table, "align": align}
    if argv[:1] == ["fixture"] and len(argv) >= 3:
        fixture(Path(argv[1]), [Path(a) for a in argv[2:]])
        return
    if len(argv) != 1 or argv[0] not in steps:
        sys.exit(
            f"usage: word_starts.py {{{'|'.join(steps)}}} | fixture PARAKEET.json WHISPER.json..."
        )
    steps[argv[0]]()


if __name__ == "__main__":
    main(sys.argv[1:])
