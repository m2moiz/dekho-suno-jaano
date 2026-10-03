#!/usr/bin/env python3
"""Does each engine write a listed swear word down? Transcribe, mute, count (#152).

Reads the audio and manifest make_audio.py wrote under scratch/bleep_recall/audio/
and works in three steps, each skipping what is already on disk:

    uv run python scratch/bleep_recall/score.py transcribe   # dsj suno, one run at a time
    uv run python scratch/bleep_recall/score.py hatao        # dsj hatao on every transcript
    uv run python scratch/bleep_recall/score.py table        # the counts, as markdown

`transcribe` runs every set through every CONFIGS entry, one `dsj suno` at a
time, and waits while another `dsj suno` runs or less than MIN_FREE_PCT of
memory is free. `hatao` runs the real command with DSJ_WORDS pointed at a file
that does not exist, so only the shipped lists count, never the user's own.

Each spoken unit lands in exactly one class, tried in this order:

    listed     a shipped-list spelling of the spoken word's own entry (any
               list's entry of that name) matched a word at the unit's time
    censored   a word there is written with asterisks, and no spelling matched
    other      something else is written there
    dropped    nothing is written there (`unclear` says whether dsj took it out)

An `other` is also counted as near when a word written there of NEAR_MIN_LEN
letters or more is within NEAR_EDITS edits of a spelling of the spoken word's
own entry (any list's entry of that name): a spelling the list lacks, rather
than a different word. dsj never matches by edit distance (dsj/hatao.py says
why); this only sorts the misses.

"At the unit's time" is the spoken word's span widened by TOL_WORD_S for a word
alone (GAP_S of silence keeps neighbours further away than that), or TOL_SENT_S
inside a sentence, where the frame's words sit JOIN_S away. Whisper only infers
word times, so a sentence's word is also counted `listed` when a match falls
anywhere in that sentence's span; the frames hold no listed word, and the table
says how many were counted that way. A match of another entry is not credited:
whisper's times can slip by a second, and on the words-alone sets every such
match measured was the neighbouring unit's word, written early or late.

`dsj hatao` is judged on the audio, not on the match: how much of the spoken
word the render's `spans` (from its bleep log) cover. All of it, FULL_COVER
or more, is muted; less than that but some is partly muted. A whisper match
whose times slipped mutes the wrong stretch, and this is where that shows.

Prints counts only. The transcripts sit in scratch/ and never enter git.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from dsj import hatao as bleep

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
AUDIO = HERE / "audio"
TRANSCRIPTS = HERE / "transcripts"
RENDERS = HERE / "renders"

CONFIGS: dict[str, list[str]] = {
    "parakeet": ["--engine", "parakeet"],
    "whisper": ["--engine", "whisper"],
    "roman-urdu": ["--roman-urdu"],
}
MIN_FREE_PCT = 30
TOL_WORD_S = 0.5
TOL_SENT_S = 0.1
SPAN_TOL_S = 0.3
NEAR_EDITS = 2
FULL_COVER = 0.9
NEAR_MIN_LEN = 4
CLASSES = ("listed", "censored", "other", "dropped")


def manifest() -> dict[str, Any]:
    return json.loads((AUDIO / "manifest.json").read_text(encoding="utf-8"))


def free_pct() -> int:
    out = subprocess.run(["memory_pressure"], capture_output=True, text=True).stdout
    found = re.search(r"free percentage:\s*(\d+)%", out)
    return int(found.group(1)) if found else 0


def busy() -> bool:
    pattern = "dsj suno|dsj.cli import main"
    return subprocess.run(["pgrep", "-f", pattern], capture_output=True).returncode == 0


def transcribe() -> None:
    for config, flags in CONFIGS.items():
        for entry in manifest()["sets"]:
            name = entry["set"]
            out = TRANSCRIPTS / config / f"{name}.json"
            if out.exists():
                continue
            while busy() or free_pct() < MIN_FREE_PCT:
                print(f"  waiting: busy={busy()} free={free_pct()}%", flush=True)
                time.sleep(30)
            out.parent.mkdir(parents=True, exist_ok=True)
            cmd = ["uv", "run", "dsj", "suno", str(AUDIO / f"{name}.wav"), "-o", str(out),
                   *flags, "--no-diarize"]
            started = time.monotonic()
            with (out.with_suffix(".log")).open("w") as log:
                rc = subprocess.run(cmd, cwd=REPO, stdout=log, stderr=subprocess.STDOUT).returncode
            wall = round(time.monotonic() - started, 1)
            (out.with_suffix(".run.json")).write_text(json.dumps(
                {"cmd": cmd[2:], "returncode": rc, "wall_s": wall, "free_pct_after": free_pct()}))
            print(f"{config} {name}: exit {rc} in {wall} s", flush=True)
            if rc != 0:
                sys.exit(f"{config} {name} failed; see {out.with_suffix('.log')}")


def hatao() -> None:
    env = {**os.environ, bleep.WORDS_ENV: str(HERE / "no-user-words.toml")}
    assert not (HERE / "no-user-words.toml").exists()
    for config in CONFIGS:
        for entry in manifest()["sets"]:
            name = entry["set"]
            transcript = TRANSCRIPTS / config / f"{name}.json"
            out = RENDERS / config / f"{name}.wav"
            if not transcript.exists() or out.with_name(f"{name}.hatao.json").exists():
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            cmd = ["uv", "run", "dsj", "hatao", str(AUDIO / f"{name}.wav"), "-t", str(transcript),
                   "-o", str(out), "--overwrite"]
            done = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True)
            recall = next((ln for ln in done.stderr.splitlines() if ln.startswith("recall:")), "")
            out.with_name(f"{name}.hatao.json").write_text(json.dumps(
                {"cmd": cmd[2:], "returncode": done.returncode, "recall_line": recall}))
            print(f"{config} {name}: hatao exit {done.returncode}", flush=True)
            if done.returncode not in (0, 3):
                sys.exit(done.stderr)


def edits(a: str, b: str) -> int:
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, cb in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (ca != cb))
    return row[-1]


def family(lists: bleep.WordList) -> dict[str, list[str]]:
    """Every normalised spelling, by entry name, across all the lists."""
    out: dict[str, list[str]] = defaultdict(list)
    for spelling, entry in lists.spellings.items():
        out[entry.split(":", 1)[1]].append(spelling.replace(" ", ""))
    return out


def overlaps(a: float, b: float, lo: float, hi: float) -> bool:
    return a < hi and max(b, a + 0.001) > lo


def classify(unit: dict[str, Any], payload: dict[str, Any],
             matches: list[tuple[float, float, str]], spellings: list[str]) -> tuple[str, bool, bool]:
    """(class, a flag, a flag): for listed, counted only by the sentence-span rule;
    for other, near a spelling of its entry; for dropped, inside `unclear`."""
    own = [(a, b) for a, b, name in matches if name == unit["entry"].split(":")[1]]
    tol = TOL_WORD_S if unit["kind"] == "word" else TOL_SENT_S
    lo, hi = unit["target"][0] - tol, unit["target"][1] + tol
    if any(overlaps(a, b, lo, hi) for a, b in own):
        return "listed", False, False
    if unit["kind"] == "sentence":
        s_lo, s_hi = unit["start"] - SPAN_TOL_S, unit["end"] + SPAN_TOL_S
        if any(overlaps(a, b, s_lo, s_hi) for a, b in own):
            return "listed", True, False
    tokens = [t for s in payload["sentences"] for t in s["tokens"]]
    here = [t for t in tokens if overlaps(float(t["t"]), float(t["e"]), lo, hi)
            and bleep.normalize(str(t["w"]))]
    if any("*" in str(t["w"]) for t in here):
        return "censored", False, False
    if here:
        written = [bleep.normalize(str(t["w"])) for t in here]
        near = any(len(w) >= NEAR_MIN_LEN and edits(w, x) <= NEAR_EDITS
                   for w in written for x in spellings)
        return "other", near, False
    unclear = any(overlaps(float(u["start"]), float(u["end"]), lo, hi)
                  for u in payload.get("unclear") or [])
    return "dropped", False, unclear


def covered(unit: dict[str, Any], spans: list[tuple[float, float]]) -> float:
    """The share of the spoken word's audio that the render's spans silence."""
    a, b = unit["target"]
    inside = sum(max(0.0, min(b, y) - max(a, x)) for x, y in spans)
    return inside / (b - a)


def shipped() -> bleep.WordList:
    words = Path(bleep.__file__).parent / "words"
    return bleep.load_words([words / f"{name}.toml" for name in bleep.SHIPPED_LISTS])


def table() -> None:
    lists = shipped()
    names = family(lists)
    meta = manifest()
    rows: dict[tuple[str, str, str], Counter[str]] = defaultdict(Counter)
    voices: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    models: dict[str, set[str]] = defaultdict(set)
    false_mutes: Counter[str] = Counter()
    for config in CONFIGS:
        for entry in meta["sets"]:
            name = entry["set"]
            path = TRANSCRIPTS / config / f"{name}.json"
            if not path.exists():
                print(f"missing: {path}", file=sys.stderr)
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            models[config].add(f"{payload.get('engine')} {payload.get('model')}")
            doc = bleep.from_transcript(payload, AUDIO / f"{name}.wav")
            found = bleep.find(doc, lists)
            matches = [(m.source_start, m.source_end, m.entry.split(":", 1)[1])
                       for m in found.matches]
            log = RENDERS / config / f"{name}.bleeps.json"
            spans = ([(float(a), float(b))
                      for a, b in json.loads(log.read_text(encoding="utf-8"))["spans"]]
                     if log.exists() else [])
            for unit in entry["units"]:
                lang = unit["entry"].split(":")[0]
                key = (config, lang, unit["kind"])
                cls, flag, unclear = classify(unit, payload, matches,
                                              names[unit["entry"].split(":")[1]])
                rows[key]["units"] += 1
                rows[key][cls] += 1
                rows[key]["by_span" if cls == "listed" else "near"] += flag
                rows[key]["unclear"] += unclear
                share = covered(unit, spans)
                rows[key]["muted"] += share >= FULL_COVER
                rows[key]["partly"] += 0 < share < FULL_COVER
                if unit["kind"] == "word" and lang == "en":
                    voices[(config, unit["tts"])]["units"] += 1
                    voices[(config, unit["tts"])][cls] += 1
            false_mutes[config] += sum(
                1 for span in spans if not any(covered(u, [span]) for u in entry["units"]))
    print("| engine | language | spoken as | units | written as listed | censored "
          "| other word (near a spelling) | dropped | `dsj hatao` mutes all (part) |")
    print("|---|---|---|---|---|---|---|---|---|")
    for (config, lang, kind), c in sorted(rows.items(), key=lambda kv: (
            list(CONFIGS).index(kv[0][0]), ["en", "ur", "pa", "hi"].index(kv[0][1]), kv[0][2])):
        notes = []
        if c["unclear"]:
            notes.append(f"{c['unclear']} of them inside `unclear`")
        dropped = f"{c['dropped']}" + (f" ({'; '.join(notes)})" if notes else "")
        kind_name = "word alone" if kind == "word" else "in a sentence"
        listed = f"{c['listed']}" + (f" ({c['by_span']} by sentence span)" if c["by_span"] else "")
        print(f"| {config} | {lang} | {kind_name} | {c['units']} | {listed} | "
              f"{c['censored']} | {c['other']} ({c['near']}) | {dropped} | {c['muted']} ({c['partly']}) |")
    print()
    print("English words alone, by voice:")
    print()
    print("| engine | voice | units | listed | censored | other word | dropped |")
    print("|---|---|---|---|---|---|---|")
    for (config, voice), c in sorted(voices.items(), key=lambda kv: (
            list(CONFIGS).index(kv[0][0]), kv[0][1])):
        print(f"| {config} | {voice} | {c['units']} | " + " | ".join(
            str(c[k]) for k in CLASSES) + " |")
    print()
    for config in CONFIGS:
        print(f"{config}: models {sorted(models[config])}; "
              f"render spans touching no spoken listed word: {false_mutes[config]}")


def main(argv: list[str]) -> None:
    steps = {"transcribe": transcribe, "hatao": hatao, "table": table}
    if len(argv) != 1 or argv[0] not in steps:
        sys.exit(f"usage: score.py {{{'|'.join(steps)}}}")
    steps[argv[0]]()


if __name__ == "__main__":
    main(sys.argv[1:])
