#!/usr/bin/env python3
"""Measure v0.2.1's fixes on the owner's own recordings (#149).

The owner cleared his `Hi-Q Recordings` Drive folder for testing on
2026-09-23. Five files from it are a fixed set, and every v0.2.1 fix that
claims an improvement quotes this script's numbers on them, before and after.
The audio is private: it never enters git, and nothing here prints or writes
a word of any transcript. Numbers only.

    export DSJ_REAL_AUDIO="$HOME/Library/CloudStorage/GoogleDrive-m.moiz1995@gmail.com/My Drive/Hi-Q Recordings"
    uv run python scratch/real_bench.py baseline
    uv run python scratch/real_bench.py run --label silence-threshold
    uv run python scratch/real_bench.py run --label try2 --only 101117 -- --prompt "..."
    uv run python scratch/real_bench.py run --label plain-threshold --unanchored
    uv run python scratch/real_bench.py fixture --label silence-threshold

`baseline` measures the transcripts the 22 Sep session left in
$DSJ_REAL_AUDIO/transcripts/. It runs no model; nearly all its time is ffmpeg
decoding audio for the loudness columns.

`run` transcribes each file with `dsj suno`, one at a time, into
scratch/real_bench/runs/<label>/, then measures. Anything after `--` is passed
to `dsj suno` on top of the file's own flags. It never writes into
$DSJ_REAL_AUDIO, and it never overwrites: a transcript already in the label's
folder is measured as it stands, so re-running a label after an interruption
picks up where it stopped, and transcribing again takes a new label. That is
#137's lesson: the one way to lose a finished transcript is to delete it before
its replacement exists. It also refuses to start a file while any other
`dsj suno` is running, because two at once froze this machine (#136).

`run --unanchored` gives the Urdu files `--engine whisper --language ur
--prompt <ROMAN_URDU_PROMPT>` in place of `--roman-urdu`: the same prompt with
no anchoring, which `--roman-urdu` always turns on (#140's conditions 1 and 3).

`fixture` runs the same measurements on #148's public recording,
scratch/urdu_cs/podcast.wav (`just urdu-fixture` builds it), transcribed with
`--roman-urdu --no-diarize` into scratch/real_bench/runs/<label>/podcast.json
under the same never-overwrite rule. `fixture --transcript PATH` measures a
transcript that already exists instead. Its extra columns count the words
whose start falls inside each of the fixture's three quiet gaps (10, 30 and
60 s): audio with no speech in it, so every word there was invented. A loop
dsj took out (#140) keeps a word count and a span but no word times, so its
words are counted into a gap in proportion to how much of its span lies in it.
That recording is public, so unlike the five files its text may be read.

Every table is printed and appended to scratch/real_bench/results.md, which is
gitignored along with the rest of scratch/'s data.

Columns:

- urdu%: seconds in sentences more than 30% Urdu script, over seconds in all
  sentences. Uses scratch/urdu_script_share.py's is_urdu, so the two agree.
- -loops: the same with repetition loops removed. This is the drift number.
  On recording-20260922-171500 the two differ by 48 points, because its loops
  are one Urdu letter repeated (#100, #140). Since #140 dsj takes loops out of
  `sentences` itself and keeps no text for them, so on a transcript written
  since then urdu% and -loops are the same number.
- words: words in the transcript, loops included: on a transcript written
  since #140, the words left in `sentences` plus each `unclear` loop's count.
- loop s: seconds in loop sentences, and since #140 in the payload's
  `unclear` loop spans; see dsj.suno.is_loop for the rule. It is wider than
  the one the 22 Sep session used, which missed loops that cycle three or more
  words, so its baseline numbers are higher than the ones first published on
  #149 (#140).
- loop dB, speech dB: median per-second loudness inside loop sentences and
  inside every other sentence. Close numbers mean the loops are not over
  silence (#99).
- quiet%: share of loop seconds quieter than -45 dB.
- x rt: audio seconds per wall-clock second, model load and diarization
  included. `run` only; the 22 Sep transcripts did not record wall time.
- agree%: English control only, `run` only. The share of the parakeet
  reference's words that the new transcript also has, in the same order.
  Parakeet reads English well and does not loop, which is why it is the
  reference, but it is not ground truth: read this as a before-and-after
  comparison between two whisper runs, not as an accuracy score.

The lang column comes from SET, and those labels are the owner's and the 22 Sep session's, not a
measurement.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from urdu_script_share import is_urdu

from dsj.suno import LOOP_REASON, is_loop
from dsj.whisper import ROMAN_URDU_PROMPT

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "scratch" / "real_bench"
SAMPLE_RATE = 16000
QUIET_DB = -45.0
CONTROL = "recording-20260922-153458"
FIXTURE = REPO / "scratch" / "urdu_cs"
# --roman-urdu without the anchoring it always turns on (dsj/cli.py).
UNANCHORED = ("--engine", "whisper", "--language", "ur", "--prompt", ROMAN_URDU_PROMPT)
WORD = re.compile(r"[^\W_]+(?:'[^\W_]+)?")


@dataclass(frozen=True)
class Recording:
    name: str
    language: str
    role: str
    flags: tuple[str, ...]


SET = (
    Recording("recording-20260920-101117", "en+ur", "the fast one: iterate here", ("--roman-urdu",)),
    Recording("recording-20260920-094234", "mostly ur", "worst drift", ("--roman-urdu",)),
    Recording("recording-20260920-162033", "en+ur", "moderate drift", ("--roman-urdu",)),
    Recording("recording-20260922-171500", "en+ur", "worst loops", ("--roman-urdu",)),
    Recording(CONTROL, "en", "control, parakeet is the reference", ("--engine", "whisper")),
)


@dataclass(frozen=True)
class Row:
    name: str
    language: str
    model: str
    minutes: float
    sentences: int
    words: int
    urdu_pct: float
    urdu_pct_no_loops: float
    loop_s: float
    loop_db: float | None
    speech_db: float | None
    quiet_pct: float | None
    speed: float | None
    agree_pct: float | None


def loudness(audio: Path) -> np.ndarray:
    """Loudness of every whole second of `audio`, in dB relative to full scale."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(audio), "-ac", "1", "-ar", str(SAMPLE_RATE),
         "-f", "f32le", "-"],
        capture_output=True, check=True,
    ).stdout
    samples = np.frombuffer(raw, dtype=np.float32)
    seconds = len(samples) // SAMPLE_RATE
    frames = samples[: seconds * SAMPLE_RATE].reshape(seconds, SAMPLE_RATE)
    return 20 * np.log10(np.maximum(np.sqrt(np.mean(frames**2, axis=1)), 1e-9))


