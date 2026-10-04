#!/usr/bin/env python3
"""Replay the loop retry of language-detected whisper runs in the detected language (#229).

    uv run --with uroman --with rapidfuzz --with num2words python scratch/accuracy/language_retry.py [SET ...]

For each `plain` run (whisper, no `--language`) under scratch/accuracy/runs/<set>/
that kept its `.preretry.json`, the language whisper detects on the file's first
30 s is found the way the main pass found it (mlx_whisper.transcribe with no
language, on those 30 s), and the pre-retry sentences go through the steps dsj
runs after a whisper pass, `_retried` with the real `redecoder` in that
language, `_without_loops`, `_without_overlaps`. One whisper model in this
process, spans one at a time.

The result goes to `<name>.langretry.json` beside the run, never over an
existing file, and the table compares the run as it was (retry under
detection) with the replay: words the retry added, the share of them that
match the reference, the share of the rest of the transcript that does, and
the word error rate. Sets default to `urdu`, the one #229 measured.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

from score import TRUTHS, load, reference_words, score, transcript_words  # noqa: E402

from dsj import media as media_mod  # noqa: E402
from dsj.asr import Transcription  # noqa: E402
from dsj.suno import (  # noqa: E402
    LOUDNESS_FRAME_S,
    Progress,
    _retried,
    _without_loops,
    _without_overlaps,
    silences,
)
from dsj.whisper import DEFAULT_WHISPER_MODEL, SAMPLE_RATE, redecoder  # noqa: E402

RUNS = REPO / "scratch" / "accuracy" / "runs"


def quiet(p: Progress, state: str) -> None:
    del p, state


def detected(audio: Path) -> str:
    """The language whisper detects when none is asked for: from the first 30 s."""
    import mlx_whisper
    from mlx_whisper.audio import load_audio

    data: Any = load_audio(str(audio), sr=SAMPLE_RATE)
    result: dict[str, Any] = mlx_whisper.transcribe(  # pyright: ignore[reportUnknownMemberType]
        data[: 30 * SAMPLE_RATE], path_or_hf_repo=DEFAULT_WHISPER_MODEL, verbose=None
    )
    return str(result["language"])


def replay(path: Path, language: str) -> Path:
    out = path.with_name(f"{path.stem}.langretry.json")
    if out.exists():
        return out
    doc = json.loads(path.read_text())
    pre: list[dict[str, Any]] = load(path.with_name(f"{path.stem}.preretry.json"))["sentences"]
    audio = Path(doc["audio"])
    stretches = silences(media_mod.loudness(audio, LOUDNESS_FRAME_S))
    got = _retried(
        Transcription(text="", sentences=pre),
        stretches,
        lambda: redecoder(audio, model_id=DEFAULT_WHISPER_MODEL, language=language, prompt=None),
        quiet,
    )
    kept, loops = _without_loops(got)
    kept = _without_overlaps(kept, merge=True)
    others = [u for u in doc["unclear"] if u["reason"] != "repetition loop"]
    unclear = sorted(others + loops, key=lambda u: float(u["start"]))
    out.write_text(json.dumps(doc | {"text": kept.text, "sentences": kept.sentences,
                                     "unclear": unclear}, ensure_ascii=False))
    return out


def added(before: list[dict[str, Any]], after: list[dict[str, Any]], ref: list[str]) -> tuple[int, int, float]:
    """Words in `after` and not in `before`, how many of them are right, and `after`'s WER."""
    w0 = {(round(w.t, 3), w.text) for w in transcript_words(before)}
    w1 = transcript_words(after)
    s1 = score([w.text for w in w1], ref)
    new = [ok for w, ok in zip(w1, s1.correct_hyp, strict=True) if (round(w.t, 3), w.text) not in w0]
    return len(new), sum(new), s1.wer


def main(argv: list[str]) -> int:
    print("| set | run | language | retry | words added | of them right | rest of transcript right | WER |")
    print("|---|---|---|---|---:|---:|---:|---:|")
    for set_name in argv or ["urdu"]:
        ref = reference_words(load(TRUTHS[set_name]))
        for path in sorted((RUNS / set_name).glob("plain-r[0-9].json")):
            side = path.with_name(f"{path.stem}.preretry.json")
            if not side.exists() or not load(side).get("retried", True):
                continue
            language = detected(Path(load(path)["audio"]))
            without, _ = _without_loops(Transcription(text="", sentences=load(side)["sentences"]))
            base = transcript_words(without.sentences)
            s0 = score([w.text for w in base], ref)
            rest = sum(s0.correct_hyp) / max(1, len(base))
            for label, doc in (("detected again per clip", load(path)),
                               (f"in `{language}`", load(replay(path, language)))):
                n, ok, wer = added(without.sentences, doc["sentences"], ref)
                print(f"| {set_name} | {path.stem} | {language} | {label} | {n} | {ok} ({ok / max(1, n):.0%}) "
                      f"| {rest:.0%} | {wer:.1%} |", flush=True)
            print(f"| {set_name} | {path.stem} | {language} | none | 0 | | {rest:.0%} | {s0.wer:.1%} |",
                  flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
