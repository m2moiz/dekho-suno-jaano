#!/usr/bin/env python3
"""Transcribe the public reference sets in every mode #184 compares, one run at a time.

    uv run python scratch/accuracy/run.py [--plan 184|235|236|240] [--only SET/MODE/RUN ...] [--dry-run]

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
same flags as `roman`, `ur` and `plain` with Silero's speech detector in front
of whisper. Since #236 `--roman-urdu` has it on by default, so `roman` and
`roman30` turn it off to stay #184's runs, and `ur_vad` and `plain_vad` turn
it on for every mode (dsj.whisper.VAD_SEGMENTS = "all"). The 14 runs on #236
were made on 34036c6, before that default, with VAD_SEGMENTS a bool set True.

`--plan 235` runs two Urdu fine-tunes of turbo (FINETUNES), each from
scratch/models/<name> (scratch/accuracy/convert_finetunes.py), as
`<name>_roman_vad` and `<name>_ur`, run 1 only. A run 2 is asked for by hand
with `--also SET/MODE/2`, which runs cells the plan does not hold.

`--plan 240` runs Oriserve's Hinglish fine-tune of turbo (scratch/models/apex,
convert_finetunes.py apex) as `apex_en_vad`, the decode its card uses
(`--language en`) with the speech detector on (VAD_SEGMENTS = "all"), and
`apex_roman_vad`, turbo's best mixed-speech mode with the model swapped. Run 1
only; a run 2 is asked for with `--also`.

`--min-speed 2` is the owner's floor from 6 Oct: speed is paramount, so a run
that cannot finish at 2x realtime or faster is stopped (by the pid its status
file records) and recorded as too slow in its bench file, and its mode is
dropped for the sets after it (`slower_than`). Not an `_ur` mode: whisper
forced to Urdu loops on mixed speech, so its speed depends on the set, and each
set is judged on its own.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent.parent
HERE = REPO / "scratch" / "accuracy"
RUNS = HERE / "runs"
MIN_FREE_PCT = 30
# --min-speed judges dsj's own speed only after this much audio (#235, owner's rule of 6 Oct).
MIN_SPEED_AFTER_S = 180.0

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
    "roman": (["--roman-urdu"], {"VAD_SEGMENTS": "off"}),
    "roman30": (["--roman-urdu"], {"ANCHOR_CHUNK_S": 30.0, "VAD_SEGMENTS": "off"}),
    "roman_vad": (["--roman-urdu"], {"VAD_SEGMENTS": "roman"}),
    "ur_vad": (["--engine", "whisper", "--language", "ur"], {"VAD_SEGMENTS": "all"}),
    "plain_vad": (["--engine", "whisper"], {"VAD_SEGMENTS": "all"}),
}
# #235: Urdu fine-tunes of turbo, converted to MLX by convert_finetunes.py.
# `<name>_roman_vad` is `roman_vad` with the model swapped; `<name>_ur` is `ur`,
# the decode the model cards use. VAD_SEGMENTS is pinned to its default
# ("roman": the detector for --roman-urdu only) so the bench file records it.
FINETUNES = ("kingabzpro", "pakurdu")
for _name in FINETUNES:
    _model = ["--model", str(REPO / "scratch" / "models" / _name)]
    MODES[f"{_name}_roman_vad"] = (["--roman-urdu", *_model], {"VAD_SEGMENTS": "roman"})
    MODES[f"{_name}_ur"] = (["--engine", "whisper", "--language", "ur", *_model], {"VAD_SEGMENTS": "roman"})
# #240: Oriserve Whisper-Hindi2Hinglish-Apex, a turbo fine-tune that writes
# Hindustani in Roman script. Its card decodes with language "en".
_apex = ["--model", str(REPO / "scratch" / "models" / "apex")]
MODES["apex_en_vad"] = (["--engine", "whisper", "--language", "en", *_apex], {"VAD_SEGMENTS": "all"})
MODES["apex_roman_vad"] = (["--roman-urdu", *_apex], {"VAD_SEGMENTS": "roman"})
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
# #235: run 1 of each fine-tune in both modes on all three sets, one model at
# a time. A run 2 is added by hand (--also) only for a cell that beats turbo's
# best by more than 2 points.
PLAN_235 = [
    (s, f"{name}_{m}", 1)
    for name in FINETUNES
    for m in ("roman_vad", "ur")
    for s in ("podcast", "urdu", "earnings")
]
# #240: run 1 of both Apex modes on all three sets.
PLAN_240 = [(s, m, 1) for m in ("apex_en_vad", "apex_roman_vad") for s in ("podcast", "urdu", "earnings")]
PLANS = {"184": PLAN, "236": PLAN_236, "235": PLAN_235, "240": PLAN_240}

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


def run_one(set_name: str, mode: str, run: int, dry: bool, min_speed: float | None = None) -> bool:
    """Run one cell; True when it was stopped for running under `min_speed` x realtime."""
    flags, overrides = MODES[mode]
    folder = RUNS / set_name
    name = f"{mode}-r{run}"
    out = folder / f"{name}.json"
    if out.exists():
        print(f"{set_name}/{name}: already done", flush=True)
        return False
    args = ["suno", str(SETS[set_name]), "-o", str(out), "--no-diarize",
            "--status", str(folder / f"{name}.status.json"), *flags]
    if dry:
        print(f"{set_name}/{name}: would run {' '.join(args[3:])} {overrides or ''}")
        return False
    while busy():
        print("  another dsj suno is running, waiting", flush=True)
        time.sleep(60)
    while (pct := free_pct()) < MIN_FREE_PCT:
        print(f"  {pct}% memory free, waiting for {MIN_FREE_PCT}%", flush=True)
        time.sleep(60)
    folder.mkdir(parents=True, exist_ok=True)
    print(f"{set_name}/{name}: starting ({free_pct()}% memory free)", flush=True)
    started = time.monotonic()
    # Other work on this Mac shares the GPU; the load average says how busy it was (#240).
    load_before = [round(x, 1) for x in os.getloadavg()]
    side = folder / f"{name}.preretry.json"
    # Kept out of the owner's app library: every finished `dsj suno` adds
    # itself to the library, and these are test runs on public audio.
    env = os.environ | {"DSJ_LIBRARY": str(RUNS / "library.db")}
    status = folder / f"{name}.status.json"
    too_slow: dict[str, Any] | None = None
    with (folder / f"{name}.log").open("w") as log:
        child = subprocess.Popen(
            ["uv", "run", "python", "-c", WRAPPER, json.dumps(overrides), str(side), *args],
            cwd=REPO, stdout=log, stderr=subprocess.STDOUT, env=env,
        )
        audio_s = 0.0
        while child.poll() is None:
            time.sleep(10)
            if min_speed and too_slow is None:
                too_slow, audio_s = slower_than(status, min_speed, time.monotonic() - started, audio_s)
                if too_slow:
                    print(f"  too slow: {too_slow}, stopping pid {too_slow['pid']}", flush=True)
                    os.kill(too_slow["pid"], signal.SIGTERM)
        rc = child.returncode
    wall = time.monotonic() - started
    meta = {"wall_s": round(wall, 1), "returncode": rc, "args": args, "overrides": overrides,
            "commit": commit(), "loadavg_before": load_before,
            "loadavg_after": [round(x, 1) for x in os.getloadavg()],
            **({"too_slow": too_slow} if too_slow else {})}
    (folder / f"{name}.bench.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"{set_name}/{name}: exit {rc} in {wall / 60:.1f} min", flush=True)
    return too_slow is not None


def slower_than(
    status: Path, floor: float, wall_s: float, audio_s: float
) -> tuple[dict[str, Any] | None, float]:
    """Why a running transcription cannot clear `floor` x realtime, or None while it still can (#235).

    Two ways to know: dsj's own speed, once it has done MIN_SPEED_AFTER_S of
    audio, is under the floor; or the wall clock, model load included, has
    already passed the recording's length over the floor, so even an instant
    finish would land under it. The second is the only one for an unchunked
    `--language` run, which reports no progress until it ends, and it holds
    through the loop retry too, whose status counts only the spans it re-reads:
    so the recording's length is the first total the run reported, `audio_s`,
    returned for the next call.
    """
    try:
        st = json.loads(status.read_text())
    except (OSError, ValueError):
        return None, audio_s
    if "pid" not in st or st.get("state") not in ("running", "retrying"):
        return None, audio_s
    done, speed = float(st["audio_done_s"]), float(st["speed"])
    if st["state"] == "running":
        audio_s = audio_s or float(st["audio_total_s"])
        if done >= MIN_SPEED_AFTER_S and speed < floor:
            return {"pid": st["pid"], "rule": "speed", "speed": speed, "audio_done_s": done,
                    "wall_s": round(wall_s)}, audio_s
    if audio_s and wall_s > audio_s / floor:
        return {"pid": st["pid"], "rule": "wall", "speed": round(audio_s / wall_s, 2), "state": st["state"],
                "wall_s": round(wall_s)}, audio_s
    return None, audio_s


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--only", nargs="*", default=None, help="SET/MODE/RUN, e.g. urdu/roman/1")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--plan", choices=sorted(PLANS), default="184", help="whose runs: #184's, #235's, #236's or #240's")
    parser.add_argument("--also", nargs="*", default=[], help="SET/MODE/RUN to run after the plan, e.g. podcast/pakurdu_ur/2")
    parser.add_argument("--min-speed", type=float, default=None,
                        help="stop a run that cannot finish at this x realtime, and drop its mode (#235)")
    parser.add_argument("--drop", nargs="*", default=[], help="modes already dropped: skip them")
    args = parser.parse_args()
    plan = PLANS[args.plan]
    if args.only:
        wanted = {tuple(o.split("/")) for o in args.only}
        plan = [p for p in plan if (p[0], p[1], str(p[2])) in wanted]
    for extra in args.also:
        set_name, mode, run = extra.split("/")
        if set_name not in SETS or mode not in MODES:
            sys.exit(f"--also {extra}: no such set or mode")
        plan = [*plan, (set_name, mode, int(run))]
    for missing in [s for s, path in SETS.items() if not path.exists()]:
        sys.exit(f"{SETS[missing]} is missing: build it first (scratch/accuracy/build_refs.py)")
    dropped = set(args.drop)
    for set_name, mode, run in plan:
        if mode in dropped:
            print(f"{set_name}/{mode}-r{run}: skipped, {mode} is dropped", flush=True)
            continue
        # A `--language ur` run's speed depends on the audio (it loops on mixed
        # speech), so it is judged per set; any other mode too slow once is dropped.
        if run_one(set_name, mode, run, args.dry_run, args.min_speed) and not mode.endswith("_ur"):
            dropped.add(mode)
    return 0


if __name__ == "__main__":
    sys.exit(main())