def span(db: np.ndarray, sentence: dict[str, Any]) -> np.ndarray:
    """The per-second loudness values a sentence covers, at least one of them."""
    start = int(sentence["start"])
    return db[start : max(start + 1, int(sentence["end"]))]


def urdu_pct(sentences: list[dict[str, Any]]) -> float:
    total = urdu = 0.0
    for s in sentences:
        seconds = s["end"] - s["start"]
        total += seconds
        if is_urdu(s.get("text") or ""):
            urdu += seconds
    return 100 * urdu / total if total else 0.0


def median_db(db: np.ndarray, sentences: list[dict[str, Any]]) -> tuple[float | None, float | None]:
    """Median loudness over `sentences`, and the share of it below QUIET_DB."""
    if not sentences:
        return None, None
    values = np.concatenate([span(db, s) for s in sentences])
    return float(np.median(values)), float(100 * np.mean(values < QUIET_DB))


def words(sentences: list[dict[str, Any]]) -> list[str]:
    return [w.lower() for s in sentences for w in WORD.findall(s.get("text") or "")]


def loop_spans(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Every repetition loop in a transcript, old or new, as dicts with `start` and `end`.

    Before #140 the loops sat in `sentences` and are found there by is_loop.
    Since #140 dsj takes them out itself and records each in the payload's
    `unclear` list with its span and word count but not its text, so they are
    read from there too. A transcript has one or the other, never both, so
    nothing is counted twice.
    """
    sentences: list[dict[str, Any]] = payload["sentences"]
    return [s for s in sentences if is_loop(s.get("text") or "")] + loops_taken(payload)


def loops_taken(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """The loops dsj took out of `sentences` itself (#140); none before it."""
    unclear: list[dict[str, Any]] = payload.get("unclear") or []
    return [u for u in unclear if u.get("reason") == LOOP_REASON]


def loop_words(payload: dict[str, Any]) -> int:
    """Words in the loops dsj took out of `sentences`, from `unclear`; 0 before #140."""
    return sum(int(u["words"]) for u in loops_taken(payload))


def agreement(reference: Path, sentences: list[dict[str, Any]]) -> float:
    ref = words(json.loads(reference.read_text())["sentences"])
    hyp = words(sentences)
    matcher = difflib.SequenceMatcher(None, ref, hyp, autojunk=False)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    return 100 * matched / len(ref) if ref else 0.0


def measure(
    rec: Recording, transcript: Path, audio: Path, wall_s: float | None, reference: Path | None
) -> Row:
    payload = json.loads(transcript.read_text())
    sentences: list[dict[str, Any]] = payload["sentences"]
    loops = loop_spans(payload)
    rest = [s for s in sentences if not is_loop(s.get("text") or "")]
    db = loudness(audio)
    loop_db, quiet = median_db(db, loops)
    speech_db, _ = median_db(db, rest)
    return Row(
        name=transcript.stem,
        language=rec.language,
        model=str(payload.get("model", "?")).rsplit("/", 1)[-1],
        minutes=len(db) / 60,
        sentences=len(sentences),
        words=len(words(sentences)) + loop_words(payload),
        urdu_pct=urdu_pct(sentences),
        urdu_pct_no_loops=urdu_pct(rest),
        loop_s=sum(s["end"] - s["start"] for s in loops),
        loop_db=loop_db,
        speech_db=speech_db,
        quiet_pct=quiet,
        speed=len(db) / wall_s if wall_s else None,
        agree_pct=agreement(reference, sentences) if reference else None,
    )


def audio_of(root: Path, rec: Recording) -> Path:
    for suffix in (".m4a", ".mp3"):
        path = root / f"{rec.name}{suffix}"
        if path.exists():
            return path
    sys.exit(f"{rec.name}: no .m4a or .mp3 in {root}")


def commit() -> str:
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
                          capture_output=True, text=True, check=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                           cwd=REPO, capture_output=True, text=True, check=True).stdout
    return f"{head}-dirty" if dirty.strip() else head


def other_runs() -> list[str]:
    """PIDs of running `dsj suno` processes.

    Anchored to a path separator or a space before `dsj` and a space after
    `suno`, so it finds `uv run dsj suno x.m4a` and `.venv/bin/dsj suno x.m4a`
    but not a shell whose own command line only mentions the words, such as a
    watcher running `pgrep -f 'dsj suno'`, which blocked every run until it
    exited.
    """
    found = subprocess.run(["pgrep", "-f", "(^|[ /])dsj suno "], capture_output=True, text=True).stdout
    return found.split()


def transcribe(name: str, audio: Path, folder: Path, flags: list[str]) -> None:
    """One `dsj suno` run into `folder`, with its wall time and command beside it."""
    cmd = ["uv", "run", "dsj", "suno", str(audio), "-o", str(folder / f"{name}.json"),
           "--status", str(folder / f"{name}.status.json"), *flags]
    started = time.monotonic()
    with (folder / f"{name}.log").open("w") as log:
        code = subprocess.run(cmd, cwd=REPO, stdout=log, stderr=subprocess.STDOUT).returncode
    meta = {"wall_s": time.monotonic() - started, "returncode": code,
            "args": cmd[4:], "commit": commit()}
    (folder / f"{name}.bench.json").write_text(json.dumps(meta, indent=2))


def start(name: str, audio: Path, folder: Path, flags: list[str]) -> None:
    """transcribe(), unless another `dsj suno` is running (#136)."""
    busy = other_runs()
    if busy:
        sys.exit(f"refusing to start {name}: dsj suno is already running "
                 f"as PID {', '.join(busy)}, and two at once froze this machine (#136)")
    folder.mkdir(parents=True, exist_ok=True)
    transcribe(name, audio, folder, flags)


def fmt(value: float | None, spec: str) -> str:
    return "-" if value is None else format(value, spec)


def table(title: str, rows: list[Row]) -> str:
    lines = [
        f"## {title}",
        "",
        "| file | lang | model | min | sent | words | urdu% | -loops | loop s | loop dB | speech dB | quiet% | x rt | agree% |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        lines.append(
            f"| {r.name.removeprefix('recording-')} | {r.language} | {r.model} | {r.minutes:.1f} | {r.sentences} | {r.words} "
            f"| {r.urdu_pct:.0f} | {r.urdu_pct_no_loops:.0f} | {r.loop_s:.0f} "
            f"| {fmt(r.loop_db, '.1f')} | {fmt(r.speech_db, '.1f')} | {fmt(r.quiet_pct, '.0f')} "
            f"| {fmt(r.speed, '.2f')} | {fmt(r.agree_pct, '.1f')} |"
        )
    return "\n".join(lines) + "\n"


def record(title: str, rows: list[Row]) -> None:
    text = table(title, rows)
    print(text)
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "results.md").open("a") as fh:
        fh.write(text + "\n")


