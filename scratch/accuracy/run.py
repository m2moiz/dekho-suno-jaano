#!/usr/bin/env python3
"""Transcribe the public reference sets in every mode #184 compares, one run at a time.

    uv run python scratch/accuracy/run.py [--plan 184|236] [--only SET/MODE/RUN ...] [--dry-run]

Each run is `dsj suno <set audio> -o scratch/accuracy/runs/<set>/<mode>-r<N>.json`
with the mode's flags and `--no-diarize`, in a fresh process. Like
scratch/whisper_sweep.py it never overwrites (a transcript already there is
skipped, so an interrupted plan picks up where it stopped), waits while any
other `dsj suno` runs, and waits for MIN_FREE_PCT of memory to be free first,
because this laptop froze under two whisper runs at once.

Two things are kept beside each transcript:

- `<name>.bench.json`: wall time, exit code, flags, overrides, commit.
- `<name>.preretry.json`: the sentences as they stood just before whisper's loop
  retry (#183), saved by wrapping `dsj.suno._retried` in the run's process. The
  scorer passes them through `_without_loops` to get the transcript the run
  would have written with RETRY_LOOPS off, so one main pass gives both sides
  of #183's comparison. Absent when the retry had nothing to do (the wrapper
  still writes the file, with `"retried": false`).

Modes: parakeet (one run: it does not vary between runs), whisper with the
language detected (`plain`), `--language ur` (`ur`), `--roman-urdu`
(`roman`, anchored every ANCHOR_CHUNK_S = 120 s) and `--roman-urdu` with
ANCHOR_CHUNK_S = 30 (`roman30`, #184's "Roman 30 s"). Whisper modes run twice.

`--plan 236` runs #236's instead: `roman_vad`, `ur_vad` and `plain_vad`, the
same flags as `roman`, `ur` and `plain` with dsj.whisper.VAD_SEGMENTS on
(Silero's speech detector in front of whisper). They run under `uv run
--extra vad`, which installs silero-vad if it is missing.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent.parent
HERE = REPO / "scratch" / "accuracy"
RUNS = HERE / "runs"
MIN_FREE_PCT = 30

SETS = {
    "podcast": REPO / "scratch" / "urdu_cs" / "podcast.wav",
    "urdu": HERE / "urdu" / "urdu.wav",
    "earnings": HERE / "earnings" / "earnings.wav",
    # The same 30 minutes from the unspliced recording (build_refs.py earnings_call).
    "earnings_call": HERE / "earnings_call" / "earnings_call.wav",
}
MODES: dict[str, tuple[list[str], dict[str, Any]]] = {
    "parakeet": (["--engine", "parakeet"], {}),
    "plain": (["--engine", "whisper"], {}),
    "ur": (["--engine", "whisper", "--language", "ur"], {}),
    "roman": (["--roman-urdu"], {}),
    "roman30": (["--roman-urdu"], {"ANCHOR_CHUNK_S": 30.0}),
    "roman_vad": (["--roman-urdu"], {"VAD_SEGMENTS": True}),
    "ur_vad": (["--engine", "whisper", "--language", "ur"], {"VAD_SEGMENTS": True}),
    "plain_vad": (["--engine", "whisper"], {"VAD_SEGMENTS": True}),
}
# (set, mode, run). Run 1 of everything before any run 2, so a plan cut short
# still has every cell once. parakeet reads Urdu as nothing useful; it runs on
# the podcast only for #198's seam count.
PLAN = [
    *[(s, "parakeet", 1) for s in ("earnings", "podcast")],
    *[(s, m, r) for r in (1, 2) for m in ("roman", "ur", "plain") for s in ("podcast", "urdu", "earnings")],
    *[(s, "roman30", r) for r in (1, 2) for s in ("podcast", "urdu", "earnings")],
    # Whether parakeet's skipped segments on `earnings` come from its splices.
    ("earnings_call", "parakeet", 1),
    ("earnings_call", "plain", 1),
]
# #236: the detector on, beside #184's roman, ur and plain rows. Run 1 of
# everything first; plain only on the English call, the one set it is for.
PLAN_236 = [
    (s, m, r)
    for r in (1, 2)
    for s, m in [
        *[(s, m) for m in ("roman_vad", "ur_vad") for s in ("podcast", "urdu", "earnings")],
        ("earnings", "plain_vad"),
    ]
]
PLANS = {"184": PLAN, "236": PLAN_236}

# Runs inside the child: saves what _retried was handed, then retries as usual.
WRAPPER = """
import json, sys
import dsj.whisper as w
for k, v in json.loads(sys.argv[1]).items():
    setattr(w, k, v)
