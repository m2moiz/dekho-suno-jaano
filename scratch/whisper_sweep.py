#!/usr/bin/env python3
"""Run whisper's anomaly-switch settings one after another, with no agent watching (#99).

Picking `hallucination_silence_threshold` needs repeated runs: two runs of the
same setting on recording-20260920-101117 gave 59% and 47% Urdu script, so one
run per setting decides nothing. Each run is 10 to 20 minutes of whisper on the
laptop. An agent waiting on that spends quota on every check-in; this script
spends none, and the orchestrator reads scratch/real_bench/results.md at the end.

    export DSJ_REAL_AUDIO="$HOME/Library/CloudStorage/GoogleDrive-m.moiz1995@gmail.com/My Drive/Hi-Q Recordings"
    uv run python scratch/whisper_sweep.py scratch/sweeps/<plan>.json

The setting is applied from outside: each run is a fresh process that sets
`dsj.whisper.HALLUCINATION_SILENCE_S` and then calls dsj's own CLI, so no code
is edited while whisper is running. Transcripts land where scratch/real_bench.py
expects them, `runs/<label>/<name>.json` with a `bench.json` beside it, so
`real_bench.py run --label X --only NAME` and `fixture --label X` measure them
without transcribing again, and an interrupted sweep picks up where it stopped.

One whisper at a time, always: this laptop froze under two. Before each run the
script waits until at least MIN_FREE_PCT of memory is free.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
RUNS = REPO / "scratch" / "real_bench" / "runs"
FIXTURE = REPO / "scratch" / "urdu_cs" / "podcast.wav"
MIN_FREE_PCT = 30

# A plan is a JSON list of runs, one object each:
#   {"label": "...", "target": "<recording name from real_bench's SET> | fixture",
#    "overrides": {"<dsj.whisper attribute>": value}, "flags": [...]}
# `overrides` are set on dsj.whisper before dsj's CLI runs; `flags` replace the
# target's default flags. The #99 sweep used HALLUCINATION_SILENCE_S; #100 uses
# ANCHOR_CHUNK_S and an unanchored prompt; #33 uses --model.
FLAGS = {
    "recording-20260922-153458": ["--engine", "whisper"],
    "fixture": ["--roman-urdu", "--no-diarize"],
}
DEFAULT_FLAGS = ["--roman-urdu"]


def free_pct() -> int:
    out = subprocess.run(["memory_pressure"], capture_output=True, text=True).stdout
    found = re.search(r"free percentage:\s*(\d+)%", out)
    return int(found.group(1)) if found else 0


def wait_for_memory() -> None:
    while (pct := free_pct()) < MIN_FREE_PCT:
        print(f"  {pct}% memory free, waiting for {MIN_FREE_PCT}%", flush=True)
        time.sleep(60)


def busy() -> bool:
    # A sweep's own runs start as `python -c "...dsj.cli import main..." suno`,
    # which "dsj suno" alone does not match, so a second sweep would not wait.
    pattern = "dsj suno|dsj.cli import main"
    return subprocess.run(["pgrep", "-f", pattern], capture_output=True).returncode == 0


def commit() -> str:
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
                          capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                           cwd=REPO, capture_output=True, text=True).stdout.strip()
    return f"{head}-dirty" if dirty else head


def run_one(run: dict[str, Any], audio_root: Path) -> None:
    label, target = str(run["label"]), str(run["target"])
    overrides: dict[str, Any] = dict(run.get("overrides") or {})
    folder = RUNS / label
    name = "podcast" if target == "fixture" else target
    out = folder / f"{name}.json"
    if out.exists():
        print(f"{label}: already done, skipping", flush=True)
        return
    audio = FIXTURE if target == "fixture" else next(
        p for p in (audio_root / f"{target}.m4a", audio_root / f"{target}.mp3") if p.exists()
    )
    while busy():
        print("  another dsj suno is running, waiting", flush=True)
        time.sleep(60)
    wait_for_memory()
    folder.mkdir(parents=True, exist_ok=True)
    args = ["suno", str(audio), "-o", str(out), "--status", str(folder / f"{name}.status.json"),
            *(list(run["flags"]) if "flags" in run else FLAGS.get(target, DEFAULT_FLAGS))]
    code = (
        "import sys, dsj.whisper as w; "
        + "".join(f"w.{k} = {v!r}; " for k, v in overrides.items())
        +
        "from dsj.cli import main; sys.exit(main(sys.argv[1:]))"
    )
    print(f"{label}: {overrides or 'defaults'} on {name} ({free_pct()}% memory free)", flush=True)
    started = time.monotonic()
    with (folder / f"{name}.log").open("w") as log:
        rc = subprocess.run(["uv", "run", "python", "-c", code, *args], cwd=REPO,
                            stdout=log, stderr=subprocess.STDOUT).returncode
    wall = time.monotonic() - started
    meta = {"wall_s": wall, "returncode": rc, "args": args, "overrides": overrides,
            "commit": commit()}
    (folder / f"{name}.bench.json").write_text(json.dumps(meta, indent=2))
    print(f"{label}: exit {rc} in {wall / 60:.1f} min", flush=True)


def measure(label: str, target: str) -> None:
    bench = [sys.executable, str(REPO / "scratch" / "real_bench.py")]
    if target == "fixture":
        cmd = [*bench, "fixture", "--label", label]
    else:
        cmd = [*bench, "run", "--label", label, "--only", target.removeprefix("recording-")]
    subprocess.run(cmd, cwd=REPO, check=False)


def main() -> int:
    folder = os.environ.get("DSJ_REAL_AUDIO")
    if not folder:
        sys.exit("set DSJ_REAL_AUDIO to the Hi-Q Recordings folder; see the docstring")
    root = Path(folder).expanduser()
    if not FIXTURE.exists():
        sys.exit(f"{FIXTURE} is missing; run `just urdu-fixture` first")
    if len(sys.argv) != 2:
        sys.exit("usage: whisper_sweep.py PLAN.json")
    plan = json.loads(Path(sys.argv[1]).read_text())
    for run in plan:
        run_one(run, root)
    for run in plan:
        measure(str(run["label"]), str(run["target"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