def baseline(root: Path, chosen: list[Recording]) -> list[Row]:
    return [measure(rec, root / "transcripts" / f"{rec.name}.json", audio_of(root, rec), None, None)
            for rec in chosen]


def flags_for(rec: Recording, unanchored: bool) -> list[str]:
    if unanchored and "--roman-urdu" in rec.flags:
        return [*(f for f in rec.flags if f != "--roman-urdu"), *UNANCHORED]
    return list(rec.flags)


def run(
    root: Path, label: str, chosen: list[Recording], extra: list[str], unanchored: bool
) -> list[Row]:
    folder = OUT / "runs" / label
    rows: list[Row] = []
    for rec in chosen:
        out = folder / f"{rec.name}.json"
        if not out.exists():
            print(f"transcribing {rec.name} ({rec.role}) ...", flush=True)
            start(rec.name, audio_of(root, rec), folder, [*flags_for(rec, unanchored), *extra])
        meta_path = folder / f"{rec.name}.bench.json"
        meta: dict[str, Any] = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        if not out.exists():
            print(f"{rec.name}: dsj exited {meta.get('returncode')}, see {folder / (rec.name + '.log')}")
            continue
        reference = root / "transcripts" / f"{CONTROL}.json" if rec.name == CONTROL else None
        rows.append(measure(rec, out, audio_of(root, rec), meta.get("wall_s"), reference))
    return rows


