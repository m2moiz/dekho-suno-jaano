#!/usr/bin/env python3
"""Run whisper's anomaly-switch settings one after another, with no agent watching (#99).

Picking `hallucination_silence_threshold` needs repeated runs: two runs of the
same setting on recording-20260920-101117 gave 59% and 47% Urdu script, so one
run per setting decides nothing. Each run is 10 to 20 minutes of whisper on the
laptop. An agent waiting on that spends quota on every check-in; this script
spends none, and the orchestrator reads scratch/real_bench/results.md at the end.

    export DSJ_REAL_AUDIO="$HOME/Library/CloudStorage/GoogleDrive-m.moiz1995@gmail.com/My Drive/Hi-Q Recordings"
    uv run python scratch/whisper_sweep.py

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

REPO = Path(__file__).resolve().parent.parent
RUNS = REPO / "scratch" / "real_bench" / "runs"
FIXTURE = REPO / "scratch" / "urdu_cs" / "podcast.wav"
MIN_FREE_PCT = 30

# (label, threshold or None for off, target). Targets are a recording name from
# scratch/real_bench.py's SET, or "fixture". Labels from earlier single runs
# (loops-before, off-repeat, threshold-2, threshold-5) are kept as repeat 1 and 2;
# these add the repeats and the checks a choice needs.
PLAN: list[tuple[str, float | None, str]] = [
    ("sweep-off-r3", None, "recording-20260920-101117"),
    ("sweep-t2-r2", 2.0, "recording-20260920-101117"),
    ("sweep-t2-r3", 2.0, "recording-20260920-101117"),
    ("sweep-t5-r2", 5.0, "recording-20260920-101117"),
    ("sweep-t5-r3", 5.0, "recording-20260920-101117"),
    ("sweep-t5-r1", 5.0, "fixture"),
    ("sweep-t2-r1", 2.0, "recording-20260922-153458"),
]
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
    return subprocess.run(["pgrep", "-f", "dsj suno"], capture_output=True).returncode == 0


def commit() -> str:
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
                          capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                           cwd=REPO, capture_output=True, text=True).stdout.strip()
    return f"{head}-dirty" if dirty else head


def run_one(label: str, threshold: float | None, target: str, audio_root: Path) -> None:
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
            *FLAGS.get(target, DEFAULT_FLAGS)]
    code = (
        "import sys, dsj.whisper as w; "
        f"w.HALLUCINATION_SILENCE_S = {threshold!r}; "
        "from dsj.cli import main; sys.exit(main(sys.argv[1:]))"
    )
    print(f"{label}: threshold={threshold} on {name} ({free_pct()}% memory free)", flush=True)
    started = time.monotonic()
    with (folder / f"{name}.log").open("w") as log:
        rc = subprocess.run(["uv", "run", "python", "-c", code, *args], cwd=REPO,
                            stdout=log, stderr=subprocess.STDOUT).returncode
    wall = time.monotonic() - started
    meta = {"wall_s": wall, "returncode": rc, "args": args, "threshold": threshold,
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
    for label, threshold, target in PLAN:
        run_one(label, threshold, target, root)
    for label, _, target in PLAN:
        measure(label, target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
