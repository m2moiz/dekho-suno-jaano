#!/usr/bin/env python3
"""Count temporal inversions in dsj transcripts on disk.

Issue #53: sentences were observed running backwards in time on long
recordings. This is the reproduction: it walks every transcript handed to it
and reports, per file, how many adjacent pairs go backwards and by how much,
at three levels -- sentences, tokens inside a sentence, and speaker runs.

    uv run python scratch/order_probe.py scratch/*.json /tmp/dsj-angle/transcript.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _token_start(token: dict) -> float:
    """Token start, under either serialization this repo has written.

    suno.py writes {"t", "w"}; older transcripts on disk carry the full
    AlignedToken field set. Both are real files a reader may hand us.
    """
    return token["t"] if "t" in token else token["start"]


def inversions(values: list[float]) -> list[tuple[int, float]]:
    """Indices where `values` goes backwards, with the size of the back-jump."""
    return [
        (i, values[i - 1] - values[i])
        for i in range(1, len(values))
        if values[i] < values[i - 1]
    ]


def probe(path: Path) -> None:
    try:
        payload = json.loads(path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return
    if not isinstance(payload, dict) or "sentences" not in payload:
        return
    sentences = payload["sentences"]
    if not sentences or not isinstance(sentences[0], dict) or "start" not in sentences[0]:
        return

    starts = [s["start"] for s in sentences]
    sent_inv = inversions(starts)

    tok_inv = 0
    tok_worst = 0.0
    for s in sentences:
        for _, back in inversions([_token_start(t) for t in s.get("tokens", [])]):
            tok_inv += 1
            tok_worst = max(tok_worst, back)

    # Speaker turns: consecutive sentences by one speaker collapse into a run,
    # and the runs themselves must move forward.
    runs: list[tuple[int, float, float]] = []
    for s in sentences:
        spk = s.get("speaker")
        if spk is None:
            continue
        if runs and runs[-1][0] == spk:
            runs[-1] = (spk, runs[-1][1], s["end"])
        else:
            runs.append((spk, s["start"], s["end"]))
    run_inv = inversions([r[1] for r in runs])

    worst = max((b for _, b in sent_inv), default=0.0)
    print(
        f"{path}: {len(sentences)} sentences, "
        f"{len(sent_inv)} sentence inversions (worst {worst:.2f}s), "
        f"{tok_inv} token inversions (worst {tok_worst:.2f}s), "
        f"{len(runs)} speaker runs, {len(run_inv)} run inversions"
    )
    for i, back in sent_inv:
        print(
            f"    #{i}: {starts[i - 1]:.2f} -> {starts[i]:.2f} (back {back:.2f}s)  "
            f"prev={sentences[i - 1]['text'][:40]!r} this={sentences[i]['text'][:40]!r}"
        )


def main(argv: list[str]) -> int:
    for arg in argv:
        probe(Path(arg))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