@dataclass(frozen=True)
class FixtureRow:
    name: str
    words: int
    urdu_pct: float
    urdu_pct_no_loops: float
    loop_s: float
    gap_words: tuple[int, ...]
    speed: float | None


def measure_fixture(transcript: Path, wall_s: float | None) -> FixtureRow:
    truth = json.loads((FIXTURE / "ground_truth.json").read_text())
    gaps = [(g["start"], g["end"]) for g in truth["segments"] if g["kind"] == "gap"]
    payload = json.loads(transcript.read_text())
    sentences: list[dict[str, Any]] = payload["sentences"]
    starts = [float(t["t"]) for s in sentences for t in s.get("tokens") or []]
    rest = [s for s in sentences if not is_loop(s.get("text") or "")]
    taken = loops_taken(payload)
    return FixtureRow(
        name=str(transcript.relative_to(REPO)) if transcript.is_relative_to(REPO) else str(transcript),
        words=len(words(sentences)) + loop_words(payload),
        urdu_pct=urdu_pct(sentences),
        urdu_pct_no_loops=urdu_pct(rest),
        loop_s=sum(s["end"] - s["start"] for s in loop_spans(payload)),
        gap_words=tuple(
            sum(1 for t in starts if a <= t < b) + round(sum(share_in(u, a, b) * u["words"] for u in taken))
            for a, b in gaps
        ),
        speed=float(truth["duration_s"]) / wall_s if wall_s else None,
    )


LATIN = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")


def english_recall(sentences: list[dict[str, Any]]) -> float:
    """Share of the fixture reference's Latin words the transcript also has, in order.

    #99's and #33's measure: the reference's Latin words, lowercased, from
    ground_truth.json's clip segments, matched in order against the
    transcript's with difflib (no autojunk), matching blocks summed over the
    reference's length.
    """
    truth = json.loads((FIXTURE / "ground_truth.json").read_text())
    ref = [w.lower() for g in truth["segments"] if g["kind"] == "clip" for w in LATIN.findall(g["ground_truth"])]
    hyp = [w.lower() for s in sentences for w in LATIN.findall(s.get("text") or "")]
    matcher = difflib.SequenceMatcher(None, ref, hyp, autojunk=False)
    return 100 * sum(block.size for block in matcher.get_matching_blocks()) / len(ref)


