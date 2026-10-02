#!/usr/bin/env python3
"""Run N labelled `dsj suno scratch/clip360.wav` one at a time and count crashes (#186).

Speaker labelling crashed inside numba's compile-cache save, `ReferenceError:
underlying object has vanished`, in two of four labelled runs on 2026-10-02.
This counts, per run: the exit code, the ReferenceErrors in its log, whether
dsj reported labelling as failed and kept the transcript unlabelled, and
whether the transcript it wrote carries speaker labels.

    uv run python scratch/diarize_crash_loop.py N [-- extra dsj suno flags]

Each run gets its own folder under scratch/diarize_crash_loop/<UTC time>/,
holding run-NN.json, run-NN.log and run-NN.status.json, and the counts go to
summary.json beside them. Speaker labelling stays on (no --no-diarize); the
default engine is parakeet, which is fast on 360 s of audio, so most of each
run is the labelling itself.

One dsj at a time, ever: it refuses to start a run while another `dsj suno`
is alive and waits for 30% free memory first, the rule scratch/whisper_sweep.py
follows. The clip is public test audio, so the logs are safe to read.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
CLIP = REPO / "scratch" / "clip360.wav"
ROOT = REPO / "scratch" / "diarize_crash_loop"
MIN_FREE_PCT = 30
# A run's own command line, `uv run dsj suno ...` or `.venv/bin/dsj suno ...`,
# and the sweep's `python -c "...dsj.cli import main..." suno`.
OTHER_DSJ = r"(^|[ /])dsj suno |dsj\.cli import main"
DEGRADED = "speaker labelling failed"


def free_pct() -> int:
    out = subprocess.run(["memory_pressure"], capture_output=True, text=True).stdout
    found = re.search(r"free percentage:\s*(\d+)%", out)
    return int(found.group(1)) if found else 0


def wait_until_alone() -> None:
    while subprocess.run(["pgrep", "-f", OTHER_DSJ], capture_output=True).returncode == 0:
        print("  another dsj suno is running, waiting", flush=True)
        time.sleep(30)
    while (pct := free_pct()) < MIN_FREE_PCT:
        print(f"  {pct}% memory free, waiting for {MIN_FREE_PCT}%", flush=True)
        time.sleep(60)


def labelled(out: Path) -> bool:
    """Whether the transcript names speakers: the legend, and a label on every sentence."""
    if not out.exists():
        return False
    payload = json.loads(out.read_text())
    sentences = payload.get("sentences", [])
    return "diarization" in payload and bool(sentences) and all("speaker" in s for s in sentences)


def run_one(i: int, folder: Path, extra: list[str]) -> dict[str, Any]:
    out = folder / f"run-{i:02d}.json"
    log_path = folder / f"run-{i:02d}.log"
    cmd = ["uv", "run", "dsj", "suno", str(CLIP), "-o", str(out),
           "--status", str(folder / f"run-{i:02d}.status.json"), *extra]
    wait_until_alone()
    started = time.monotonic()
    with log_path.open("w") as log:
        code = subprocess.run(cmd, cwd=REPO, stdout=log, stderr=subprocess.STDOUT).returncode
    text = log_path.read_text(errors="replace")
    return {
        "run": i,
        "exit": code,
        "wall_s": round(time.monotonic() - started, 1),
        "reference_errors": text.count("ReferenceError"),
        "degraded": DEGRADED in text,
        "labelled": labelled(out),
    }


def main(argv: list[str]) -> int:
    if not argv or not argv[0].isdigit() or (len(argv) > 1 and argv[1] != "--"):
        sys.exit(__doc__)
    n, extra = int(argv[0]), argv[2:]
    if not CLIP.exists():
        sys.exit(f"{CLIP} is missing")
    folder = ROOT / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    folder.mkdir(parents=True)
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
                          capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"],
                           cwd=REPO, capture_output=True, text=True).stdout.strip()
    head += "-dirty" if dirty else ""
    print(f"{n} labelled runs of {CLIP.name} at {head}, into {folder}", flush=True)
    rows: list[dict[str, Any]] = []
    for i in range(1, n + 1):
        row = run_one(i, folder, extra)
        rows.append(row)
        print(f"  run {i:2d}: exit {row['exit']}, {row['reference_errors']} ReferenceError, "
              f"degraded={row['degraded']}, labelled={row['labelled']}, {row['wall_s']} s", flush=True)
    summary = {
        "commit": head,
        "runs": n,
        "extra_flags": extra,
        "exit_0": sum(r["exit"] == 0 for r in rows),
        "with_reference_error": sum(r["reference_errors"] > 0 for r in rows),
        "degraded": sum(r["degraded"] for r in rows),
        "labelled": sum(r["labelled"] for r in rows),
        "rows": rows,
    }
    (folder / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"exit 0: {summary['exit_0']}/{n}  with ReferenceError: {summary['with_reference_error']}/{n}  "
          f"degraded: {summary['degraded']}/{n}  labelled: {summary['labelled']}/{n}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