import dsj.suno as s
side = sys.argv[2]
original = s._retried
def recorded(transcription, *args, **kwargs):
    out = original(transcription, *args, **kwargs)
    with open(side, "w") as fh:
        json.dump({"retried": out is not transcription, "sentences": transcription.sentences}, fh,
                  ensure_ascii=False)
    return out
s._retried = recorded
from dsj.cli import main
sys.exit(main(sys.argv[3:]))
"""


def free_pct() -> int:
    out = subprocess.run(["memory_pressure"], capture_output=True, text=True).stdout
    found = re.search(r"free percentage:\s*(\d+)%", out)
    return int(found.group(1)) if found else 0


def busy() -> bool:
    pattern = "dsj suno|dsj.cli import main"
    return subprocess.run(["pgrep", "-f", pattern], capture_output=True).returncode == 0


def commit() -> str:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True).stdout.strip()

    dirty = git("status", "--porcelain", "--untracked-files=no", "--", "dsj")
    return git("rev-parse", "--short", "HEAD") + ("-dirty" if dirty else "")


def run_one(set_name: str, mode: str, run: int, dry: bool) -> None:
    flags, overrides = MODES[mode]
    folder = RUNS / set_name
    name = f"{mode}-r{run}"
    out = folder / f"{name}.json"
    if out.exists():
        print(f"{set_name}/{name}: already done", flush=True)
        return
    args = ["suno", str(SETS[set_name]), "-o", str(out), "--no-diarize",
            "--status", str(folder / f"{name}.status.json"), *flags]
    if dry:
        print(f"{set_name}/{name}: would run {' '.join(args[3:])} {overrides or ''}")
        return
    while busy():
        print("  another dsj suno is running, waiting", flush=True)
        time.sleep(60)
    while (pct := free_pct()) < MIN_FREE_PCT:
        print(f"  {pct}% memory free, waiting for {MIN_FREE_PCT}%", flush=True)
        time.sleep(60)
    folder.mkdir(parents=True, exist_ok=True)
    print(f"{set_name}/{name}: starting ({free_pct()}% memory free)", flush=True)
    started = time.monotonic()
    side = folder / f"{name}.preretry.json"
    # Kept out of the owner's app library: every finished `dsj suno` adds
    # itself to the library, and these are test runs on public audio.
    env = os.environ | {"DSJ_LIBRARY": str(RUNS / "library.db")}
    extra = ["--extra", "vad"] if overrides.get("VAD_SEGMENTS") else []
    with (folder / f"{name}.log").open("w") as log:
        rc = subprocess.run(
            ["uv", "run", *extra, "python", "-c", WRAPPER, json.dumps(overrides), str(side), *args],
            cwd=REPO, stdout=log, stderr=subprocess.STDOUT, env=env,
        ).returncode
    wall = time.monotonic() - started
    meta = {"wall_s": round(wall, 1), "returncode": rc, "args": args, "overrides": overrides,
            "commit": commit()}
    (folder / f"{name}.bench.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"{set_name}/{name}: exit {rc} in {wall / 60:.1f} min", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--only", nargs="*", default=None, help="SET/MODE/RUN, e.g. urdu/roman/1")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--plan", choices=sorted(PLANS), default="184", help="whose runs: #184's or #236's")
    args = parser.parse_args()
    plan = PLANS[args.plan]
    if args.only:
        wanted = {tuple(o.split("/")) for o in args.only}
        plan = [p for p in plan if (p[0], p[1], str(p[2])) in wanted]
    for missing in [s for s, path in SETS.items() if not path.exists()]:
        sys.exit(f"{SETS[missing]} is missing: build it first (scratch/accuracy/build_refs.py)")
    for set_name, mode, run in plan:
        run_one(set_name, mode, run, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