def share_in(span: dict[str, Any], a: float, b: float) -> float:
    """How much of `span` lies inside [a, b), as a fraction of its length.

    A loop dsj took out keeps its word count but not its word times, so its
    words are spread evenly over its span to count how many fell in a gap.
    """
    length = span["end"] - span["start"]
    if length <= 0:
        return 1.0 if a <= span["start"] < b else 0.0
    return max(0.0, min(span["end"], b) - max(span["start"], a)) / length


def fixture_table(title: str, row: FixtureRow) -> str:
    gaps = " | ".join(str(n) for n in row.gap_words)
    return (
        f"## {title}\n\n"
        "| transcript | words | urdu% | -loops | loop s | words in 10 s gap | 30 s gap | 60 s gap | x rt |\n"
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|\n"
        f"| {row.name} | {row.words} | {row.urdu_pct:.0f} | {row.urdu_pct_no_loops:.0f} "
        f"| {row.loop_s:.0f} | {gaps} | {fmt(row.speed, '.2f')} |\n"
    )


def fixture(label: str | None, transcript: str | None, extra: list[str]) -> str:
    """Transcribe #148's fixture under `label`, or measure `transcript`; return the table."""
    if transcript:
        path = Path(transcript).resolve()
        return fixture_table(f"fixture, {path.name} as it stands", measure_fixture(path, None))
    assert label is not None
    audio = FIXTURE / "podcast.wav"
    if not audio.exists():
        sys.exit(f"{audio} is missing; build it with `just urdu-fixture` (#148)")
    folder = OUT / "runs" / label
    out = folder / "podcast.json"
    if not out.exists():
        print(f"transcribing {audio.name} (#148's fixture) ...", flush=True)
        start("podcast", audio, folder, ["--roman-urdu", "--no-diarize", *extra])
    meta_path = folder / "podcast.bench.json"
    meta: dict[str, Any] = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    if not out.exists():
        sys.exit(f"podcast: dsj exited {meta.get('returncode')}, see {folder / 'podcast.log'}")
    title = f"fixture, {label} · commit {meta.get('commit', commit())} · extra flags: {' '.join(extra) or 'none'}"
    return fixture_table(title, measure_fixture(out, meta.get("wall_s")))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    base = sub.add_parser("baseline", help="measure the 22 Sep transcripts; runs no model")
    base.add_argument("--only", help="substring of one file name, e.g. 101117")
    go = sub.add_parser("run", help="transcribe the set with dsj suno, then measure")
    go.add_argument("--label", required=True, help="folder under scratch/real_bench/runs/")
    go.add_argument("--only", help="substring of one file name, e.g. 101117")
    go.add_argument("--unanchored", action="store_true",
                    help="the Roman Urdu prompt without --roman-urdu's anchoring")
    go.add_argument("extra", nargs=argparse.REMAINDER, help="after --: extra dsj suno flags")
    fx = sub.add_parser("fixture", help="transcribe or measure #148's public fixture")
    which = fx.add_mutually_exclusive_group(required=True)
    which.add_argument("--label", help="folder under scratch/real_bench/runs/")
    which.add_argument("--transcript", help="measure this transcript of podcast.wav instead")
    fx.add_argument("extra", nargs=argparse.REMAINDER, help="after --: extra dsj suno flags")
    args = parser.parse_args(argv)

    if args.command == "fixture":
        text = fixture(args.label, args.transcript, [a for a in args.extra if a != "--"])
        print(text)
        OUT.mkdir(parents=True, exist_ok=True)
        with (OUT / "results.md").open("a") as fh:
            fh.write(text + "\n")
        return 0

    folder = os.environ.get("DSJ_REAL_AUDIO")
    if not folder:
        sys.exit("set DSJ_REAL_AUDIO to the Hi-Q Recordings folder; see #149 and this docstring")
    root = Path(folder).expanduser()
    chosen = [rec for rec in SET if not args.only or args.only in rec.name]
    if not chosen:
        sys.exit(f"--only {args.only!r} matches nothing in the set")

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    if args.command == "baseline":
        record(f"baseline, 22 Sep transcripts · {stamp} · commit {commit()}", baseline(root, chosen))
    else:
        extra = [a for a in args.extra if a != "--"]
        anchoring = " · unanchored" if args.unanchored else ""
        title = f"{args.label} · {stamp} · commit {commit()}{anchoring} · extra flags: {' '.join(extra) or 'none'}"
        record(title, run(root, args.label, chosen, extra, args.unanchored))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
